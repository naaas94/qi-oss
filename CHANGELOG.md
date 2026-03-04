# Changelog

All notable changes to QI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project does not use semantic versioning for now.

### [Unreleased]

## 2026-03-02

### Added

- **Report `--force`**: `qi report weekly` and `qi report monthly` accept `--force` to regenerate the report for the target window even when an artifact already exists. Without `--force`, re-running for the same window remains idempotent (returns existing artifact with a warning). With `--force`, the existing artifact is removed (and `llm_runs` unlinked), then a new report is generated and saved. New `delete_artifact_for_window()` in `qi/db.py` handles deletion and FK cleanup.
- **Config unit tests**: New `tests/test_config.py` covering `load_config()` (missing file returns defaults, existing TOML merges with defaults), path resolution (`QI_DB_PATH`, `QI_CONFIG_PATH` under `QI_HOME`), `ensure_qi_home()`, `get_config_value()` dot-path and defaults, `get_principles_path()` relative/absolute, and `parse_principle_names()` from principles markdown.
- **CLI unit tests**: New `tests/test_cli.py` covering subcommand presence (`init`, `dci`, `version`, `stats`, `week`, `report`, `principles`, `export`), `qi version`, `qi init` (creates config.toml, principles.md, qi.db; idempotent), `qi stats` / `qi stats --days N`, `qi export -o path`, and `qi process`. Uses a temp `QI_HOME` with patches on `qi.config`, `qi.db`, and `qi.cli` so commands run in isolation.

### Changed

- **EOD principles context**: EOD relevance prompts now use the full `principles.md` content instead of a compact summary, improving alignment classification. Removed the unused `build_principles_summary()` and the `re` import from `qi/llm/prompts.py`.

## 2026-02-27

### Added

- **Property-Based Testing**: Added `hypothesis` test suites to `tests/test_features.py` ensuring statistical invariants and trend calculation bounds.
- **EOD Async Tests**: Added `tests/test_eod.py` to cover async pipeline orchestration, error incrementing, and valid runs.
- **Single-Source LLM Schema**: Introduced `qi/llm/schema.py` to construct the `OUTPUT_SCHEMA` dict directly from the Pydantic `NarrativeOutput` models, preventing schema drift across prompt generation, validation, and rendering.
- **Unix DB Security Hardening**: Added best-effort permission bounds (`0o600`) when initializing the `qi.db` on Unix platforms.
- **Remote LLM Warnings**: The LLM client now prints a warning if `base_url` points to a non-local endpoint, to ensure user awareness of data transmission.

### Changed

- **UX/Metrics Prompting**: `qi dci` now surfaces the full descriptive metric label (e.g. `training_done (Training done?)`) from config rather than just the variable key.
- **"Not Logged" Preservation**: Skipped DCI dynamic metrics are now stored and processed as explicit `None` instead of conflating them with `0` or `False`. `FeatureSnapshot` is now strictly typed via `TypedDict`.
- **DRY Pipeline Consolidation**: Abstracted the shared `--sync` logic (import + heuristics + EOD) across `qi eod`, `qi report weekly`, and `qi report monthly` into a single `_run_sync_pipeline()` handler.
- **Shared Date Helpers**: Centralized robust parsing for CLI args (`parse_date`) and mixed-format SnR timestamps (`parse_timestamp`) into `qi/utils/time.py`.
- **Persistent HTTP Client**: `OllamaClient` now maintains an ongoing `httpx.Client` session context for better connection pooling across rapid API calls.
- **Heuristic Classifier Accuracy**: `qi process` event keywords now match on explicit word boundaries (regex `\b`) to eliminate substring false positives (e.g., matching "tissue" as "issue").
- **Migration Transaction Safety**: `qi/db.py` applies schema migrations atomically within `BEGIN IMMEDIATE; ... COMMIT;` wrappers to prevent drift on crashes.
- **Import Memory Optimization**: `qi import-snr` and `qi import-snr-db` now use lazy line reading and iteration, preventing large datasets from being fully loaded into memory before processing.

### Removed

- **Vestigial Code & Scripts**: Deleted unused `qi/processing/events.py`, stale exploration script `test_snr_db_import.py`, and outdated migration helpers (`merge_dci_from_mobile.py`, `dci_backlog_insert.sql`).
- **Completed Planning Specs**: Removed `bug_fixes_plan.md`, `llm_testing_plan.md`, `next_steps.md`, and `2026_02_15_text_relevance_and_context_shape_update_specs.md` as they are completed and fully integrated into the codebase history.
- **Stale JSON Schemas**: Removed `schemas/dci.schema.json` which drifted and was functionally replaced by `qi/config.py` metrics declarations.

