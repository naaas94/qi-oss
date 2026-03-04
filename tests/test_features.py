"""Tests for feature engineering."""

from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import HealthCheck
from hypothesis import settings
from hypothesis import strategies as st

from qi.db import save_dci
from qi.models import DCI
from qi.processing.features import (
    compute_features,
    get_trend,
    _compute_streak,
    _get_top_items,
)


class TestComputeFeatures:
    """Tests for compute_features function."""

    def test_empty_data(self, initialized_db):
        """Test with no data."""
        features = compute_features(date.today(), date.today())
        assert features.get("insufficient_data") is True

    def test_with_dcis(self, initialized_db, sample_dcis):
        """Test with sample DCIs."""
        from qi.db import save_dci
        
        for dci in sample_dcis:
            save_dci(dci)
        
        start = date.today() - timedelta(days=6)
        end = date.today()
        
        features = compute_features(start, end)
        
        assert features.get("dci_count") == 7
        assert features.get("energy_mean") is not None
        assert features.get("dci_streak") >= 0


class TestGetTrend:
    """Tests for trend detection."""

    def test_improving_trend(self):
        """Test detecting improving trend."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert get_trend(values) == "improving"

    def test_declining_trend(self):
        """Test detecting declining trend."""
        values = [5.0, 4.0, 3.0, 2.0, 1.0]
        assert get_trend(values) == "declining"

    def test_stable_trend(self):
        """Test detecting stable trend."""
        values = [5.0, 5.0, 5.0, 5.0, 5.0]
        assert get_trend(values) == "stable"

    def test_insufficient_data(self):
        """Test with insufficient data."""
        assert get_trend([5.0]) == "insufficient_data"
        assert get_trend([]) == "insufficient_data"

    @given(
        st.lists(
            st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=50,
        ),
        st.floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
    )
    def test_trend_invariant_under_translation(self, values, offset):
        """Adding a constant offset should not change trend classification."""
        translated = [v + offset for v in values]
        assert get_trend(values) == get_trend(translated)


class TestPropertyBasedFeatures:
    """Property-based tests for feature outputs."""

    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=10),  # energy
                st.integers(min_value=0, max_value=10),  # mood
                st.integers(min_value=0, max_value=10),  # sleep
            ),
            min_size=1,
            max_size=20,
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_compute_features_preserves_basic_invariants(self, initialized_db, score_triplets):
        """
        For any non-empty valid DCI sequence:
        - dci_count matches inserted records
        - means stay in the configured input range
        """
        start = date(2026, 1, 1)

        for i, (energy, mood, sleep) in enumerate(score_triplets):
            save_dci(
                DCI(
                    date=start + timedelta(days=i),
                    energy=energy,
                    mood=mood,
                    sleep=sleep,
                    metrics={},
                )
            )

        end = start + timedelta(days=len(score_triplets) - 1)
        features = compute_features(start, end)

        assert features["dci_count"] == len(score_triplets)
        assert 0 <= features["energy_mean"] <= 10
        assert 0 <= features["mood_mean"] <= 10
        assert 0 <= features["sleep_mean"] <= 10


class TestComputeStreak:
    """Tests for streak computation."""

    def test_empty_streak(self):
        """Test with no data."""
        assert _compute_streak([]) == 0

    def test_consecutive_streak(self):
        """Test with consecutive days."""
        dcis = [
            DCI(date=date.today(), energy=5, mood=5, sleep=5),
            DCI(date=date.today() - timedelta(days=1), energy=5, mood=5, sleep=5),
            DCI(date=date.today() - timedelta(days=2), energy=5, mood=5, sleep=5),
        ]
        assert _compute_streak(dcis) == 3

    def test_broken_streak(self):
        """Test with a gap in dates."""
        dcis = [
            DCI(date=date.today(), energy=5, mood=5, sleep=5),
            DCI(date=date.today() - timedelta(days=2), energy=5, mood=5, sleep=5),
        ]
        assert _compute_streak(dcis) == 1


class TestGetTopItems:
    """Tests for top items computation."""

    def test_empty_list(self):
        """Test with empty list."""
        assert _get_top_items([], 3) == []

    def test_single_item(self):
        """Test with single item."""
        items = ["youtube", "youtube", "youtube"]
        result = _get_top_items(items, 3)
        assert result == [("youtube", 3)]

    def test_multiple_items(self):
        """Test with multiple items."""
        items = ["youtube", "reddit", "youtube", "twitter", "youtube", "reddit"]
        result = _get_top_items(items, 2)
        assert result[0] == ("youtube", 3)
        assert result[1] == ("reddit", 2)
