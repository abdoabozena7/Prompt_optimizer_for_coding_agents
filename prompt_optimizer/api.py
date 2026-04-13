from __future__ import annotations

import re
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from prompt_optimizer.commit_sync_service import CommitSyncService
from prompt_optimizer.intent_analysis_service import IntentAnalysisService
from prompt_optimizer.models import AnalysisResult, BlindSpot
from prompt_optimizer.project_memory import (
    append_prompt_history,
    get_project,
    list_projects,
    upsert_project,
)
from prompt_optimizer.providers import (
    DEFAULT_OLLAMA_MODEL,
    OllamaProvider,
    select_preferred_model,
)
from prompt_optimizer.repo_ops import ensure_local_project_path
from prompt_optimizer.retrieval_index_service import RetrievalIndexService


class ProjectUpsertRequest(BaseModel):
    local_path: str = Field(min_length=1)
    remote_url: str = ""
    preferred_model: str = ""


class AnalyzeRequest(BaseModel):
    current_prompt: str = ""
    missed_prompts_blob: str = ""
    missed_prompts: list[str] = Field(default_factory=list)
    selected_commit_hashes: list[str] = Field(default_factory=list)
    ui_language: str = "en"
    model: str = ""


class ClarificationAnswerPayload(BaseModel):
    question: str
    selected_option: str = ""
    custom_text: str = ""


class FinalizeRequest(AnalyzeRequest):
    clarification_answers: list[ClarificationAnswerPayload] = Field(
        default_factory=list
    )
    analysis_result: dict[str, Any]
    clarified_intent: str = ""


def parse_prompt_blob(blob: str) -> list[str]:
    if not blob.strip():
        return []
    return [
        chunk.strip()
        for chunk in re.split(r"(?m)^\s*---\s*$", blob.strip())
        if chunk.strip()
    ]


def parse_missed_prompts(payload: AnalyzeRequest) -> list[str]:
    if payload.missed_prompts:
        return [item.strip() for item in payload.missed_prompts if item.strip()]
    return parse_prompt_blob(payload.missed_prompts_blob)


def validate_missed_prompt_count(
    missed_prompts: list[str], expected_prompt_count: int
) -> None:
    if len(missed_prompts) > expected_prompt_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Expected at most {expected_prompt_count} prompt notes for older missed commits, "
                f"received {len(missed_prompts)}."
            ),
        )


def project_to_payload(project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "localPath": project.local_path,
        "remoteUrl": project.remote_url,
        "preferredModel": project.preferred_model,
        "createdAt": project.created_at,
        "updatedAt": project.updated_at,
        "lastSeenRemoteCommit": project.last_seen_remote_commit,
        "lastProcessedCommit": project.last_processed_commit,
        "promptHistoryCount": len(project.prompt_history),
    }


def load_project_or_404(project_id: str):
    project = get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def resolve_model(requested_model: str, preferred_model: str) -> dict[str, Any]:
    provider = OllamaProvider()
    available_models = provider.list_models()
    selection = select_preferred_model(
        available_models,
        requested_model or preferred_model or DEFAULT_OLLAMA_MODEL,
    )
    return {"provider": provider, "selection": selection}


