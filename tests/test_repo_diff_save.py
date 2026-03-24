from pathlib import Path

from prompt_optimizer import repo_ops


def test_save_diff_to_app_storage(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(repo_ops, "APP_DIFFS_DIR", tmp_path / "saved-diffs")
    repo_ops.APP_DIFFS_DIR.mkdir(parents=True, exist_ok=True)

    target = repo_ops.save_diff_to_app_storage(
        "abc123_test.diff",
        "diff --git a/a.py b/a.py",
    )

    assert target == tmp_path / "saved-diffs" / "abc123_test.diff"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "diff --git a/a.py b/a.py"
