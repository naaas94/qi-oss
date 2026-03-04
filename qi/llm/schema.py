"""Single-source narrative schema for LLM prompts and validation."""

from __future__ import annotations

from typing import Literal, get_args, get_origin

from pydantic import BaseModel, Field


class PrincipleAlignment(BaseModel):
    """LLM-assessed alignment status for a principle."""

    principle_id: int
    status: Literal["on_track", "slipping", "no_data"]
    note: str


class KRProgress(BaseModel):
    """LLM-assessed progress status for a KR."""

    kr: str
    assessment: str


class NarrativeOutput(BaseModel):
    """Validated narrative output contract."""

    weekly_summary: str
    delta_narrative: str
    principle_alignment: list[PrincipleAlignment]
    kr_progress: list[KRProgress]
    coaching_focus: str
    next_experiment: str
    risks: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


def narrative_output_schema() -> dict[str, object]:
    """Render a lightweight JSON schema spec from the Pydantic model."""
    status_annotation = PrincipleAlignment.model_fields["status"].annotation
    status_values = get_args(status_annotation) if get_origin(status_annotation) is Literal else ()
    status_spec = "|".join(str(v) for v in status_values) if status_values else "string"
    return {
        "weekly_summary": "string",
        "delta_narrative": "string",
        "principle_alignment": [
            {"principle_id": "integer", "status": status_spec, "note": "string"}
        ],
        "kr_progress": [{"kr": "string", "assessment": "string"}],
        "coaching_focus": "string",
        "next_experiment": "string",
        "risks": ["string"],
        "confidence": "number between 0 and 1",
    }
