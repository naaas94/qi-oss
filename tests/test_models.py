"""Tests for QI models."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from qi.models import DCI, ImportedNote, Event, WeeklyRetro, OneChange


class TestDCI:
    """Tests for DCI model."""

    def test_valid_dci(self):
        """Test creating a valid DCI."""
        dci = DCI(
            date=date.today(),
            energy=7.5,
            mood=6.0,
            sleep=8.0,
        )
        assert dci.energy == 7.5
        assert dci.mood == 6.0
        assert dci.sleep == 8.0

    def test_dci_defaults(self):
        """Test DCI default values."""
        dci = DCI(
            date=date.today(),
            energy=5.0,
            mood=5.0,
            sleep=5.0,
        )
        assert dci.metrics == {}
        assert dci.residual == []

    def test_dci_energy_range(self):
        """Test energy must be between 0 and 10."""
        with pytest.raises(ValidationError):
            DCI(date=date.today(), energy=11.0, mood=5.0, sleep=5.0)
        
        with pytest.raises(ValidationError):
            DCI(date=date.today(), energy=-1.0, mood=5.0, sleep=5.0)

    def test_dci_dynamic_metrics(self):
        """Test that dynamic metrics can be stored."""
        dci = DCI(
            date=date.today(),
            energy=5.0,
            mood=5.0,
            sleep=5.0,
            metrics={"habit_1": True, "habit_2": False, "optional_note": "done"},
        )
        assert dci.metrics.get("habit_1") is True
        assert dci.metrics.get("habit_2") is False
        assert dci.metrics.get("optional_note") == "done"


class TestImportedNote:
    """Tests for ImportedNote model."""

    def test_valid_note(self):
        """Test creating a valid imported note."""
        note = ImportedNote(
            ts=datetime.now(),
            text="Test note",
        )
        assert note.text == "Test note"
        assert note.qi_processed is False

    def test_note_with_snr_fields(self):
        """Test note with SnR QC parsed fields."""
        note = ImportedNote(
            snr_id="abc123",
            ts=datetime.now(),
            text="Meeting with John",
            snr_tags=["meeting", "work"],
            snr_sentiment="neutral",
            snr_people=["John"],
        )
        assert note.snr_tags == ["meeting", "work"]
        assert note.snr_sentiment == "neutral"


class TestEvent:
    """Tests for Event model."""

    def test_valid_event(self):
        """Test creating a valid event."""
        event = Event(
            ts=datetime.now(),
            event_type="win",
        )
        assert event.event_type == "win"

    def test_event_with_domain(self):
        """Test event with domain."""
        event = Event(
            ts=datetime.now(),
            event_type="friction",
            domain="career",
            trigger="deadline",
        )
        assert event.domain == "career"
        assert event.trigger == "deadline"

    def test_event_intensity_range(self):
        """Test intensity must be between 1 and 5."""
        with pytest.raises(ValidationError):
            Event(ts=datetime.now(), event_type="win", intensity=0)
        
        with pytest.raises(ValidationError):
            Event(ts=datetime.now(), event_type="win", intensity=6)


class TestWeeklyRetro:
    """Tests for WeeklyRetro model."""

    def test_valid_weekly_retro(self):
        """Test creating a valid weekly retro."""
        retro = WeeklyRetro(
            week_start=date.today(),
            scoreboard={"habit_days": 4, "focus_blocks": 5},
            wins=["Shipped feature", "Fixed bug"],
            frictions=["Meeting overran"],
            one_change=OneChange(
                title="Wake up earlier",
                mechanism="Set alarm for 6am",
                measurement="Track wake time",
            ),
            minimums={"habit_days": 3},
        )
        assert len(retro.wins) == 2
        assert retro.one_change.title == "Wake up earlier"