## 2026-02-24

### Added

- **Bug-fix regression tests**: New `tests/test_bug_fixes.py` covering critical failure paths and behavior guarantees for capture import, weekly prompt validation, synthesis model consistency, and bulk-import DB connection reuse.
- **LLM test coverage (new suites)**: Added `tests/test_llm_client.py`, `tests/test_llm_prompts.py`, `tests/test_llm_validate.py`, `tests/test_llm_render.py`, and `tests/test_llm_synthesis.py` to cover client transport errors, prompt versioning and serialization, validation/repair-loop behavior, markdown rendering, and synthesis orchestration + observability persistence.
- **Idempotency guard on report generation**: New `get_artifact_for_window()` in `qi/db.py`. Running `qi report weekly` or `qi report monthly` for the same window again returns the existing artifact with a warning instead of creating duplicates.
- **Export includes observability tables**: `qi export --format jsonl` now includes `relevance_digests` and `llm_runs` in addition to `dci`, `notes_imported`, `events`, `weekly_retro`, and `artifacts`.
- **Config I/O caching**: `qi/config.py:load_config()` is now wrapped in `@functools.lru_cache()` to prevent redundant TOML disk reads during hot loops, improving feature computation and report generation speed.
- **Read-only DB imports**: `qi/capture/snr_db_import.py` now opens the QuickCapture SQLite database with URI `?mode=ro` to prevent accidental writes to the source database.
- **Export privacy warning**: Added an explicit console warning to `qi export` about the sensitivity of the plaintext JSONL data.

### Changed

- **JSON Metrics Migration**: Decoupled `dci` schema from hardcoded personal habits. The explicit `w`, `p`, `m`, `e`, `compulsion_flag`, and `trigger_tag` fields have been abstracted into a single dynamic `metrics` JSON column.
- **Config-driven UX and Feature Pipeline**: `qi dci` prompts and `qi report` metric aggregation (sum, count, rate) are now entirely driven by the `[dci_metrics]` configuration in `~/.qi/config.toml`, making the engine universally applicable.
- **Dependency hygiene**: `qi/config.py` now prefers stdlib `tomllib` (Python 3.11+), with `tomli` as fallback. Removed `tomli` from `pyproject.toml` and `requirements.txt`. Added `httpx` to `requirements.txt` so `pip install -r requirements.txt` installs full core deps.
- **Privacy hygiene**: Sanitized `DEFAULT_PRINCIPLES_TEMPLATE` in `qi/config.py` to be generic. Added `dci_backlog_insert.sql` and `merge_dci_from_mobile.py` to `.gitignore` and untracked them from git history.
- **Dead YAML config removed**: Deleted unused `config/defaults.yaml` and `config/heuristics.yaml` (no Python code loaded them).
- **README**: Heuristics now documented as in `processing/heuristics.py`; removed `config/` YAML files from project structure; export table list and report idempotency noted; DCI Training row updated to generic "Training done?" label.

### Fixed

