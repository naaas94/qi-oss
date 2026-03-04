"""Tests for LLM response validation and repair loop."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from qi.llm.client import LLMResponse
from qi.llm.prompts import PromptPackage
from qi.llm.validate import _parse_narrative_output, synthesize_with_validation


def _valid_payload() -> dict[str, Any]:
    return {
        "weekly_summary": "Good week overall.",
        "delta_narrative": "Energy improved while friction stayed manageable.",
        "principle_alignment": [
            {"principle_id": 1, "status": "on_track", "note": "Training stayed consistent."}
        ],
        "kr_progress": [{"kr": "KR1", "assessment": "On track"}],
        "coaching_focus": "Keep sleep consistency.",
        "next_experiment": "Track pre-sleep routine adherence for 7 days.",
        "risks": ["Late-night screen time."],
        "confidence": 0.84,
    }


def test_parse_narrative_output_success() -> None:
    """Valid JSON payload should parse into NarrativeOutput."""
    parsed = _parse_narrative_output(json.dumps(_valid_payload()))
    assert parsed.weekly_summary == "Good week overall."
    assert parsed.confidence == pytest.approx(0.84)


def test_parse_narrative_output_strips_markdown_code_fence() -> None:
    """Parser should accept JSON wrapped in fenced markdown blocks."""
    wrapped = "```json\n" + json.dumps(_valid_payload()) + "\n```"
    parsed = _parse_narrative_output(wrapped)
    assert parsed.next_experiment.startswith("Track pre-sleep")


def test_parse_narrative_output_missing_required_field_raises_validation_error() -> None:
    """Missing required fields should fail schema validation."""
    broken = _valid_payload()
    broken.pop("confidence")
    with pytest.raises(ValidationError):
        _parse_narrative_output(json.dumps(broken))


def test_synthesize_with_validation_repair_loop_success() -> None:
    """Invalid first output + valid repair output should recover successfully."""
    responses = [
        LLMResponse(content='{"weekly_summary":"oops"', model="qwen3:30b"),
        LLMResponse(content=json.dumps(_valid_payload()), model="qwen3:30b"),
    ]
    calls: list[dict[str, Any]] = []

    class FakeClient:
        def generate(
            self,
            *,
            model: str,
            system_prompt: str,
            user_prompt: str,
            temperature: float,
            think: bool | None,
        ) -> LLMResponse:
            calls.append(
                {
                    "model": model,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "temperature": temperature,
                    "think": think,
                }
            )
            return responses.pop(0)

    prompts = PromptPackage(
        system_prompt="system",
        user_prompt="user",
        prompt_version="v-test",
    )
    result = synthesize_with_validation(
        client=FakeClient(),
        model="qwen3:30b",
        temperature=0.4,
        think=False,
        prompts=prompts,
    )

    assert result.output is not None
    assert result.error is None
    assert len(result.traces) == 2
    assert result.traces[0].run_type == "initial"
    assert result.traces[0].validation_passed is False
    assert result.traces[1].run_type == "repair"
    assert result.traces[1].validation_passed is True
    assert "Invalid_output" in calls[1]["user_prompt"]


def test_synthesize_with_validation_double_failure_returns_fallback_error() -> None:
    """Two invalid outputs should fail gracefully with terminal error metadata."""
    responses = [
        LLMResponse(content='{"weekly_summary":"oops"', model="qwen3:30b"),
        LLMResponse(content='{"weekly_summary":"still oops"', model="qwen3:30b"),
    ]

    class FakeClient:
        def generate(
            self,
            *,
            model: str,  # noqa: ARG002 - signature compatibility
            system_prompt: str,  # noqa: ARG002 - signature compatibility
            user_prompt: str,  # noqa: ARG002 - signature compatibility
            temperature: float,  # noqa: ARG002 - signature compatibility
            think: bool | None,  # noqa: ARG002 - signature compatibility
        ) -> LLMResponse:
            return responses.pop(0)

    prompts = PromptPackage(
        system_prompt="system",
        user_prompt="user",
        prompt_version="v-test",
    )
    result = synthesize_with_validation(
        client=FakeClient(),
        model="qwen3:30b",
        temperature=0.4,
        think=False,
        prompts=prompts,
    )

    assert result.output is None
    assert result.error == "LLM output failed validation after one repair attempt"
    assert len(result.traces) == 2
    assert result.traces[0].validation_passed is False
    assert result.traces[1].validation_passed is False
