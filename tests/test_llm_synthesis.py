"""Tests for LLM synthesis orchestration."""

from __future__ import annotations

from datetime import date
from typing import Any

from qi.llm.client import LLMClientError, LLMResponse
from qi.llm.prompts import PromptPackage
from qi.llm.synthesis import _persist_llm_runs, synthesize_report_narrative
from qi.llm.validate import LLMRunTrace, NarrativeOutput, NarrativeSynthesisResult


def _valid_narrative_output() -> NarrativeOutput:
    return NarrativeOutput.model_validate(
        {
            "weekly_summary": "Good week.",
            "delta_narrative": "Energy improved.",
            "principle_alignment": [
                {"principle_id": 1, "status": "on_track", "note": "Kept routines."}
            ],
            "kr_progress": [{"kr": "KR1", "assessment": "On track"}],
            "coaching_focus": "Maintain consistency.",
            "next_experiment": "Track bedtime regularity.",
            "risks": ["Workload spikes."],
            "confidence": 0.82,
        }
    )


def test_synthesis_uses_config_overrides(monkeypatch) -> None:
    """Synthesis should pass config-derived settings into orchestration."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "qi.llm.synthesis.load_config",
        lambda: {
            "llm": {
                "enabled": True,
                "base_url": "http://example-ollama:11434",
                "timeout_seconds": 10,  # should normalize to min 60
                "model": "custom-model:1",
                "temperature": 0.77,
                "think": True,
            }
        },
    )
    monkeypatch.setattr(
        "qi.llm.synthesis.read_principles_markdown",
        lambda _config: "## 1. Health\n",
    )
    monkeypatch.setattr(
        "qi.llm.synthesis.build_report_prompts",
        lambda **_: PromptPackage(
            system_prompt="system",
            user_prompt="user",
            prompt_version="prompt-v1",
        ),
    )

    class FakeClient:
        def __init__(self, base_url: str, timeout_seconds: int | None) -> None:
            captured["base_url"] = base_url
            captured["timeout_seconds"] = timeout_seconds

        def check_ready(self) -> None:
            captured["check_ready_called"] = True

    monkeypatch.setattr("qi.llm.synthesis.OllamaClient", FakeClient)

    def _fake_synthesize_with_validation(
        *,
        client: FakeClient,  # noqa: ARG001 - signature compatibility
        model: str,
        temperature: float,
        think: bool | None,
        prompts: PromptPackage,  # noqa: ARG001 - signature compatibility
    ) -> NarrativeSynthesisResult:
        captured["model"] = model
        captured["temperature"] = temperature
        captured["think"] = think
        return NarrativeSynthesisResult(
            output=_valid_narrative_output(),
            raw_output='{"weekly_summary":"Good week."}',
            model_id="runtime-model-id",
            traces=[],
        )

    monkeypatch.setattr("qi.llm.synthesis.synthesize_with_validation", _fake_synthesize_with_validation)
    monkeypatch.setattr("qi.llm.synthesis._persist_llm_runs", lambda **_: [101])

    narrative, metadata = synthesize_report_narrative(
        report_type="weekly_digest",
        window_start=date(2026, 2, 17),
        window_end=date(2026, 2, 24),
        input_snapshot={},
        features_snapshot={},
        analysis_snapshot={},
    )

    assert captured["base_url"] == "http://example-ollama:11434"
    assert captured["timeout_seconds"] == 60
    assert captured["model"] == "custom-model:1"
    assert captured["temperature"] == 0.77
    assert captured["think"] is True
    assert captured["check_ready_called"] is True
    assert narrative is not None
    assert "## LLM Narrative" in narrative
    assert metadata["prompt_version"] == "prompt-v1"
    assert metadata["model_id"] == "runtime-model-id"
    assert metadata["llm_run_ids"] == [101]


def test_synthesis_gracefully_degrades_when_readiness_check_fails(monkeypatch) -> None:
    """Readiness check failures should not crash report generation."""
    monkeypatch.setattr(
        "qi.llm.synthesis.load_config",
        lambda: {"llm": {"enabled": True}},
    )
    monkeypatch.setattr("qi.llm.synthesis.read_principles_markdown", lambda _config: None)
    monkeypatch.setattr(
        "qi.llm.synthesis.build_report_prompts",
        lambda **_: PromptPackage(
            system_prompt="system",
            user_prompt="user",
            prompt_version="prompt-v1",
        ),
    )

    class FailingClient:
        def __init__(self, base_url: str, timeout_seconds: int | None) -> None:  # noqa: ARG002
            pass

        def check_ready(self) -> None:
            raise LLMClientError("ollama unavailable")

    monkeypatch.setattr("qi.llm.synthesis.OllamaClient", FailingClient)

    narrative, metadata = synthesize_report_narrative(
        report_type="weekly_digest",
        window_start=date(2026, 2, 17),
        window_end=date(2026, 2, 24),
        input_snapshot={},
        features_snapshot={},
        analysis_snapshot={},
    )

    assert narrative is None
    assert metadata["llm_skipped_reason"] == "readiness_check_failed"
    assert "ollama unavailable" in str(metadata["error"])


def test_synthesis_returns_none_when_validation_or_request_fails(monkeypatch) -> None:
    """Failed validation/request should return None narrative with metadata."""
    monkeypatch.setattr(
        "qi.llm.synthesis.load_config",
        lambda: {"llm": {"enabled": True, "model": "qwen3:30b"}},
    )
    monkeypatch.setattr("qi.llm.synthesis.read_principles_markdown", lambda _config: None)
    monkeypatch.setattr(
        "qi.llm.synthesis.build_report_prompts",
        lambda **_: PromptPackage(
            system_prompt="system",
            user_prompt="user",
            prompt_version="prompt-v1",
        ),
    )

    class ReadyClient:
        def __init__(self, base_url: str, timeout_seconds: int | None) -> None:  # noqa: ARG002
            pass

        def check_ready(self) -> None:
            return None

    monkeypatch.setattr("qi.llm.synthesis.OllamaClient", ReadyClient)
    monkeypatch.setattr(
        "qi.llm.synthesis.synthesize_with_validation",
        lambda **_: NarrativeSynthesisResult(
            output=None,
            raw_output='{"broken":"json"}',
            model_id="qwen3:30b",
            traces=[],
            error="validation failed",
        ),
    )
    monkeypatch.setattr("qi.llm.synthesis._persist_llm_runs", lambda **_: [7, 8])

    narrative, metadata = synthesize_report_narrative(
        report_type="weekly_digest",
        window_start=date(2026, 2, 17),
        window_end=date(2026, 2, 24),
        input_snapshot={},
        features_snapshot={},
        analysis_snapshot={},
    )

    assert narrative is None
    assert metadata["llm_skipped_reason"] == "validation_or_request_failure"
    assert metadata["error"] == "validation failed"
    assert metadata["llm_run_ids"] == [7, 8]


def test_persist_llm_runs_logs_failure_then_repair(monkeypatch) -> None:
    """Trace persistence should write one row per trace with mapped fields."""
    saved_rows: list[dict[str, Any]] = []

    def _fake_save_llm_run(run_data: dict[str, Any]) -> int:
        saved_rows.append(run_data)
        return len(saved_rows)

    monkeypatch.setattr("qi.llm.synthesis.save_llm_run", _fake_save_llm_run)

    traces = [
        LLMRunTrace(
            run_type="initial",
            system_prompt="sys",
            user_prompt="user",
            temperature=0.4,
            think_enabled=False,
            response=LLMResponse(
                content='{"bad":"json"}',
                model=None,
                done_reason="stop",
                total_duration=3_000_000,
                load_duration=1_000_000,
                prompt_eval_count=10,
                prompt_eval_duration=500_000,
                eval_count=20,
                eval_duration=1_500_000,
            ),
            validation_passed=False,
            validation_error="missing confidence",
        ),
        LLMRunTrace(
            run_type="repair",
            system_prompt="sys",
            user_prompt="repair-user",
            temperature=0.4,
            think_enabled=False,
            response=LLMResponse(
                content='{"weekly_summary":"ok"}',
                model="repair-model",
                done_reason="stop",
            ),
            validation_passed=True,
        ),
    ]

    run_ids = _persist_llm_runs(
        report_type="weekly_digest",
        prompt_version="prompt-v1",
        configured_model="configured-model",
        traces=traces,
    )

    assert run_ids == [1, 2]
    assert len(saved_rows) == 2

    first = saved_rows[0]
    second = saved_rows[1]
    assert first["run_type"] == "initial"
    assert first["model"] == "configured-model"
    assert first["validation_passed"] == 0
    assert first["validation_error"] == "missing confidence"
    assert first["total_duration_ms"] == 3
    assert first["load_duration_ms"] == 1
    assert first["prompt_eval_duration_ms"] == 0
    assert first["eval_duration_ms"] == 1

    assert second["run_type"] == "repair"
    assert second["model"] == "repair-model"
    assert second["validation_passed"] == 1


def test_synthesis_closes_client_after_successful_path(monkeypatch) -> None:
    """Client close should run even when synthesis completes."""
    closed: dict[str, bool] = {"value": False}

    monkeypatch.setattr("qi.llm.synthesis.load_config", lambda: {"llm": {"enabled": True}})
    monkeypatch.setattr("qi.llm.synthesis.read_principles_markdown", lambda _config: None)
    monkeypatch.setattr(
        "qi.llm.synthesis.build_report_prompts",
        lambda **_: PromptPackage(
            system_prompt="system",
            user_prompt="user",
            prompt_version="prompt-v1",
        ),
    )

    class ClosingClient:
        def __init__(self, base_url: str, timeout_seconds: int | None) -> None:  # noqa: ARG002
            pass

        def check_ready(self) -> None:
            return None

        def close(self) -> None:
            closed["value"] = True

    monkeypatch.setattr("qi.llm.synthesis.OllamaClient", ClosingClient)
    monkeypatch.setattr(
        "qi.llm.synthesis.synthesize_with_validation",
        lambda **_: NarrativeSynthesisResult(
            output=_valid_narrative_output(),
            raw_output='{"weekly_summary":"Good week."}',
            model_id="qwen3:30b",
            traces=[],
        ),
    )
    monkeypatch.setattr("qi.llm.synthesis._persist_llm_runs", lambda **_: [])

    narrative, _metadata = synthesize_report_narrative(
        report_type="weekly_digest",
        window_start=date(2026, 2, 17),
        window_end=date(2026, 2, 24),
        input_snapshot={},
        features_snapshot={},
        analysis_snapshot={},
    )

    assert narrative is not None
    assert closed["value"] is True


def test_synthesis_closes_client_after_readiness_failure(monkeypatch) -> None:
    """Client close should run even when readiness fails early."""
    closed: dict[str, bool] = {"value": False}

    monkeypatch.setattr("qi.llm.synthesis.load_config", lambda: {"llm": {"enabled": True}})
    monkeypatch.setattr("qi.llm.synthesis.read_principles_markdown", lambda _config: None)
    monkeypatch.setattr(
        "qi.llm.synthesis.build_report_prompts",
        lambda **_: PromptPackage(
            system_prompt="system",
            user_prompt="user",
            prompt_version="prompt-v1",
        ),
    )

    class ClosingFailingClient:
        def __init__(self, base_url: str, timeout_seconds: int | None) -> None:  # noqa: ARG002
            pass

        def check_ready(self) -> None:
            raise LLMClientError("ollama unavailable")

        def close(self) -> None:
            closed["value"] = True

    monkeypatch.setattr("qi.llm.synthesis.OllamaClient", ClosingFailingClient)

    narrative, metadata = synthesize_report_narrative(
        report_type="weekly_digest",
        window_start=date(2026, 2, 17),
        window_end=date(2026, 2, 24),
        input_snapshot={},
        features_snapshot={},
        analysis_snapshot={},
    )

    assert narrative is None
    assert metadata["llm_skipped_reason"] == "readiness_check_failed"
    assert closed["value"] is True
