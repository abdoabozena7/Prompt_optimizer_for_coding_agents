from __future__ import annotations

from pathlib import Path

from prompt_optimizer.models import RepoContextSnippet

MAX_FILE_CHARS = 6000
RELATED_FILES_PER_DIR = 2


def read_text_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    except OSError:
        return None

    if not text.strip():
        return None
    return text[:MAX_FILE_CHARS]


def _candidate_related_files(target_path: Path) -> list[Path]:
    parent = target_path.parent
    if not parent.exists():
        return []

    stem = target_path.stem.lower()
    extension = target_path.suffix.lower()
    scored: list[tuple[int, Path]] = []

    for child in parent.iterdir():
        if child == target_path or not child.is_file():
            continue

        score = 0
        if child.name == "__init__.py":
            score += 5
        if child.stem.lower() == stem:
            score += 4
        if extension and child.suffix.lower() == extension:
            score += 2
        if child.name in {"package.json", "pyproject.toml", "requirements.txt"}:
            score += 3
        if score > 0:
            scored.append((score, child))

    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [path for _, path in scored[:RELATED_FILES_PER_DIR]]


def build_repo_context(
    repo_path: Path | None, changed_paths: list[str]
) -> list[RepoContextSnippet]:
    if repo_path is None:
        return []

    repo_root = repo_path.resolve()
    snippets: list[RepoContextSnippet] = []
    seen: set[Path] = set()

    for relative_path in changed_paths:
        candidate = (repo_root / relative_path).resolve()
        try:
            relative_candidate = candidate.relative_to(repo_root)
        except ValueError:
            continue
        if not candidate.exists() or not candidate.is_file():
            continue

        text = read_text_file(candidate)
        if text:
            snippets.append(
                RepoContextSnippet(
                    path=relative_candidate.as_posix(),
                    content=text,
                    reason="changed file",
                )
            )
            seen.add(candidate)

        for related in _candidate_related_files(candidate):
            if related in seen:
                continue
            text = read_text_file(related)
            if not text:
                continue
            try:
                relative_related = related.relative_to(repo_root)
            except ValueError:
                continue
            snippets.append(
                RepoContextSnippet(
                    path=relative_related.as_posix(),
                    content=text,
                    reason=f"related to {relative_path}",
                )
            )
            seen.add(related)

    return snippets
