import os
import subprocess
from pathlib import Path

# Inputs from GitHub Actions
ORG = os.environ["ORG"]
REPOS = os.environ["REPOS"]
TOKEN = os.environ["ORG_PAT"]

BASE_DIR = Path.cwd()
REPO_DIR = BASE_DIR / "repositories"

REPO_DIR.mkdir(exist_ok=True)

# Handle repo list
if REPOS.strip().lower() == "all":
    raise Exception(
        "Add GitHub API logic here for fetching all repos dynamically"
    )

repo_list = [repo.strip() for repo in REPOS.split(",") if repo.strip()]

for repo in repo_list:

    repo_path = REPO_DIR / repo

    print(f"Cloning {repo}...")

    clone_url = f"https://{TOKEN}@github.com/{ORG}/{repo}.git"

    subprocess.run(
        [
            "git",
            "clone",
            clone_url,
            str(repo_path)
        ],
        check=True
    )

    print(f"{repo} cloned successfully")

    # Get default branch
    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "HEAD"
        ],
        cwd=repo_path,
        text=True,
        capture_output=True,
        check=True
    )

    default_branch = result.stdout.strip()

    print(f"Default branch for {repo}: {default_branch}")

    # Get latest commit
    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "HEAD"
        ],
        cwd=repo_path,
        text=True,
        capture_output=True,
        check=True
    )

    latest_commit = result.stdout.strip()

    print(f"Latest commit for {repo}: {latest_commit}")

    # Run analysis script
    output_file = BASE_DIR / "reports" / f"{repo}-analysis.csv"

    output_file.parent.mkdir(exist_ok=True)

    subprocess.run(
        [
            "python",
            "scripts/get_changes_diff.py",
            "--target-commit",
            "HEAD~1",
            "--output",
            str(output_file)
        ],
        cwd=repo_path,
        check=True
    )

    print(f"Report generated: {output_file}")
