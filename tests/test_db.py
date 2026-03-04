"""Tests for database operations."""

from datetime import date, datetime, timedelta

import pytest

from qi.models import DCI, ImportedNote, Event, WeeklyRetro, OneChange
from qi.db import (
    init_db,
    save_dci,
    get_dci,
    get_dci_range,
    save_imported_note,
    get_unprocessed_notes,
    mark_note_processed,
    save_event,
    get_events_in_range,
    save_weekly_retro,
    get_weekly_retro,
)


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_init_creates_db(self, temp_qi_home):
        """Test that init_db creates the database."""
        from qi.config import QI_DB_PATH
        
        assert not QI_DB_PATH.exists()
        created, migrations = init_db()
        assert created is True
        assert migrations >= 1
        assert QI_DB_PATH.exists()

    def test_init_idempotent(self, initialized_db):
        """Test that init_db can be run multiple times."""
        created, migrations = init_db()
        assert created is False
        assert migrations == 0


class TestDCIOperations:
    """Tests for DCI database operations."""

    def test_save_and_get_dci(self, initialized_db, sample_dci):
        """Test saving and retrieving a DCI."""
        save_dci(sample_dci)
        
        retrieved = get_dci(sample_dci.date)
        assert retrieved is not None
        assert retrieved.energy == sample_dci.energy
        assert retrieved.mood == sample_dci.mood
        assert retrieved.metrics == sample_dci.metrics

    def test_get_dci_range(self, initialized_db, sample_dcis):
        """Test getting DCIs in a range."""
        for dci in sample_dcis:
            save_dci(dci)
        
        start = date.today() - timedelta(days=6)
        end = date.today()
        
        dcis = get_dci_range(start, end)
        assert len(dcis) == 7

    def test_update_dci(self, initialized_db, sample_dci):
        """Test updating an existing DCI."""
        save_dci(sample_dci)
        
        # Update
        sample_dci.energy = 9.0
        save_dci(sample_dci)
        
        retrieved = get_dci(sample_dci.date)
        assert retrieved.energy == 9.0

    def test_save_and_get_unicode_and_empty_fields(self, initialized_db):
        """Unicode text and empty strings should round-trip correctly."""
        dci = DCI(
            date=date.today(),
            energy=7,
            mood=8,
            sleep=6,
            primary_focus="",
            one_win="Felt calm - mañana",
            one_friction="",
            comment="Worked through naïve approach",
            metrics={"habit_1": True},
            residual=["review PR", "hydrate"],
        )
        save_dci(dci)
        retrieved = get_dci(dci.date)
        assert retrieved is not None
        assert retrieved.primary_focus == ""
        assert retrieved.one_friction == ""
        assert "mañana" in (retrieved.one_win or "")
        assert "naïve" in (retrieved.comment or "")

    def test_boundary_dates_round_trip(self, initialized_db):
        """Boundary date values should persist and query reliably."""
        early = DCI(date=date(1970, 1, 1), energy=5, mood=5, sleep=5)
        future = DCI(date=date(2099, 12, 31), energy=6, mood=6, sleep=6)
        save_dci(early)
        save_dci(future)
        in_range = get_dci_range(date(1970, 1, 1), date(2099, 12, 31))
        dates = {entry.date for entry in in_range}
        assert date(1970, 1, 1) in dates
        assert date(2099, 12, 31) in dates


class TestNoteOperations:
    """Tests for note database operations."""

    def test_save_and_get_note(self, initialized_db, sample_note):
        """Test saving and retrieving a note."""
        save_imported_note(sample_note)
        
        notes = get_unprocessed_notes()
        assert len(notes) == 1
        assert notes[0][1].text == sample_note.text

    def test_mark_note_processed(self, initialized_db, sample_note):
        """Test marking a note as processed."""
        save_imported_note(sample_note)
        notes = get_unprocessed_notes()
        note_id = notes[0][0]
        
        mark_note_processed(note_id, None)
        
        notes = get_unprocessed_notes()
        assert len(notes) == 0

    def test_duplicate_snr_id_upserts(self, initialized_db):
        """Saving the same snr_id twice should update, not duplicate."""
        ts = datetime.now()
        first = ImportedNote(snr_id="dup-1", ts=ts, text="original")
        second = ImportedNote(snr_id="dup-1", ts=ts, text="updated")
        save_imported_note(first)
        save_imported_note(second)
        notes = get_unprocessed_notes()
        assert len(notes) == 1
        assert notes[0][1].text == "updated"


class TestEventOperations:
    """Tests for event database operations."""

    def test_save_and_get_event(self, initialized_db):
        """Test saving and retrieving an event."""
        event = Event(
            ts=datetime.now(),
            event_type="win",
            domain="career",
        )
        event_id = save_event(event)
        assert event_id > 0
        
        events = get_events_in_range(date.today(), date.today())
        assert len(events) == 1
        assert events[0].event_type == "win"


class TestWeeklyRetroOperations:
    """Tests for weekly retro database operations."""

    def test_save_and_get_retro(self, initialized_db):
        """Test saving and retrieving a weekly retro."""
        retro = WeeklyRetro(
            week_start=date.today(),
            scoreboard={"training": 4},
            wins=["Win 1"],
            frictions=["Friction 1"],
            one_change=OneChange(
                title="Test",
                mechanism="Test",
                measurement="Test",
            ),
            minimums={"training": 3},
        )
        
        save_weekly_retro(retro)
        retrieved = get_weekly_retro(date.today())
        
        assert retrieved is not None
        assert retrieved.wins == ["Win 1"]
