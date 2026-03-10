"""Shared reporting helpers."""

from datetime import date

from qi.db import delete_artifact_for_window, get_artifact_for_window
from qi.models import Artifact


def resolve_existing_artifact(
    artifact_type: str,
    window_start: date,
    window_end: date,
    force_regenerate: bool,
) -> Artifact | None:
    """
    Return existing artifact if one exists and force_regenerate is False.
    If exists and force_regenerate, delete it and return None.
    If none exists, return None. Caller should print a warning when returning non-None.
    """
    existing = get_artifact_for_window(artifact_type, window_start, window_end)
    if not existing:
        return None
    if force_regenerate:
        delete_artifact_for_window(artifact_type, window_start, window_end)
        return None
    return existing
