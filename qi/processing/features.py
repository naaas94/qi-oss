"""Feature engineering for QI reports."""

from datetime import date
from statistics import mean, stdev
from typing import Any, TypedDict

from qi.db import get_dci_range, get_events_in_range
from qi.models import DCI, Event


class FeatureSnapshot(TypedDict, total=False):
    """Typed snapshot of report features (plus dynamic metric keys from config)."""

    insufficient_data: bool
    energy_mean: float | None
    mood_mean: float | None
    sleep_mean: float | None
    mood_volatility: float | None
    dci_streak: int
    habit_streak: int
    win_count: int
    friction_count: int
    insight_count: int
    compulsion_event_count: int
    dci_count: int
    event_count: int


def compute_features(
    start_date: date,
    end_date: date,
    *,
    dcis: list[DCI] | None = None,
    events: list[Event] | None = None,
) -> FeatureSnapshot:
    """
    Compute features for a date range.
    
    Returns a dictionary with:
    - Core metrics (means, volatility)
    - Training metrics
    - Token aggregates
    - Event counts
    - Streaks
    """
    if dcis is None:
        dcis = get_dci_range(start_date, end_date)
    if events is None:
        events = get_events_in_range(start_date, end_date)
    
    features: FeatureSnapshot = {}
    
    if not dcis:
        features["insufficient_data"] = True
        return features
    
    # Core metrics
    energies = [d.energy for d in dcis]
    moods = [d.mood for d in dcis]
    sleeps = [d.sleep for d in dcis]
    
    features["energy_mean"] = mean(energies) if energies else None
    features["mood_mean"] = mean(moods) if moods else None
    features["sleep_mean"] = mean(sleeps) if sleeps else None
    
    # Volatility (requires at least 2 data points)
    if len(moods) >= 2:
        features["mood_volatility"] = stdev(moods)
    else:
        features["mood_volatility"] = None
    
    # Dynamic metrics from config only
    from qi.config import load_config
    config = load_config()
    dci_metrics = config.get("dci_metrics", {})

    for key, metric_def in dci_metrics.items():
        if metric_def.get("type") in ("bool", "int", "float"):
            values = [d.metrics.get(key) for d in dcis if d.metrics.get(key) is not None]
            if metric_def.get("aggregate") == "sum":
                features[f"{key}_total"] = sum(values) if values else 0
            elif metric_def.get("aggregate") == "rate":
                features[f"{key}_rate"] = sum(bool(v) for v in values) / len(values) if values else 0
            elif metric_def.get("aggregate") == "count":
                features[f"{key}_count"] = sum(bool(v) for v in values)

    # Streaks
    features["dci_streak"] = _compute_streak(dcis)
    features["habit_streak"] = _compute_habit_streak(dcis, dci_metrics)

    # Event counts
    features["win_count"] = sum(1 for e in events if e.event_type == "win")
    features["friction_count"] = sum(1 for e in events if e.event_type == "friction")
    features["insight_count"] = sum(1 for e in events if e.event_type == "insight")
    features["compulsion_event_count"] = sum(1 for e in events if e.event_type == "compulsion")
    
    # Total entries
    features["dci_count"] = len(dcis)
    features["event_count"] = len(events)
    
    return features


def compute_daily_series(
    start_date: date,
    end_date: date,
    *,
    dcis: list[DCI] | None = None,
) -> dict[str, Any]:
    """Compute day-ordered series for report-window temporal reasoning."""
    if dcis is None:
        dcis = get_dci_range(start_date, end_date)
    
    # Initialize with core metrics
    series: dict[str, list[Any]] = {
        "dates": [],
        "energy": [],
        "mood": [],
        "sleep": [],
    }

    # Dynamically find what boolean/numeric metrics to include in daily series
    from qi.config import load_config
    config = load_config()
    dci_metrics = config.get("dci_metrics", {})
    metric_keys = [k for k, v in dci_metrics.items() if v.get("type") in ("bool", "int", "float")]
    for k in metric_keys:
        series[k] = []

    for dci in dcis:
        series["dates"].append(dci.date.isoformat())
        series["energy"].append(dci.energy)
        series["mood"].append(dci.mood)
        series["sleep"].append(dci.sleep)
        for k in metric_keys:
            val = dci.metrics.get(k)
            # Preserve missing values as None to distinguish not-logged from zero/false.
            series[k].append(val)

    return series


def _compute_streak(dcis: list) -> int:
    """Compute current streak of consecutive DCI entries."""
    if not dcis:
        return 0
    
    # Sort by date descending
    sorted_dcis = sorted(dcis, key=lambda d: d.date, reverse=True)
    
    streak = 1
    for i in range(1, len(sorted_dcis)):
        # Check if dates are consecutive
        diff = (sorted_dcis[i - 1].date - sorted_dcis[i].date).days
        if diff == 1:
            streak += 1
        else:
            break
    
    return streak


def _compute_habit_streak(dcis: list[DCI], dci_metrics: dict) -> int:
    """Compute streak of consecutive days where the first config bool (count) metric is true."""
    if not dcis:
        return 0
    first_count_bool = next(
        (k for k, v in dci_metrics.items() if v.get("type") == "bool" and v.get("aggregate") == "count"),
        None,
    )
    if not first_count_bool:
        return 0
    sorted_dcis = sorted(dcis, key=lambda d: d.date, reverse=True)
    streak = 0
    for i, dci in enumerate(sorted_dcis):
        if dci.metrics.get(first_count_bool):
            if i == 0:
                streak = 1
            elif (sorted_dcis[i - 1].date - dci.date).days == 1:
                streak += 1
            else:
                break
        else:
            if streak > 0:
                break
    return streak


def _get_top_items(items: list[str], n: int) -> list[tuple[str, int]]:
    """Get top N items by frequency."""
    from collections import Counter
    counter = Counter(items)
    return counter.most_common(n)


def compute_delta(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Compute week-over-week deltas."""
    deltas = {}
    
    numeric_keys = [
        "energy_mean", "mood_mean", "sleep_mean",
        "win_count", "friction_count", "insight_count",
    ]
    
    # Add dynamic metric keys that end in _total, _rate, or _count
    for k in current:
        if k.endswith("_total") or k.endswith("_rate") or k.endswith("_count"):
            if k not in numeric_keys:
                numeric_keys.append(k)
    
    for key in numeric_keys:
        curr_val = current.get(key)
        prev_val = previous.get(key)
        
        if curr_val is not None and prev_val is not None:
            deltas[f"{key}_delta"] = curr_val - prev_val
        else:
            deltas[f"{key}_delta"] = None
    
    return deltas


def get_trend(values: list[float]) -> str:
    """Determine trend from a list of values."""
    if len(values) < 2:
        return "insufficient_data"
    
    # Simple linear regression slope
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = mean(values)
    
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    
    if denominator == 0:
        return "stable"
    
    slope = numerator / denominator
    
    # Thresholds for trend detection
    if slope > 0.1:
        return "improving"
    elif slope < -0.1:
        return "declining"
    else:
        return "stable"
