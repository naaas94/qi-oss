# QI - Quality Intelligence

A local-first CLI system for personal development tracking and reporting, designed for 52-week compounding data accumulation.

## What QI Does

QI turns daily self-observations and ad-hoc notes into structured, computable signals and narrative reports. It captures daily metrics through a low-friction check-in, ingests notes from an external note-capture system (SnR QuickCapture), classifies them into structured events, engineers features over rolling time windows, and generates weekly/monthly reports with optional LLM-assisted narrative synthesis via Ollama.

**Core philosophy**: *Signal accumulation per unit friction* -- maximize insight yield while keeping daily effort under two minutes.

**What compounding looks like after 12-52 weeks**: 365 micro-observations, hundreds of classified events, 52 weekly retros with intervention tracking, 12 monthly dossiers. Enough data to answer "what conditions produce high output?", "what precedes avoidance spikes?", and "which interventions actually moved the needle?"

## Quick Start

```bash
# Install (editable, with dev tools)
pip install -e ".[dev]"

# Initialize QI (creates ~/.qi directory, database, config, principles file)
qi init

# First daily check-in
qi dci

# Quick check-in (energy, mood, sleep only)
qi dci --quick
```

## How the System Works

QI has four layers: **Capture**, **Processing**, **Reporting**, and **LLM Synthesis**. Each layer is independent -- the system produces useful output even without LLM, and even without note imports.

### Data Flow

```
                External System                           QI System
               ┌─────────────┐
               │  SnR QC DB  │──── qi import-snr-db ────┐
               │  (SQLite)   │                           │
               │             │──── qi import-snr ────────┤ (JSONL)
               └─────────────┘                           │
                                                         ▼
                                                  notes_imported
                                                         │
                                                    qi process
                                                   (heuristics)
                                                         │
               ┌─────────────┐                           ▼
               │   qi dci    │──────────────────►     events
               └─────────────┘                           │
                                                  Feature Engine
               ┌─────────────┐                  (means, deltas,
               │   qi week   │──────────────►    streaks, counts)
               └─────────────┘                           │
                                                         ▼
                                                  qi eod (optional)
                                                  (relevance digests)
                                                         │
                                                         ▼
                                                  qi report weekly
                                                  qi report monthly
                                                         │
                                           ┌─────────────┴──────────────┐
                                           │                            │
                                    Deterministic              LLM Narrative
                                     Sections                   (Ollama)
                                           │                            │
                                           └─────────────┬──────────────┘
                                                         ▼
                                                     Artifact
                                              (markdown + metadata)
```

**Sync shortcut**: `qi report weekly --sync` chains import + heuristic process + **EOD relevance** + report in one command. Same for `qi report monthly --sync`.

### 1. Capture Layer

**Daily Check-In (DCI)** -- the primary data stream. A stepped interactive prompt that takes 30-120 seconds:

| Section | Fields | Required |
|---------|--------|----------|
| Core Metrics | energy, mood, sleep (0-10 float) | Yes |
| Focus & Reflection | primary_focus, one_win, one_friction | No |
| Custom Metrics | Configurable via `[dci_metrics]` in config (bools, floats, ints, strings; labels and aggregates defined per metric) | No |
| Carryover | residual items from previous days | No |

Quick mode (`qi dci --quick`) captures only the three core metrics. Custom metrics are driven by `~/.qi/config.toml`; see the Configuration section for the structure.

**SnR QuickCapture Import** -- ingests notes from a companion QuickCapture system (e.g. SnR QuickCapture or your own note-capture tool). QC is an intelligent note-capture tool with a global hotkey, local LLM parsing (tags, sentiment, entities, intent), and hybrid SQLite/vector storage. QI consumes these notes and reuses the metadata QC already extracted, avoiding redundant LLM calls.

Two import modes:
- `qi import-snr <file.jsonl>` -- from a JSONL export file
- `qi import-snr-db [path]` -- directly from the QC SQLite database (idempotent via `ON CONFLICT(snr_id)`)

**Weekly Retro** (`qi week`) -- a 15-25 minute structured retrospective: scoreboard, wins (up to 5), frictions (up to 5), root-cause hypothesis, one-change commitment (title + mechanism + measurement), minimums for next week, and previous commitment tracking.

### 2. Processing Layer

**Heuristic Event Classifier** (`qi process`) -- converts imported notes into structured events using a hybrid approach:

- Reuses SnR QC's LLM-extracted tags and sentiment (already paid for at capture time)
- Applies QI-specific keyword heuristics for event classification
- Not every note becomes an event -- only those matching detectable patterns

