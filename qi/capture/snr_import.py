"""Import notes from SnR QC JSONL export."""

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from qi.db import get_db, save_imported_note
from qi.models import ImportedNote
from qi.utils.time import parse_timestamp

console = Console()


def import_snr_jsonl(file_path: Path, since_days: int | None = None) -> tuple[int, int]:
    """Import notes from SnR QC JSONL export.
    
    Args:
        file_path: Path to the JSONL file
        since_days: Only import notes from the last N days (None = all)
        
    Returns:
        Tuple of (imported_count, skipped_count)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    cutoff_date = None
    if since_days is not None:
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=since_days)

    imported = 0
    skipped = 0

    with open(file_path, "r", encoding="utf-8") as f:
        total = sum(1 for _ in f)
        f.seek(0)

        with get_db() as conn:
            with Progress(console=console) as progress:
                task = progress.add_task("[cyan]Importing notes...", total=total)

                for line in f:
                    line = line.strip()
                    if not line:
                        progress.advance(task)
                        continue

                    try:
                        data = json.loads(line)
                        note = _parse_snr_note(data)

                        # Check date filter
                        if cutoff_date:
                            # Make ts naive if it is aware to compare with cutoff_date
                            compare_ts = note.ts.replace(tzinfo=None) if note.ts.tzinfo else note.ts
                            if compare_ts < cutoff_date:
                                skipped += 1
                                progress.advance(task)
                                continue

                        save_imported_note(note, conn=conn)
                        imported += 1

                    except (json.JSONDecodeError, ValueError) as e:
                        console.print(f"[yellow]Warning: Skipping invalid line: {e}[/yellow]")
                        skipped += 1

                    progress.advance(task)

    return imported, skipped


def _parse_snr_note(data: dict) -> ImportedNote:
    """Parse a note from SnR QC export format."""
    # Extract ID
    snr_id = str(data.get("id") or data.get("snr_id") or data.get("note_id", ""))
    # Handle timestamp - try multiple formats
    ts_raw = data.get("timestamp") or data.get("ts") or data.get("created_at")
    ts = parse_timestamp(
        ts_raw,
        note_id=snr_id or "unknown",
        warn=lambda msg: console.print(f"[yellow]Warning: {msg}[/yellow]"),
    )
    # Extract text
    text = data.get("text") or data.get("content") or data.get("note", "")

    # Extract parsed fields from SnR QC
    return ImportedNote(
        snr_id=snr_id if snr_id else None,
        ts=ts,
        text=text,
        snr_tags=data.get("tags"),
        snr_sentiment=data.get("sentiment"),
        snr_entities=data.get("entities"),
        snr_intent=data.get("intent"),
        snr_action_items=data.get("action_items"),
        snr_people=data.get("people"),
        snr_summary=data.get("summary"),
        snr_quality_score=data.get("quality_score") or data.get("semantic_coherence_score"),
    )
