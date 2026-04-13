from prompt_optimizer import preferences
from prompt_optimizer.project_memory import (
    build_prompt_context,
    commit_gap_count,
    list_projects,
    upsert_project,
)


def test_upsert_project_reuses_same_normalized_path(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(preferences, "PREFERENCES_PATH", state_file)

    project = upsert_project(
        local_path=str(tmp_path / "demo"),
        remote_url="https://github.com/example/repo",
        preferred_model="model-a",
    )
    updated = upsert_project(
        local_path=str(tmp_path / "demo"),
        remote_url="https://github.com/example/other",
        preferred_model="model-b",
    )

    projects = list_projects()
    assert len(projects) == 1
    assert project.id == updated.id
    assert projects[0].remote_url == "https://github.com/example/other"
    assert projects[0].preferred_model == "model-b"


def test_commit_gap_count_uses_last_processed_commit():
    commit_hashes = ["c4", "c3", "c2", "c1"]

    assert commit_gap_count(commit_hashes, "c2") == 2
    assert commit_gap_count(commit_hashes, "missing") == 4
    assert commit_gap_count(commit_hashes, "") == 4


def test_build_prompt_context_compacts_older_missed_prompts():
    prompt_text = build_prompt_context(
        current_prompt="Current user prompt must stay verbatim.",
        missed_prompt_trail=[
            "Prompt one with a lot of detail.",
            "Prompt two with a lot of detail.",
            "Prompt three with a lot of detail.",
            "Prompt four with a lot of detail.",
            "Prompt five should stay verbatim.",
        ],
        stored_history=[],
        compact_after=4,
    )

    assert "Current user prompt (never compact this section):" in prompt_text
    assert "Current user prompt must stay verbatim." in prompt_text
    assert (
        "Older prompts for missed commits (compacted, newest excluded):" in prompt_text
    )
    assert (
        "Latest prompt for the newest missed commit:\nPrompt five should stay verbatim."
        in prompt_text
    )