Event types: `win`, `friction`, `insight`, `compulsion`, `avoidance`
Domains: `health`, `career`, `social`, `cognition`, `nature`, `finance`

Keyword rules are defined in `processing/heuristics.py` (module-level constants).

**EOD Relevance Pipeline** (`qi eod`) -- optional batch that runs a small LLM on unprocessed notes and DCI free-text to produce per-item relevance digests (principle/KR alignment, citation). Idempotent; processes only items with `date(ts) <= target_date`. Supports `--sync` (import + heuristic process before EOD). Use `qi eod --date YYYY-MM-DD` to process past dates.

**Feature Engineering** -- deterministic computation over any date window:

| Category | Features |
|----------|----------|
| Core | energy_mean, mood_mean, sleep_mean, mood_volatility |
| Config-driven | Per `[dci_metrics]`: `{key}_count`, `{key}_rate`, or `{key}_total` based on aggregate type (count/rate/sum) |
| Behavioral | compulsion_rate, good_period_rate, top_triggers (when those metrics exist in config) |
| Events | win_count, friction_count, insight_count, compulsion_event_count |
| Streaks | dci_streak, training_streak |
| Deltas | Week-over-week change for all numeric features |
| Trends | Linear regression slope (improving / stable / declining) |

Missing data strategy: skip gaps in calculations (no interpolation), reset streaks on gaps, require minimum 3 data points for rolling means.

### 3. Reporting Layer

**Weekly Digest** (`qi report weekly`) -- deterministic sections covering core metrics, training, behavioral tracking, events, tokens, week-over-week deltas, and streaks. Optionally appends an LLM narrative.

**Monthly Dossier** (`qi report monthly`) -- same deterministic sections plus trend analysis (linear regression on energy/mood/sleep) and a summary of weekly retros (wins, frictions, commitment tracking).

Both commands support:
- `--sync` -- import from QC DB + heuristic process + EOD relevance batch + generate report (full pipeline)
- `--no-llm` -- skips LLM narrative (deterministic-only output)
- `--force` -- regenerate report even if an artifact already exists for the window (replaces existing)
- `--date YYYY-MM-DD` -- target a specific week or month

Every report is saved as an **artifact** in the database with full input/feature snapshots, rendered markdown, and LLM metadata. Re-running `qi report weekly` or `qi report monthly` for the same window returns the existing artifact (idempotent). Use `--force` to regenerate and replace it.

### 4. LLM Synthesis Layer (Optional)

When enabled, the LLM layer appends a narrative section to reports. It uses Ollama (local inference) and follows a strict contract:

**Flow**:
1. Build deterministic prompts from feature data + user's `principles.md` (guiding principles and OKRs)
2. Call Ollama chat API with JSON output format
3. Validate response against Pydantic schema (`NarrativeOutput`)
4. On validation failure: one retry with a repair prompt
5. On second failure: report is still produced without the narrative (graceful degradation)

**Report context** now includes: `daily_series` (energy/mood/sleep by day), `digests` (relevance digests from notes and DCI with principle/KR alignment and citations). The LLM uses these for evidence-based narrative.

**Narrative output contract** (validated via Pydantic):
- `weekly_summary` -- what happened
- `delta_narrative` -- what changed and plausible causes
- `principle_alignment` -- per-principle status (on_track / slipping / no_data) with evidence
- `kr_progress` -- OKRs assessment
- `coaching_focus` -- one theme to focus on
- `next_experiment` -- one practical change with measurable outcome
- `risks` -- top failure modes
- `confidence` -- 0-1 self-assessed confidence

**Observability**: every LLM call is traced in the `llm_runs` table with timing (total/load/prompt_eval/eval duration in ms), token counts, validation outcome, full prompts, and raw output. Enables queries like per-model latency, validation failure rate, and token usage over time.

The principles file (`~/.qi/principles.md`) contains user-defined guiding principles and OKRs (objectives and key responsibilities). It is injected into the LLM prompt to ground the narrative in your actual goals. Edit with `qi principles edit`.

## CLI Reference

