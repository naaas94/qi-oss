"""Time and date utilities for QI."""

from datetime import date, datetime, timedelta


def parse_date(value: str, *, field_name: str = "date") -> date:
    """Parse YYYY-MM-DD date strings with a consistent error message."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name} format: {value}. Use YYYY-MM-DD") from exc


def parse_timestamp(
    timestamp_raw: str | int | float | None,
    *,
    note_id: str = "unknown",
    warn: callable | None = None,
) -> datetime:
    """
    Parse timestamp from ISO string, other supported formats, or unix epoch.

    Falls back to current time with an optional warning callback.
    """
    if isinstance(timestamp_raw, str):
        try:
            return datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(timestamp_raw, fmt)
                except ValueError:
                    continue
            if warn:
                warn(
                    f"Note {note_id} invalid timestamp {timestamp_raw}, "
                    "falling back to current time."
                )
            return datetime.now()

    if isinstance(timestamp_raw, (int, float)):
        return datetime.fromtimestamp(timestamp_raw)

    if warn:
        warn(f"Note {note_id} missing timestamp, falling back to current time.")
    return datetime.now()


def get_week_bounds(target_date: date | None = None) -> tuple[date, date]:
    """Get Monday-Sunday bounds for the week containing target_date.
    
    Uses ISO week (Monday = 0, Sunday = 6).
    """
    if target_date is None:
        target_date = date.today()
    
    # Monday of the week
    week_start = target_date - timedelta(days=target_date.weekday())
    # Sunday of the week
    week_end = week_start + timedelta(days=6)
    
    return week_start, week_end


def get_previous_week_bounds(target_date: date | None = None) -> tuple[date, date]:
    """Get Monday-Sunday bounds for the previous week."""
    if target_date is None:
        target_date = date.today()
    
    week_start, _ = get_week_bounds(target_date)
    prev_week_end = week_start - timedelta(days=1)
    prev_week_start = prev_week_end - timedelta(days=6)
    
    return prev_week_start, prev_week_end


def get_month_bounds(target_date: date | None = None) -> tuple[date, date]:
    """Get first and last day of the month containing target_date."""
    if target_date is None:
        target_date = date.today()
    
    # First day of month
    month_start = target_date.replace(day=1)
    
    # Last day of month
    if target_date.month == 12:
        next_month = target_date.replace(year=target_date.year + 1, month=1, day=1)
    else:
        next_month = target_date.replace(month=target_date.month + 1, day=1)
    month_end = next_month - timedelta(days=1)
    
    return month_start, month_end


def get_n_days_ago(n: int, from_date: date | None = None) -> date:
    """Get the date n days ago from from_date (or today)."""
    if from_date is None:
        from_date = date.today()
    return from_date - timedelta(days=n)


def days_between(start: date, end: date) -> int:
    """Get number of days between two dates (inclusive)."""
    return (end - start).days + 1
