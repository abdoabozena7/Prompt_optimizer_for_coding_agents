from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prompt_optimizer.models import RetrievalDocument
from prompt_optimizer.preferences import load_app_state, save_app_state

PROJECTS_KEY = "projects"
SYNC_NOTICE_COMPACTION_THRESHOLD = 4


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_local_path(local_path: str) -> str:
    return str(Path(local_path).expanduser().resolve())


def project_id_from_path(local_path: str) -> str:
    normalized = normalize_local_path(local_path)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


@dataclass(slots=True)
class PromptEntry:
    id: str
    created_at: str
    prompt_text: str
    clarified_intent: str = ""
    inferred_user_intent: str = ""
    related_commit_hashes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProjectRecord:
    id: str
    name: str
    local_path: str
    remote_url: str = ""
    preferred_model: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_seen_remote_commit: str = ""
    last_processed_commit: str = ""
    prompt_history: list[PromptEntry] = field(default_factory=list)
    retrieval_documents: list[RetrievalDocument] = field(default_factory=list)


def _prompt_entry_from_dict(payload: dict[str, Any]) -> PromptEntry:
    return PromptEntry(
        id=str(payload.get("id", "")).strip()
        or hashlib.sha1(
            str(payload.get("created_at", utc_now_iso())).encode("utf-8")
        ).hexdigest()[:12],
        created_at=str(payload.get("created_at", utc_now_iso())).strip(),
        prompt_text=str(payload.get("prompt_text", "")).strip(),
        clarified_intent=str(payload.get("clarified_intent", "")).strip(),
        inferred_user_intent=str(payload.get("inferred_user_intent", "")).strip(),
        related_commit_hashes=[
            str(item).strip()
            for item in payload.get("related_commit_hashes", [])
            if str(item).strip()
        ],
    )


def _project_from_dict(payload: dict[str, Any]) -> ProjectRecord:
    local_path = normalize_local_path(str(payload.get("local_path", "")).strip())
    name = str(payload.get("name", "")).strip() or Path(local_path).name or local_path
    return ProjectRecord(
        id=str(payload.get("id", "")).strip() or project_id_from_path(local_path),
        name=name,
        local_path=local_path,
        remote_url=str(payload.get("remote_url", "")).strip(),
        preferred_model=str(payload.get("preferred_model", "")).strip(),
        created_at=str(payload.get("created_at", utc_now_iso())).strip(),
        updated_at=str(payload.get("updated_at", utc_now_iso())).strip(),
        last_seen_remote_commit=str(payload.get("last_seen_remote_commit", "")).strip(),
        last_processed_commit=str(payload.get("last_processed_commit", "")).strip(),
        prompt_history=[
            _prompt_entry_from_dict(item)
            for item in payload.get("prompt_history", [])
            if isinstance(item, dict)
        ],
        retrieval_documents=[
            RetrievalDocument(
                id=str(item.get("id", "")).strip(),
                kind=str(item.get("kind", "")).strip(),
                title=str(item.get("title", "")).strip(),
                content=str(item.get("content", "")).strip(),
                project_id=str(item.get("project_id", "")).strip(),
                commit_hash=str(item.get("commit_hash", "")).strip(),
                file_path=str(item.get("file_path", "")).strip(),
                summary=str(item.get("summary", "")).strip(),
                recency_rank=int(item.get("recency_rank", 0) or 0),
                metadata=(
                    {
                        str(key): str(value)
                        for key, value in item.get("metadata", {}).items()
                        if isinstance(key, str)
                    }
                    if isinstance(item.get("metadata"), dict)
                    else {}
                ),
            )
            for item in payload.get("retrieval_documents", [])
            if isinstance(item, dict)
        ],
    )


def _load_projects() -> list[ProjectRecord]:
    state = load_app_state()
    raw_projects = state.get(PROJECTS_KEY, [])
    if not isinstance(raw_projects, list):
        return []
    projects = [
        _project_from_dict(item) for item in raw_projects if isinstance(item, dict)
    ]
    return sorted(projects, key=lambda item: (item.name.lower(), item.local_path))


def _save_projects(projects: list[ProjectRecord]) -> None:
    state = load_app_state()
    state[PROJECTS_KEY] = [asdict(project) for project in projects]
    save_app_state(state)


def list_projects() -> list[ProjectRecord]:
    return _load_projects()


def get_project(project_id: str) -> ProjectRecord | None:
    for project in _load_projects():
        if project.id == project_id:
            return project
    return None


