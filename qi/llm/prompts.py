"""Prompt builders for report narrative synthesis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from qi.llm.schema import narrative_output_schema


@dataclass
class PromptPackage:
    """Container for prompts and prompt version hash."""

    system_prompt: str
    user_prompt: str
    prompt_version: str


EOD_OUTPUT_SCHEMA = {
    "relevant": "boolean",
    "principle_ids": ["integer"],
    "kr_refs": ["string"],
    "digest": "string (1-2 sentences)",
    "citation": "string (verbatim quote from item text)",
}


def build_report_prompts(
    *,
    report_type: str,
    window_start: date,
    window_end: date,
    input_snapshot: dict[str, Any],
    features_snapshot: dict[str, Any],
    analysis_snapshot: dict[str, Any],
    principles_markdown: str | None,
    daily_series: dict[str, Any] | None = None,
    digests: list[dict[str, Any]] | None = None,
) -> PromptPackage:
    """Build deterministic prompts for report synthesis."""
    principles_text = principles_markdown or "No principles file available."
    context = {
        "report_type": report_type,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "input_snapshot": input_snapshot,
        "features_snapshot": features_snapshot,
        "analysis_snapshot": analysis_snapshot,
    }
    if daily_series:
        context["daily_series"] = daily_series
    if digests:
        context["digests"] = digests
    context_json = json.dumps(context, indent=2, ensure_ascii=True, sort_keys=True)

    system_prompt = (
        "You are a reflective performance analyst. "
        "Use only the evidence from the provided context JSON and principles markdown. "
        "Do not invent events or metrics. "
        "Do not use emojis in your response. Keep it sober. "
        "If evidence is missing, use 'no_data' status and mention insufficient data in narrative. "
        "Return only valid JSON with exactly the required keys. "
        f"Required JSON schema: {json.dumps(narrative_output_schema(), ensure_ascii=True)}"
    )

    user_prompt = (
        f"Principles_and_KRs_markdown:\n{principles_text}\n\n"
        f"Context_JSON:\n{context_json}\n\n"
        "Digest_schema_notes:\n"
        "- item_type = 'note' means SnR imported note text evidence.\n"
        "- item_type = 'dci' means Daily Check-In retro free-text evidence.\n"
        "- citation is verbatim evidence from the original item text.\n\n"
        "Task:\n"
        "1) Summarize what changed.\n"
        "2) Assess alignment to principles using evidence.\n"
        "3) Assess KR progress based on available evidence.\n"
        "4) Use the provided digests as evidence for principle alignment and KR assessment.\n"
        "5) Propose one practical next experiment with a measurable outcome."
    )

    prompt_fingerprint = f"{system_prompt}\n---\n{user_prompt}"
    prompt_version = hashlib.sha256(prompt_fingerprint.encode("utf-8")).hexdigest()[:16]
    return PromptPackage(system_prompt=system_prompt, user_prompt=user_prompt, prompt_version=prompt_version)


def build_repair_prompt(invalid_output: str) -> str:
    """Build a one-shot repair prompt for malformed JSON outputs."""
    return (
        "The previous response did not satisfy the required JSON contract. "
        "Rewrite it as valid JSON only with the required keys and no extra text.\n\n"
        f"Invalid_output:\n{invalid_output}"
    )


def build_eod_relevance_prompt(
    *,
    item_type: str,
    item_text: str,
    principles_markdown: str | None,
) -> PromptPackage:
    """Build deterministic prompts for EOD relevance + digest extraction."""
    clean_text = item_text.strip() or "(empty)"
    principles_text = principles_markdown or "No principles file available."
    system_prompt = (
        "You classify whether a personal activity note is relevant to the provided principles/KRs. "
        "If relevant, identify linked principle ids and KR refs and provide a concise digest. "
        "Always include one verbatim citation from the item text in the citation field. "
        "Use only provided text; do not infer facts not present. "
        "Return valid JSON only with exactly required keys. "
        f"Required JSON schema: {json.dumps(EOD_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    user_prompt = (
        f"Item_type: {item_type}\n\n"
        f"Principles_and_KRs_markdown:\n{principles_text}\n\n"
        f"Item_text:\n{clean_text}\n\n"
        "Task:\n"
        "1) Determine if this item is relevant to any principle or KR.\n"
        "2) Return principle_ids as integer ids.\n"
        "3) Return kr_refs as short labels when applicable.\n"
        "4) Write digest as 1-2 sentences explaining why/how it is relevant.\n"
        "5) citation must be a direct quote from Item_text (verbatim)."
    )
    prompt_fingerprint = f"{system_prompt}\n---\n{user_prompt}"
    prompt_version = hashlib.sha256(prompt_fingerprint.encode("utf-8")).hexdigest()[:16]
    return PromptPackage(system_prompt=system_prompt, user_prompt=user_prompt, prompt_version=prompt_version)