- **`sqlite3.Row.get()` crash in QC DB import**: `qi/capture/snr_db_import.py` now resolves `note_id` via row key checks instead of `row.get(...)`, preventing secondary `AttributeError` in error handling.
- **`prompt_list` required-item bypass**: `qi/capture/weekly.py` now uses collected-item count (`while len(items) < max_items`) so blank input cannot skip required entries (`min_items` is enforced correctly).
- **LLM default model mismatch in synthesis observability**: `qi/llm/synthesis.py` now resolves one `model_name` value and reuses it for both inference and run persistence, eliminating model drift in logs.
- **N+1 DB connection overhead during bulk note import**: `qi/db.py` now supports optional connection injection in `save_imported_note(...)`, and both `qi/capture/snr_import.py` and `qi/capture/snr_db_import.py` now reuse a single `get_db()` connection per batch import.
- **Malformed Ollama JSON responses**: `qi/llm/client.py` now catches `response.json()` parse failures and raises `LLMClientError` with a clear message instead of leaking decoder exceptions.
- **Markdown-fenced JSON parsing in validation**: `qi/llm/validate.py` now strips surrounding ```json code fences before parsing, improving robustness for common LLM output formatting.
- **Premature "Saved" confirmation**: DCI and weekly retro no longer show "Saved!" before the DB write. Confirmation is printed in `cli.py` only after `save_dci()` / `save_weekly_retro()` succeed.
- **Silent `datetime.now()` fallback on import**: When a note's timestamp is missing or unparseable, import now logs a yellow warning before falling back to current time (`snr_import.py`, `snr_db_import.py`).
- **Naive vs timezone-aware datetime comparison**: `snr_import.py` now normalizes note timestamps to naive for comparison with `cutoff_date`, avoiding `TypeError` when `--since` is used with UTC timestamps.
- **Scoreboard training days range**: Weekly retro "Training days (0-7)" now validated in a loop; values outside 0–7 are rejected with a message.
- **DCI training section flow**: Training section prompt asks "Training done?" and always prompts for Cardio, Gym, and routine when logging training details; answering "n" to training done no longer skips the rest of the section.

## Backlog changes [undated]

### Added

- **EOD relevance pipeline**: New `qi eod` command runs an LLM batch on unprocessed notes and DCI free-text to produce per-item relevance digests (relevant, principle_ids, kr_refs, digest, citation). Idempotent; filters by `target_date` for both notes and DCIs. Supports `--sync` (import + heuristic process before EOD) and `--date YYYY-MM-DD`. Config: `llm.eod_model`, `llm.eod_temperature`, `llm.eod_concurrency`.
- **Relevance digests storage**: New `relevance_digests` table and migrations (004–006). Includes `source_ts`, `citation`, `total_tokens`, `processing_duration_ms`, `status`, `error_message`. New flags: `notes_imported.qi_relevance_processed`, `dci.relevance_processed`.
- **Time-series context for reports**: `compute_daily_series()` adds `daily_series` (energy, mood, sleep, training_done, compulsion_flag by day) to report context.
- **Digests in report synthesis**: Weekly and monthly reports now pass relevance digests to the LLM prompt (item_type, source_ts, principle_ids, kr_refs, digest, citation). Digest schema notes explain `note` vs `dci` and citation semantics.
- **Report --sync runs EOD**: `qi report weekly --sync` and `qi report monthly --sync` now chain import + heuristic process + **EOD relevance batch** + report. Ensures digests exist before synthesis.
- **LLM-assisted report narrative**: Weekly and monthly reports can include an LLM-generated narrative section (Ollama). Configurable via `~/.qi/config.toml` under `[llm]`: `enabled`, `model`, `base_url`, `temperature`, `timeout_seconds`, `principles_path`, `think`. Use `--no-llm` on `qi report weekly` / `qi report monthly` to skip synthesis.
- **Guiding principles and OKRs**: `~/.qi/principles.md` holds user-editable principles and OKRs (objectives and key responsibilities); contents are injected into the LLM prompt. Seed template created on `qi init`. New CLI: `qi principles edit` to open the file in `$EDITOR`.
- **LLM observability**: New `llm_runs` table stores a trace per LLM API call (initial + optional repair). Each row includes artifact link, run type, model, prompt version, full prompts, raw output, Ollama timing (total/load/prompt_eval/eval duration in ms), token counts, validation outcome, and errors. Enables queries like per-model latency, validation failure rate, and token usage.
- **Artifact LLM metadata**: `artifacts` table has nullable `prompt_version` and `model_id` (in initial schema).
- **Ollama `think` flag**: Config option `llm.think` (default `false`) disables reasoning/thinking for compatible models to avoid long timeouts on slow hardware.
- **Configurable / no timeout**: `llm.timeout_seconds` in config; set to `0` for no timeout (wait indefinitely for slow local models).
- **Dependency**: `httpx` for Ollama API calls.

### Changed

- **weekly_summary schema**: Removed `<=150 words` constraint from report narrative output schema to allow longer summaries.
- **Consistent target_date filtering**: EOD batch applies `target_date` to both notes (`date(ts) <= target_date`) and DCIs (`date <= target_date`), fixing inconsistent data inclusion when called from report --sync.
- Weekly and monthly report generation appends the LLM narrative section when enabled; context now includes `daily_series` and `digests`. Existing deterministic sections are unchanged. On LLM or validation failure, report is still produced without the narrative.
- Report artifact `output_json` now includes an `llm` object with `prompt_version`, `model_id`, `raw_output`, `error`, `llm_run_ids`, and related metadata.
- `save_artifact()` returns the new artifact row ID so callers can link `llm_runs` to the artifact.

### Fixed

- Timeout handling: explicit `httpx.Timeout` usage and support for `timeout_seconds = 0` (no timeout) so large/slow local models can complete.
- Config merge: `[llm]` section must be present in `~/.qi/config.toml` for LLM options (e.g. `timeout_seconds`) to apply; defaults live in code only when the section is missing.