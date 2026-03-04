"""Database management for QI."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Generator

from qi.config import QI_DB_PATH, QI_HOME, ensure_qi_home
from qi.models import (
    Artifact,
    DCI,
    Event,
    ImportedNote,
    OneChange,
    RelevanceDigest,
    WeeklyRetro,
)


class ReadinessError(RuntimeError):
    """Raised when a readiness check fails (e.g. DB locked)."""


def get_migrations_dir() -> Path:
    """Get the migrations directory."""
    return Path(__file__).parent.parent / "migrations"


def get_connection() -> sqlite3.Connection:
    """Get a database connection with proper settings."""
    ensure_qi_home()
    db_preexisting = QI_DB_PATH.exists()
    conn = sqlite3.connect(QI_DB_PATH)
    if not db_preexisting and os.name != "nt":
        # Best-effort hardening for local privacy on Unix-like systems.
        os.chmod(QI_DB_PATH, 0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def check_db_writable() -> None:
    """Verify the database is writable. Raises ReadinessError if locked."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()
    except sqlite3.OperationalError as exc:
        conn.close()
        raise ReadinessError(
            "QI database appears locked. Close other applications using it "
            "(e.g. DB Browser, another QI instance) and retry."
        ) from exc
    finally:
        conn.close()


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Get current schema version."""
    try:
        cursor = conn.execute("SELECT MAX(version) FROM schema_version")
        result = cursor.fetchone()
        return result[0] if result and result[0] else 0
    except sqlite3.OperationalError:
        return 0


def run_migrations(conn: sqlite3.Connection) -> int:
    """Run pending migrations and return number of migrations applied."""
    migrations_dir = get_migrations_dir()
    if not migrations_dir.exists():
        return 0

    current_version = get_schema_version(conn)
    applied = 0

    migration_files = sorted(migrations_dir.glob("*.sql"))
    for migration_file in migration_files:
        # Extract version number from filename (e.g., 001_initial.sql -> 1)
        version = int(migration_file.stem.split("_")[0])
        if version > current_version:
            with open(migration_file) as f:
                sql = f.read()
            # Apply each migration atomically so schema_version updates cannot drift
            # from DDL/DML changes if an error happens mid-migration.
            try:
                conn.executescript(f"BEGIN IMMEDIATE;\n{sql}\nCOMMIT;")
            except sqlite3.Error:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            applied += 1

    return applied


def init_db() -> tuple[bool, int]:
    """Initialize the database. Returns (created, migrations_applied)."""
    created = not QI_DB_PATH.exists()
    ensure_qi_home()

    with get_db() as conn:
        migrations_applied = run_migrations(conn)

    return created, migrations_applied


# DCI Operations


def save_dci(dci: DCI) -> int:
    """Save or update a DCI entry. Returns the row ID."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO dci (
                date, energy, mood, sleep, primary_focus, one_win, one_friction,
                comment, residual, metrics
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                energy = excluded.energy,
                mood = excluded.mood,
                sleep = excluded.sleep,
                primary_focus = excluded.primary_focus,
                one_win = excluded.one_win,
                one_friction = excluded.one_friction,
                comment = excluded.comment,
                residual = excluded.residual,
                metrics = excluded.metrics
            """,
            (
                dci.date.isoformat(),
                dci.energy,
                dci.mood,
                dci.sleep,
                dci.primary_focus,
                dci.one_win,
                dci.one_friction,
                dci.comment,
                json.dumps(dci.residual) if dci.residual else None,
                json.dumps(dci.metrics),
            ),
        )
        return cursor.lastrowid or 0


def get_dci(target_date: date) -> DCI | None:
    """Get DCI for a specific date."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM dci WHERE date = ?", (target_date.isoformat(),)
        )
        row = cursor.fetchone()
        if not row:
            return None

        return _row_to_dci(row)


