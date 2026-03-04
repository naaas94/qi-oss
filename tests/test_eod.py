"""Tests for EOD relevance pipeline orchestration."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime

from qi.models import DCI, ImportedNote
from qi.processing import eod


@dataclass
class _PromptPackage:
    system_prompt: str
    user_prompt: str
    prompt_version: str


@dataclass
class _FakeResponse:
    content: str
    model: str
    done_reason: str = "stop"
    total_duration: int = 10_000_000
    load_duration: int = 1_000_000
    prompt_eval_count: int = 12
    prompt_eval_duration: int = 2_000_000
    eval_count: int = 20
    eval_duration: int = 4_000_000


def test_eod_batch_processes_items_and_counts_relevance(monkeypatch) -> None:
    """Batch should process all queued items and aggregate relevance counts."""
    note = ImportedNote(ts=datetime.now(), text="won a key milestone")
    dci = DCI(date=date.today(), energy=7, mood=6, sleep=8, metrics={"habit_1": True})
    saved_digests = []
    saved_runs = []

    class _Client:
        def __init__(self, base_url: str, timeout_seconds: int | None = 120) -> None:
            self.base_url = base_url
            self.timeout_seconds = timeout_seconds

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def check_ready(self) -> None:
            return None

        def generate(self, **kwargs):
            return _FakeResponse(
                content=json.dumps(
                    {
                        "relevant": True,
                        "principle_ids": [1],
                        "kr_refs": ["KR1"],
                        "digest": "Useful signal",
                        "citation": "from note",
                    }
                ),
                model="qwen3:8b",
            )

    monkeypatch.setattr(eod, "OllamaClient", _Client)
    monkeypatch.setattr(eod, "load_config", lambda: {"llm": {"enabled": True, "base_url": "http://localhost:11434"}})
    monkeypatch.setattr(eod, "read_principles_markdown", lambda config=None: "# Principles")
    monkeypatch.setattr(
        eod,
        "build_eod_relevance_prompt",
        lambda **kwargs: _PromptPackage("sys", f"user:{kwargs['item_type']}", "v1"),
    )
    monkeypatch.setattr(eod, "get_unprocessed_notes_for_relevance", lambda target_date=None: [(1, note)])
    monkeypatch.setattr(eod, "get_unprocessed_dcis_for_relevance", lambda target_date=None: [(2, dci)])
    monkeypatch.setattr(eod, "save_relevance_digest", lambda digest: saved_digests.append(digest) or 1)
    monkeypatch.setattr(eod, "save_llm_run", lambda run: saved_runs.append(run) or 1)
    monkeypatch.setattr(eod, "mark_note_relevance_processed", lambda note_id: None)
    monkeypatch.setattr(eod, "mark_dci_relevance_processed", lambda dci_id: None)

    result = asyncio.run(eod._run_eod_batch_async())
    assert result.processed == 2
    assert result.relevant == 2
    assert result.errors == 0
    assert len(saved_digests) == 2
    assert len(saved_runs) == 2


def test_eod_batch_records_failures_without_crashing(monkeypatch) -> None:
    """Single-item failures should increment errors and persist failed digest state."""
    note = ImportedNote(ts=datetime.now(), text="bad payload")
    saved_digests = []

    class _FailingClient:
        def __init__(self, base_url: str, timeout_seconds: int | None = 120) -> None:
            self.base_url = base_url
            self.timeout_seconds = timeout_seconds

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def check_ready(self) -> None:
            return None

        def generate(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(eod, "OllamaClient", _FailingClient)
    monkeypatch.setattr(eod, "load_config", lambda: {"llm": {"enabled": True, "base_url": "http://localhost:11434"}})
    monkeypatch.setattr(eod, "read_principles_markdown", lambda config=None: "# Principles")
    monkeypatch.setattr(
        eod,
        "build_eod_relevance_prompt",
        lambda **kwargs: _PromptPackage("sys", "user", "v1"),
    )
    monkeypatch.setattr(eod, "get_unprocessed_notes_for_relevance", lambda target_date=None: [(1, note)])
    monkeypatch.setattr(eod, "get_unprocessed_dcis_for_relevance", lambda target_date=None: [])
    monkeypatch.setattr(eod, "save_relevance_digest", lambda digest: saved_digests.append(digest) or 1)
    monkeypatch.setattr(eod, "save_llm_run", lambda run: 1)
    monkeypatch.setattr(eod, "mark_note_relevance_processed", lambda note_id: None)
    monkeypatch.setattr(eod, "mark_dci_relevance_processed", lambda dci_id: None)

    result = asyncio.run(eod._run_eod_batch_async())
    assert result.processed == 0
    assert result.errors == 1
    assert len(result.error_messages) == 1
    assert saved_digests[0].status == "failed"
