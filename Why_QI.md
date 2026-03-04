# Why QI?

QI (Quality Intelligence) is a local-first CLI for personal development: you do a short daily check-in and optionally pull in notes from your capture system. Over time, QI turns that into structured signals, trends, and narrative reports — all on your machine, with no cloud account and no data export.

This page is for **you** (the end user): what you get, why it’s different, and why the curve of your data matters.

---

## Data boundary and privacy

All your data stays on your machine. QI does not use a cloud account, does not send your journal, notes, or reports to any external service, and does not exfiltrate your data. The database, config, and principles file live in a single directory (e.g. `~/.qi/`, overridable with `QI_HOME`). When you use the optional LLM narrative, inference runs locally via Ollama — no prompts or responses leave your computer. You own the data boundary: you can inspect the SQLite database and every LLM run, back up or delete the directory, and control exactly what is stored and where.

---

## Your principles and goals drive everything

You keep one file — **principles and OKRs** (objectives and key responsibilities: what you want and/or have to achieve) — that defines what matters to you. QI uses it to:

- **Ground the AI narrative** so weekly and monthly reports speak to *your* goals, not generic advice.
- **Align relevance** so ingested notes and check-in free text are linked to specific principles and OKRs, with citations.
- **Track progress** so reports can say whether you’re on track, slipping, or have no data yet, per principle and per OKR.

Edit it anytime with `qi principles edit`. No principles file, no problem: reports still run with deterministic sections; the narrative layer simply has nothing to align to until you add them.

Your system stays aligned to what you care about. Reports and narratives are about *your* principles and OKRs, not a one-size-fits-all template.

---

## EOD relevance: notes and check-in text become evidence

QI can run an **end-of-day relevance** step on:

- **Imported notes** (e.g. from SnR QuickCapture or your own capture tool)
- **DCI free text** (wins, frictions, focus, carryover)

For each item it produces a **relevance digest**: whether it’s relevant, which principles or OKRs it touches, and a short citation. Those digests are then fed into the **LLM narrative** so the AI can refer to real quotes and events instead of guessing.

You can run this yourself (`qi eod`) or use `qi report weekly --sync` / `qi report monthly --sync` to run import, processing, EOD relevance, and report in one go.

Your notes and daily reflections aren’t just stored — they’re linked to your principles and OKRs and cited in your reports, so insights are evidence-based. You decide what to feed in: notes from your capture system, daily check-in free text, or both—whatever you ingest or link flows into the EOD relevance digest and into the LLM synthesis reports.

---

## You choose what feeds relevance and reports

QI doesn't lock you into one data source. You can ingest or link whatever you want—notes from your capture tool, daily check-in free text, or both—into the EOD relevance digest and into the LLM synthesis reports. The narrative and principle/OKR alignment are based on the data you actually include.

---

## LLM synthesis: narrative that follows your goals

When you use Ollama locally, QI can append an **LLM narrative** to every weekly and monthly report. That narrative is built from:

- Your **principles and OKRs**
- **Feature data** (metrics, streaks, deltas, trends)
- **Relevance digests** from notes and DCI free text (with citations)

The model outputs a **structured narrative** (validated so it stays in a known shape), including:

- What happened this week/month
- What changed and plausible causes
- Per-principle status (on track / slipping / no data) with evidence
- OKRs progress
- One coaching focus and one next experiment
- Risks and a confidence score

Everything runs **locally**; every LLM call is logged (prompts, tokens, latency) so you can inspect or debug it. You can turn the narrative off with `--no-llm` and still get full deterministic reports.

AI-written summaries follow *your* principles and OKRs, cite your notes and check-ins, and run entirely on your machine with full observability.

---

## Curve tracking: the more you use it, the sharper the picture

QI is built for **compounding**: small, low-friction inputs over time become a rich curve of signals.

- **Daily check-in** — energy, mood, sleep, optional focus/win/friction and custom metrics (e.g. training, habits). Quick mode keeps it to a couple of minutes.
- **Accumulated entries** — rolling means, volatility, streaks (e.g. check-in streak, training streak), and week-over-week deltas.
- **Trends** — linear regression on core metrics (improving / stable / declining) so you see direction, not just snapshots.
- **Events** — wins, frictions, insights, compulsion/avoidance events classified from your notes, with counts and rates over time.
- **Weekly retros** — structured look back, one-change commitment, and tracking of past commitments so you can see what actually moved the needle.

After 12–52 weeks you have hundreds of data points, 52 weekly retros, and 12 monthly dossiers — enough to answer “what conditions produce high output?”, “what precedes avoidance spikes?”, and “which interventions worked?”

Your data accumulates; trends, streaks, and cause-effect hypotheses become visible over weeks and months, not just single days.

---

## Other reasons to use QI

- **Low daily friction** — Design goal: under two minutes for the core check-in; quick mode is even faster.
- **Deterministic reports even without LLM** — Weekly and monthly digests with metrics, events, streaks, and deltas work without Ollama; the narrative is an optional layer on top.
- **Structured retros and commitments** — Weekly retros and “one change” commitments are stored and summarized in monthly reports so you can track what you tried and what happened.
- **Custom metrics** — Configure your own DCI questions and aggregates (counts, rates, sums) in config so reports reflect your own habits and goals.

---

*Use this document to understand what QI offers you as an end user: principles-driven reporting, EOD relevance for notes and DCI text, optional local LLM synthesis, and curve tracking through sustained data accumulation.*
