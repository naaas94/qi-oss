"""Validation and retry logic for LLM narrative outputs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from qi.llm.client import LLMClientError, LLMResponse, OllamaClient
from qi.llm.prompts import PromptPackage, build_repair_prompt
from qi.llm.schema import NarrativeOutput


@dataclass
class NarrativeSynthesisResult:
    """Result of LLM synthesis with validation metadata."""

    output: NarrativeOutput | None
    raw_output: str | None
    model_id: str | None
    traces: list["LLMRunTrace"]
    error: str | None = None


@dataclass
class LLMRunTrace:
    """Trace data for each LLM call attempt."""

    run_type: Literal["initial", "repair"]
    system_prompt: str
    user_prompt: str
    temperature: float
    think_enabled: bool
    response: LLMResponse | None
    validation_passed: bool
    validation_error: str | None = None
    error: str | None = None


def _parse_narrative_output(raw_output: str) -> NarrativeOutput:
    parsed = json.loads(_strip_markdown_json_fence(raw_output))
    return NarrativeOutput.model_validate(parsed)


def _strip_markdown_json_fence(raw_output: str) -> str:
    """Strip a surrounding fenced code block if the model wraps JSON in markdown."""
    cleaned = raw_output.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return cleaned


def synthesize_with_validation(
    *,
    client: OllamaClient,
    model: str,
    temperature: float,
    think: bool | None,
    prompts: PromptPackage,
) -> NarrativeSynthesisResult:
    """Call LLM, validate output, retry once with repair prompt when needed."""
    traces: list[LLMRunTrace] = []
    think_enabled = bool(think)

    try:
        first = client.generate(
            model=model,
            system_prompt=prompts.system_prompt,
            user_prompt=prompts.user_prompt,
            temperature=temperature,
            think=think,
        )
    except LLMClientError as exc:
        traces.append(
            LLMRunTrace(
                run_type="initial",
                system_prompt=prompts.system_prompt,
                user_prompt=prompts.user_prompt,
                temperature=temperature,
                think_enabled=think_enabled,
                response=None,
                validation_passed=False,
                error=str(exc),
            )
        )
        return NarrativeSynthesisResult(
            output=None,
            raw_output=None,
            model_id=None,
            traces=traces,
            error=str(exc),
        )

    first_parsed, first_validation_error = _try_parse(first)
    traces.append(
        LLMRunTrace(
            run_type="initial",
            system_prompt=prompts.system_prompt,
            user_prompt=prompts.user_prompt,
            temperature=temperature,
            think_enabled=think_enabled,
            response=first,
            validation_passed=first_parsed is not None,
            validation_error=first_validation_error,
        )
    )
    if first_parsed is not None:
        return NarrativeSynthesisResult(
            output=first_parsed,
            raw_output=first.content,
            model_id=first.model,
            traces=traces,
        )

    repair_prompt = build_repair_prompt(first.content)
    try:
        second = client.generate(
            model=model,
            system_prompt=prompts.system_prompt,
            user_prompt=repair_prompt,
            temperature=temperature,
            think=think,
        )
    except LLMClientError as exc:
        traces.append(
            LLMRunTrace(
                run_type="repair",
                system_prompt=prompts.system_prompt,
                user_prompt=repair_prompt,
                temperature=temperature,
                think_enabled=think_enabled,
                response=None,
                validation_passed=False,
                error=str(exc),
            )
        )
        return NarrativeSynthesisResult(
            output=None,
            raw_output=first.content,
            model_id=first.model,
            traces=traces,
            error=f"Initial output invalid and repair failed: {exc}",
        )

    second_parsed, second_validation_error = _try_parse(second)
    traces.append(
        LLMRunTrace(
            run_type="repair",
            system_prompt=prompts.system_prompt,
            user_prompt=repair_prompt,
            temperature=temperature,
            think_enabled=think_enabled,
            response=second,
            validation_passed=second_parsed is not None,
            validation_error=second_validation_error,
        )
    )
    if second_parsed is not None:
        return NarrativeSynthesisResult(
            output=second_parsed,
            raw_output=second.content,
            model_id=second.model,
            traces=traces,
        )

    return NarrativeSynthesisResult(
        output=None,
        raw_output=second.content,
        model_id=second.model,
        traces=traces,
        error="LLM output failed validation after one repair attempt",
    )


def _try_parse(response: LLMResponse) -> tuple[NarrativeOutput | None, str | None]:
    try:
        return _parse_narrative_output(response.content), None
    except (json.JSONDecodeError, ValidationError) as exc:
        return None, str(exc)
