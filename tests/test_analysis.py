import pytest

from prompt_optimizer.analysis import (
    build_analysis_payload,
    build_final_prompt_payload,
    parse_analysis_response,
    parse_final_prompt_response,
)
from prompt_optimizer.models import AnalysisResult, RepoContextSnippet


def test_build_analysis_payload_contains_all_inputs():
    payload = build_analysis_payload(
        prompt_text="Add auth",
        diff_text="diff --git a/app.py b/app.py",
        ui_language="Arabic",
        repo_context=[
            RepoContextSnippet(
                path="app.py", content="print('x')", reason="changed file"
            )
        ],
    )

    assert "Requested UI language: Arabic" in payload
    assert "Add auth" in payload
    assert "diff --git a/app.py b/app.py" in payload
    assert "Path: app.py" in payload


def test_build_final_prompt_payload_contains_answers():
    payload = build_final_prompt_payload(
        prompt_text="Add auth",
        diff_text="diff --git a/app.py b/app.py",
        repo_context=[
            RepoContextSnippet(
                path="app.py", content="print('x')", reason="changed file"
            )
        ],
        analysis_result=AnalysisResult(
            agent_intent="Implement login flow",
            user_intent="Ask for auth",
            missing_info=["Token expiry"],
        ),
        clarification_answers=[
            {
                "question": "Which auth strategy?",
                "selected_option": "JWT",
                "custom_text": "Access token only",
            }
        ],
    )

    assert "Selected option: JWT" in payload
    assert "Additional clarification: Access token only" in payload


def test_parse_analysis_response_complete():
    raw = """
    {
      "agent_intent": "Implement login flow",
      "user_intent": "Ask for secure auth changes",
      "missing_info": ["Token expiry is missing"],
      "followup_questions": [
        {
          "question": "Should refresh tokens be added?",
          "options": ["Yes, add them", "No, access token only", "Keep current token flow"]
        }
      ]
    }
    """
    result = parse_analysis_response(raw)

    assert result.agent_intent == "Implement login flow"
    assert result.user_intent == "Ask for secure auth changes"
    assert result.missing_info == ["Token expiry is missing"]
    assert result.followup_questions[0].question == "Should refresh tokens be added?"
    assert result.followup_questions[0].options == [
        "Yes, add them",
        "No, access token only",
        "Keep current token flow",
    ]


def test_parse_analysis_response_from_markdown_fence():
    raw = """```json
    {
      "agent_intent": "Refactor API client",
      "user_intent": "Improve request handling",
      "missing_info": [],
      "followup_questions": []
    }
    ```"""
    result = parse_analysis_response(raw)
    assert result.agent_intent == "Refactor API client"


def test_parse_analysis_response_malformed():
    with pytest.raises(ValueError):
        parse_analysis_response("not json at all")


def test_parse_final_prompt_response():
    raw = """
    {
      "final_prompt": "Implement JWT auth with explicit expiry and updated tests."
    }
    """
    assert parse_final_prompt_response(raw) == (
        "Implement JWT auth with explicit expiry and updated tests."
    )
