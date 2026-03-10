"""Tests for LLM prompt builders."""

from __future__ import annotations

from datetime import date

from qi.llm.prompts import build_eod_relevance_prompt, build_report_prompts


def test_report_prompt_fingerprint_is_stable_for_same_input() -> None:
    """prompt_version hash should be deterministic for identical inputs."""
    kwargs = {
        "report_type": "weekly_digest",
        "window_start": date(2026, 2, 17),
        "window_end": date(2026, 2, 24),
        "input_snapshot": {"wins": []},
        "features_snapshot": {"energy_mean": 7.2},
        "analysis_snapshot": {"trend": "stable"},
        "principles_markdown": "## 1. Health\n",
        "daily_series": {"energy": [7.0, 8.0]},
        "digests": [{"item_type": "note", "digest": "shipped"}],
    }
    first = build_report_prompts(**kwargs)
    second = build_report_prompts(**kwargs)
    assert first.prompt_version == second.prompt_version


def test_report_prompt_fingerprint_changes_when_context_changes() -> None:
    """prompt_version hash should change when serialized context changes."""
    common = {
        "report_type": "weekly_digest",
        "window_start": date(2026, 2, 17),
        "window_end": date(2026, 2, 24),
        "input_snapshot": {},
        "analysis_snapshot": {},
        "principles_markdown": "## 1. Health\n",
        "daily_series": None,
        "digests": None,
    }
    base = build_report_prompts(
        **common,
        features_snapshot={"energy_mean": 7.2},
    )
    changed = build_report_prompts(
        **common,
        features_snapshot={"energy_mean": 8.2},
    )
    assert base.prompt_version != changed.prompt_version


def test_report_prompt_handles_missing_principles_and_empty_collections() -> None:
    """Prompt builder should not fail on missing principles / empty lists."""
    prompt = build_report_prompts(
        report_type="weekly_digest",
        window_start=date(2026, 2, 17),
        window_end=date(2026, 2, 24),
        input_snapshot={},
        features_snapshot={},
        analysis_snapshot={},
        principles_markdown=None,
        daily_series={},
        digests=[],
    )
    assert "No principles file available." in prompt.user_prompt
    assert "Context_JSON" in prompt.user_prompt


def test_report_prompt_serializes_features_and_daily_series_data() -> None:
    """Serialized context should include numeric features and timeseries."""
    prompt = build_report_prompts(
        report_type="weekly_digest",
        window_start=date(2026, 2, 17),
        window_end=date(2026, 2, 24),
        input_snapshot={},
        features_snapshot={"energy_mean": 7.2},
        analysis_snapshot={},
        principles_markdown="## 1. Health\n",
        daily_series={"energy": [6.0, 7.0, 8.0]},
        digests=[{"item_type": "note", "digest": "shipped"}],
    )
    assert '"energy_mean": 7.2' in prompt.user_prompt
    assert '"daily_series"' in prompt.user_prompt
    assert '"digests"' in prompt.user_prompt


def test_eod_prompt_handles_empty_item_text() -> None:
    """EOD prompt should replace blank text with explicit '(empty)' marker."""
    prompt = build_eod_relevance_prompt(
        item_type="note",
        item_text="   ",
        principles_markdown=None,
    )
    assert "Item_text:\n(empty)" in prompt.user_prompt
    assert "No principles file available." in prompt.user_prompt


# ── Prompt preferences tests ──────────────────────────────────────────


_COMMON_KWARGS = {
    "report_type": "weekly_digest",
    "window_start": date(2026, 3, 3),
    "window_end": date(2026, 3, 10),
    "input_snapshot": {},
    "features_snapshot": {},
    "analysis_snapshot": {},
    "principles_markdown": "## 1. Health\n",
}


def test_report_prompt_defaults_preserve_original_behavior() -> None:
    """Without prompt_preferences the prompt should match the original analyst/sober/strict text."""
    prompt = build_report_prompts(**_COMMON_KWARGS, prompt_preferences=None)
    assert "reflective performance analyst" in prompt.system_prompt
    assert "Keep it sober" in prompt.system_prompt
    assert "Do not invent events" in prompt.system_prompt


def test_report_prompt_coach_persona() -> None:
    prefs = {"persona": "coach", "tone": "supportive", "strictness": "moderate"}
    prompt = build_report_prompts(**_COMMON_KWARGS, prompt_preferences=prefs)
    assert "supportive performance coach" in prompt.system_prompt
    assert "warm, supportive tone" in prompt.system_prompt
    assert "cautious inferences" in prompt.system_prompt
    assert "reflective performance analyst" not in prompt.system_prompt


def test_report_prompt_custom_nomenclature() -> None:
    prefs = {
        "nomenclature": {
            "principles_label": "Values",
            "kr_label": "Goals",
            "dci_label": "Journal",
        }
    }
    prompt = build_report_prompts(**_COMMON_KWARGS, prompt_preferences=prefs)
    assert "Values_and_Goals_markdown:" in prompt.user_prompt
    assert "Journal retro free-text evidence" in prompt.user_prompt
    assert "Assess alignment to values using evidence" in prompt.user_prompt
    assert "Assess Goals progress" in prompt.user_prompt


def test_report_prompt_preferences_change_fingerprint() -> None:
    base = build_report_prompts(**_COMMON_KWARGS, prompt_preferences=None)
    custom = build_report_prompts(
        **_COMMON_KWARGS,
        prompt_preferences={"persona": "accountability", "tone": "direct"},
    )
    assert base.prompt_version != custom.prompt_version


def test_eod_prompt_custom_nomenclature() -> None:
    prefs = {
        "nomenclature": {
            "principles_label": "Pillars",
            "kr_label": "Commitments",
        }
    }
    prompt = build_eod_relevance_prompt(
        item_type="note",
        item_text="Trained today",
        principles_markdown="## 1. Health\n",
        prompt_preferences=prefs,
    )
    assert "Pillars_and_Commitments_markdown:" in prompt.user_prompt
    assert "relevant to any pillars or commitments" in prompt.user_prompt.lower()


def test_eod_prompt_defaults_without_preferences() -> None:
    prompt = build_eod_relevance_prompt(
        item_type="note",
        item_text="Ran 5k",
        principles_markdown="## 1. Health\n",
        prompt_preferences=None,
    )
    assert "Principles_and_OKRs_markdown:" in prompt.user_prompt
    assert "principles/OKRs" in prompt.system_prompt
