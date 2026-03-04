"""High-level report synthesis orchestration."""

from __future__ import annotations

from datetime import date
from typing import Any

from qi.config import load_config, parse_principle_names, read_principles_markdown
from qi.db import save_llm_run
from qi.llm.client import LLMClientError, OllamaClient
from qi.llm.prompts import build_report_prompts
from qi.llm.render import render_narrative_markdown
from qi.llm.validate import NarrativeSynthesisResult, synthesize_with_validation


def synthesize_report_narrative(
    *,
    report_type: str,
    window_start: date,
    window_end: date,
    input_snapshot: dict[str, Any],
    features_snapshot: dict[str, Any],
    analysis_snapshot: dict[str, Any],
    daily_series: dict[str, Any] | None = None,
    digests: list[dict[str, Any]] | None = None,
    force_disable: bool = False,
) -> tuple[str | None, dict[str, Any]]:
    """Synthesize narrative markdown and metadata for a report."""
    config = load_config()
    llm_cfg = config.get("llm", {})
    enabled = bool(llm_cfg.get("enabled", False)) and not force_disable
    metadata: dict[str, Any] = {
        "llm_enabled": enabled,
        "llm_skipped_reason": None,
        "prompt_version": None,
        "model_id": None,
        "raw_output": None,
        "error": None,
        "llm_run_ids": [],
    }

    if not enabled:
        metadata["llm_skipped_reason"] = "disabled"
        return None, metadata

    principles_markdown = read_principles_markdown(config)
    prompts = build_report_prompts(
        report_type=report_type,
        window_start=window_start,
        window_end=window_end,
        input_snapshot=input_snapshot,
        features_snapshot=features_snapshot,
        analysis_snapshot=analysis_snapshot,
        principles_markdown=principles_markdown,
        daily_series=daily_series,
        digests=digests,
    )

    # Timeout for the LLM call; config in ~/.qi/config.toml [llm] timeout_seconds. Use 0 for no timeout (slow local models).
    timeout_seconds = llm_cfg.get("timeout_seconds", 120)
    if isinstance(timeout_seconds, (int, float)):
        timeout_seconds = int(timeout_seconds)
    else:
        timeout_seconds = 120
    if timeout_seconds <= 0:
        timeout_seconds = None  # wait indefinitely
    else:
        timeout_seconds = max(60, timeout_seconds)
    think = llm_cfg.get("think", False)
    if not isinstance(think, bool):
        think = False
    model_name = str(llm_cfg.get("model", "qwen3:30b"))

    client = OllamaClient(
        base_url=str(llm_cfg.get("base_url", "http://localhost:11434")),
        timeout_seconds=timeout_seconds,
    )
    try:
        try:
            client.check_ready()
        except LLMClientError as exc:
            metadata["llm_skipped_reason"] = "readiness_check_failed"
            metadata["error"] = str(exc)
            return None, metadata

        result: NarrativeSynthesisResult = synthesize_with_validation(
            client=client,
            model=model_name,
            temperature=float(llm_cfg.get("temperature", 0.4)),
            think=think,
            prompts=prompts,
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    metadata["prompt_version"] = prompts.prompt_version
    metadata["model_id"] = result.model_id
    metadata["raw_output"] = result.raw_output
    metadata["error"] = result.error
    metadata["llm_run_ids"] = _persist_llm_runs(
        report_type=report_type,
        prompt_version=prompts.prompt_version,
        configured_model=model_name,
        traces=result.traces,
    )

    if result.output is None:
        metadata["llm_skipped_reason"] = "validation_or_request_failure"
        return None, metadata

    principle_names = parse_principle_names(principles_markdown or "") if principles_markdown else {}
    return render_narrative_markdown(result.output, principle_names=principle_names), metadata


def _persist_llm_runs(
    *,
    report_type: str,
    prompt_version: str,
    configured_model: str,
    traces: list[Any],
) -> list[int]:
    """Persist per-call LLM traces and return row ids."""
    run_ids: list[int] = []
    for trace in traces:
        response = trace.response
        run_id = save_llm_run(
            {
                "artifact_id": None,
                "artifact_type": report_type,
                "run_type": trace.run_type,
                "model": response.model if response and response.model else configured_model,
                "prompt_version": prompt_version,
                "temperature": trace.temperature,
                "think_enabled": int(trace.think_enabled),
                "system_prompt": trace.system_prompt,
                "user_prompt": trace.user_prompt,
                "raw_output": response.content if response else None,
                "done_reason": response.done_reason if response else None,
                "prompt_tokens": response.prompt_eval_count if response else None,
                "completion_tokens": response.eval_count if response else None,
                "total_duration_ms": _ns_to_ms(response.total_duration) if response else None,
                "load_duration_ms": _ns_to_ms(response.load_duration) if response else None,
                "prompt_eval_duration_ms": _ns_to_ms(response.prompt_eval_duration) if response else None,
                "eval_duration_ms": _ns_to_ms(response.eval_duration) if response else None,
                "validation_passed": int(trace.validation_passed),
                "validation_error": trace.validation_error,
                "error": trace.error,
            }
        )
        if run_id:
            run_ids.append(run_id)
    return run_ids


def _ns_to_ms(value: int | None) -> int | None:
    """Convert nanoseconds to milliseconds."""
    if value is None:
        return None
    return int(value / 1_000_000)
