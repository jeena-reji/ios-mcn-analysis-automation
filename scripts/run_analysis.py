import requests
import os
import subprocess
import shutil
from pathlib import Path

# Inputs from GitHub Actions
ORG = os.environ["ORG"]
REPOS = os.environ["REPOS"]
TOKEN = os.environ["ORG_PAT"]
TARGET_COMMIT = os.environ.get("TARGET_COMMIT", "HEAD~1")

BASE_DIR = Path.cwd()
REPO_DIR = BASE_DIR / "repositories"
SCRIPT_PATH = BASE_DIR / "scripts" / "get_changes_diff.py"

REPO_DIR.mkdir(exist_ok=True)
# ORG_SUBMODULE_TARGETS = {
#     "ios-mcn-ran": [
#         "--target", "o1-adapter=0df0437",
#         "--target", "openairinterface5g=f0fce7c167",
#         "--target", "phy=2de97529a4c5a1922214ba0e6f0fb84cacbd0bc7",
#     ],
#     "ios-mcn-core": [],
#     "ios-mcn-smo": [],
#     "ios-mcn-ims": [],
# }

# Handle repo list
if REPOS.strip().lower() == "all":

    headers = {
        "Authorization": f"token {TOKEN}"
    }

    url = f"https://api.github.com/orgs/{ORG}/repos?per_page=100"

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise Exception(
            f"Failed to fetch repositories: {response.text}"
        )

    repos_data = response.json()

    repo_list = [
        repo["name"]
        for repo in repos_data
    ]

else:

    repo_list = [
        repo.strip()
        for repo in REPOS.split(",")
        if repo.strip()
    ]

print(f"Repositories to analyze: {repo_list}")
subprocess.run(
    ["git", "config", "--global",
     f"url.https://{TOKEN}@github.com/.insteadOf",
     "https://github.com/"],
    check=True
)

for repo in repo_list:

    repo_path = REPO_DIR / repo

    # Remove old repo if exists
    if repo_path.exists():
        subprocess.run(
            ["rm", "-rf", str(repo_path)],
            check=True
        )

    print(f"Cloning {repo}...")

    clone_url = f"https://{TOKEN}@github.com/{ORG}/{repo}.git"

    subprocess.run(
        [
            "git",
            "clone",
            "--recurse-submodules",
            clone_url,
            str(repo_path)
        ],
        check=True
    )

    print(f"{repo} cloned successfully")

    # Get current branch
    result = subprocess.run(
        [
            "git",
            "branch",
            "--show-current"
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

    check_commit = subprocess.run(
        ["git", "rev-parse", "--verify", TARGET_COMMIT],
        cwd=repo_path,
        text=True,
        capture_output=True
    )
    if check_commit.returncode != 0:
        print(f"Skipping {repo} - target commit '{TARGET_COMMIT}' not found")
        continue

    # Create reports directory
    reports_dir = BASE_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)

    output_file = reports_dir / f"{repo}-analysis.csv"

    # Copy script into cloned repo so path resolves correctly
  
    scripts_dir = repo_path / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    script_copy = scripts_dir / "get_changes_diff.py"
    shutil.copy(SCRIPT_PATH, script_copy)

    Run analysis script
    subprocess.run(
        [
            "python",
            # str(SCRIPT_PATH),
            str(script_copy),
            "--target-commit",
            TARGET_COMMIT,  
            "--output",
            # "HEAD~1",
            str(output_file),
            "--no-reference-xlsx"
        ],
        cwd=repo_path,
        check=True
    )
    # Run analysis script
# cmd = ["python", str(script_copy),
#        "--no-reference-xlsx",
#        "--output", str(output_file)]

# submodule_args = ORG_SUBMODULE_TARGETS.get(ORG, [])
# if submodule_args:
#     cmd.extend(submodule_args)
# elif TARGET_COMMIT:
#     cmd.extend(["--target-commit", TARGET_COMMIT])

# subprocess.run(cmd, cwd=repo_path, check=True)
    print(f"Report generated: {output_file}")

print("All repository analysis completed successfully")
