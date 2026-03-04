"""Tests for LLM narrative markdown rendering."""

from __future__ import annotations

from qi.llm.render import render_narrative_markdown
from qi.llm.validate import NarrativeOutput


def test_render_narrative_markdown_happy_path() -> None:
    """Fully populated narrative should render all sections and bullets."""
    narrative = NarrativeOutput.model_validate(
        {
            "weekly_summary": "Good week overall.",
            "delta_narrative": "Energy trended up.",
            "principle_alignment": [
                {"principle_id": 1, "status": "on_track", "note": "Training remained consistent."}
            ],
            "kr_progress": [{"kr": "KR1", "assessment": "On track"}],
            "coaching_focus": "Preserve morning routine.",
            "next_experiment": "Measure bedtime consistency for 7 days.",
            "risks": ["Late work spillover."],
            "confidence": 0.83,
        }
    )

    rendered = render_narrative_markdown(narrative, principle_names={1: "Health Baseline"})
    assert "## LLM Narrative" in rendered
    assert "### Summary" in rendered
    assert "- Health Baseline (on_track): Training remained consistent." in rendered
    assert "- KR1: On track" in rendered
    assert "### Confidence\n0.83" in rendered


def test_render_narrative_markdown_handles_empty_lists() -> None:
    """Renderer should gracefully handle empty list fields."""
    narrative = NarrativeOutput.model_validate(
        {
            "weekly_summary": "Sparse evidence.",
            "delta_narrative": "Not enough data to infer a trend.",
            "principle_alignment": [],
            "kr_progress": [],
            "coaching_focus": "Collect higher quality observations.",
            "next_experiment": "Capture one concrete example daily.",
            "risks": [],
            "confidence": 0.41,
        }
    )

    rendered = render_narrative_markdown(narrative)
    assert "- No principle alignment data." in rendered
    assert "- No KR progress data." in rendered
    assert "- No explicit risks identified." in rendered

