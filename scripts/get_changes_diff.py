#!/usr/bin/env python3
"""Generate a tree-style CSV diff summary for the root repo and submodules."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


DEFAULT_OUTPUT = "IOS-MCN Agartala Analysis.csv"
DEFAULT_REFERENCE_XLSX = "IOS-MCN Agartala 0.3.0-RAN Anaysis.xlsx"


@dataclass(frozen=True)
class DiffEntry:
    submodule: str
    path: str
    additions: int
    deletions: int
    total_lines: int
    base_commit: str
    current_commit: str


@dataclass(frozen=True)
class TreeEntry:
    scope: str
    path: str
    row_type: str
    total_lines: int
    additions: int
    deletions: int
    base_commit: str
    current_commit: str


@dataclass(frozen=True)
class SubmoduleSummary:
    submodule: str
    base_commit: str
    current_commit: str


@dataclass(frozen=True)
class RootSummary:
    base_commit: str
    current_commit: str


@dataclass(frozen=True)
class ReferenceRow:
    relevance: int
    row_type: str


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        command = "git " + " ".join(args)
        raise RuntimeError(f"{command} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout


def discover_submodules(repo_root: Path) -> list[str]:
    output = run_git(
        ["config", "--file", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
        repo_root,
    )
    return sorted(line.split(maxsplit=1)[1] for line in output.splitlines() if line.strip())


def resolve_commit(repo: Path, commit: str) -> str:
    return run_git(["rev-parse", "--verify", f"{commit}^{{commit}}"], repo).strip()


def current_commit(repo: Path) -> str:
    return run_git(["rev-parse", "HEAD"], repo).strip()


def is_submodule_path(path: str, submodules: list[str]) -> bool:
    return any(path == submodule or path.startswith(f"{submodule}/") for submodule in submodules)


def parse_module_commits(values: list[str], option_name: str) -> dict[str, str]:
    commits: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option_name} must use SUBMODULE=COMMIT format")
        submodule, commit = value.split("=", 1)
        submodule = submodule.strip().rstrip("/")
        commit = commit.strip()
        if not submodule or not commit:
            raise ValueError(f"{option_name} must include both SUBMODULE and COMMIT")
        commits[submodule] = commit
    return commits


def parse_numstat(output: str) -> list[tuple[str, int, int]]:
    entries: list[tuple[str, int, int]] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        additions, deletions, path = parts[0], parts[1], parts[2]
        if additions == "-" or deletions == "-":
            continue
        entries.append((path, int(additions), int(deletions)))
    return entries


def pathspecs_for_extensions(extensions: tuple[str, ...]) -> list[str]:
    return [f"*{extension}" for extension in extensions]


def list_tracked_files(repo: Path, extensions: tuple[str, ...]) -> list[str]:
    pathspecs = pathspecs_for_extensions(extensions)
    command = ["ls-files"]
    if pathspecs:
        command.extend(["--", *pathspecs])
    output = run_git(command, repo)
    return sorted(line for line in output.splitlines() if line.strip())


def list_changed_files(
    repo: Path,
    base_commit: str,
    current_commit: str,
    extensions: tuple[str, ...],
) -> list[str]:
    pathspecs = pathspecs_for_extensions(extensions)
    command = ["diff", "--name-only", "--diff-filter=ACMRTD", base_commit, current_commit]
    if pathspecs:
        command.extend(["--", *pathspecs])
    output = run_git(command, repo)
    return sorted(line for line in output.splitlines() if line.strip())


def line_count_at_commit(repo: Path, commit: str, file_path: str) -> int:
    result = subprocess.run(
        ["git", "show", f"{commit}:{file_path}"],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return 0
    if not result.stdout:
        return 0
    return result.stdout.count(b"\n") + (0 if result.stdout.endswith(b"\n") else 1)


def line_count_at_path(file_path: Path) -> int:
    if not file_path.is_file():
        return 0
    with file_path.open("rb") as source:
        content = source.read()
    if not content:
        return 0
    return content.count(b"\n") + (0 if content.endswith(b"\n") else 1)


def collect_root_entries(
    repo_root: Path,
    submodules: list[str],
    extensions: tuple[str, ...],
) -> tuple[RootSummary, list[DiffEntry]]:
    root_current = current_commit(repo_root)
    entries: list[DiffEntry] = []
    for path in list_tracked_files(repo_root, extensions):
        if is_submodule_path(path, submodules):
            continue
        total_lines = line_count_at_path(repo_root / path)
        entries.append(
            DiffEntry(
                submodule="root",
                path=path,
                additions=total_lines,
                deletions=0,
                total_lines=total_lines,
                base_commit="all additions",
                current_commit=root_current,
            )
        )
    return RootSummary(base_commit="all additions", current_commit=root_current), entries


def collect_diff_entries(
    repo_root: Path,
    submodule: str,
    base_commit: str,
    extensions: tuple[str, ...],
) -> tuple[SubmoduleSummary, list[DiffEntry]]:
    submodule_path = repo_root / submodule
    if not submodule_path.is_dir():
        raise RuntimeError(f"Submodule path does not exist: {submodule}")

    resolved_base = resolve_commit(submodule_path, base_commit)
    resolved_current = current_commit(submodule_path)
    pathspecs = pathspecs_for_extensions(extensions)
    diff_command = ["diff", "--numstat", "--diff-filter=ACMRTD", resolved_base, resolved_current]
    if pathspecs:
        diff_command.extend(["--", *pathspecs])
    diff_output = run_git(diff_command, submodule_path)

    summary = SubmoduleSummary(
        submodule=submodule,
        base_commit=resolved_base,
        current_commit=resolved_current,
    )
    changed_paths = {
        path: (additions, deletions)
        for path, additions, deletions in parse_numstat(diff_output)
    }
    all_paths = set(list_tracked_files(submodule_path, extensions))
    all_paths.update(list_changed_files(submodule_path, resolved_base, resolved_current, extensions))

    entries: list[DiffEntry] = []
    for path in sorted(all_paths):
        additions, deletions = changed_paths.get(path, (0, 0))
        total_lines = line_count_at_commit(submodule_path, resolved_current, path)
        if total_lines == 0 and deletions > 0:
            total_lines = line_count_at_commit(submodule_path, resolved_base, path)
        entries.append(
            DiffEntry(
                submodule=submodule,
                path=path,
                additions=additions,
                deletions=deletions,
                total_lines=total_lines,
                base_commit=resolved_base,
                current_commit=resolved_current,
            )
        )
    return summary, sorted(entries, key=lambda entry: (entry.submodule, entry.path))


def tree_labels(paths: list[str]) -> dict[str, str]:
    children: dict[str, set[str]] = {"": set()}
    all_paths: set[str] = set()
    file_paths = set(paths)

    for path in paths:
        parts = path.split("/")
        parent = ""
        for index, part in enumerate(parts):
            current = "/".join(parts[: index + 1])
            children.setdefault(parent, set()).add(current)
            children.setdefault(current, set())
            all_paths.add(current)
            parent = current

    labels: dict[str, str] = {}

    def walk(parent: str, prefix: str) -> None:
        items = sorted(children[parent])
        for index, item in enumerate(items):
            is_last = index == len(items) - 1
            connector = "`-- " if is_last else "|-- "
            name = item.rsplit("/", 1)[-1]
            labels[item] = f"{prefix}{connector}{name}"
            if item not in file_paths:
                next_prefix = prefix + ("    " if is_last else "|   ")
                walk(item, next_prefix)

    walk("", "")
    return {path: labels[path] for path in all_paths}


def xlsx_column(cell_ref: str) -> str:
    return "".join(char for char in cell_ref if char.isalpha())


def parse_reference_xlsx(path: Path) -> dict[str, ReferenceRow]:
    if not path.is_file():
        return {}

    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: dict[str, ReferenceRow] = {}
    with ZipFile(path) as workbook:
        shared_strings: list[str] = []
        shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        for item in shared_root.findall("a:si", namespace):
            shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", namespace)))

        sheet_name = sorted(
            name for name in workbook.namelist() if name.startswith("xl/worksheets/sheet")
        )[0]
        sheet_root = ET.fromstring(workbook.read(sheet_name))
        for row in sheet_root.findall(".//a:row", namespace):
            values: dict[str, str] = {}
            for cell in row.findall("a:c", namespace):
                value = cell.find("a:v", namespace)
                cell_value = "" if value is None else value.text or ""
                if cell.attrib.get("t") == "s" and cell_value:
                    cell_value = shared_strings[int(cell_value)]
                values[xlsx_column(cell.attrib.get("r", ""))] = cell_value

            summary = values.get("K", "")
            if not summary or summary == "- .":
                continue
            parts = summary.split(" ", 1)
            if len(parts) != 2:
                continue
            file_path = parts[1].removeprefix("./")
            if not file_path:
                continue
            row_type = values.get("B", "")
            if summary.startswith("- "):
                row_type = "Folder"
            elif row_type not in {"File", "Image"}:
                row_type = "File"
            try:
                relevance = int(float(values.get("F", "0") or 0))
            except ValueError:
                relevance = 0
            rows[file_path] = ReferenceRow(
                relevance=1 if relevance else 0,
                row_type=row_type,
            )
    return rows


def image_like_path(path: str) -> bool:
    image_extensions = {
        ".bmp",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".svg",
        ".vsdx",
    }
    suffix = Path(path).suffix.lower()
    return suffix in image_extensions


def build_tree_entries(
    scope: str,
    prefix: str,
    summary_base_commit: str,
    summary_current_commit: str,
    file_entries: list[DiffEntry],
) -> list[TreeEntry]:
    labels = tree_labels([entry.path for entry in file_entries])
    entry_by_path = {entry.path: entry for entry in file_entries}
    rows: list[TreeEntry] = [
        TreeEntry(
            scope=scope,
            path=prefix,
            row_type="Root" if scope == "root" else "Submodule",
            total_lines=0,
            additions=sum(entry.additions for entry in file_entries),
            deletions=sum(entry.deletions for entry in file_entries),
            base_commit=summary_base_commit,
            current_commit=summary_current_commit,
        )
    ]

    for path in sorted(labels):
        entry = entry_by_path.get(path)
        full_path = path if scope == "root" else f"{prefix}/{path}"
        if entry is None:
            rows.append(
                TreeEntry(
                    scope=scope,
                    path=full_path,
                    row_type="Folder",
                    total_lines=0,
                    additions=0,
                    deletions=0,
                    base_commit=summary_base_commit,
                    current_commit=summary_current_commit,
                )
            )
            continue
        rows.append(
            TreeEntry(
                scope=scope,
                path=full_path,
                row_type="File",
                total_lines=entry.total_lines,
                additions=entry.additions,
                deletions=entry.deletions,
                base_commit=entry.base_commit,
                current_commit=entry.current_commit,
            )
        )
    return rows


def workbook_summary_value(row: TreeEntry) -> str:
    line_value = "-" if row.row_type in {"Folder", "Root", "Submodule"} else str(row.total_lines)
    if row.path == ".":
        return "- ."
    return f"{line_value} ./{row.path}"


def to_workbook_row(
    tree_label: str,
    row: TreeEntry,
    reference_rows: dict[str, ReferenceRow],
) -> dict[str, object]:
    is_file = row.row_type == "File"
    reference = reference_rows.get(row.path)
    relevance = reference.relevance if reference and is_file else int(is_file)
    row_type = reference.row_type if reference and reference.row_type else row.row_type
    if reference is None and is_file and image_like_path(row.path):
        row_type = "Image"
    total_relevant_lines = row.total_lines if is_file else 0
    if not relevance:
        total_relevant_lines = 0
    improvement_lines = row.additions + row.deletions if is_file else 0
    impacted_lines = row.total_lines if is_file and (row.additions or row.deletions) else 0
    if not relevance:
        improvement_lines = 0
        impacted_lines = 0
    return {
        "Tree": tree_label,
        "File/Folder": row_type,
        "Total lines": row.total_lines,
        "Additions": row.additions,
        "Deletions": row.deletions,
        "Relevance": relevance,
        "Total relevant lines": total_relevant_lines,
        "Improvement lines": improvement_lines,
        "Impacted lines": impacted_lines,
        "Notes": "",
        "Summary": workbook_summary_value(row),
        "Base commit": row.base_commit,
        "Current commit": row.current_commit,
    }


def build_rows(
    root_summary: RootSummary | None,
    summaries: list[SubmoduleSummary],
    entries: list[DiffEntry],
    reference_rows: dict[str, ReferenceRow],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_submodule: dict[str, list[DiffEntry]] = {}
    for entry in entries:
        by_submodule.setdefault(entry.submodule, []).append(entry)

    if root_summary is not None:
        root_entries = by_submodule.get("root", [])
        root_tree_entries = build_tree_entries(
            "root",
            ".",
            root_summary.base_commit,
            root_summary.current_commit,
            root_entries,
        )
        rows.append(to_workbook_row(".", root_tree_entries[0], reference_rows))
        labels = tree_labels([entry.path for entry in root_entries])
        for row in root_tree_entries[1:]:
            rows.append(to_workbook_row(labels[row.path], row, reference_rows))

    for summary in sorted(summaries, key=lambda item: item.submodule):
        submodule = summary.submodule
        submodule_entries = by_submodule.get(submodule, [])
        submodule_tree_entries = build_tree_entries(
            submodule,
            submodule,
            summary.base_commit,
            summary.current_commit,
            submodule_entries,
        )
        rows.append(to_workbook_row(submodule, submodule_tree_entries[0], reference_rows))
        labels = tree_labels([entry.path for entry in submodule_entries])
        for row in submodule_tree_entries[1:]:
            relative_path = row.path[len(submodule) + 1 :]
            rows.append(to_workbook_row(labels[relative_path], row, reference_rows))

    measured_rows = [row for row in rows if row["File/Folder"] in {"File", "Image"}]
    rows.append(
        {
            "Tree": "TOTAL",
            "File/Folder": "Total",
            "Total lines": sum(int(row["Total lines"]) for row in measured_rows),
            "Additions": sum(int(row["Additions"]) for row in measured_rows),
            "Deletions": sum(int(row["Deletions"]) for row in measured_rows),
            "Relevance": "",
            "Total relevant lines": sum(int(row["Total relevant lines"]) for row in measured_rows),
            "Improvement lines": sum(int(row["Improvement lines"]) for row in measured_rows),
            "Impacted lines": sum(int(row["Impacted lines"]) for row in measured_rows),
            "Notes": "",
            "Summary": "",
            "Base commit": "",
            "Current commit": "",
        }
    )
    return rows


def write_csv(output_path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "Tree",
        "File/Folder",
        "Total lines",
        "Additions",
        "Deletions",
        "Relevance",
        "Total relevant lines",
        "Improvement lines",
        "Impacted lines",
        "Notes",
        "Summary",
        "Base commit",
        "Current commit",
    ]
    with output_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a tree-style CSV summary of root files and submodule diffs."
    )
    parser.add_argument(
        "--base-commit",
        help="Target commit to use for every selected submodule. Kept for compatibility.",
    )
    parser.add_argument(
        "--target-commit",
        help="Target commit to use for every selected submodule.",
    )
    parser.add_argument(
        "--base",
        action="append",
        default=[],
        metavar="SUBMODULE=COMMIT",
        help="Target commit for one submodule. Kept for compatibility.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="SUBMODULE=COMMIT",
        help="Target commit for one submodule. Can be passed multiple times.",
    )
    parser.add_argument(
        "--submodule",
        action="append",
        dest="submodules",
        help="Submodule path to include. Defaults to all top-level submodules.",
    )
    parser.add_argument(
        "--extension",
        action="append",
        dest="extensions",
        help="File extension to include. Can be passed multiple times. Defaults to all tracked files.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"CSV output path. Defaults to '{DEFAULT_OUTPUT}'.",
    )
    parser.add_argument(
        "--no-root",
        action="store_true",
        help="Do not include root repository files as all-addition rows.",
    )
    parser.add_argument(
        "--reference-xlsx",
        default=DEFAULT_REFERENCE_XLSX,
        help=(
            "Workbook to copy relevance and row-type hints from when present. "
            f"Defaults to '{DEFAULT_REFERENCE_XLSX}'."
        ),
    )
    parser.add_argument(
        "--no-reference-xlsx",
        action="store_true",
        help="Do not use workbook relevance hints even if the reference workbook exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    submodules = args.submodules or discover_submodules(repo_root)
    base_commits = parse_module_commits(args.base, "--base")
    target_commits = parse_module_commits(args.target, "--target")
    base_commits.update(target_commits)
    default_target_commit = args.target_commit or args.base_commit
    extensions = tuple(args.extensions or ())

    if not default_target_commit and not base_commits:
        print(
            "error: provide --target-commit or at least one --target SUBMODULE=COMMIT",
            file=sys.stderr,
        )
        return 2

    root_summary: RootSummary | None = None
    summaries: list[SubmoduleSummary] = []
    entries: list[DiffEntry] = []
    reference_rows = (
        {}
        if args.no_reference_xlsx
        else parse_reference_xlsx(repo_root / args.reference_xlsx)
    )
    if not args.no_root:
        root_summary, root_entries = collect_root_entries(repo_root, submodules, extensions)
        entries.extend(root_entries)
    for submodule in submodules:
        base_commit = base_commits.get(submodule, default_target_commit)
        if not base_commit:
            print(f"error: no base commit provided for submodule '{submodule}'", file=sys.stderr)
            return 2
        summary, module_entries = collect_diff_entries(repo_root, submodule, base_commit, extensions)
        summaries.append(summary)
        entries.extend(module_entries)

    output_path = repo_root / args.output
    write_csv(output_path, build_rows(root_summary, summaries, entries, reference_rows))
    print(f"Wrote {output_path} ({len(entries)} file rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