def get_dci_range(start_date: date, end_date: date) -> list[DCI]:
    """Get DCIs in a date range."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM dci WHERE date >= ? AND date <= ? ORDER BY date",
            (start_date.isoformat(), end_date.isoformat()),
        )
        return [_row_to_dci(row) for row in cursor.fetchall()]


def _row_to_dci(row: sqlite3.Row) -> DCI:
    """Convert a database row to a DCI model. Metrics are read from the metrics JSON column."""
    residual = json.loads(row["residual"]) if row["residual"] else []
    metrics = json.loads(row["metrics"]) if "metrics" in row.keys() and row["metrics"] else {}

    return DCI(
        date=date.fromisoformat(row["date"]),
        energy=row["energy"],
        mood=row["mood"],
        sleep=row["sleep"],
        primary_focus=row["primary_focus"],
        one_win=row["one_win"],
        one_friction=row["one_friction"],
        comment=row["comment"],
        metrics=metrics,
        residual=residual,
    )


def get_latest_residual() -> list[str]:
    """Get residual from the most recent DCI."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT residual FROM dci ORDER BY date DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row and row["residual"]:
            return json.loads(row["residual"])
        return []


# Notes Operations


def save_imported_note(note: ImportedNote, conn: sqlite3.Connection | None = None) -> int:
    """Save an imported note. Returns the row ID.

    When ``conn`` is provided, the caller controls transaction scope.
    """
    if conn is None:
        with get_db() as managed_conn:
            return _save_imported_note_with_conn(managed_conn, note)
    return _save_imported_note_with_conn(conn, note)


def _save_imported_note_with_conn(conn: sqlite3.Connection, note: ImportedNote) -> int:
    """Execute imported-note upsert on an existing connection."""
    cursor = conn.execute(
        """
        INSERT INTO notes_imported (
            snr_id, ts, text, snr_tags, snr_sentiment, snr_entities,
            snr_intent, snr_action_items, snr_people, snr_summary,
            snr_quality_score, qi_processed, qi_event_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snr_id) DO UPDATE SET
            text = excluded.text,
            snr_tags = excluded.snr_tags,
            snr_sentiment = excluded.snr_sentiment,
            snr_entities = excluded.snr_entities,
            snr_intent = excluded.snr_intent,
            snr_action_items = excluded.snr_action_items,
            snr_people = excluded.snr_people,
            snr_summary = excluded.snr_summary,
            snr_quality_score = excluded.snr_quality_score
        """,
        (
            note.snr_id,
            note.ts.isoformat(),
            note.text,
            json.dumps(note.snr_tags) if note.snr_tags else None,
            note.snr_sentiment,
            json.dumps(note.snr_entities) if note.snr_entities else None,
            note.snr_intent,
            json.dumps(note.snr_action_items) if note.snr_action_items else None,
            json.dumps(note.snr_people) if note.snr_people else None,
            note.snr_summary,
            note.snr_quality_score,
            int(note.qi_processed),
            note.qi_event_id,
        ),
    )
    return cursor.lastrowid or 0


def get_unprocessed_notes() -> list[tuple[int, ImportedNote]]:
    """Get notes that haven't been processed by QI yet."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM notes_imported WHERE qi_processed = 0 ORDER BY ts"
        )
        results = []
        for row in cursor.fetchall():
            note = _row_to_imported_note(row)
            results.append((row["id"], note))
        return results


def get_unprocessed_notes_for_relevance(
    target_date: date | None = None,
) -> list[tuple[int, ImportedNote]]:
    """Get notes that haven't been processed by EOD relevance pipeline yet."""
    with get_db() as conn:
        if target_date is None:
            cursor = conn.execute(
                "SELECT * FROM notes_imported WHERE qi_relevance_processed = 0 ORDER BY ts"
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM notes_imported WHERE qi_relevance_processed = 0 AND date(ts) <= ? ORDER BY ts",
                (target_date.isoformat(),),
            )
        results = []
        for row in cursor.fetchall():
            note = _row_to_imported_note(row)
            results.append((row["id"], note))
        return results


def mark_note_processed(note_id: int, event_id: int | None) -> None:
    """Mark a note as processed and optionally link to an event."""
    with get_db() as conn:
        conn.execute(
            "UPDATE notes_imported SET qi_processed = 1, qi_event_id = ? WHERE id = ?",
            (event_id, note_id),
        )


def mark_note_relevance_processed(note_id: int) -> None:
    """Mark a note as processed for relevance pipeline."""
    with get_db() as conn:
        conn.execute(
            "UPDATE notes_imported SET qi_relevance_processed = 1 WHERE id = ?",
            (note_id,),
        )