def upsert_project(
    *,
    local_path: str,
    remote_url: str = "",
    preferred_model: str = "",
) -> ProjectRecord:
    normalized_path = normalize_local_path(local_path)
    project_id = project_id_from_path(normalized_path)
    projects = _load_projects()
    now = utc_now_iso()

    for index, project in enumerate(projects):
        if project.id != project_id:
            continue
        updated = ProjectRecord(
            id=project.id,
            name=Path(normalized_path).name or project.name,
            local_path=normalized_path,
            remote_url=remote_url.strip(),
            preferred_model=preferred_model.strip(),
            created_at=project.created_at,
            updated_at=now,
            last_seen_remote_commit=project.last_seen_remote_commit,
            last_processed_commit=project.last_processed_commit,
            prompt_history=project.prompt_history,
            retrieval_documents=project.retrieval_documents,
        )
        projects[index] = updated
        _save_projects(projects)
        return updated

    created = ProjectRecord(
        id=project_id,
        name=Path(normalized_path).name or normalized_path,
        local_path=normalized_path,
        remote_url=remote_url.strip(),
        preferred_model=preferred_model.strip(),
        created_at=now,
        updated_at=now,
    )
    projects.append(created)
    _save_projects(projects)
    return created


def update_project(project: ProjectRecord) -> ProjectRecord:
    projects = _load_projects()
    for index, current in enumerate(projects):
        if current.id != project.id:
            continue
        project.updated_at = utc_now_iso()
        projects[index] = project
        _save_projects(projects)
        return project
    raise KeyError(project.id)


def append_prompt_history(
    project_id: str,
    *,
    prompt_text: str,
    clarified_intent: str,
    inferred_user_intent: str,
    related_commit_hashes: list[str],
) -> ProjectRecord:
    project = get_project(project_id)
    if project is None:
        raise KeyError(project_id)

    prompt_hash_source = f"{utc_now_iso()}\x1f{prompt_text.strip()}"
    project.prompt_history.append(
        PromptEntry(
            id=hashlib.sha1(prompt_hash_source.encode("utf-8")).hexdigest()[:12],
            created_at=utc_now_iso(),
            prompt_text=prompt_text.strip(),
            clarified_intent=clarified_intent.strip(),
            inferred_user_intent=inferred_user_intent.strip(),
            related_commit_hashes=[item for item in related_commit_hashes if item],
        )
    )
    if related_commit_hashes:
        project.last_processed_commit = related_commit_hashes[0]
    return update_project(project)


def replace_retrieval_documents(
    project_id: str, retrieval_documents: list[RetrievalDocument]
) -> ProjectRecord:
    project = get_project(project_id)
    if project is None:
        raise KeyError(project_id)

    project.retrieval_documents = retrieval_documents
    return update_project(project)


def commit_gap_count(commit_hashes: list[str], last_processed_commit: str) -> int:
    if not commit_hashes:
        return 0
    if not last_processed_commit:
        return len(commit_hashes)
    try:
        return commit_hashes.index(last_processed_commit)
    except ValueError:
        return len(commit_hashes)


def compact_prompt_entries(entries: list[str]) -> str:
    cleaned = [entry.strip() for entry in entries if entry and entry.strip()]
    if not cleaned:
        return ""
    lines = [
        f"- Prompt {index + 1}: {' '.join(entry.split())[:220]}"
        for index, entry in enumerate(cleaned)
    ]
    return "\n".join(lines)


def build_prompt_context(
    *,
    current_prompt: str,
    missed_prompt_trail: list[str],
    stored_history: list[PromptEntry],
    compact_after: int = SYNC_NOTICE_COMPACTION_THRESHOLD,
) -> str:
    sections: list[str] = []

    if stored_history:
        historical = stored_history[:-1]
        latest = stored_history[-1]
        if historical:
            sections.append(
                "Previous project prompt history (compacted):\n"
                + compact_prompt_entries([entry.prompt_text for entry in historical])
            )
        if latest.prompt_text.strip():
            sections.append(
                "Latest stored prompt before this run:\n" + latest.prompt_text.strip()
            )

    trail = [item.strip() for item in missed_prompt_trail if item and item.strip()]
    if len(trail) > compact_after:
        older = trail[:-1]
        newest = trail[-1]
        if older:
            sections.append(
                "Older prompts for missed commits (compacted, newest excluded):\n"
                + compact_prompt_entries(older)
            )
        sections.append("Latest prompt for the newest missed commit:\n" + newest)
    elif trail:
        sections.append(
            "Recent prompts for missed commits:\n"
            + "\n\n".join(
                f"Prompt {index + 1}:\n{prompt}" for index, prompt in enumerate(trail)
            )
        )

    if current_prompt.strip():
        sections.append(
            "Current user prompt (never compact this section):\n"
            + current_prompt.strip()
        )

    return "\n\n".join(section for section in sections if section.strip())
