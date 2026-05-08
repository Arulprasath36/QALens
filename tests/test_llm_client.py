"""Tests for qara.llm.client (Phase 7) — uses pytest-httpx to mock HTTP."""

from __future__ import annotations

import json

import pytest

from qara.llm.client import LLMClient, LLMError
from qara.llm.config import LLMConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ollama_cfg(**kwargs) -> LLMConfig:
    defaults = dict(
        provider="ollama",
        base_url="http://localhost:11434/v1",
        model="llama3.2",
        api_key="",
        timeout=10,
        max_tokens=256,
        temperature=0.2,
    )
    defaults.update(kwargs)
    return LLMConfig(**defaults)


def _openai_response(text: str = "Test answer") -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": text}}
        ]
    }


def _anthropic_response(text: str = "Claude answer") -> dict:
    return {
        "content": [{"type": "text", "text": text}]
    }


def _gemini_response(text: str = "Gemini answer", finish_reason: str = "STOP") -> dict:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}]},
                "finishReason": finish_reason,
            }
        ]
    }


# ---------------------------------------------------------------------------
# OpenAI-compatible (Ollama)
# ---------------------------------------------------------------------------


def test_chat_openai_compatible_returns_answer(httpx_mock):
    cfg = _ollama_cfg()
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_openai_response("Root cause: element not found."),
    )
    client = LLMClient(cfg)
    result = client.chat("Why is testLogin failing?")
    assert result == "Root cause: element not found."


def test_chat_strips_whitespace(httpx_mock):
    cfg = _ollama_cfg()
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_openai_response("  Answer with spaces.  "),
    )
    result = LLMClient(cfg).chat("question")
    assert result == "Answer with spaces."


def test_chat_sends_model_in_payload(httpx_mock):
    cfg = _ollama_cfg(model="mistral")
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_openai_response("ok"),
    )
    LLMClient(cfg).chat("q")
    request = httpx_mock.get_request()
    payload = json.loads(request.content)
    assert payload["model"] == "mistral"


def test_chat_sends_system_and_user_messages(httpx_mock):
    cfg = _ollama_cfg()
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_openai_response("ok"),
    )
    LLMClient(cfg).chat("my question", system_prompt="be concise")
    request = httpx_mock.get_request()
    payload = json.loads(request.content)
    messages = payload["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "be concise"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "my question"


def test_chat_redacts_secrets_before_sending_prompt(httpx_mock):
    cfg = _ollama_cfg()
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_openai_response("ok"),
    )
    secret = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
    LLMClient(cfg).chat(f"Failure log leaked api_key={secret}")
    request = httpx_mock.get_request()
    payload = json.loads(request.content)
    assert secret not in payload["messages"][1]["content"]
    assert "[REDACTED]" in payload["messages"][1]["content"]


def test_chat_truncates_oversized_prompt_before_sending(httpx_mock):
    cfg = _ollama_cfg()
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_openai_response("ok"),
    )
    LLMClient(cfg).chat("x" * 90_000)
    request = httpx_mock.get_request()
    payload = json.loads(request.content)
    content = payload["messages"][1]["content"]
    assert len(content) < 81_000
    assert "prompt text was truncated" in content


def test_chat_sends_bearer_token_when_api_key_set(httpx_mock):
    cfg = _ollama_cfg(api_key="sk-mykey")
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_openai_response("ok"),
    )
    LLMClient(cfg).chat("q")
    request = httpx_mock.get_request()
    assert request.headers.get("authorization") == "Bearer sk-mykey"


def test_chat_no_auth_header_when_no_api_key(httpx_mock):
    cfg = _ollama_cfg(api_key="")
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json=_openai_response("ok"),
    )
    LLMClient(cfg).chat("q")
    request = httpx_mock.get_request()
    assert "authorization" not in request.headers


def test_chat_blocks_external_provider_without_opt_in():
    cfg = LLMConfig(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="sk-test",
    )
    with pytest.raises(LLMError, match="External LLM provider"):
        LLMClient(cfg).chat("q")


def test_chat_allows_external_provider_with_opt_in(httpx_mock):
    cfg = LLMConfig(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key="sk-test",
        allow_external=True,
    )
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        json=_openai_response("ok"),
    )
    assert LLMClient(cfg).chat("q") == "ok"