def _row_to_imported_note(row: sqlite3.Row) -> ImportedNote:
    """Convert a database row to an ImportedNote model."""
    return ImportedNote(
        snr_id=row["snr_id"],
        ts=datetime.fromisoformat(row["ts"]),
        text=row["text"],
        snr_tags=json.loads(row["snr_tags"]) if row["snr_tags"] else None,
        snr_sentiment=row["snr_sentiment"],
        snr_entities=json.loads(row["snr_entities"]) if row["snr_entities"] else None,
        snr_intent=row["snr_intent"],
        snr_action_items=json.loads(row["snr_action_items"]) if row["snr_action_items"] else None,
        snr_people=json.loads(row["snr_people"]) if row["snr_people"] else None,
        snr_summary=row["snr_summary"],
        snr_quality_score=row["snr_quality_score"],
        qi_processed=bool(row["qi_processed"]),
        qi_event_id=row["qi_event_id"],
    )


def get_unprocessed_dcis_for_relevance(
    target_date: date | None = None,
) -> list[tuple[int, DCI]]:
    """Get DCI entries that haven't been processed by EOD relevance pipeline yet."""
    with get_db() as conn:
        if target_date is None:
            cursor = conn.execute(
                "SELECT * FROM dci WHERE relevance_processed = 0 ORDER BY date"
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM dci WHERE relevance_processed = 0 AND date <= ? ORDER BY date",
                (target_date.isoformat(),),
            )
        results = []
        for row in cursor.fetchall():
            dci = _row_to_dci(row)
            results.append((row["id"], dci))
        return results


def mark_dci_relevance_processed(dci_id: int) -> None:
    """Mark a DCI row as processed for relevance pipeline."""
    with get_db() as conn:
        conn.execute(
            "UPDATE dci SET relevance_processed = 1 WHERE id = ?",
            (dci_id,),
        )


def save_relevance_digest(digest: RelevanceDigest) -> int:
    """Save or update a relevance digest row. Returns row id when available."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO relevance_digests (
                item_type, item_id, source_ts, relevant, principle_ids, kr_refs, digest,
                citation, model, total_tokens, processing_duration_ms, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_type, item_id) DO UPDATE SET
                source_ts = excluded.source_ts,
                relevant = excluded.relevant,
                principle_ids = excluded.principle_ids,
                kr_refs = excluded.kr_refs,
                digest = excluded.digest,
                citation = excluded.citation,
                model = excluded.model,
                total_tokens = excluded.total_tokens,
                processing_duration_ms = excluded.processing_duration_ms,
                status = excluded.status,
                error_message = excluded.error_message,
                processed_at = CURRENT_TIMESTAMP
            """,
            (
                digest.item_type,
                digest.item_id,
                digest.source_ts.isoformat(),
                int(digest.relevant),
                json.dumps(digest.principle_ids),
                json.dumps(digest.kr_refs),
                digest.digest,
                digest.citation,
                digest.model,
                digest.total_tokens,
                digest.processing_duration_ms,
                digest.status,
                digest.error_message,
            ),
        )
        return cursor.lastrowid or 0


def get_relevance_digests_in_range(
    start_date: date,
    end_date: date,
) -> list[RelevanceDigest]:
    """Get relevant digests whose source item falls within a date range."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT
              rd.*,
              COALESCE(
                rd.source_ts,
                ni.ts,
                CASE WHEN d.date IS NOT NULL THEN d.date || 'T00:00:00' ELSE NULL END
              ) AS effective_source_ts
            FROM relevance_digests rd
            LEFT JOIN notes_imported ni
              ON rd.item_type = 'note' AND rd.item_id = ni.id
            LEFT JOIN dci d
              ON rd.item_type = 'dci' AND rd.item_id = d.id
            WHERE rd.relevant = 1
              AND rd.status = 'success'
              AND (
                date(
                  COALESCE(
                    rd.source_ts,
                    ni.ts,
                    CASE WHEN d.date IS NOT NULL THEN d.date || 'T00:00:00' ELSE NULL END
                  )
                ) >= ?
                AND date(
                  COALESCE(
                    rd.source_ts,
                    ni.ts,
                    CASE WHEN d.date IS NOT NULL THEN d.date || 'T00:00:00' ELSE NULL END
                  )
                ) <= ?
              )
            ORDER BY effective_source_ts, rd.processed_at
            """,
            (
                start_date.isoformat(),
                end_date.isoformat(),
            ),
        )
        digests: list[RelevanceDigest] = []
        for row in cursor.fetchall():
            source_ts_raw = row["effective_source_ts"] or row["source_ts"]
            if source_ts_raw:
                source_ts = datetime.fromisoformat(source_ts_raw)
            else:
                source_ts = datetime.combine(start_date, datetime.min.time())
            digests.append(
                RelevanceDigest(
                    item_type=row["item_type"],
                    item_id=row["item_id"],
                    source_ts=source_ts,
                    relevant=bool(row["relevant"]),
                    principle_ids=json.loads(row["principle_ids"]) if row["principle_ids"] else [],
                    kr_refs=json.loads(row["kr_refs"]) if row["kr_refs"] else [],
                    digest=row["digest"],
                    citation=row["citation"] if "citation" in row.keys() else None,
                    model=row["model"],
                    total_tokens=row["total_tokens"] if "total_tokens" in row.keys() else None,
                    processing_duration_ms=row["processing_duration_ms"] if "processing_duration_ms" in row.keys() else None,
                    status=row["status"] if "status" in row.keys() else "success",
                    error_message=row["error_message"] if "error_message" in row.keys() else None,
                )
            )
        return digests


