"""End-of-day relevance and digest processing pipeline."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from qi.config import load_config, read_principles_markdown
from qi.db import (
    get_unprocessed_dcis_for_relevance,
    get_unprocessed_notes_for_relevance,
    mark_dci_relevance_processed,
    mark_note_relevance_processed,
    save_llm_run,
    save_relevance_digest,
)
from qi.llm.client import LLMClientError, OllamaClient
from qi.llm.prompts import build_eod_relevance_prompt
from qi.models import DCI, ImportedNote, RelevanceDigest


@dataclass
class EodBatchResult:
    """Aggregated batch result for CLI/reporting."""

    processed: int = 0
    relevant: int = 0
    errors: int = 0
    skipped: int = 0
    error_messages: list[str] = field(default_factory=list)


def run_eod_batch(target_date: date | None = None) -> EodBatchResult:
    """Run the EOD relevance pipeline for unprocessed notes and DCI entries."""
    return asyncio.run(_run_eod_batch_async(target_date=target_date))


async def _run_eod_batch_async(target_date: date | None = None) -> EodBatchResult:
    config = load_config()
    llm_cfg = config.get("llm", {})
    if not bool(llm_cfg.get("enabled", False)):
        return EodBatchResult(skipped=1, error_messages=["LLM is disabled in configuration."])

    principles_md = read_principles_markdown(config) or ""

    timeout_seconds = llm_cfg.get("timeout_seconds", 120)
    if isinstance(timeout_seconds, (int, float)):
        timeout_seconds = int(timeout_seconds)
    else:
        timeout_seconds = 120
    if timeout_seconds <= 0:
        timeout_seconds = None
    else:
        timeout_seconds = max(60, timeout_seconds)

    model = str(llm_cfg.get("eod_model") or llm_cfg.get("model", "qwen3:8b"))
    temperature = float(llm_cfg.get("eod_temperature", 0.3))
    concurrency = int(llm_cfg.get("eod_concurrency", 3))
    concurrency = max(1, concurrency)
    think = llm_cfg.get("think", False)
    if not isinstance(think, bool):
        think = False

    with OllamaClient(
        base_url=str(llm_cfg.get("base_url", "http://localhost:11434")),
        timeout_seconds=timeout_seconds,
    ) as client:
        try:
            client.check_ready()
        except LLMClientError as exc:
            return EodBatchResult(errors=1, error_messages=[f"LLM readiness check failed: {exc}"])

        notes = get_unprocessed_notes_for_relevance(target_date=target_date)
        dcis = get_unprocessed_dcis_for_relevance(target_date=target_date)
        work_items = [
            {"item_type": "note", "item_id": note_id, "payload": note}
            for note_id, note in notes
        ] + [
            {"item_type": "dci", "item_id": dci_id, "payload": dci}
            for dci_id, dci in dcis
        ]

        result = EodBatchResult()
        if not work_items:
            return result

        semaphore = asyncio.Semaphore(concurrency)
        tasks = [
            asyncio.create_task(
                _process_item(
                    semaphore=semaphore,
                    client=client,
                    model=model,
                    temperature=temperature,
                    think=think,
                    item_type=item["item_type"],
                    item_id=item["item_id"],
                    payload=item["payload"],
                    principles_markdown=principles_md,
                    result=result,
                )
            )
            for item in work_items
        ]
        await asyncio.gather(*tasks)
        return result


async def _process_item(
    *,
    semaphore: asyncio.Semaphore,
    client: OllamaClient,
    model: str,
    temperature: float,
    think: bool,
    item_type: str,
    item_id: int,
    payload: ImportedNote | DCI,
    principles_markdown: str,
    result: EodBatchResult,
) -> None:
    async with semaphore:
        item_text = _build_item_text(item_type=item_type, payload=payload)
        source_ts = _get_source_ts(item_type=item_type, payload=payload)
        prompts = build_eod_relevance_prompt(
            item_type=item_type,
            item_text=item_text,
            principles_markdown=principles_markdown,
        )
        started = time.perf_counter()
        try:
            response = await asyncio.to_thread(
                client.generate,
                model=model,
                system_prompt=prompts.system_prompt,
                user_prompt=prompts.user_prompt,
                temperature=temperature,
                think=think,
            )
            parsed = _parse_relevance_output(response.content)
        except Exception as exc:  # noqa: BLE001
            duration_ms = int((time.perf_counter() - started) * 1000)
            failed_digest = RelevanceDigest(
                item_type=item_type,  # type: ignore[arg-type]
                item_id=item_id,
                source_ts=source_ts,
                relevant=False,
                principle_ids=[],
                kr_refs=[],
                digest=None,
                citation=None,
                model=model,
                total_tokens=None,
                processing_duration_ms=duration_ms,
                status="failed",
                error_message=str(exc),
            )
            save_relevance_digest(failed_digest)
            result.errors += 1
            result.error_messages.append(f"{item_type}:{item_id} failed: {exc}")
            save_llm_run(
                _build_llm_run_record(
                    model=model,
                    prompt_version=prompts.prompt_version,
                    temperature=temperature,
                    think=think,
                    system_prompt=prompts.system_prompt,
                    user_prompt=prompts.user_prompt,
                    response=None,
                    validation_passed=False,
                    validation_error=str(exc),
                    error=str(exc),
                )
            )
            return

        duration_ms = int((time.perf_counter() - started) * 1000)
        citation = parsed["citation"]
        digest_text = parsed["digest"]
        digest = RelevanceDigest(
            item_type=item_type,  # type: ignore[arg-type]
            item_id=item_id,
            source_ts=source_ts,
            relevant=parsed["relevant"],
            principle_ids=parsed["principle_ids"],
            kr_refs=parsed["kr_refs"],
            digest=digest_text,
            citation=citation,
            model=response.model or model,
            total_tokens=_sum_tokens(response.prompt_eval_count, response.eval_count),
            processing_duration_ms=duration_ms,
            status="success",
            error_message=None,
        )
        save_relevance_digest(digest)
        if item_type == "note":
            mark_note_relevance_processed(item_id)
        else:
            mark_dci_relevance_processed(item_id)

        save_llm_run(
            _build_llm_run_record(
                model=response.model or model,
                prompt_version=prompts.prompt_version,
                temperature=temperature,
                think=think,
                system_prompt=prompts.system_prompt,
                user_prompt=prompts.user_prompt,
                response=response,
                validation_passed=True,
                validation_error=None,
                error=None,
            )
        )

        result.processed += 1
        if digest.relevant:
            result.relevant += 1


def _build_item_text(*, item_type: str, payload: ImportedNote | DCI) -> str:
    if item_type == "note":
        note = payload
        assert isinstance(note, ImportedNote)
        return note.text

    dci = payload
    assert isinstance(dci, DCI)
    parts: list[str] = []
    if dci.primary_focus:
        parts.append(f"primary_focus: {dci.primary_focus}")
    if dci.one_win:
        parts.append(f"one_win: {dci.one_win}")
    if dci.one_friction:
        parts.append(f"one_friction: {dci.one_friction}")
    if dci.comment:
        parts.append(f"comment: {dci.comment}")
    for k, v in (dci.metrics or {}).items():
        if isinstance(v, str) and v.strip():
            parts.append(f"{k}: {v}")
    if dci.residual:
        parts.append("residual: " + "; ".join(dci.residual))
    return "\n".join(parts)


def _parse_relevance_output(raw_output: str) -> dict[str, Any]:
    parsed = json.loads(raw_output)
    relevant = bool(parsed.get("relevant", False))

    principle_ids_raw = parsed.get("principle_ids", [])
    if isinstance(principle_ids_raw, list):
        principle_ids = [int(v) for v in principle_ids_raw if str(v).strip()]
    else:
        principle_ids = []

    kr_refs_raw = parsed.get("kr_refs", [])
    if isinstance(kr_refs_raw, list):
        kr_refs = [str(v).strip() for v in kr_refs_raw if str(v).strip()]
    elif isinstance(kr_refs_raw, str) and kr_refs_raw.strip():
        kr_refs = [kr_refs_raw.strip()]
    else:
        kr_refs = []

    digest = parsed.get("digest")
    digest_text = str(digest).strip() if digest is not None else None
    if digest_text == "":
        digest_text = None
    citation_raw = parsed.get("citation")
    citation = str(citation_raw).strip() if citation_raw is not None else None
    if citation == "":
        citation = None

    return {
        "relevant": relevant,
        "principle_ids": principle_ids,
        "kr_refs": kr_refs,
        "digest": digest_text,
        "citation": citation,
    }


def _get_source_ts(*, item_type: str, payload: ImportedNote | DCI) -> datetime:
    if item_type == "note":
        note = payload
        assert isinstance(note, ImportedNote)
        return note.ts
    dci = payload
    assert isinstance(dci, DCI)
    return datetime.combine(dci.date, datetime.min.time())


def _ns_to_ms(value: int | None) -> int | None:
    if value is None:
        return None
    return int(value / 1_000_000)


def _sum_tokens(prompt_tokens: int | None, completion_tokens: int | None) -> int | None:
    if prompt_tokens is None and completion_tokens is None:
        return None
    return int(prompt_tokens or 0) + int(completion_tokens or 0)


def _build_llm_run_record(
    *,
    model: str,
    prompt_version: str,
    temperature: float,
    think: bool,
    system_prompt: str,
    user_prompt: str,
    response: Any | None,
    validation_passed: bool,
    validation_error: str | None,
    error: str | None,
) -> dict[str, Any]:
    """Build a normalized llm_runs payload for EOD relevance."""
    return {
        "artifact_id": None,
        "artifact_type": "eod_relevance",
        "run_type": "eod_relevance",
        "model": model,
        "prompt_version": prompt_version,
        "temperature": temperature,
        "think_enabled": int(think),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "raw_output": response.content if response else None,
        "done_reason": response.done_reason if response else None,
        "prompt_tokens": response.prompt_eval_count if response else None,
        "completion_tokens": response.eval_count if response else None,
        "total_duration_ms": _ns_to_ms(response.total_duration) if response else None,
        "load_duration_ms": _ns_to_ms(response.load_duration) if response else None,
        "prompt_eval_duration_ms": _ns_to_ms(response.prompt_eval_duration) if response else None,
        "eval_duration_ms": _ns_to_ms(response.eval_duration) if response else None,
        "validation_passed": int(validation_passed),
        "validation_error": validation_error,
        "error": error,
    }