| Command | Description |
|---------|-------------|
| `qi init` | Create `~/.qi` directory, database, config, principles file |
| `qi dci` | Interactive daily check-in (stepped prompts) |
| `qi dci --quick` | Quick DCI (energy, mood, sleep only) |
| `qi dci --date YYYY-MM-DD` | Backfill a DCI for a specific date |
| `qi import-snr <path>` | Import notes from SnR QC JSONL export |
| `qi import-snr-db [path]` | Import from QuickCapture SQLite DB |
| `qi import-snr-db --week YYYY-MM-DD` | Import week containing date |
| `qi import-snr-db --since 7d` | Import last N days |
| `qi process` | Run heuristic classifier on unprocessed notes |
| `qi eod` | Run EOD relevance batch (notes + DCI → digests) |
| `qi eod --sync --date YYYY-MM-DD` | Import + process + EOD batch for date |
| `qi week` | Interactive weekly retrospective |
| `qi stats` | Show trend statistics (last 7 days default) |
| `qi stats --tokens` | Include token aggregates |
| `qi stats --days 28` | Change analysis window |
| `qi residuals` | Show residual items from most recent DCI |
| `qi report weekly` | Generate weekly digest |
| `qi report weekly --sync` | Import + process + EOD relevance + generate weekly report |
| `qi report weekly --no-llm` | Skip LLM narrative |
| `qi report weekly --force` | Regenerate weekly report even if artifact exists |
| `qi report monthly` | Generate monthly dossier |
| `qi report monthly --sync` | Import + process + EOD relevance + generate monthly report |
| `qi report monthly --no-llm` | Skip LLM narrative |
| `qi report monthly --force` | Regenerate monthly report even if artifact exists |
| `qi principles edit` | Open principles and KRs in `$EDITOR` |
| `qi export --format jsonl` | Export all data for backup (dci, notes_imported, events, weekly_retro, artifacts, relevance_digests, llm_runs) |
| `qi version` | Show version |

## Data Storage

All data lives in `~/.qi/` (override with the `QI_HOME` environment variable):

| File | Purpose |
|------|---------|
| `qi.db` | SQLite database (WAL mode) |
| `config.toml` | User configuration |
| `principles.md` | Guiding principles and OKRs for LLM narrative |

**Database tables**:

| Table | Content |
|-------|---------|
| `dci` | Daily check-ins (one row per date, upsert on conflict) |
| `notes_imported` | Notes from SnR QC (idempotent via `snr_id`; has `qi_relevance_processed` flag) |
| `relevance_digests` | Per-item relevance/digest from EOD pipeline (notes + DCI; source_ts, citation, status) |
| `events` | Structured events classified from notes |
| `weekly_retro` | Weekly retrospectives (one per week_start) |
| `artifacts` | Generated reports with full input/feature/output snapshots |
| `llm_runs` | LLM call traces (timing, tokens, prompts, validation) |

Schema is version-tracked via a `schema_version` table and SQL migration files in `migrations/`.

## Configuration

Config file: `~/.qi/config.toml`

```toml
[general]
week_start_day = "monday"
timezone = "local"

[dci]
quick_mode_fields = ["energy", "mood", "sleep"]

[dci_metrics]
# Add your own metrics. Each: type (bool|float|str), label (prompt text), aggregate (count|rate|sum).
# Optional: conditional_on = "other_key" to show only when another metric is truthy.
habit_1 = { type = "bool", label = "Habit 1 done?", aggregate = "count" }
habit_2 = { type = "bool", label = "Habit 2 done?", aggregate = "count" }
optional_note = { type = "str", label = "Optional note", aggregate = "count" }

[snr]
# Path to SnR QuickCapture database for import-snr-db and --sync (leave empty if not used)
qc_db_path = ""

[llm]
enabled = true
model = "qwen3:30b"           # report synthesis model
eod_model = "qwen3:8b"        # EOD relevance batch model
eod_temperature = 0.3
eod_concurrency = 3           # parallel EOD calls (semaphore limit)
base_url = "http://localhost:11434"
temperature = 0.4
timeout_seconds = 1200        # 0 = no timeout (for slow local models)
principles_path = "principles.md"  # relative to QI_HOME
think = false                 # set true only if model supports extended thinking
```

Set `llm.enabled = false` or omit the `[llm]` section entirely to run without LLM (deterministic-only reports).

## Project Structure

