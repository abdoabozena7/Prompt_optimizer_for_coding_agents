from __future__ import annotations

import json
import re
from typing import Any

from ollama import Client, ResponseError

from prompt_optimizer.models import (
    AnalysisResult,
    ClarificationQuestion,
    RepoContextSnippet,
)


INITIAL_ANALYSIS_SYSTEM_PROMPT = """You analyze coding diffs and prompts.

Return strict JSON with this schema:
{
  "agent_intent": "string",
  "user_intent": "string",
  "missing_info": ["string"],
  "followup_questions": [
    {
      "question": "string",
      "options": ["string", "string", "string"]
    }
  ]
}

Rules:
- Be concrete and concise.
- Explain what the coding agent appears to be implementing from the diff.
- Explain what the human prompt appears to request.
- List only real gaps in missing_info.
- Write agent_intent, user_intent, missing_info, and followup_questions in the requested UI language.
- Ask at most 4 high-value clarification questions.
- Each followup question must include exactly 3 realistic, mutually exclusive answer options.
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
            "Relevant repository context:",
            "\n\n".join(context_blocks) if context_blocks else "(no repo context found)",
        ]
    )


def build_final_prompt_payload(
    prompt_text: str,
    diff_text: str,
    repo_context: list[RepoContextSnippet],
    analysis_result: AnalysisResult,
    clarification_answers: list[dict[str, str]],
) -> str:
    context_blocks = []
    missing_items = [f"- {item}" for item in analysis_result.missing_info] or ["- (none)"]
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
                ]
            ),
            "Clarification answers:",
            "\n\n".join(answer_blocks) if answer_blocks else "(none)",
            "Relevant repository context:",
            "\n\n".join(context_blocks) if context_blocks else "(no repo context found)",
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
                    options = [str(option).strip() for option in options_raw if str(option).strip()]
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

    return AnalysisResult(
        agent_intent=str(payload.get("agent_intent", "")).strip(),
        user_intent=str(payload.get("user_intent", "")).strip(),
        missing_info=ensure_string_list(payload.get("missing_info")),
        followup_questions=parse_followup_questions(payload.get("followup_questions")),
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
    model: str = "gpt-oss:120b-cloud",
    client: Client | None = None,
) -> AnalysisResult:
    client = client or Client()
    payload = build_analysis_payload(
        prompt_text=prompt_text,
        diff_text=diff_text,
        repo_context=repo_context,
        ui_language=ui_language,
    )

    try:
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": INITIAL_ANALYSIS_SYSTEM_PROMPT},
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
    return parse_analysis_response(content)


def generate_final_prompt(
    prompt_text: str,
    diff_text: str,
    repo_context: list[RepoContextSnippet],
    analysis_result: AnalysisResult,
    clarification_answers: list[dict[str, str]],
    model: str = "gpt-oss:120b-cloud",
    client: Client | None = None,
) -> str:
    client = client or Client()
    payload = build_final_prompt_payload(
        prompt_text=prompt_text,
        diff_text=diff_text,
        repo_context=repo_context,
        analysis_result=analysis_result,
        clarification_answers=clarification_answers,
    )

    try:
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": FINAL_PROMPT_SYSTEM_PROMPT},
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
    return parse_final_prompt_response(content)
