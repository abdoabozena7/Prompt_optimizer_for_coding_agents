from pathlib import Path

import pytest

from prompt_optimizer import preferences
from prompt_optimizer.blind_spot_service import BlindSpotService
from prompt_optimizer.commit_sync_service import CommitSyncService
from prompt_optimizer.models import AnalysisResult, BlindSpot, CommitInfo
from prompt_optimizer.project_memory import get_project, upsert_project
from prompt_optimizer.retrieval_index_service import RetrievalIndexService


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_commit_sync_defaults_to_all_missed_commits(tmp_path: Path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(preferences, "PREFERENCES_PATH", state_file)

    service = CommitSyncService()
    project = upsert_project(
        local_path=str(tmp_path), remote_url="", preferred_model=""
    )
    project.last_processed_commit = "c2"
    project = get_project(project.id)
    assert project is not None
    project.last_processed_commit = "c2"
    commits = [
        CommitInfo("c4", "c4", "A", "2026-01-04", "Fourth"),
        CommitInfo("c3", "c3", "A", "2026-01-03", "Third"),
        CommitInfo("c2", "c2", "A", "2026-01-02", "Second"),
    ]

    snapshot = service.build_sync_snapshot_from_commits(project, commits)

    assert snapshot["missedCommitCount"] == 2
    assert snapshot["promptRequestCount"] == 1
    assert snapshot["defaultSelectedCommitHashes"] == ["c4"]
    assert snapshot["commits"][0]["fullHash"] == "c4"
    assert snapshot["commits"][0]["shortHash"] == "c4"


def test_commit_sync_treats_all_commits_as_missed_without_history(
    tmp_path: Path, monkeypatch
):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(preferences, "PREFERENCES_PATH", state_file)

    service = CommitSyncService()
    project = upsert_project(local_path=str(tmp_path), remote_url="", preferred_model="")
    commits = [
        CommitInfo("c3", "c3", "A", "2026-01-03", "Third"),
        CommitInfo("c2", "c2", "A", "2026-01-02", "Second"),
        CommitInfo("c1", "c1", "A", "2026-01-01", "First"),
    ]

    snapshot = service.build_sync_snapshot_from_commits(project, commits)

    assert snapshot["missedCommitCount"] == 3
    assert snapshot["promptRequestCount"] == 2
    assert snapshot["defaultSelectedCommitHashes"] == ["c3"]


def test_retrieval_index_service_limits_repo_context_to_changed_files(
    tmp_path: Path, monkeypatch
):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(preferences, "PREFERENCES_PATH", state_file)

    write_file(tmp_path / "app" / "service.py", "def run():\n    return True\n")
    write_file(tmp_path / "app" / "__init__.py", "from .service import run\n")
    write_file(tmp_path / "README.md", "top level docs")

    project = upsert_project(
        local_path=str(tmp_path), remote_url="", preferred_model=""
    )
    commits = [CommitInfo("c1", "c1", "A", "2026-01-01", "Change service")]

    service = RetrievalIndexService()
    monkeypatch.setattr(
        service._commit_sync_service,
        "load_diff",
        lambda project, commit_hash: "\n".join(
            [
                "diff --git a/app/service.py b/app/service.py",
                "+++ b/app/service.py",
                "@@ -1 +1 @@",
                "-def run():",
                "+def run(flag=True):",
            ]
        ),
    )

    documents, repo_context, _ = service.build_index(
        project,
        commits,
        selected_commit_hashes=["c1"],
    )

    kinds = {document.kind for document in documents}
    paths = {snippet.path for snippet in repo_context}

    assert "diff_chunk" in kinds
    assert "repo_context" in kinds
    assert "app/service.py" in paths
    assert "README.md" not in paths


def test_blind_spot_service_blocks_generation_on_high_severity():
    service = BlindSpotService()
    analysis = AnalysisResult(
        agent_intent="Ship auth flow",
        user_intent="Add auth",
        blind_spots=[
            BlindSpot(
                title="Auth scope is missing",
                reason="Protected routes are not defined.",
                severity="high",
            )
        ],
    )

    guarded = service.apply_guards(
        analysis,
        current_prompt="Add auth",
        selected_commit_hashes=["c1"],
        retrieval_hits=[],
    )

    assert guarded.can_generate_final_prompt is False

    with pytest.raises(RuntimeError, match="Final prompt generation is blocked"):
        service.require_clear_to_generate(guarded)
