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

# ── Persona / tone / strictness fragments ──────────────────────────────

_PERSONA_MAP: dict[str, str] = {
    "analyst": "You are a reflective performance analyst.",
    "coach": "You are a supportive performance coach.",
    "journal": "You are a thoughtful journaling companion.",
    "accountability": "You are a direct accountability partner.",
}

_TONE_MAP: dict[str, str] = {
    "sober": "Do not use emojis in your response. Keep it sober.",
    "supportive": "Use a warm, supportive tone. Encourage progress.",
    "direct": "Be direct and to the point. Challenge weak spots.",
    "neutral": "Use a neutral, factual tone.",
}

_STRICTNESS_MAP: dict[str, str] = {
    "strict": (
        "Use only the evidence from the provided context JSON and principles markdown. "
        "Do not invent events or metrics. "
        "If evidence is missing, use 'no_data' status and mention insufficient data in narrative."
    ),
    "moderate": (
        "Use the evidence from the provided context JSON and principles markdown. "
        "You may make cautious inferences when patterns are clear, but flag them as interpretive. "
        "If evidence is thin, note it."
    ),
    "interpretive": (
        "Use the evidence from the provided context JSON and principles markdown. "
        "You may interpret patterns and offer insights beyond the literal data, but keep them grounded. "
        "If evidence is missing, say so."
    ),
}

_DEFAULT_NOMENCLATURE: dict[str, str] = {
    "principles_label": "Principles",
    "kr_label": "OKRs",
    "dci_label": "Daily Check-In",
    "win_label": "Win",
    "friction_label": "Friction",
}


def _resolve_preferences(prefs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve prompt_preferences into concrete text fragments."""
    p = prefs or {}
    nomenclature = {**_DEFAULT_NOMENCLATURE, **(p.get("nomenclature") or {})}
    return {
        "persona": _PERSONA_MAP.get(p.get("persona", "analyst"), _PERSONA_MAP["analyst"]),
        "tone": _TONE_MAP.get(p.get("tone", "sober"), _TONE_MAP["sober"]),
        "strictness": _STRICTNESS_MAP.get(
            p.get("strictness", "strict"), _STRICTNESS_MAP["strict"]
        ),
        "nomenclature": nomenclature,
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
    prompt_preferences: dict[str, Any] | None = None,
) -> PromptPackage:
    """Build deterministic prompts for report synthesis.

    prompt_preferences is the ``[prompt_preferences]`` section from config.
    When *None* the original hardcoded behaviour is preserved.
    """
    rp = _resolve_preferences(prompt_preferences)
    nom = rp["nomenclature"]
    principles_label = nom["principles_label"]
    kr_label = nom["kr_label"]
    dci_label = nom["dci_label"]

    principles_text = principles_markdown or f"No {principles_label.lower()} file available."
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
        f"{rp['persona']} "
        f"{rp['strictness']} "
        f"{rp['tone']} "
        "Return only valid JSON with exactly the required keys. "
        f"Required JSON schema: {json.dumps(narrative_output_schema(), ensure_ascii=True)}"
    )

    user_prompt = (
        f"{principles_label}_and_{kr_label}_markdown:\n{principles_text}\n\n"
        f"Context_JSON:\n{context_json}\n\n"
        "Digest_schema_notes:\n"
        "- item_type = 'note' means SnR imported note text evidence.\n"
        f"- item_type = 'dci' means {dci_label} retro free-text evidence.\n"
        "- citation is verbatim evidence from the original item text.\n\n"
        "Task:\n"
        "1) Summarize what changed.\n"
        f"2) Assess alignment to {principles_label.lower()} using evidence.\n"
        f"3) Assess {kr_label} progress based on available evidence.\n"
        f"4) Use the provided digests as evidence for {principles_label.lower()} alignment and {kr_label} assessment.\n"
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
    prompt_preferences: dict[str, Any] | None = None,
) -> PromptPackage:
    """Build deterministic prompts for EOD relevance + digest extraction."""
    rp = _resolve_preferences(prompt_preferences)
    nom = rp["nomenclature"]
    principles_label = nom["principles_label"]
    kr_label = nom["kr_label"]

    clean_text = item_text.strip() or "(empty)"
    principles_text = principles_markdown or f"No {principles_label.lower()} file available."
    system_prompt = (
        f"You classify whether a personal activity note is relevant to the provided {principles_label.lower()}/{kr_label}. "
        f"If relevant, identify linked {principles_label.lower()} ids and {kr_label} refs and provide a concise digest. "
        "Always include one verbatim citation from the item text in the citation field. "
        "Use only provided text; do not infer facts not present. "
        "Return valid JSON only with exactly required keys. "
        f"Required JSON schema: {json.dumps(EOD_OUTPUT_SCHEMA, ensure_ascii=True)}"
    )
    user_prompt = (
        f"Item_type: {item_type}\n\n"
        f"{principles_label}_and_{kr_label}_markdown:\n{principles_text}\n\n"
        f"Item_text:\n{clean_text}\n\n"
        "Task:\n"
        f"1) Determine if this item is relevant to any {principles_label.lower()} or {kr_label}.\n"
        f"2) Return {principles_label.lower()}_ids as integer ids.\n"
        f"3) Return {kr_label.lower()}_refs as short labels when applicable.\n"
        "4) Write digest as 1-2 sentences explaining why/how it is relevant.\n"
        "5) citation must be a direct quote from Item_text (verbatim)."
    )
    prompt_fingerprint = f"{system_prompt}\n---\n{user_prompt}"
    prompt_version = hashlib.sha256(prompt_fingerprint.encode("utf-8")).hexdigest()[:16]
    return PromptPackage(system_prompt=system_prompt, user_prompt=user_prompt, prompt_version=prompt_version)
