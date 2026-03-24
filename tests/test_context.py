from pathlib import Path

from prompt_optimizer.context import build_repo_context


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_repo_context_prefers_changed_and_related_files(tmp_path: Path):
    write_file(tmp_path / "app" / "service.py", "def changed():\n    return 1\n")
    write_file(tmp_path / "app" / "__init__.py", "from .service import changed\n")
    write_file(tmp_path / "app" / "service_test.py", "def test_changed():\n    assert True\n")
    write_file(tmp_path / "README.md", "top level")

    snippets = build_repo_context(tmp_path, ["app/service.py"])
    paths = [snippet.path for snippet in snippets]

    assert "app/service.py" in paths
    assert "app/__init__.py" in paths
    assert "README.md" not in paths


def test_build_repo_context_skips_missing_files(tmp_path: Path):
    assert build_repo_context(tmp_path, ["missing.py"]) == []

