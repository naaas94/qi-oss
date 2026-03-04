"""Import notes from SnR QuickCapture SQLite database."""

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from qi.db import get_db, save_imported_note
from qi.models import ImportedNote
from qi.utils.time import parse_timestamp

console = Console()


def import_from_qc_db(
    db_path: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    since_days: int | None = None,
) -> tuple[int, int]:
    """Import notes from QuickCapture DB into QI.
    
    Args:
        db_path: Path to the QuickCapture SQLite database
        start_date: Only import notes from this date onwards
        end_date: Only import notes up to this date
        since_days: Import notes from the last N days (alternative to start/end)
        
    Returns:
        Tuple of (imported_count, skipped_count).
        Import is idempotent via snr_id UNIQUE constraint.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"QuickCapture database not found: {db_path}")

    # Handle since_days by converting to start_date
    if since_days is not None:
        start_date = date.today() - timedelta(days=since_days)
        if end_date is None:
            end_date = date.today()

    # Open in read-only mode to prevent accidental writes to the SnR database
    db_uri = f"file:{db_path.absolute().as_posix()}?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        total_notes = _count_qc_notes(conn, start_date, end_date)
        console.print(f"[cyan]Found {total_notes} notes in QuickCapture DB[/cyan]")
        if total_notes == 0:
            console.print("[yellow]No notes found to import[/yellow]")
            return 0, 0

        imported = 0
        skipped = 0

        with get_db() as db_conn:
            with Progress(console=console) as progress:
                task = progress.add_task("[cyan]Importing notes...", total=total_notes)

                for row in _query_qc_notes(conn, start_date, end_date):
                    try:
                        note = _parse_qc_note(row)
                        save_imported_note(note, conn=db_conn)
                        imported += 1
                    except Exception as e:
                        note_id = row["note_id"] if "note_id" in row.keys() else "unknown"
                        console.print(f"[yellow]Warning: Skipping note {note_id}: {e}[/yellow]")
                        skipped += 1

                    progress.advance(task)

        return imported, skipped

    finally:
        conn.close()


def _query_qc_notes(
    conn: sqlite3.Connection,
    start_date: date | None = None,
    end_date: date | None = None,
) -> sqlite3.Cursor:
    """Query notes from QuickCapture database.
    
    Uses the known schema:
    - Table: notes
    - Columns: note_id, timestamp, note_body, tags, snr_metadata,
               confidence_score, tag_quality_score
    """
    query = """
        SELECT note_id, timestamp, note_body, tags, snr_metadata,
               confidence_score, tag_quality_score
        FROM notes
    """
    params: list = []

    # Build WHERE clause for date filtering
    conditions = []
    if start_date:
        conditions.append("date(timestamp) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        conditions.append("date(timestamp) <= ?")
        params.append(end_date.isoformat())

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY timestamp"

    return conn.execute(query, params)


def _count_qc_notes(
    conn: sqlite3.Connection,
    start_date: date | None = None,
    end_date: date | None = None,
) -> int:
    """Count notes in the selected date window."""
    query = "SELECT COUNT(*) AS note_count FROM notes"
    params: list[str] = []
    conditions: list[str] = []
    if start_date:
        conditions.append("date(timestamp) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        conditions.append("date(timestamp) <= ?")
        params.append(end_date.isoformat())
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    row = conn.execute(query, params).fetchone()
    return int(row["note_count"]) if row and "note_count" in row.keys() else 0


def _parse_qc_note(row: sqlite3.Row) -> ImportedNote:
    """Parse a QuickCapture database row into an ImportedNote.
    
    QC Schema mapping:
    - note_id → snr_id (stable unique ID)
    - timestamp → ts
    - note_body → text
    - tags → snr_tags (JSON parse)
    - snr_metadata.sentiment → snr_sentiment
    - snr_metadata.entities → snr_entities
    - snr_metadata.intent → snr_intent
    - snr_metadata.action_items → snr_action_items
    - snr_metadata.people → snr_people
    - snr_metadata.summary → snr_summary
    - confidence_score or tag_quality_score → snr_quality_score
    """
    # Parse snr_metadata JSON
    snr_metadata = {}
    if row["snr_metadata"]:
        try:
            snr_metadata = json.loads(row["snr_metadata"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Parse tags JSON
    snr_tags = None
    if row["tags"]:
        try:
            parsed_tags = json.loads(row["tags"])
            if isinstance(parsed_tags, list):
                snr_tags = parsed_tags
            elif isinstance(parsed_tags, dict):
                # If tags is a dict, extract keys as tag names
                snr_tags = list(parsed_tags.keys()) if parsed_tags else None
        except (json.JSONDecodeError, TypeError):
            # Fallback: try comma-separated
            snr_tags = [t.strip() for t in row["tags"].split(",") if t.strip()] or None

    # Parse timestamp
    ts = parse_timestamp(
        row["timestamp"],
        note_id=str(row["note_id"]),
        warn=lambda msg: console.print(f"[yellow]Warning: {msg}[/yellow]"),
    )

    # Get quality score (prefer confidence_score, fallback to tag_quality_score)
    quality_score = None
    if row["confidence_score"] is not None:
        try:
            quality_score = float(row["confidence_score"])
        except (ValueError, TypeError):
            pass
    if quality_score is None and row["tag_quality_score"] is not None:
        try:
            quality_score = float(row["tag_quality_score"])
        except (ValueError, TypeError):
            pass

    # Helper to safely extract list fields from metadata
    def get_list_field(key: str) -> list[str] | None:
        value = snr_metadata.get(key)
        if isinstance(value, list):
            return value if value else None
        return None

    return ImportedNote(
        snr_id=row["note_id"],
        ts=ts,
        text=row["note_body"] or "",
        snr_tags=snr_tags,
        snr_sentiment=snr_metadata.get("sentiment"),
        snr_entities=get_list_field("entities"),
        snr_intent=snr_metadata.get("intent"),
        snr_action_items=get_list_field("action_items"),
        snr_people=get_list_field("people"),
        snr_summary=snr_metadata.get("summary"),
        snr_quality_score=quality_score,
    )
