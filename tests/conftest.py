"""Pytest fixtures for QI tests."""

import tempfile
from datetime import date, datetime
from pathlib import Path

# Hypothesis: use temp dir for example/constants storage so no local paths appear in repo.
# Must run before Hypothesis is used by any test.
_qi_hypothesis_dir = Path(tempfile.gettempdir()) / "qi_hypothesis"
_qi_hypothesis_dir.mkdir(exist_ok=True)
import hypothesis.configuration
hypothesis.configuration.set_hypothesis_home_dir(_qi_hypothesis_dir)

import pytest

from qi.models import DCI, ImportedNote, Event


@pytest.fixture
def temp_qi_home(monkeypatch):
    """Create a temporary QI home directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        qi_home = Path(tmpdir)
        qi_db_path = qi_home / "qi.db"
        qi_config_path = qi_home / "config.toml"
        
        # Create the directory
        qi_home.mkdir(parents=True, exist_ok=True)
        
        # Patch the config module variables BEFORE importing db
        import qi.config as config_module
        monkeypatch.setattr(config_module, "QI_HOME", qi_home)
        monkeypatch.setattr(config_module, "QI_DB_PATH", qi_db_path)
        monkeypatch.setattr(config_module, "QI_CONFIG_PATH", qi_config_path)
        
        # Also patch in db module since it imports these at module level
        import qi.db as db_module
        monkeypatch.setattr(db_module, "QI_DB_PATH", qi_db_path)
        monkeypatch.setattr(db_module, "QI_HOME", qi_home)
        
        yield qi_home


@pytest.fixture
def initialized_db(temp_qi_home):
    """Initialize the database for testing."""
    from qi.db import init_db
    init_db()
    return temp_qi_home


@pytest.fixture
def sample_dci():
    """Sample DCI for testing."""
    return DCI(
        date=date.today(),
        energy=7.5,
        mood=6.0,
        sleep=8.0,
        primary_focus="Test focus",
        one_win="Test win",
        one_friction="Test friction",
        metrics={
            "habit_1": True,
            "habit_2": True,
            "optional_note": "",
        }
    )


@pytest.fixture
def sample_dcis():
    """Sample list of DCIs for testing."""
    from datetime import timedelta
    
    dcis = []
    base_date = date.today()
    
    for i in range(7):
        dcis.append(DCI(
            date=base_date - timedelta(days=i),
            energy=5.0 + (i % 3),
            mood=6.0 + (i % 2),
            sleep=7.0 + (i % 4),
            metrics={
                "habit_1": (i % 2 == 0),
                "habit_2": (i % 3 == 0),
                "optional_note": f"note_{i}" if i % 2 else "",
            }
        ))
    
    return dcis


@pytest.fixture
def sample_note():
    """Sample imported note for testing."""
    return ImportedNote(
        snr_id="test-123",
        ts=datetime.now(),
        text="Finally shipped the new feature!",
        snr_tags=["work", "code"],
        snr_sentiment="positive",
        snr_intent="task",
    )


@pytest.fixture
def sample_notes():
    """Sample list of notes for testing."""
    from datetime import timedelta
    
    notes = [
        ImportedNote(
            snr_id="note-1",
            ts=datetime.now() - timedelta(hours=1),
            text="Shipped the auth module finally!",
            snr_tags=["work", "code"],
            snr_sentiment="positive",
        ),
        ImportedNote(
            snr_id="note-2",
            ts=datetime.now() - timedelta(hours=2),
            text="Struggled with the database migration",
            snr_tags=["work"],
            snr_sentiment="negative",
        ),
        ImportedNote(
            snr_id="note-3",
            ts=datetime.now() - timedelta(hours=3),
            text="Realized I should batch the API calls",
            snr_tags=["code", "insight"],
            snr_intent="idea",
        ),
        ImportedNote(
            snr_id="note-4",
            ts=datetime.now() - timedelta(hours=4),
            text="Wasted an hour on YouTube",
            snr_tags=["distraction"],
            snr_sentiment="negative",
        ),
    ]
    return notes
