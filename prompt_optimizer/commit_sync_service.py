from __future__ import annotations

from typing import Any

from prompt_optimizer.models import CommitInfo
from prompt_optimizer.project_memory import (
    SYNC_NOTICE_COMPACTION_THRESHOLD,
    commit_gap_count,
    update_project,
)
from prompt_optimizer.repo_ops import (
    ensure_local_project_path,
    get_commit_diff,
    get_last_commits,
    get_remote_commit_diff,
    get_remote_last_commits,
    is_git_repository,
)


def commit_to_payload(commit: CommitInfo) -> dict[str, str]:
    return {
        "fullHash": commit.full_hash,
        "shortHash": commit.short_hash,
        "author": commit.author,
        "date": commit.date,
        "subject": commit.subject,
        "summary": commit.summary,
    }


class CommitSyncService:
    def load_commits(self, project, *, count: int = 20) -> list[CommitInfo]:
        if project.remote_url.strip():
            try:
                return get_remote_last_commits(project.remote_url, count=count)
            except RuntimeError:
                local_path = ensure_local_project_path(project.local_path)
                if is_git_repository(local_path):
                    return get_last_commits(local_path, count=count)
                raise

        local_path = ensure_local_project_path(project.local_path)
        if not is_git_repository(local_path):
            return []
        return get_last_commits(local_path, count=count)

    def load_diff(self, project, commit_hash: str) -> str:
        if project.remote_url.strip():
            try:
                return get_remote_commit_diff(project.remote_url, commit_hash)
            except RuntimeError:
                local_path = ensure_local_project_path(project.local_path)
                if is_git_repository(local_path):
                    return get_commit_diff(local_path, commit_hash)
                raise
        return get_commit_diff(
            ensure_local_project_path(project.local_path), commit_hash
        )

    def build_diff_summary(self, diff_text: str) -> str:
        files: list[str] = []
        hunks: list[str] = []

        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                files.append(line.removeprefix("+++ b/").strip())
            elif line.startswith("@@"):
                hunks.append(line.strip())

        file_summary = ", ".join(files[:3]) if files else "No changed files detected"
        if len(files) > 3:
            file_summary += f" (+{len(files) - 3} more)"

        hunk_summary = "; ".join(hunks[:2]) if hunks else "No hunk headers detected"
        if len(hunks) > 2:
            hunk_summary += f" (+{len(hunks) - 2} more)"

        return f"Files: {file_summary}\nFocus: {hunk_summary}"

    def build_sync_snapshot(self, project) -> dict[str, Any]:
        commits = self.load_commits(project)
        return self.build_sync_snapshot_from_commits(project, commits)

    def build_sync_snapshot_from_commits(
        self, project, commits: list[CommitInfo]
    ) -> dict[str, Any]:
        commit_hashes = [commit.full_hash for commit in commits]
        missed_commit_count = commit_gap_count(
            commit_hashes, project.last_processed_commit
        )
        missed_commits = commits[:missed_commit_count]
        prompt_request_count = max(missed_commit_count - 1, 0)
        default_selection = (
            [missed_commits[0].full_hash]
            if missed_commits
            else ([commits[0].full_hash] if commits else [])
        )

        if commits:
            project.last_seen_remote_commit = commits[0].full_hash
            update_project(project)

        return {
            "commits": [commit_to_payload(commit) for commit in commits],
            "missedCommits": [commit_to_payload(commit) for commit in missed_commits],
            "missedCommitCount": missed_commit_count,
            "promptRequestCount": prompt_request_count,
            "defaultSelectedCommitHashes": default_selection,
            "shouldCompactMissedPrompts": (
                prompt_request_count > SYNC_NOTICE_COMPACTION_THRESHOLD
            ),
            "compactionThreshold": SYNC_NOTICE_COMPACTION_THRESHOLD,
        }