# Events Operations


def save_event(event: Event) -> int:
    """Save an event. Returns the row ID."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO events (ts, note_id, domain, event_type, trigger, intensity, behavior, counterfactual)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.ts.isoformat(),
                event.note_id,
                event.domain,
                event.event_type,
                event.trigger,
                event.intensity,
                event.behavior,
                event.counterfactual,
            ),
        )
        return cursor.lastrowid or 0


def get_events_in_range(start_date: date, end_date: date) -> list[Event]:
    """Get events in a date range."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM events 
            WHERE date(ts) >= ? AND date(ts) <= ? 
            ORDER BY ts
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        return [_row_to_event(row) for row in cursor.fetchall()]


def _row_to_event(row: sqlite3.Row) -> Event:
    """Convert a database row to an Event model."""
    return Event(
        ts=datetime.fromisoformat(row["ts"]),
        note_id=row["note_id"],
        domain=row["domain"],
        event_type=row["event_type"],
        trigger=row["trigger"],
        intensity=row["intensity"],
        behavior=row["behavior"],
        counterfactual=row["counterfactual"],
    )


# Weekly Retro Operations


def save_weekly_retro(retro: WeeklyRetro) -> int:
    """Save or update a weekly retro. Returns the row ID."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO weekly_retro (
                week_start, scoreboard, wins, frictions, root_cause,
                one_change, minimums, commitment_met
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_start) DO UPDATE SET
                scoreboard = excluded.scoreboard,
                wins = excluded.wins,
                frictions = excluded.frictions,
                root_cause = excluded.root_cause,
                one_change = excluded.one_change,
                minimums = excluded.minimums,
                commitment_met = excluded.commitment_met
            """,
            (
                retro.week_start.isoformat(),
                json.dumps(retro.scoreboard),
                json.dumps(retro.wins),
                json.dumps(retro.frictions),
                retro.root_cause,
                json.dumps(retro.one_change.model_dump()),
                json.dumps(retro.minimums),
                int(retro.commitment_met) if retro.commitment_met is not None else None,
            ),
        )
        return cursor.lastrowid or 0


def get_weekly_retro(week_start: date) -> WeeklyRetro | None:
    """Get weekly retro for a specific week."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM weekly_retro WHERE week_start = ?",
            (week_start.isoformat(),)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_weekly_retro(row)


def get_weekly_retros_in_range(start_date: date, end_date: date) -> list[WeeklyRetro]:
    """Get weekly retros in a date range."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM weekly_retro 
            WHERE week_start >= ? AND week_start <= ? 
            ORDER BY week_start
            """,
            (start_date.isoformat(), end_date.isoformat()),
        )
        return [_row_to_weekly_retro(row) for row in cursor.fetchall()]


def _row_to_weekly_retro(row: sqlite3.Row) -> WeeklyRetro:
    """Convert a database row to a WeeklyRetro model."""
    one_change_data = json.loads(row["one_change"])
    return WeeklyRetro(
        week_start=date.fromisoformat(row["week_start"]),
        scoreboard=json.loads(row["scoreboard"]),
        wins=json.loads(row["wins"]),
        frictions=json.loads(row["frictions"]),
        root_cause=row["root_cause"],
        one_change=OneChange(**one_change_data),
        minimums=json.loads(row["minimums"]),
        commitment_met=bool(row["commitment_met"]) if row["commitment_met"] is not None else None,
    )


# Artifact Operations


def save_artifact(artifact: Artifact) -> int:
    """Save an artifact. Returns the row ID."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO artifacts (
                artifact_type, window_start, window_end,
                input_snapshot, features_snapshot, output_json, rendered_markdown,
                prompt_version, model_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_type,
                artifact.window_start.isoformat(),
                artifact.window_end.isoformat(),
                json.dumps(artifact.input_snapshot),
                json.dumps(artifact.features_snapshot),
                json.dumps(artifact.output_json),
                artifact.rendered_markdown,
                artifact.prompt_version,
                artifact.model_id,
            ),
        )
        return cursor.lastrowid or 0