def parse_analysis_result(payload: dict[str, Any]) -> AnalysisResult:
    blind_spots = []
    for item in payload.get("blind_spots", []):
        if not isinstance(item, dict):
            continue
        blind_spots.append(
            BlindSpot(
                title=str(item.get("title", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
                severity=str(item.get("severity", "medium")).strip() or "medium",
            )
        )

    return AnalysisResult(
        agent_intent=str(payload.get("agent_intent", "")).strip(),
        user_intent=str(payload.get("user_intent", "")).strip(),
        missing_info=[
            str(item).strip()
            for item in payload.get("missing_info", [])
            if str(item).strip()
        ],
        blind_spots=[item for item in blind_spots if item.title and item.reason],
        can_generate_final_prompt=bool(payload.get("can_generate_final_prompt", True)),
        followup_questions=[],
        improved_prompt=str(payload.get("improved_prompt", "")).strip(),
        raw_response=str(payload.get("raw_response", "")).strip(),
    )


def pick_directory() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError(
            "Native folder picker is unavailable in this Python environment."
        ) from exc

    selection: dict[str, str] = {"path": ""}
    error: dict[str, Exception] = {}

    def _run_dialog() -> None:
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selection["path"] = filedialog.askdirectory(
                title="Choose local project folder"
            )
            root.destroy()
        except Exception as exc:  # pragma: no cover
            error["value"] = exc

    thread = threading.Thread(target=_run_dialog)
    thread.start()
    thread.join()

    if error:
        raise RuntimeError("Failed to open the native folder picker.") from error[
            "value"
        ]

    return selection["path"].strip()


commit_sync_service = CommitSyncService()
retrieval_index_service = RetrievalIndexService(commit_sync_service)
intent_analysis_service = IntentAnalysisService(retrieval_index_service)

app = FastAPI(title="Prompt Optimizer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models")
def get_models() -> dict[str, Any]:
    try:
        data = resolve_model("", "")
    except RuntimeError as exc:
        return {
            "models": [],
            "defaultModel": DEFAULT_OLLAMA_MODEL,
            "error": str(exc),
        }

    selection = data["selection"]
    return {
        "models": selection.available_models,
        "defaultModel": selection.resolved_model,
    }


@app.post("/api/system/pick-project-directory")
def pick_project_directory() -> dict[str, str]:
    try:
        selected_path = pick_directory()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not selected_path:
        raise HTTPException(status_code=400, detail="No folder was selected.")

    return {"path": selected_path}


@app.get("/api/projects")
def get_projects() -> dict[str, Any]:
    return {"projects": [project_to_payload(project) for project in list_projects()]}


@app.post("/api/projects")
def save_project(payload: ProjectUpsertRequest) -> dict[str, Any]:
    try:
        ensure_local_project_path(payload.local_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    project = upsert_project(
        local_path=payload.local_path,
        remote_url=payload.remote_url,
        preferred_model=payload.preferred_model,
    )
    return {"project": project_to_payload(project)}


@app.get("/api/projects/{project_id}")
def get_project_detail(project_id: str) -> dict[str, Any]:
    project = load_project_or_404(project_id)
    try:
        commits = commit_sync_service.load_commits(project)
        snapshot = commit_sync_service.build_sync_snapshot_from_commits(
            project, commits
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"project": project_to_payload(project), "sync": snapshot}


@app.post("/api/projects/{project_id}/refresh")
def refresh_project(project_id: str) -> dict[str, Any]:
    project = load_project_or_404(project_id)
    try:
        commits = commit_sync_service.load_commits(project)
        snapshot = commit_sync_service.build_sync_snapshot_from_commits(
            project, commits
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"project": project_to_payload(project), "sync": snapshot}


@app.get("/api/projects/{project_id}/selection/default")
def get_default_selection(project_id: str) -> dict[str, list[str]]:
    project = load_project_or_404(project_id)
    try:
        commits = commit_sync_service.load_commits(project)
        snapshot = commit_sync_service.build_sync_snapshot_from_commits(
            project, commits
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"selectedCommitHashes": snapshot["defaultSelectedCommitHashes"]}


@app.get("/api/projects/{project_id}/diff/{commit_hash}")
def get_diff(project_id: str, commit_hash: str) -> dict[str, str]:
    project = load_project_or_404(project_id)
    try:
        diff_text = commit_sync_service.load_diff(project, commit_hash)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"commitHash": commit_hash, "diff": diff_text}


@app.get("/api/projects/{project_id}/diff-summary/{commit_hash}")
def get_diff_summary(project_id: str, commit_hash: str) -> dict[str, str]:
    project = load_project_or_404(project_id)
    try:
        summary = retrieval_index_service.summarize_commit(project, commit_hash)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"commitHash": commit_hash, "summary": summary}


@app.post("/api/projects/{project_id}/analyze")
def analyze_project(project_id: str, payload: AnalyzeRequest) -> dict[str, Any]:
    project = load_project_or_404(project_id)
    try:
        commits = commit_sync_service.load_commits(project)
        snapshot = commit_sync_service.build_sync_snapshot_from_commits(
            project, commits
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    missed_prompts = parse_missed_prompts(payload)
    expected_prompt_count = int(snapshot["promptRequestCount"])
    validate_missed_prompt_count(missed_prompts, expected_prompt_count)

    try:
        resolved = resolve_model(payload.model, project.preferred_model)
        selection = resolved["selection"]
        analysis_result, curated_context = intent_analysis_service.analyze(
            provider=resolved["provider"],
            model=selection.resolved_model,
            project=project,
            commits=commits,
            current_prompt=payload.current_prompt,
            missed_prompts=missed_prompts,
            selected_commit_hashes=payload.selected_commit_hashes,
            ui_language=payload.ui_language,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "analysis": {
            "agentIntent": analysis_result.agent_intent,
            "userIntent": analysis_result.user_intent,
            "missingInfo": analysis_result.missing_info,
            "blindSpots": [asdict(item) for item in analysis_result.blind_spots],
            "followupQuestions": [
                asdict(question) for question in analysis_result.followup_questions
            ],
            "canGenerateFinalPrompt": analysis_result.can_generate_final_prompt,
            "retrievedEvidence": curated_context.retrieved_evidence[:6],
        },
        "sync": snapshot,
        "selectedModel": selection.resolved_model,
        "usedFallbackModel": selection.used_fallback,
    }


@app.post("/api/projects/{project_id}/finalize")
def finalize_project(project_id: str, payload: FinalizeRequest) -> dict[str, Any]:
    project = load_project_or_404(project_id)
    try:
        commits = commit_sync_service.load_commits(project)
        snapshot = commit_sync_service.build_sync_snapshot_from_commits(
            project, commits
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    missed_prompts = parse_missed_prompts(payload)
    expected_prompt_count = int(snapshot["promptRequestCount"])
    validate_missed_prompt_count(missed_prompts, expected_prompt_count)

    analysis_result = parse_analysis_result(payload.analysis_result)
    if payload.clarified_intent.strip():
        analysis_result.user_intent = payload.clarified_intent.strip()

    try:
        resolved = resolve_model(payload.model, project.preferred_model)
        selection = resolved["selection"]
        final_prompt, _ = intent_analysis_service.finalize(
            provider=resolved["provider"],
            model=selection.resolved_model,
            project=project,
            commits=commits,
            current_prompt=payload.current_prompt,
            missed_prompts=missed_prompts,
            selected_commit_hashes=payload.selected_commit_hashes,
            analysis_result=analysis_result,
            clarification_answers=[
                answer.model_dump() for answer in payload.clarification_answers
            ],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated_project = append_prompt_history(
        project_id,
        prompt_text=payload.current_prompt,
        clarified_intent=payload.clarified_intent or analysis_result.user_intent,
        inferred_user_intent=analysis_result.user_intent,
        related_commit_hashes=payload.selected_commit_hashes,
    )
    refreshed_commits = commit_sync_service.load_commits(updated_project)
    refreshed = commit_sync_service.build_sync_snapshot_from_commits(
        updated_project, refreshed_commits
    )

    return {
        "finalPrompt": final_prompt,
        "project": project_to_payload(updated_project),
        "sync": refreshed,
        "selectedModel": selection.resolved_model,
        "usedFallbackModel": selection.used_fallback,
    }


frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
frontend_assets = frontend_dist / "assets"

if frontend_assets.exists():
    app.mount("/assets", StaticFiles(directory=frontend_assets), name="assets")


@app.get("/{path:path}")
def serve_frontend(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    requested = frontend_dist / path
    if path and requested.exists() and requested.is_file():
        return FileResponse(requested)

    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    return JSONResponse(
        {
            "detail": "Frontend build not found. Run the React build or start the dev server."
        },
        status_code=503,
    )
