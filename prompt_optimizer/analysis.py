from __future__ import annotations

import json
import re
from typing import Any

from prompt_optimizer.models import (
    AnalysisResult,
    BlindSpot,
    ClarificationQuestion,
    RepoContextSnippet,
)

INITIAL_ANALYSIS_SYSTEM_PROMPT = """You analyze coding diffs and prompts.

Return strict JSON with this schema:
{
  "agent_intent": "string",
  "user_intent": "string",
  "missing_info": ["string"],
  "blind_spots": [
    {
      "title": "string",
      "reason": "string",
      "severity": "high|medium|low"
    }
  ],
  "followup_questions": [
    {
      "question": "string",
      "options": ["string", "string", "string"]
    }
  ],
  "can_generate_final_prompt": true
}

Rules:
- Be concrete and concise.
- Explain what the coding agent appears to be implementing from the diff.
- Explain what the human prompt appears to request.
- List only real gaps in missing_info.
- Add blind_spots only for real contradictions, ambiguity, or likely missing intent.
- Mark severity as high when the issue should block final prompt generation.
- Write agent_intent, user_intent, missing_info, and followup_questions in the requested UI language.
- Ask at most 4 high-value clarification questions.
- Each followup question must include exactly 3 realistic, mutually exclusive answer options.
- Set can_generate_final_prompt to false when any high-severity blind spot remains unresolved.
- Do not generate the final prompt in this step.
- Do not include markdown fences or extra text outside JSON.
"""

FINAL_PROMPT_SYSTEM_PROMPT = """You write the final implementation prompt.

Return strict JSON with this schema:
{
  "final_prompt": "string"
}

Rules:
- final_prompt must always be written in English.
- Use the original prompt, diff, repository context, initial analysis, and clarification answers.
- Be concrete and implementation-ready.
- Preserve important constraints from the user's request.
- If something is still uncertain, state the assumption briefly inside the final prompt.
- Do not include markdown fences or extra text outside JSON.
"""

DEFAULT_FALLBACK_OPTIONS = [
    "Keep the current behavior",
    "Use a stricter implementation",
    "Choose a different direction",
]


def build_analysis_payload(
    prompt_text: str,
    diff_text: str,
    repo_context: list[RepoContextSnippet],
    ui_language: str,
    retrieved_evidence: list[str] | None = None,
) -> str:
    context_blocks = []

    for snippet in repo_context:
        context_blocks.append(
            "\n".join(
                [
                    f"Path: {snippet.path}",
                    f"Reason: {snippet.reason}",
                    "Content:",
                    snippet.content,
                ]
            )
        )

    return "\n\n".join(
        [
            f"Requested UI language: {ui_language}",
            "Prompt or plan from the user:",
            prompt_text.strip() or "(empty)",
            "Diff under analysis:",
            diff_text.strip() or "(empty)",
            "Retrieved evidence:",
            (
                "\n\n".join(retrieved_evidence or [])
                if retrieved_evidence
                else "(no retrieved evidence)"
            ),
            "Relevant repository context:",
            (
                "\n\n".join(context_blocks)
                if context_blocks
                else "(no repo context found)"
            ),
        ]
    )


def build_final_prompt_payload(
    prompt_text: str,
    diff_text: str,
    repo_context: list[RepoContextSnippet],
    analysis_result: AnalysisResult,
    clarification_answers: list[dict[str, str]],
    retrieved_evidence: list[str] | None = None,
) -> str:
    context_blocks = []
    missing_items = [f"- {item}" for item in analysis_result.missing_info] or [
        "- (none)"
    ]
    blind_spot_items = [
        f"- [{item.severity}] {item.title}: {item.reason}"
        for item in analysis_result.blind_spots
    ] or ["- (none)"]
    for snippet in repo_context:
        context_blocks.append(
            "\n".join(
                [
                    f"Path: {snippet.path}",
                    f"Reason: {snippet.reason}",
                    "Content:",
                    snippet.content,
                ]
            )
        )

    answer_blocks = []
    for answer in clarification_answers:
        answer_blocks.append(
            "\n".join(
                [
                    f"Question: {answer.get('question', '').strip()}",
                    f"Selected option: {answer.get('selected_option', '').strip() or '(none)'}",
                    f"Additional clarification: {answer.get('custom_text', '').strip() or '(none)'}",
                ]
            )
        )

    return "\n\n".join(
        [
            "Original prompt or plan:",
            prompt_text.strip() or "(empty)",
            "Diff under analysis:",
            diff_text.strip() or "(empty)",
            "Initial analysis:",
            "\n".join(
                [
                    f"Agent intent: {analysis_result.agent_intent}",
                    f"User intent: {analysis_result.user_intent}",
                    "Missing info:",
                    *missing_items,
                    "Blind spots:",
                    *blind_spot_items,
                    (
                        "Can generate final prompt now: yes"
                        if analysis_result.can_generate_final_prompt
                        else "Can generate final prompt now: no"
                    ),
                ]
            ),
            "Clarification answers:",
            "\n\n".join(answer_blocks) if answer_blocks else "(none)",
            "Retrieved evidence:",
            (
                "\n\n".join(retrieved_evidence or [])
                if retrieved_evidence
                else "(no retrieved evidence)"
            ),
            "Relevant repository context:",
            (
                "\n\n".join(context_blocks)
                if context_blocks
                else "(no repo context found)"
            ),
        ]
    )


def extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        code_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if code_match:
            text = code_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Model response did not contain a JSON object.") from None
        return json.loads(match.group(0))


def parse_analysis_response(raw_text: str) -> AnalysisResult:
    payload = extract_json_object(raw_text)

    def ensure_string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def parse_followup_questions(value: Any) -> list[ClarificationQuestion]:
        questions: list[ClarificationQuestion] = []

        if not isinstance(value, list):
            return questions

        for item in value:
            if isinstance(item, dict):
                question = str(item.get("question", "")).strip()
                options_raw = item.get("options", [])
                if isinstance(options_raw, list):
                    options = [
                        str(option).strip()
                        for option in options_raw
                        if str(option).strip()
                    ]
                else:
                    options = []
                if question:
                    normalized = (options + DEFAULT_FALLBACK_OPTIONS)[:3]
                    questions.append(
                        ClarificationQuestion(
                            question=question,
                            options=normalized,
                        )
                    )
            elif isinstance(item, str) and item.strip():
                questions.append(
                    ClarificationQuestion(
                        question=item.strip(),
                        options=DEFAULT_FALLBACK_OPTIONS.copy(),
                    )
                )

        return questions

    def parse_blind_spots(value: Any) -> list[BlindSpot]:
        blind_spots: list[BlindSpot] = []
        if not isinstance(value, list):
            return blind_spots

        for item in value:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            reason = str(item.get("reason", "")).strip()
            severity = str(item.get("severity", "medium")).strip().lower() or "medium"
            if title and reason:
                blind_spots.append(
                    BlindSpot(
                        title=title,
                        reason=reason,
                        severity=(
                            severity
                            if severity in {"high", "medium", "low"}
                            else "medium"
                        ),
                    )
                )
        return blind_spots

    return AnalysisResult(
        agent_intent=str(payload.get("agent_intent", "")).strip(),
        user_intent=str(payload.get("user_intent", "")).strip(),
        missing_info=ensure_string_list(payload.get("missing_info")),
        blind_spots=parse_blind_spots(payload.get("blind_spots")),
        followup_questions=parse_followup_questions(payload.get("followup_questions")),
        can_generate_final_prompt=bool(payload.get("can_generate_final_prompt", True)),
        improved_prompt=str(payload.get("improved_prompt", "")).strip(),
        raw_response=raw_text,
    )


def parse_final_prompt_response(raw_text: str) -> str:
    payload = extract_json_object(raw_text)
    return str(payload.get("final_prompt", "")).strip()


def analyze_for_clarification(
    prompt_text: str,
    diff_text: str,
    repo_context: list[RepoContextSnippet],
    ui_language: str,
    retrieved_evidence: list[str] | None = None,
    model: str = "",
    provider: Any | None = None,
) -> AnalysisResult:
    if provider is None:
        from prompt_optimizer.providers import DEFAULT_OLLAMA_MODEL, OllamaProvider

        provider = OllamaProvider()
        model = model or DEFAULT_OLLAMA_MODEL

    return provider.analyze_for_clarification(
        prompt_text=prompt_text,
        diff_text=diff_text,
        repo_context=repo_context,
        retrieved_evidence=retrieved_evidence or [],
        ui_language=ui_language,
        model=model,
    )


def generate_final_prompt(
    prompt_text: str,
    diff_text: str,
    repo_context: list[RepoContextSnippet],
    analysis_result: AnalysisResult,
    clarification_answers: list[dict[str, str]],
    retrieved_evidence: list[str] | None = None,
    model: str = "",
    provider: Any | None = None,
) -> str:
    if provider is None:
        from prompt_optimizer.providers import DEFAULT_OLLAMA_MODEL, OllamaProvider

        provider = OllamaProvider()
        model = model or DEFAULT_OLLAMA_MODEL

    return provider.generate_final_prompt(
        prompt_text=prompt_text,
        diff_text=diff_text,
        repo_context=repo_context,
        retrieved_evidence=retrieved_evidence or [],
        analysis_result=analysis_result,
        clarification_answers=clarification_answers,
        model=model,
    )
