from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ollama import Client, ResponseError

from prompt_optimizer.analysis import (
    FINAL_PROMPT_SYSTEM_PROMPT,
    INITIAL_ANALYSIS_SYSTEM_PROMPT,
    build_analysis_payload,
    build_final_prompt_payload,
    parse_analysis_response,
    parse_final_prompt_response,
)
from prompt_optimizer.models import AnalysisResult, RepoContextSnippet

DEFAULT_OLLAMA_MODEL = "gpt-oss:120b-cloud"


class PromptOptimizerProvider(Protocol):
    def list_models(self) -> list[str]:
        """Return available model identifiers."""

    def analyze_for_clarification(
        self,
        prompt_text: str,
        diff_text: str,
        repo_context: list[RepoContextSnippet],
        ui_language: str,
        model: str,
    ) -> AnalysisResult:
        """Analyze a prompt/diff pair and return clarification guidance."""

    def generate_final_prompt(
        self,
        prompt_text: str,
        diff_text: str,
        repo_context: list[RepoContextSnippet],
        analysis_result: AnalysisResult,
        clarification_answers: list[dict[str, str]],
        model: str,
    ) -> str:
        """Generate the final implementation-ready prompt."""


@dataclass(slots=True)
class ModelSelection:
    requested_model: str
    resolved_model: str
    available_models: list[str]
    used_fallback: bool = False


def select_preferred_model(
    available_models: list[str],
    requested_model: str,
    *,
    default_model: str = DEFAULT_OLLAMA_MODEL,
) -> ModelSelection:
    models = [model.strip() for model in available_models if model and model.strip()]
    if not models:
        raise RuntimeError(
            "No Ollama models are available. Pull a model first, then try again."
        )

    preferred = requested_model.strip() or default_model
    if preferred in models:
        return ModelSelection(
            requested_model=preferred,
            resolved_model=preferred,
            available_models=models,
            used_fallback=False,
        )

    return ModelSelection(
        requested_model=preferred,
        resolved_model=models[0],
        available_models=models,
        used_fallback=True,
    )


class OllamaProvider:
    def __init__(self, client: Client | None = None) -> None:
        self._client = client or Client()

    def list_models(self) -> list[str]:
        try:
            response = self._client.list()
        except ResponseError as exc:
            raise RuntimeError(f"Ollama request failed: {exc.error}") from exc
        except Exception as exc:
            raise RuntimeError(f"Could not reach Ollama: {exc}") from exc

        models = response.get("models", [])
        names: list[str] = []
        seen: set[str] = set()

        for model in models:
            name = str(model.get("model") or model.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)

        return names

    def analyze_for_clarification(
        self,
        prompt_text: str,
        diff_text: str,
        repo_context: list[RepoContextSnippet],
        ui_language: str,
        model: str,
    ) -> AnalysisResult:
        payload = build_analysis_payload(
            prompt_text=prompt_text,
            diff_text=diff_text,
            repo_context=repo_context,
            ui_language=ui_language,
        )
        content = self._chat_json(
            model=model,
            system_prompt=INITIAL_ANALYSIS_SYSTEM_PROMPT,
            payload=payload,
        )
        try:
            return parse_analysis_response(content)
        except ValueError as exc:
            raise RuntimeError(
                f"Model returned invalid JSON for analysis: {exc}"
            ) from exc

    def generate_final_prompt(
        self,
        prompt_text: str,
        diff_text: str,
        repo_context: list[RepoContextSnippet],
        analysis_result: AnalysisResult,
        clarification_answers: list[dict[str, str]],
        model: str,
    ) -> str:
        payload = build_final_prompt_payload(
            prompt_text=prompt_text,
            diff_text=diff_text,
            repo_context=repo_context,
            analysis_result=analysis_result,
            clarification_answers=clarification_answers,
        )
        content = self._chat_json(
            model=model,
            system_prompt=FINAL_PROMPT_SYSTEM_PROMPT,
            payload=payload,
        )
        try:
            return parse_final_prompt_response(content)
        except ValueError as exc:
            raise RuntimeError(
                f"Model returned invalid JSON for final prompt generation: {exc}"
            ) from exc

    def _chat_json(self, model: str, system_prompt: str, payload: str) -> str:
        try:
            response = self._client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": payload},
                ],
                options={"temperature": 0.2},
                format="json",
            )
        except ResponseError as exc:
            raise RuntimeError(f"Ollama request failed: {exc.error}") from exc
        except Exception as exc:
            raise RuntimeError(f"Could not reach Ollama: {exc}") from exc

        message = response.get("message", {})
        content = str(message.get("content", "")).strip()
        if not content:
            raise RuntimeError("Ollama returned an empty response.")
        return content
