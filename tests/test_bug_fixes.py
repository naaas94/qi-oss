"""Regression tests for critical bug fixes."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from qi.capture import snr_db_import, snr_import, weekly
from qi.llm.prompts import PromptPackage
from qi.llm.synthesis import synthesize_report_narrative
from qi.llm.validate import NarrativeSynthesisResult


def _create_quickcapture_db(db_path: Path, rows: list[tuple[Any, ...]]) -> None:
    """Create a temporary QuickCapture-style SQLite DB for tests."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE notes (
                note_id TEXT,
                timestamp TEXT,
                note_body TEXT,
                tags TEXT,
                snr_metadata TEXT,
                confidence_score REAL,
                tag_quality_score REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO notes (
                note_id, timestamp, note_body, tags, snr_metadata,
                confidence_score, tag_quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_import_from_qc_db_does_not_crash_on_sqlite_row_missing_get(
    initialized_db,  # noqa: ARG001 - ensures isolated QI DB is initialized
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Import should skip failed rows without calling sqlite3.Row.get()."""
    db_path = tmp_path / "quickcapture.db"
    _create_quickcapture_db(
        db_path,
        [
            (
                "note-1",
                "2026-02-24T10:00:00",
                "text",
                None,
                None,
                None,
                None,
            )
        ],
    )

    def _always_fail(_: sqlite3.Row) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(snr_db_import, "_parse_qc_note", _always_fail)

    imported, skipped = snr_db_import.import_from_qc_db(db_path)
    assert imported == 0
    assert skipped == 1


def test_prompt_list_enforces_required_items_after_blank_inputs(monkeypatch) -> None:
    """Blank inputs should not consume required slots."""
    responses = iter(["", "", "Ship patch", ""])

    def _fake_ask(*_: Any, **__: Any) -> str:
        return next(responses)

    monkeypatch.setattr(weekly.Prompt, "ask", _fake_ask)

    items = weekly.prompt_list("Win", min_items=1, max_items=2)
    assert items == ["Ship patch"]


def test_synthesis_uses_consistent_default_model(monkeypatch) -> None:
    """Inference and persistence should share the same default model."""
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "qi.llm.synthesis.load_config",
        lambda: {"llm": {"enabled": True, "base_url": "http://localhost:11434"}},
    )
    monkeypatch.setattr("qi.llm.synthesis.read_principles_markdown", lambda _config: None)
    monkeypatch.setattr(
        "qi.llm.synthesis.build_report_prompts",
        lambda **_: PromptPackage(
            system_prompt="system",
            user_prompt="user",
            prompt_version="test-prompt-v1",
        ),
    )

    class _FakeClient:
        def __init__(self, base_url: str, timeout_seconds: int | None) -> None:
            self.base_url = base_url
            self.timeout_seconds = timeout_seconds

        def check_ready(self) -> None:
            return None

    monkeypatch.setattr("qi.llm.synthesis.OllamaClient", _FakeClient)

    def _fake_synthesize_with_validation(
        *,
        client: _FakeClient,  # noqa: ARG001 - signature compatibility
        model: str,
        temperature: float,  # noqa: ARG001 - signature compatibility
        think: bool | None,  # noqa: ARG001 - signature compatibility
        prompts: PromptPackage,  # noqa: ARG001 - signature compatibility
    ) -> NarrativeSynthesisResult:
        captured["inference_model"] = model
        return NarrativeSynthesisResult(
            output=None,
            raw_output=None,
            model_id=None,
            traces=[],
            error="forced test failure",
        )

    monkeypatch.setattr("qi.llm.synthesis.synthesize_with_validation", _fake_synthesize_with_validation)

    def _fake_persist_llm_runs(
        *,
        report_type: str,  # noqa: ARG001 - signature compatibility
        prompt_version: str,  # noqa: ARG001 - signature compatibility
        configured_model: str,
        traces: list[Any],  # noqa: ARG001 - signature compatibility
    ) -> list[int]:
        captured["configured_model"] = configured_model
        return []

    monkeypatch.setattr("qi.llm.synthesis._persist_llm_runs", _fake_persist_llm_runs)

    narrative, metadata = synthesize_report_narrative(
        report_type="weekly_digest",
        window_start=date(2026, 2, 17),
        window_end=date(2026, 2, 24),
        input_snapshot={},
        features_snapshot={},
        analysis_snapshot={},
    )

    assert narrative is None
    assert metadata["llm_skipped_reason"] == "validation_or_request_failure"
    assert captured["inference_model"] == "qwen3:30b"
    assert captured["configured_model"] == "qwen3:30b"


def test_import_snr_jsonl_uses_single_db_connection(tmp_path: Path, monkeypatch) -> None:
    """JSONL import should reuse one DB connection for all notes."""
    jsonl_path = tmp_path / "notes.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"id": "n1", "timestamp": "2026-02-24T08:00:00", "text": "a"}),
                json.dumps({"id": "n2", "timestamp": "2026-02-24T09:00:00", "text": "b"}),
            ]
        ),
        encoding="utf-8",
    )

    fake_conn = object()
    entered = 0
    used_conns: list[object | None] = []

    @contextmanager
    def _fake_get_db() -> Iterator[object]:
        nonlocal entered
        entered += 1
        yield fake_conn

    def _fake_save_imported_note(*_: Any, conn: object | None = None) -> int:
        used_conns.append(conn)
        return 1

    monkeypatch.setattr(snr_import, "get_db", _fake_get_db)
    monkeypatch.setattr(snr_import, "save_imported_note", _fake_save_imported_note)

    imported, skipped = snr_import.import_snr_jsonl(jsonl_path)
    assert imported == 2
    assert skipped == 0
    assert entered == 1
    assert used_conns == [fake_conn, fake_conn]


def test_import_qc_db_uses_single_db_connection(tmp_path: Path, monkeypatch) -> None:
    """QC DB import should reuse one DB connection for all notes."""
    db_path = tmp_path / "quickcapture.db"
    _create_quickcapture_db(
        db_path,
        [
            ("note-1", "2026-02-24T10:00:00", "a", None, None, None, None),
            ("note-2", "2026-02-24T11:00:00", "b", None, None, None, None),
        ],
    )

    fake_conn = object()
    entered = 0
    used_conns: list[object | None] = []

    @contextmanager
    def _fake_get_db() -> Iterator[object]:
        nonlocal entered
        entered += 1
        yield fake_conn

    def _fake_save_imported_note(*_: Any, conn: object | None = None) -> int:
        used_conns.append(conn)
        return 1

    monkeypatch.setattr(snr_db_import, "get_db", _fake_get_db)
    monkeypatch.setattr(snr_db_import, "save_imported_note", _fake_save_imported_note)

    imported, skipped = snr_db_import.import_from_qc_db(db_path)
    assert imported == 2
    assert skipped == 0
    assert entered == 1
    assert used_conns == [fake_conn, fake_conn]