```
qi/
├── __init__.py              # Package + version
├── __main__.py              # python -m qi entrypoint
├── cli.py                   # Typer CLI with all commands
├── config.py                # Config loading from ~/.qi/config.toml
├── db.py                    # SQLite connection, migrations, all CRUD
├── models.py                # Pydantic models (DCI, ImportedNote, Event, etc.)
├── capture/
│   ├── dci.py               # Interactive DCI prompt (Rich TUI)
│   ├── snr_import.py        # JSONL import from SnR QC
│   ├── snr_db_import.py     # Direct SQLite import from QC database
│   └── weekly.py            # Weekly retro interactive prompt
├── processing/
│   ├── heuristics.py        # Keyword/tag event classifier
│   ├── features.py          # Rolling stats, deltas, streaks, trends, daily_series
│   └── eod.py               # EOD relevance batch (async, semaphore-limited)
├── reporting/
│   ├── weekly.py            # Weekly digest builder
│   ├── monthly.py           # Monthly dossier builder
│   └── render.py            # Markdown section renderers
├── llm/
│   ├── schema.py            # Single-source LLM narrative schema
│   ├── client.py            # Ollama HTTP client (httpx)
│   ├── prompts.py           # Versioned prompt builder
│   ├── validate.py          # Pydantic output validation + repair retry
│   ├── synthesis.py         # High-level orchestration + observability
│   └── render.py            # Narrative markdown renderer
└── utils/
    └── time.py              # Week/month bounds, date helpers

migrations/
├── 001_initial.sql          # Core tables (dci, notes_imported, events, weekly_retro, artifacts + prompt_version/model_id)
├── 003_llm_runs.sql         # LLM observability traces table
├── 004_relevance_digests.sql      # relevance_digests table, qi_relevance_processed, relevance_processed
├── 005_relevance_digest_observability.sql  # source_ts, citation, processing_duration_ms, status, error_message
└── 006_relevance_digest_total_tokens.sql   # total_tokens
tests/
```

## SnR QuickCapture Integration

QI is designed to work alongside a separate note-capture system (e.g. QuickCapture) with:
- Global hotkey (`Alt+Space`) for instant thought capture
- Local LLM parsing via Ollama (tags, sentiment, entities, intent, action items)
- Hybrid SQLite + FAISS vector storage

QI reuses QC's parsed metadata rather than re-running LLM inference on notes. The integration is decoupled: QI reads from QC's database (or JSONL export) and stores a copy in its own `notes_imported` table. QI works standalone without QC -- the DCI is an independent capture stream.

## Desktop Shortcut (Windows)

Create a shortcut that runs `qi dci`: use **New → Shortcut**, set target to your Python or `qi` executable with argument `dci`, or run `qi dci` from a batch file / terminal. Alternatively, pin a shortcut to `run_dci.bat` (in the repo) after installing QI.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Linting
ruff check qi/
mypy qi/
```

**Tech stack**: Python 3.11+, Typer + Rich (CLI/TUI), Pydantic v2 (validation), SQLite (storage), httpx (Ollama API), TOML (config), Hypothesis (property testing).

## Architecture Decisions (Case Study)

QI is designed to be a resilient, privacy-first, and highly observable system. Key architectural decisions include:

- **Local-First & Privacy by Default:** All personal journal data, behavioral flags, and insights are highly sensitive. By using SQLite in WAL mode and local inference via Ollama, the system guarantees zero data exfiltration while still providing advanced LLM synthesis.
- **Decoupled Processing Layers:** The system separates deterministic heuristic processing from LLM synthesis. Even if the LLM is unavailable or times out, the system gracefully degrades to produce deterministic reports.
- **Idempotent Pipelines:** The data ingestion (from SnR QuickCapture) and EOD relevance batches are designed to be idempotent. You can re-run them safely without duplicating data, utilizing `ON CONFLICT` upserts and date-windowing.
- **LLM Observability:** An often-overlooked aspect of LLM applications is instrumentation. QI logs every inference call to an `llm_runs` table, capturing prompt/completion tokens, latency (load vs. eval duration), model versions, and validation errors. This makes debugging prompt drift and performance regressions empirical rather than guesswork.
- **Strict Data Contracts:** LLM outputs are forced into structured JSON and validated against Pydantic models (e.g., `NarrativeOutput`). If the LLM hallucinates or breaks schema, the system catches it, attempts a repair prompt, and logs the validation failure.

## Roadmap

**Recently implemented (text relevance and context shape):**
- **EOD relevance pipeline**: `qi eod` runs a small model on notes and DCI free-text to produce per-item digests (relevant, principle_ids, kr_refs, digest, citation). Idempotent; `target_date` filters both notes and DCIs consistently.
- **Time-series context**: `daily_series` (energy, mood, sleep, plus each config metric by day) passed to report prompt.
- **Model tiering**: `eod_model` for EOD batch, `model` for report synthesis; `eod_concurrency` controls parallel EOD calls.
- **Report --sync**: `qi report weekly --sync` and `qi report monthly --sync` now run import + heuristic process + EOD relevance + report in one command.

Planned improvements (not yet implemented):

- **Scheduling**: External scheduler (cron / Task Scheduler) integration for automated EOD processing and report generation
- **GUI/TUI selector**: Menu-driven interface for CLI commands
- **Compiled executable**: Standalone packaged binary for DCI and other frequent commands

## License

MIT License

---

*QI - Quality Intelligence for personal development tracking*
