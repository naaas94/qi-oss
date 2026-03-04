"""Tests for Ollama LLM client wrapper."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import httpx
import pytest

from qi.llm.client import LLMClientError, OllamaClient


def test_generate_happy_path_returns_llm_response() -> None:
    """Successful API call should return parsed LLMResponse fields."""
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "model": "qwen3:30b",
        "done_reason": "stop",
        "total_duration": 1000,
        "load_duration": 100,
        "prompt_eval_count": 12,
        "prompt_eval_duration": 120,
        "eval_count": 24,
        "eval_duration": 240,
        "message": {"content": '{"weekly_summary":"ok"}'},
    }

    with patch("qi.llm.client.httpx.Client") as client_cls:
        http_client = client_cls.return_value
        http_client.post.return_value = response

        client = OllamaClient(base_url="http://localhost:11434", timeout_seconds=90)
        result = client.generate(
            model="qwen3:30b",
            system_prompt="system",
            user_prompt="user",
            temperature=0.2,
            think=True,
        )

    assert result.model == "qwen3:30b"
    assert result.content == '{"weekly_summary":"ok"}'
    assert result.prompt_eval_count == 12
    assert result.eval_count == 24
    call_kwargs = http_client.post.call_args.kwargs
    assert call_kwargs["json"]["think"] is True


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError(
            "connection failed",
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
        ),
    ],
)
def test_generate_network_errors_raise_llm_client_error(error: httpx.HTTPError) -> None:
    """Transport-layer httpx errors should map to LLMClientError."""
    with patch("qi.llm.client.httpx.Client") as client_cls:
        http_client = client_cls.return_value
        http_client.post.side_effect = error
        client = OllamaClient(base_url="http://localhost:11434")

        with pytest.raises(LLMClientError, match="Ollama API request failed"):
            client.generate(
                model="qwen3:30b",
                system_prompt="system",
                user_prompt="user",
            )


def test_generate_http_status_error_raises_llm_client_error() -> None:
    """HTTP status failures (e.g. 500) should map to LLMClientError."""
    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    response = httpx.Response(500, request=request, text="internal error")

    with patch("qi.llm.client.httpx.Client") as client_cls:
        http_client = client_cls.return_value
        http_client.post.return_value = response
        client = OllamaClient(base_url="http://localhost:11434")

        with pytest.raises(LLMClientError, match="Ollama API status error"):
            client.generate(
                model="qwen3:30b",
                system_prompt="system",
                user_prompt="user",
            )


def test_generate_invalid_json_body_raises_llm_client_error() -> None:
    """Malformed JSON payload should raise a readable LLMClientError."""
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.side_effect = json.JSONDecodeError("Expecting value", "x", 0)

    with patch("qi.llm.client.httpx.Client") as client_cls:
        http_client = client_cls.return_value
        http_client.post.return_value = response
        client = OllamaClient(base_url="http://localhost:11434")

        with pytest.raises(LLMClientError, match="not valid JSON"):
            client.generate(
                model="qwen3:30b",
                system_prompt="system",
                user_prompt="user",
            )


def test_generate_missing_message_content_raises_llm_client_error() -> None:
    """Missing `message.content` should be treated as malformed response."""
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "model": "qwen3:30b",
        "message": {},
    }

    with patch("qi.llm.client.httpx.Client") as client_cls:
        http_client = client_cls.return_value
        http_client.post.return_value = response
        client = OllamaClient(base_url="http://localhost:11434")

        with pytest.raises(LLMClientError, match="missing message content"):
            client.generate(
                model="qwen3:30b",
                system_prompt="system",
                user_prompt="user",
            )
