"""Heuristic classifier for event extraction from notes."""

import re

from qi.db import get_unprocessed_notes, mark_note_processed, save_event
from qi.models import Event, EventType, ImportedNote

# Default keyword lists (can be overridden via config)
WIN_KEYWORDS = [
    "shipped",
    "completed",
    "achieved",
    "finally",
    "breakthrough",
    "success",
    "won",
    "finished",
    "accomplished",
    "nailed",
    "crushed",
]

FRICTION_KEYWORDS = [
    "blocked",
    "struggled",
    "frustrated",
    "stuck",
    "failed",
    "problem",
    "issue",
    "difficulty",
    "challenge",
    "obstacle",
    "friction",
]

INSIGHT_KEYWORDS = [
    "realized",
    "insight",
    "learned",
    "discovered",
    "understood",
    "aha",
    "eureka",
    "idea",
    "noticed",
]

COMPULSION_TRIGGERS = [
    "youtube",
    "scroll",
    "distraction",
    "procrastination",
    "compulsion",
    "twitter",
    "reddit",
    "netflix",
    "binge",
    "wasted",
]

DOMAIN_TAG_MAP = {
    "health": ["gym", "sleep", "nutrition", "training", "workout", "exercise", "health"],
    "career": ["work", "project", "meeting", "code", "job", "career", "professional"],
    "social": ["friend", "family", "call", "hangout", "social", "relationship"],
    "cognition": ["learning", "study", "reading", "thinking", "cognitive"],
    "nature": ["nature", "outdoor", "hiking", "walk", "garden"],
    "finance": ["money", "finance", "budget", "investment", "savings"],
}


def classify_event(note: ImportedNote) -> Event | None:
    """
    Use SnR tags + text patterns to classify into QI event types.
    Returns None if note doesn't map to a trackable event.
    """
    text_lower = note.text.lower()
    snr_tags = set(note.snr_tags or [])

    event_type: EventType | None = None
    domain = None
    trigger = None

    # Compulsion detection (high priority - behavioral tracking)
    if "compulsion" in snr_tags or any(_contains_word(text_lower, t) for t in COMPULSION_TRIGGERS):
        event_type = "compulsion"
        # Try to extract trigger
        for trigger_word in COMPULSION_TRIGGERS:
            if _contains_word(text_lower, trigger_word):
                trigger = trigger_word
                break

    # Win detection
    elif note.snr_sentiment == "positive" and any(_contains_word(text_lower, w) for w in WIN_KEYWORDS):
        event_type = "win"
    elif "win" in snr_tags:
        event_type = "win"

    # Friction detection
    elif note.snr_sentiment == "negative" or "friction" in snr_tags:
        event_type = "friction"
    elif any(_contains_word(text_lower, f) for f in FRICTION_KEYWORDS):
        event_type = "friction"

    # Insight detection
    elif note.snr_intent == "idea" or "insight" in snr_tags:
        event_type = "insight"
    elif any(_contains_word(text_lower, i) for i in INSIGHT_KEYWORDS):
        event_type = "insight"

    # If no event type detected, skip
    if event_type is None:
        return None

    # Detect domain from tags
    for domain_name, domain_tags in DOMAIN_TAG_MAP.items():
        if snr_tags & set(domain_tags):
            domain = domain_name
            break
        # Also check in text
        for tag in domain_tags:
            if _contains_word(text_lower, tag):
                domain = domain_name
                break
        if domain:
            break

    return Event(
        ts=note.ts,
        event_type=event_type,
        domain=domain,
        trigger=trigger,
    )


def process_unprocessed_notes() -> tuple[int, int]:
    """
    Process all unprocessed notes with heuristic classifier.
    Returns (notes_processed, events_created).
    """
    notes = get_unprocessed_notes()
    processed = 0
    events_created = 0

    for note_id, note in notes:
        event = classify_event(note)
        event_id = None

        if event:
            event.note_id = note_id
            event_id = save_event(event)
            events_created += 1

        mark_note_processed(note_id, event_id)
        processed += 1

    return processed, events_created


def _contains_word(text: str, keyword: str) -> bool:
    """Match keywords on word boundaries to avoid substring false positives."""
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
