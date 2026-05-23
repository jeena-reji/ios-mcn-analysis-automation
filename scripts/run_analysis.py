import os
import subprocess
from pathlib import Path

ORG = os.environ.get("ORG")
REPOS = os.environ.get("REPOS")

workspace = Path.cwd()
reports_dir = workspace / "reports"
repos_dir = workspace / "repositories"

reports_dir.mkdir(exist_ok=True)
repos_dir.mkdir(exist_ok=True)

# If user enters "all"
if REPOS.lower() == "all":
    repos = [
        "amf",
        "smf",
        "upf",
        "nrf"
    ]
else:
    repos = [repo.strip() for repo in REPOS.split(",")]

for repo in repos:

    repo_path = repos_dir / repo

    print(f"\nCloning {repo}...")

    subprocess.run(
        [
            "git",
            "clone",
            f"https://github.com/{ORG}/{repo}.git",
            str(repo_path)
        ],
        check=True
    )

    print(f"Running analysis for {repo}...")

    subprocess.run(
        [
            "python",
            str(workspace / "scripts" / "get_changes_diff.py"),
            "--target-commit",
            "HEAD~1",
            "--output",
            str(reports_dir / f"{repo}-analysis.csv")
        ],
        cwd=repo_path,
        check=True
    )

print("\nAll reports generated successfully.")