def get_artifact_for_window(artifact_type: str, window_start: date, window_end: date) -> Artifact | None:
    """Check if an artifact already exists for the given type and window."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM artifacts 
            WHERE artifact_type = ? AND window_start = ? AND window_end = ?
            ORDER BY created_at DESC 
            LIMIT 1
            """,
            (artifact_type, window_start.isoformat(), window_end.isoformat()),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_artifact(row)


def delete_artifact_for_window(artifact_type: str, window_start: date, window_end: date) -> None:
    """Delete existing artifact(s) for the given type and window. Unlinks llm_runs first (FK)."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT id FROM artifacts
            WHERE artifact_type = ? AND window_start = ? AND window_end = ?
            """,
            (artifact_type, window_start.isoformat(), window_end.isoformat()),
        )
        ids = [row["id"] for row in cursor.fetchall()]
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE llm_runs SET artifact_id = NULL WHERE artifact_id IN ({placeholders})",
            ids,
        )
        conn.execute(
            "DELETE FROM artifacts WHERE id IN (" + placeholders + ")",
            ids,
        )


def get_artifacts(artifact_type: str | None = None, limit: int = 10) -> list[Artifact]:
    """Get artifacts, optionally filtered by type."""
    with get_db() as conn:
        if artifact_type:
            cursor = conn.execute(
                """
                SELECT * FROM artifacts 
                WHERE artifact_type = ? 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (artifact_type, limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [_row_to_artifact(row) for row in cursor.fetchall()]


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    """Convert a database row to an Artifact model."""
    return Artifact(
        artifact_type=row["artifact_type"],
        window_start=date.fromisoformat(row["window_start"]),
        window_end=date.fromisoformat(row["window_end"]),
        input_snapshot=json.loads(row["input_snapshot"]),
        features_snapshot=json.loads(row["features_snapshot"]),
        output_json=json.loads(row["output_json"]),
        rendered_markdown=row["rendered_markdown"],
        prompt_version=row["prompt_version"] if "prompt_version" in row.keys() else None,
        model_id=row["model_id"] if "model_id" in row.keys() else None,
    )


# LLM Observability Operations


def save_llm_run(run_data: dict[str, Any]) -> int:
    """Save an LLM run trace row. Returns the row ID."""
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO llm_runs (
                artifact_id, artifact_type, run_type, model, prompt_version,
                temperature, think_enabled, system_prompt, user_prompt, raw_output,
                done_reason, prompt_tokens, completion_tokens, total_duration_ms,
                load_duration_ms, prompt_eval_duration_ms, eval_duration_ms,
                validation_passed, validation_error, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_data.get("artifact_id"),
                run_data.get("artifact_type"),
                run_data.get("run_type"),
                run_data.get("model"),
                run_data.get("prompt_version"),
                run_data.get("temperature"),
                run_data.get("think_enabled"),
                run_data.get("system_prompt"),
                run_data.get("user_prompt"),
                run_data.get("raw_output"),
                run_data.get("done_reason"),
                run_data.get("prompt_tokens"),
                run_data.get("completion_tokens"),
                run_data.get("total_duration_ms"),
                run_data.get("load_duration_ms"),
                run_data.get("prompt_eval_duration_ms"),
                run_data.get("eval_duration_ms"),
                run_data.get("validation_passed"),
                run_data.get("validation_error"),
                run_data.get("error"),
            ),
        )
        return cursor.lastrowid or 0


def link_llm_runs_to_artifact(run_ids: list[int], artifact_id: int) -> None:
    """Backfill artifact_id for existing llm_run rows."""
    if not run_ids:
        return
    placeholders = ",".join("?" for _ in run_ids)
    params: list[Any] = [artifact_id, *run_ids]
    with get_db() as conn:
        conn.execute(
            f"UPDATE llm_runs SET artifact_id = ? WHERE id IN ({placeholders})",
            params,
        )
