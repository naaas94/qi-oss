"""Tests for heuristic classifier."""

from datetime import datetime

import pytest

from qi.models import ImportedNote
from qi.processing.heuristics import classify_event


class TestClassifyEvent:
    """Tests for event classification."""

    def test_win_from_positive_sentiment(self):
        """Test win detection from positive sentiment + keywords."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Finally shipped the new feature!",
            snr_sentiment="positive",
        )
        event = classify_event(note)
        assert event is not None
        assert event.event_type == "win"

    def test_win_from_tag(self):
        """Test win detection from win tag."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Got the promotion",
            snr_tags=["win", "career"],
        )
        event = classify_event(note)
        assert event is not None
        assert event.event_type == "win"

    def test_friction_from_negative_sentiment(self):
        """Test friction detection from negative sentiment."""
        note = ImportedNote(
            ts=datetime.now(),
            text="The meeting went poorly",
            snr_sentiment="negative",
        )
        event = classify_event(note)
        assert event is not None
        assert event.event_type == "friction"

    def test_friction_from_keywords(self):
        """Test friction detection from keywords."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Struggled with the database setup all day",
        )
        event = classify_event(note)
        assert event is not None
        assert event.event_type == "friction"

    def test_insight_from_intent(self):
        """Test insight detection from idea intent."""
        note = ImportedNote(
            ts=datetime.now(),
            text="What if we used caching?",
            snr_intent="idea",
        )
        event = classify_event(note)
        assert event is not None
        assert event.event_type == "insight"

    def test_insight_from_keywords(self):
        """Test insight detection from keywords."""
        note = ImportedNote(
            ts=datetime.now(),
            text="I realized the bottleneck is in the API calls",
        )
        event = classify_event(note)
        assert event is not None
        assert event.event_type == "insight"

    def test_compulsion_from_trigger(self):
        """Test compulsion detection."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Spent 2 hours on YouTube when I should have been working",
        )
        event = classify_event(note)
        assert event is not None
        assert event.event_type == "compulsion"
        assert event.trigger == "youtube"

    def test_domain_detection(self):
        """Test domain detection from tags."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Crushed my workout today",
            snr_tags=["gym", "training"],
            snr_sentiment="positive",
        )
        event = classify_event(note)
        assert event is not None
        assert event.domain == "health"

    def test_no_event_for_neutral(self):
        """Test that neutral notes without keywords don't create events."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Had lunch at the new place",
            snr_sentiment="neutral",
        )
        event = classify_event(note)
        assert event is None

    def test_compulsion_priority(self):
        """Test that compulsion detection has high priority."""
        # Even with positive sentiment, compulsion triggers should win
        note = ImportedNote(
            ts=datetime.now(),
            text="Finally finished binge watching that show",
            snr_sentiment="positive",
        )
        event = classify_event(note)
        assert event is not None
        assert event.event_type == "compulsion"

    def test_friction_keyword_does_not_match_substring(self):
        """Word-boundary matching should avoid false positives like tissue->issue."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Bought tissue and cleaned the desk.",
            snr_sentiment="neutral",
        )
        event = classify_event(note)
        assert event is None

    def test_win_keyword_does_not_match_substring(self):
        """Word-boundary matching should avoid false positives like wonderful->won."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Had a wonderful walk with no notable outcomes.",
            snr_sentiment="neutral",
        )
        event = classify_event(note)
        assert event is None
