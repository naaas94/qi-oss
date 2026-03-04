"""Ollama client utilities for report synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Any

import httpx
from rich.console import Console


class LLMClientError(RuntimeError):
    """Raised when an LLM provider call fails."""


@dataclass
class LLMResponse:
    """Structured response metadata from an LLM call."""

    content: str
    model: str | None
    done_reason: str | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    prompt_eval_duration: int | None = None
    eval_count: int | None = None
    eval_duration: int | None = None


class OllamaClient:
    """Thin Ollama chat API wrapper."""

    def __init__(self, base_url: str, timeout_seconds: int | None = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds  # None = no timeout (wait indefinitely)
        self._client = httpx.Client(
            timeout=None if self.timeout_seconds is None else httpx.Timeout(self.timeout_seconds)
        )
        self._console = Console(stderr=True)
        self._warn_if_remote_endpoint()

    def close(self) -> None:
        """Close underlying HTTP client resources."""
        self._client.close()

    def __enter__(self) -> "OllamaClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _warn_if_remote_endpoint(self) -> None:
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").lower()
        if host not in {"localhost", "127.0.0.1", "::1"}:
            self._console.print(
                "[yellow]Warning: LLM endpoint is remote; prompts and personal data "
                "will be sent over the network.[/yellow]"
            )

    def check_ready(self) -> None:
        """Verify Ollama is reachable. Raises LLMClientError if not."""
        url = f"{self.base_url}/api/tags"
        timeout = httpx.Timeout(5.0)
        try:
            response = self._client.get(url, timeout=timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise LLMClientError(f"Ollama API status error: {detail}") from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(
                f"Ollama is not reachable at {self.base_url}. Is it running?"
            ) from exc

    def generate(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
        think: bool | None = None,
    ) -> LLMResponse:
        """Generate a response using Ollama's chat API."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_predict": 8192},
        }
        if think is not None:
            payload["think"] = think

        url = f"{self.base_url}/api/chat"
        # None = no timeout (for slow local models); otherwise limit wait time
        timeout = None if self.timeout_seconds is None else httpx.Timeout(self.timeout_seconds)
        try:
            response = self._client.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise LLMClientError(f"Ollama API status error: {detail}") from exc
        except httpx.HTTPError as exc:
            raise LLMClientError(f"Ollama API request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMClientError(f"Ollama response was not valid JSON: {exc}") from exc

        message = data.get("message", {})
        if not isinstance(message, dict):
            raise LLMClientError("Ollama response missing message content")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMClientError("Ollama response missing message content")

        return LLMResponse(
            content=content,
            model=data.get("model"),
            done_reason=data.get("done_reason"),
            total_duration=data.get("total_duration"),
            load_duration=data.get("load_duration"),
            prompt_eval_count=data.get("prompt_eval_count"),
            prompt_eval_duration=data.get("prompt_eval_duration"),
            eval_count=data.get("eval_count"),
            eval_duration=data.get("eval_duration"),
        )