def test_chat_raises_llm_error_on_http_500(httpx_mock):
    cfg = _ollama_cfg()
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        status_code=500,
        text="Internal Server Error",
    )
    with pytest.raises(LLMError, match="HTTP 500"):
        LLMClient(cfg).chat("q")


def test_chat_raises_llm_error_on_bad_response_format(httpx_mock):
    cfg = _ollama_cfg()
    httpx_mock.add_response(
        url="http://localhost:11434/v1/chat/completions",
        json={"unexpected": "format"},
    )
    with pytest.raises(LLMError, match="Unexpected response format"):
        LLMClient(cfg).chat("q")


# ---------------------------------------------------------------------------
# Anthropic adapter
# ---------------------------------------------------------------------------


def test_chat_anthropic_returns_answer(httpx_mock):
    cfg = LLMConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        model="claude-3-haiku-20240307",
        api_key="sk-ant-test",
        timeout=10,
        allow_external=True,
    )
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        json=_anthropic_response("Claude says: flaky test detected."),
    )
    result = LLMClient(cfg).chat("Why is testSearch flaky?")
    assert result == "Claude says: flaky test detected."


def test_chat_anthropic_sends_api_key_header(httpx_mock):
    cfg = LLMConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        model="claude-3-haiku-20240307",
        api_key="sk-ant-key",
        timeout=10,
        allow_external=True,
    )
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        json=_anthropic_response("ok"),
    )
    LLMClient(cfg).chat("q")
    request = httpx_mock.get_request()
    assert request.headers.get("x-api-key") == "sk-ant-key"


def test_chat_anthropic_raises_on_error(httpx_mock):
    cfg = LLMConfig(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        model="claude-3-haiku-20240307",
        api_key="bad-key",
        timeout=10,
        allow_external=True,
    )
    httpx_mock.add_response(
        url="https://api.anthropic.com/v1/messages",
        status_code=401,
        json={"error": {"message": "Invalid API key"}},
    )
    with pytest.raises(LLMError, match="HTTP 401"):
        LLMClient(cfg).chat("q")


# ---------------------------------------------------------------------------
# Gemini adapter
# ---------------------------------------------------------------------------


def test_chat_gemini_returns_answer(httpx_mock):
    cfg = LLMConfig(
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model="gemini-2.0-flash",
        api_key="gemini-key",
        timeout=10,
        allow_external=True,
    )
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=gemini-key",
        json=_gemini_response("Gemini: consistent failure due to assertion error."),
    )
    result = LLMClient(cfg).chat("Why does testCreate always fail?")
    assert "consistent failure" in result


def test_chat_gemini_raises_on_bad_format(httpx_mock):
    cfg = LLMConfig(
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model="gemini-2.0-flash",
        api_key="key",
        timeout=10,
        allow_external=True,
    )
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=key",
        json={"unexpected": "format"},
    )
    with pytest.raises(LLMError, match="Unexpected Gemini response format"):
        LLMClient(cfg).chat("q")


def test_chat_gemini_raises_on_max_tokens(httpx_mock):
    """Gemini MAX_TOKENS finish_reason should raise LLMError, not silently truncate."""
    cfg = LLMConfig(
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model="gemini-2.0-flash",
        api_key="key",
        timeout=10,
        max_tokens=256,
        allow_external=True,
    )
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=key",
        json=_gemini_response("Truncated respon", finish_reason="MAX_TOKENS"),
    )
    with pytest.raises(LLMError, match="MAX_TOKENS"):
        LLMClient(cfg).chat("q")


def test_chat_gemini_joins_multiple_parts(httpx_mock):
    """Gemini can return multi-part responses; all parts should be concatenated."""
    cfg = LLMConfig(
        provider="gemini",
        base_url="https://generativelanguage.googleapis.com",
        model="gemini-2.0-flash",
        api_key="key",
        timeout=10,
        allow_external=True,
    )
    multi_part_response = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello "}, {"text": "world"}]},
                "finishReason": "STOP",
            }
        ]
    }
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=key",
        json=multi_part_response,
    )
    result = LLMClient(cfg).chat("q")
    assert result == "Hello world"


# ---------------------------------------------------------------------------
# LLMClient instantiation
# ---------------------------------------------------------------------------


def test_llm_client_requires_httpx():
    """LLMClient should raise ImportError when httpx is not available.
    We just test the happy path here since httpx is always installed in CI.
    """
    cfg = LLMConfig()
    # Should not raise — httpx is installed
    client = LLMClient(cfg)
    assert client is not None
