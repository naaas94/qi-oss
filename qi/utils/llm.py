"""Shared helpers for LLM-related utilities."""


def ns_to_ms(value: int | None) -> int | None:
    """Convert nanoseconds to milliseconds."""
    if value is None:
        return None
    return int(value / 1_000_000)
