import pytest
from ollama import ResponseError

from prompt_optimizer.models import AnalysisResult, RepoContextSnippet
from prompt_optimizer.providers import (
    DEFAULT_OLLAMA_MODEL,
    OllamaProvider,
    select_preferred_model,
)


class FakeOllamaClient:
    def __init__(
        self,
        *,
        models=None,
        chat_response=None,
        list_error=None,
        chat_error=None,
    ):
        self._models = models if models is not None else []
        self._chat_response = chat_response
        self._list_error = list_error
        self._chat_error = chat_error
        self.calls: list[dict] = []

    def list(self):
        if self._list_error is not None:
            raise self._list_error
        return {"models": self._models}

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self._chat_error is not None:
            raise self._chat_error
        return self._chat_response


def test_select_preferred_model_keeps_requested_model():
    selection = select_preferred_model(
        ["gpt-oss:120b-cloud", "llama3.2"],
        "llama3.2",
    )

    assert selection.resolved_model == "llama3.2"
    assert selection.used_fallback is False


def test_select_preferred_model_falls_back_to_first_available():
    selection = select_preferred_model(
        ["llama3.2", "qwen2.5-coder"],
        DEFAULT_OLLAMA_MODEL,
    )

    assert selection.requested_model == DEFAULT_OLLAMA_MODEL
    assert selection.resolved_model == "llama3.2"
    assert selection.used_fallback is True


def test_select_preferred_model_raises_when_no_models():
    with pytest.raises(RuntimeError, match="No Ollama models are available"):
        select_preferred_model([], DEFAULT_OLLAMA_MODEL)


def test_list_models_returns_names():
    provider = OllamaProvider(
        client=FakeOllamaClient(
            models=[
                {"model": "gpt-oss:120b-cloud"},
                {"name": "llama3.2"},
            ]
        )
    )

    assert provider.list_models() == ["gpt-oss:120b-cloud", "llama3.2"]


def test_list_models_raises_when_ollama_is_unreachable():
    provider = OllamaProvider(client=FakeOllamaClient(list_error=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="Could not reach Ollama"):
        provider.list_models()


def test_analyze_for_clarification_raises_on_response_error():
    provider = OllamaProvider(
        client=FakeOllamaClient(
            chat_error=ResponseError('{"error":"missing model"}', 404)
        )
    )

    with pytest.raises(RuntimeError, match="Ollama request failed: missing model"):
        provider.analyze_for_clarification(
            prompt_text="Add auth",
            diff_text="diff --git a/app.py b/app.py",
            repo_context=[],
            ui_language="English",
            model="missing",
        )


def test_analyze_for_clarification_raises_on_empty_response():
    provider = OllamaProvider(
        client=FakeOllamaClient(chat_response={"message": {"content": ""}})
    )

    with pytest.raises(RuntimeError, match="Ollama returned an empty response"):
        provider.analyze_for_clarification(
            prompt_text="Add auth",
            diff_text="diff --git a/app.py b/app.py",
            repo_context=[],
            ui_language="English",
            model="llama3.2",
        )


def test_analyze_for_clarification_raises_on_invalid_json():
    provider = OllamaProvider(
        client=FakeOllamaClient(chat_response={"message": {"content": "not-json"}})
    )

    with pytest.raises(RuntimeError, match="Model returned invalid JSON for analysis"):
        provider.analyze_for_clarification(
            prompt_text="Add auth",
            diff_text="diff --git a/app.py b/app.py",
            repo_context=[],
            ui_language="English",
            model="llama3.2",
        )


def test_generate_final_prompt_raises_on_invalid_json():
    provider = OllamaProvider(
        client=FakeOllamaClient(chat_response={"message": {"content": "not-json"}})
    )

    with pytest.raises(
        RuntimeError,
        match="Model returned invalid JSON for final prompt generation",
    ):
        provider.generate_final_prompt(
            prompt_text="Add auth",
            diff_text="diff --git a/app.py b/app.py",
            repo_context=[],
            analysis_result=AnalysisResult(
                agent_intent="Implement auth",
                user_intent="Add auth",
            ),
            clarification_answers=[],
            model="llama3.2",
        )


def test_generate_final_prompt_uses_selected_model():
    fake_client = FakeOllamaClient(
        chat_response={"message": {"content": '{"final_prompt":"Ship it."}'}}
    )
    provider = OllamaProvider(client=fake_client)

    result = provider.generate_final_prompt(
        prompt_text="Add auth",
        diff_text="diff --git a/app.py b/app.py",
        repo_context=[
            RepoContextSnippet(
                path="app.py", content="print('x')", reason="changed file"
            )
        ],
        analysis_result=AnalysisResult(
            agent_intent="Implement auth",
            user_intent="Add auth",
        ),
        clarification_answers=[],
        model="qwen2.5-coder",
    )

    assert result == "Ship it."
    assert fake_client.calls[0]["model"] == "qwen2.5-coder"
