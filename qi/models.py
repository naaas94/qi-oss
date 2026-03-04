"""Pydantic models for QI data types."""

from datetime import date, datetime
from typing import Literal, Any

from pydantic import BaseModel, Field


class DCI(BaseModel):
    """Daily Check-In model."""

    date: date
    energy: float = Field(ge=0, le=10)
    mood: float = Field(ge=0, le=10)
    sleep: float = Field(ge=0, le=10)
    primary_focus: str | None = None
    one_win: str | None = None
    one_friction: str | None = None
    comment: str | None = None

    # Dynamic metrics
    metrics: dict[str, Any] = Field(default_factory=dict)

    # Carryover
    residual: list[str] = Field(default_factory=list)


class ImportedNote(BaseModel):
    """Note imported from SnR QC JSONL export."""

    snr_id: str | None = None
    ts: datetime
    text: str

    # SnR QC parsed fields
    snr_tags: list[str] | None = None
    snr_sentiment: Literal["positive", "neutral", "negative"] | None = None
    snr_entities: list[str] | None = None
    snr_intent: str | None = None
    snr_action_items: list[str] | None = None
    snr_people: list[str] | None = None
    snr_summary: str | None = None
    snr_quality_score: float | None = None

    # QI processing state
    qi_processed: bool = False
    qi_event_id: int | None = None


EventType = Literal["win", "friction", "insight", "compulsion", "avoidance"]
Domain = Literal["health", "career", "social", "cognition", "nature", "finance"]


class Event(BaseModel):
    """Structured event extracted from notes."""

    ts: datetime
    note_id: int | None = None
    domain: Domain | None = None
    event_type: EventType
    trigger: str | None = None
    intensity: int | None = Field(default=None, ge=1, le=5)
    behavior: str | None = None
    counterfactual: str | None = None


class OneChange(BaseModel):
    """One change commitment for weekly retro."""

    title: str
    mechanism: str
    measurement: str


class WeeklyRetro(BaseModel):
    """Weekly retrospective model."""

    week_start: date
    scoreboard: dict[str, int | float]
    wins: list[str]
    frictions: list[str]
    root_cause: str | None = None
    one_change: OneChange
    minimums: dict[str, int | float]
    commitment_met: bool | None = None


class Artifact(BaseModel):
    """Report artifact model."""

    artifact_type: Literal["weekly_digest", "monthly_dossier"]
    window_start: date
    window_end: date
    input_snapshot: dict
    features_snapshot: dict
    output_json: dict
    rendered_markdown: str
    prompt_version: str | None = None
    model_id: str | None = None


class RelevanceDigest(BaseModel):
    """Per-item relevance and digest produced by EOD processing."""

    item_type: Literal["note", "dci"]
    item_id: int
    source_ts: datetime
    relevant: bool
    principle_ids: list[int] = Field(default_factory=list)
    kr_refs: list[str] = Field(default_factory=list)
    digest: str | None = None
    citation: str | None = None
    model: str | None = None
    total_tokens: int | None = None
    processing_duration_ms: int | None = None
    status: Literal["success", "failed"] = "success"
    error_message: str | None = None
