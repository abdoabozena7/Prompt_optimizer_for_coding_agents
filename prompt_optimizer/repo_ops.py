from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests

from prompt_optimizer.models import CommitInfo


BASE_DIR = Path("cloned_repos")
BASE_DIR.mkdir(exist_ok=True)
APP_DIFFS_DIR = Path(__file__).resolve().parent.parent / "saved-diffs"
APP_DIFFS_DIR.mkdir(parents=True, exist_ok=True)

REPO_PATTERNS = [
    r"^https://github\.com/[^/]+/[^/]+/?$",
    r"^https://github\.com/[^/]+/[^/]+\.git$",
    r"^git@github\.com:[^/]+/[^/]+\.git$",
    r"^https://gitlab\.com/.+?/[^/]+/?$",
    r"^https://gitlab\.com/.+?/[^/]+\.git$",
]


def run_git_command(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout


def is_valid_repo_url(url: str) -> bool:
    return any(re.match(pattern, url.strip()) for pattern in REPO_PATTERNS)


def repo_folder_name(repo_url: str) -> str:
    return hashlib.md5(repo_url.strip().encode("utf-8")).hexdigest()


def ensure_repo_from_url(repo_url: str) -> Path:
    folder = BASE_DIR / repo_folder_name(repo_url)

    if not folder.exists():
        run_git_command(["git", "clone", "--quiet", repo_url, str(folder)])
    else:
        run_git_command(["git", "fetch", "--all", "--prune"], cwd=folder)

    return folder


def ensure_local_project_path(local_path: str) -> Path:
    path = Path(local_path).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"Local path does not exist: {path}")
    if not path.is_dir():
        raise RuntimeError(f"Local path is not a directory: {path}")
    return path


def ensure_local_repo_path(local_path: str) -> Path:
    return ensure_local_project_path(local_path)


def get_default_branch(repo_path: Path) -> str:
    try:
        ref = run_git_command(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=repo_path,
        ).strip()
        return ref.split("/")[-1]
    except Exception:
        return run_git_command(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
        ).strip()


def update_to_default_branch(repo_path: Path) -> None:
    branch = get_default_branch(repo_path)
    run_git_command(["git", "checkout", branch], cwd=repo_path)
    try:
        run_git_command(["git", "pull", "--ff-only"], cwd=repo_path)
    except Exception:
        pass


def is_git_repository(path: Path) -> bool:
    try:
        output = run_git_command(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
        ).strip()
    except Exception:
        return False
    return output == "true"


def get_last_commits(repo_path: Path, count: int = 5) -> list[CommitInfo]:
    log_format = "%H%x1f%h%x1f%an%x1f%ad%x1f%s"
    output = run_git_command(
        [
            "git",
            "log",
            f"-n{count}",
            f"--pretty=format:{log_format}",
            "--date=iso",
        ],
        cwd=repo_path,
    )

    commits: list[CommitInfo] = []
    for line in output.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        commits.append(
            CommitInfo(
                full_hash=parts[0],
                short_hash=parts[1],
                author=parts[2],
                date=parts[3],
                subject=parts[4],
            )
        )
    return commits


def get_commit_diff(repo_path: Path, commit_hash: str) -> str:
    return run_git_command(
        [
            "git",
            "show",
            "--format=fuller",
            "--stat",
            "--patch",
            "--no-color",
            commit_hash,
        ],
        cwd=repo_path,
    )


def safe_filename(text: str) -> str:
    text = re.sub(r"[^\w\-\. ]+", "_", text, flags=re.UNICODE).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:120] if text else "commit"


def save_diff_to_app_storage(filename: str, diff_text: str) -> Path:
    target_path = APP_DIFFS_DIR / filename
    target_path.write_text(diff_text, encoding="utf-8")
    return target_path


def parse_remote_repo_url(repo_url: str) -> tuple[str, str, str]:
    url = repo_url.strip().rstrip("/")

    github_match = re.match(
        r"^(?:https://github\.com|git@github\.com:)/(.+?)/([^/]+?)(?:\.git)?$",
        url,
    )
    if github_match:
        owner, repo = github_match.groups()
        return "github", owner, repo

    gitlab_match = re.match(
        r"^(?:https://gitlab\.com|git@gitlab\.com:)/(.+?)/([^/]+?)(?:\.git)?$",
        url,
    )
    if gitlab_match:
        namespace, repo = gitlab_match.groups()
        return "gitlab", namespace, repo

    raise RuntimeError("Remote Git URL must be a GitHub or GitLab repository URL.")


def _github_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_remote_last_commits(repo_url: str, count: int = 5) -> list[CommitInfo]:
    provider, namespace, repo = parse_remote_repo_url(repo_url)

    if provider == "github":
        repo_response = requests.get(
            f"https://api.github.com/repos/{namespace}/{repo}",
            headers=_github_headers(),
            timeout=20,
        )
        repo_response.raise_for_status()
        default_branch = repo_response.json()["default_branch"]

        commits_response = requests.get(
            f"https://api.github.com/repos/{namespace}/{repo}/commits",
            headers=_github_headers(),
            params={"sha": default_branch, "per_page": count},
            timeout=20,
        )
        commits_response.raise_for_status()

        commits: list[CommitInfo] = []
        for item in commits_response.json():
            commit = item["commit"]
            message = commit["message"].splitlines()[0].strip()
            author = commit.get("author") or {}
            commits.append(
                CommitInfo(
                    full_hash=item["sha"],
                    short_hash=item["sha"][:7],
                    author=author.get("name", "Unknown"),
                    date=author.get("date", ""),
                    subject=message,
                )
            )
        return commits

    project_id = quote(f"{namespace}/{repo}", safe="")
    project_response = requests.get(
        f"https://gitlab.com/api/v4/projects/{project_id}",
        timeout=20,
    )
    project_response.raise_for_status()
    default_branch = project_response.json()["default_branch"]

    commits_response = requests.get(
        f"https://gitlab.com/api/v4/projects/{project_id}/repository/commits",
        params={"ref_name": default_branch, "per_page": count},
        timeout=20,
    )
    commits_response.raise_for_status()

    commits = []
    for item in commits_response.json():
        title = item.get("title") or item.get("message", "").splitlines()[0].strip()
        commits.append(
            CommitInfo(
                full_hash=item["id"],
                short_hash=item["short_id"],
                author=item.get("author_name", "Unknown"),
                date=item.get("created_at", ""),
                subject=title,
            )
        )
    return commits


def get_remote_commit_diff(repo_url: str, commit_hash: str) -> str:
    provider, namespace, repo = parse_remote_repo_url(repo_url)

    if provider == "github":
        response = requests.get(
            f"https://github.com/{namespace}/{repo}/commit/{commit_hash}.diff",
            timeout=20,
        )
        response.raise_for_status()
        return response.text

    response = requests.get(
        f"https://gitlab.com/{namespace}/{repo}/-/commit/{commit_hash}.diff",
        timeout=20,
    )
    response.raise_for_status()
    return response.text
