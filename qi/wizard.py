"""Interactive setup wizard for QI."""

from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from qi.config import (
    DEFAULT_CONFIG,
    QI_CONFIG_PATH,
    QI_HOME,
    ensure_principles_file,
    ensure_qi_home,
    get_principles_path,
    load_config,
    save_config,
)
from qi.db import init_db

# ── Helpers ─────────────────────────────────────────────────────────────


def _menu(console: Console, prompt: str, options: list[tuple[str, str]], default: str | None = None) -> str:
    """Numbered menu. *options* is a list of ``(key, label)`` tuples.

    Returns the *key* of the selected option.
    """
    for i, (key, label) in enumerate(options, 1):
        marker = " [dim](default)[/dim]" if key == default else ""
        console.print(f"  [cyan]{i}[/cyan]) {label}{marker}")
    while True:
        raw = console.input(f"\n{prompt} ").strip()
        if not raw and default is not None:
            return default
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        except ValueError:
            pass
        console.print("[red]Invalid choice, try again.[/red]")


def _confirm(console: Console, prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = console.input(f"{prompt} [{hint}] ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _input(console: Console, prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    raw = console.input(f"{prompt}{hint} ").strip()
    return raw or default


def _valid_toml_key(name: str) -> bool:
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))


# ── Step 1: Dependencies ───────────────────────────────────────────────


def _step_dependencies(console: Console, config: dict[str, Any]) -> None:
    console.print(Panel("[bold]Step 1 / 6 — Dependencies (Ollama + model)[/bold]", style="cyan"))

    llm_report = config.setdefault("llm-report", copy.deepcopy(DEFAULT_CONFIG["llm-report"]))
    llm_eod = config.setdefault("llm-eod", copy.deepcopy(DEFAULT_CONFIG["llm-eod"]))
    base_url = str(llm_report.get("base_url", "http://localhost:11434")).rstrip("/")

    if not _confirm(console, "Use LLM for report narratives and EOD relevance?", default=True):
        llm_report["enabled"] = False
        llm_eod["enabled"] = False
        console.print("  LLM disabled. Reports will be deterministic-only.\n")
        return

    llm_report["enabled"] = True
    llm_eod["enabled"] = True

    models = _fetch_ollama_models(base_url)
    if models is None:
        console.print(f"  [yellow]Ollama is not reachable at {base_url}.[/yellow]")
        if shutil.which("ollama"):
            console.print("  [dim]'ollama' found on PATH — try running:[/dim] ollama serve")
        else:
            console.print("  [dim]Install Ollama from https://ollama.com and start the service.[/dim]")
        console.print("  Keeping current model settings; you can change them later in config.toml.\n")
        return

    if not models:
        console.print("  [yellow]Ollama is running but no models are pulled.[/yellow]")
        console.print("  Pull a model first, e.g.: ollama pull qwen3:30b\n")
        return

    console.print(f"  [green]Ollama reachable[/green] at {base_url}  ({len(models)} model(s) available)")

    report_model = _pick_model(console, models, "Report synthesis model", llm_report.get("model", ""))
    llm_report["model"] = report_model

    eod_model = _pick_model(console, models, "EOD relevance model (can be smaller)", llm_eod.get("model", report_model))
    llm_eod["model"] = eod_model
    console.print()


def _fetch_ollama_models(base_url: str) -> list[str] | None:
    """Return sorted model names from Ollama /api/tags, or None if unreachable."""
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        return sorted(m["name"] for m in data.get("models", []))
    except Exception:  # noqa: BLE001
        return None


def _pick_model(console: Console, models: list[str], label: str, current: str) -> str:
    console.print(f"\n  [bold]{label}[/bold] (current: {current or 'none'})")
    for i, name in enumerate(models, 1):
        marker = " [dim]<- current[/dim]" if name == current else ""
        console.print(f"    [cyan]{i}[/cyan]) {name}{marker}")
    console.print(f"    [cyan]{len(models) + 1}[/cyan]) Type a model name manually")

    while True:
        raw = console.input("  Choice (Enter to keep current): ").strip()
        if not raw:
            return current
        try:
            idx = int(raw)
            if 1 <= idx <= len(models):
                return models[idx - 1]
            if idx == len(models) + 1:
                return console.input("  Model name: ").strip() or current
        except ValueError:
            pass
        console.print("  [red]Invalid choice.[/red]")


# ── Step 2: Data location & sources ────────────────────────────────────


def _step_data_sources(console: Console, config: dict[str, Any]) -> None:
    console.print(Panel("[bold]Step 2 / 6 — Data location & sources[/bold]", style="cyan"))

    console.print(f"  QI home directory: [bold]{QI_HOME}[/bold]")
    console.print("  [dim]Change with QI_HOME environment variable before running QI.[/dim]\n")

    snr = config.setdefault("snr", {"qc_db_path": ""})
    current_qc = snr.get("qc_db_path", "")

    choice = _menu(
        console,
        "Connect a data source now?",
        [
            ("snr", f"SnR QuickCapture DB{' (configured)' if current_qc else ''}"),
            ("skip", "I'll add data sources later"),
        ],
        default="skip",
    )

    if choice == "snr":
        path_str = _input(console, "  Path to QuickCapture DB", default=current_qc)
        if path_str:
            p = Path(path_str).expanduser()
            if p.exists():
                snr["qc_db_path"] = str(p)
                console.print(f"  [green]Set[/green] snr.qc_db_path = {p}")
            else:
                console.print(f"  [yellow]Path not found: {p}[/yellow] — saving anyway, fix later.")
                snr["qc_db_path"] = str(p)
    console.print()


# ── Step 3: Metrics ────────────────────────────────────────────────────


def _step_metrics(console: Console, config: dict[str, Any]) -> None:
    console.print(Panel("[bold]Step 3 / 6 — Core & custom metrics[/bold]", style="cyan"))

    dci = config.setdefault("dci", copy.deepcopy(DEFAULT_CONFIG["dci"]))
    quick_fields = dci.get("quick_mode_fields", ["energy", "mood", "sleep"])

    console.print(f"  Core quick-mode fields: [bold]{', '.join(quick_fields)}[/bold]")
    if _confirm(console, "  Keep these?", default=True):
        pass
    else:
        raw = _input(console, "  Enter core fields (comma-separated)", default=", ".join(quick_fields))
        dci["quick_mode_fields"] = [f.strip() for f in raw.split(",") if f.strip()]
        console.print(f"  Updated: {dci['quick_mode_fields']}")

    dci_metrics: dict[str, Any] = config.setdefault(
        "dci_metrics", copy.deepcopy(DEFAULT_CONFIG["dci_metrics"])
    )
    _show_metrics_table(console, dci_metrics)

    while True:
        action = _menu(
            console,
            "Custom metrics:",
            [
                ("add", "Add a new metric"),
                ("remove", "Remove a metric"),
                ("done", "Done — keep current metrics"),
            ],
            default="done",
        )
        if action == "done":
            break
        elif action == "add":
            _add_metric(console, dci_metrics)
        elif action == "remove":
            _remove_metric(console, dci_metrics)
    console.print()


def _show_metrics_table(console: Console, metrics: dict[str, Any]) -> None:
    if not metrics:
        console.print("  [dim]No custom metrics defined.[/dim]")
        return
    table = Table(title="Custom DCI Metrics", show_lines=False)
    table.add_column("Key", style="cyan")
    table.add_column("Type")
    table.add_column("Label")
    table.add_column("Aggregate")
    for key, meta in metrics.items():
        table.add_row(key, meta.get("type", "?"), meta.get("label", ""), meta.get("aggregate", ""))
    console.print(table)


def _add_metric(console: Console, metrics: dict[str, Any]) -> None:
    key = _input(console, "  Metric key (snake_case, e.g. training_done)")
    if not key or not _valid_toml_key(key):
        console.print("  [red]Invalid key (use letters, digits, underscores; start with letter/underscore).[/red]")
        return
    if key in metrics:
        console.print(f"  [yellow]Key '{key}' already exists.[/yellow]")
        return
    mtype = _menu(
        console,
        "  Type:",
        [("bool", "bool (yes/no)"), ("float", "float (numeric)"), ("str", "str (free text)")],
        default="bool",
    )
    label = _input(console, "  Label (shown in DCI prompt)", default=f"{key}?")
    aggregate = _menu(
        console,
        "  Aggregate for reports:",
        [("count", "count"), ("rate", "rate (% of days)"), ("sum", "sum")],
        default="count",
    )
    metrics[key] = {"type": mtype, "label": label, "aggregate": aggregate}
    console.print(f"  [green]Added[/green] {key}")


def _remove_metric(console: Console, metrics: dict[str, Any]) -> None:
    if not metrics:
        console.print("  [dim]No metrics to remove.[/dim]")
        return
    keys = list(metrics.keys())
    options = [(k, f"{k} — {metrics[k].get('label', '')}") for k in keys]
    options.append(("cancel", "Cancel"))
    key = _menu(console, "  Remove which metric?", options, default="cancel")
    if key != "cancel":
        del metrics[key]
        console.print(f"  [green]Removed[/green] {key}")


# ── Step 4: Principles & OKRs ──────────────────────────────────────────


def _step_principles(console: Console, config: dict[str, Any]) -> None:
    console.print(Panel("[bold]Step 4 / 6 — Principles & OKRs[/bold]", style="cyan"))

    principles_path, created = ensure_principles_file(config)
    if created:
        console.print(f"  [green]Created[/green] {principles_path}")
    else:
        console.print(f"  [dim]Principles file:[/dim] {principles_path}")

    choice = _menu(
        console,
        "How do you want to set up your principles and OKRs?",
        [
            ("llm", "Generate with LLM (describe your goals, AI drafts the file)"),
            ("edit", "Edit the file myself (opens in $EDITOR)"),
            ("keep", "Keep the template for now"),
        ],
        default="keep",
    )

    if choice == "llm":
        _generate_principles_with_llm(console, config, principles_path)
    elif choice == "edit":
        typer.edit(filename=str(principles_path))
        console.print(f"  [green]Editor closed.[/green] Principles at {principles_path}")
    else:
        console.print("  Template kept. Run [bold]qi principles edit[/bold] anytime to update.")
    console.print()


def _generate_principles_with_llm(
    console: Console, config: dict[str, Any], principles_path: Path
) -> None:
    """Ask user for a short description, call Ollama, write principles.md."""
    llm_cfg = config.get("llm-report", {})
    base_url = str(llm_cfg.get("base_url", "http://localhost:11434")).rstrip("/")
    model = str(llm_cfg.get("model", "qwen3:30b"))

    if not llm_cfg.get("enabled", False):
        console.print("  [yellow]LLM is disabled — skipping generation.[/yellow]")
        console.print("  You can edit the file manually: [bold]qi principles edit[/bold]")
        return

    description = _input(console, "  Describe your goals and areas of focus in 1-2 sentences")
    if not description.strip():
        console.print("  [dim]No description provided — keeping template.[/dim]")
        return

    console.print(f"  [cyan]Generating principles with {model}...[/cyan]")
    try:
        from qi.llm.client import OllamaClient

        with OllamaClient(base_url=base_url, timeout_seconds=120) as client:
            client.check_ready()
            response = client.generate(
                model=model,
                system_prompt=(
                    "You output only valid Markdown. "
                    "Generate a set of 5-7 guiding principles and 3 OKRs (Objectives and Key Responsibilities). "
                    "Use this exact format:\n"
                    "# Guiding Principles\n\n"
                    "## 1. Principle title\nShort description.\n\n"
                    "## 2. ...\n\n"
                    "# OKRs (Objectives and Key Responsibilities)\n\n"
                    "## Current Quarter\n"
                    "- KR1: ...\n- KR2: ...\n- KR3: ...\n\n"
                    "Do not add any preamble or explanation outside the markdown."
                ),
                user_prompt=f"Goals and areas of focus:\n{description}",
                temperature=0.5,
            )
        md = _strip_code_fences(response.content)
        principles_path.write_text(md, encoding="utf-8")
        console.print(f"  [green]Wrote[/green] {principles_path}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]LLM generation failed: {exc}[/red]")
        console.print("  Keeping existing template. Edit manually: [bold]qi principles edit[/bold]")
        return

    if _confirm(console, "  Open in editor to refine?", default=True):
        typer.edit(filename=str(principles_path))
        console.print("  [green]Editor closed.[/green]")


def _strip_code_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.index("\n") if "\n" in text else len(text)
        text = text[first_nl + 1:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


# ── Step 5: Usage ──────────────────────────────────────────────────────


def _step_usage(console: Console, _config: dict[str, Any]) -> None:
    console.print(Panel("[bold]Step 5 / 6 — How will you use QI?[/bold]", style="cyan"))

    choice = _menu(
        console,
        "Primary usage:",
        [
            ("dci", "Daily check-in only"),
            ("weekly", "Check-in + weekly reports"),
            ("full", "Full pipeline (DCI + import + EOD + reports)"),
        ],
        default="weekly",
    )

    console.print()
    console.print("[bold]Next steps:[/bold]")
    if choice == "dci":
        console.print("  Run [bold]qi dci[/bold] daily (or [bold]qi dci --quick[/bold] for core metrics only).")
    elif choice == "weekly":
        console.print("  Run [bold]qi dci[/bold] daily.")
        console.print("  Run [bold]qi report weekly[/bold] at the end of each week.")
    else:
        console.print("  Run [bold]qi dci[/bold] daily.")
        console.print("  Run [bold]qi report weekly --sync[/bold] to import, process, and generate reports.")
        console.print("  Run [bold]qi report monthly --sync[/bold] for monthly dossiers.")
    console.print()


# ── Step 6: Prompt persona ─────────────────────────────────────────────


def _step_prompt_persona(console: Console, config: dict[str, Any]) -> None:
    console.print(Panel("[bold]Step 6 / 6 — AI personality & prompt preferences[/bold]", style="cyan"))

    if not _confirm(console, "Customize how the AI speaks and works in reports?", default=False):
        console.print("  Keeping defaults (reflective analyst, sober tone, strict evidence).\n")
        return

    prefs = config.setdefault(
        "prompt_preferences", copy.deepcopy(DEFAULT_CONFIG["prompt_preferences"])
    )

    prefs["persona"] = _menu(
        console,
        "Primary role:",
        [
            ("analyst", "Reflective analyst — data-driven, observational"),
            ("coach", "Performance coach — supportive, growth-oriented"),
            ("journal", "Journaling companion — reflective, exploratory"),
            ("accountability", "Accountability partner — direct, challenging"),
        ],
        default=prefs.get("persona", "analyst"),
    )

    prefs["tone"] = _menu(
        console,
        "Tone:",
        [
            ("sober", "Sober and factual"),
            ("supportive", "Supportive and warm"),
            ("direct", "Direct and challenging"),
            ("neutral", "Neutral"),
        ],
        default=prefs.get("tone", "sober"),
    )

    prefs["strictness"] = _menu(
        console,
        "Evidence strictness:",
        [
            ("strict", "Only state what's in the data"),
            ("moderate", "Allow cautious inferences, flagged as interpretive"),
            ("interpretive", "Allow broader interpretation, stay grounded"),
        ],
        default=prefs.get("strictness", "strict"),
    )

    if _confirm(console, "Customize terminology (Principles, OKRs, etc.)?", default=False):
        nom = prefs.setdefault("nomenclature", copy.deepcopy(DEFAULT_CONFIG["prompt_preferences"]["nomenclature"]))
        nom["principles_label"] = _input(console, '  Term for "Principles"', default=nom.get("principles_label", "Principles"))
        nom["kr_label"] = _input(console, '  Term for "OKRs"', default=nom.get("kr_label", "OKRs"))
        nom["dci_label"] = _input(console, '  Term for "Daily Check-In"', default=nom.get("dci_label", "Daily Check-In"))
        nom["win_label"] = _input(console, '  Term for "Win"', default=nom.get("win_label", "Win"))
        nom["friction_label"] = _input(console, '  Term for "Friction"', default=nom.get("friction_label", "Friction"))

    console.print()


# ── Main wizard ─────────────────────────────────────────────────────────


def run_wizard(console: Console) -> None:
    """Run the full interactive setup wizard."""
    console.print(Panel(
        "[bold]QI Setup Wizard[/bold]\n\n"
        "This wizard will walk you through configuring QI.\n"
        "Press Enter to accept defaults at any prompt.",
        style="cyan",
    ))

    ensure_qi_home()
    init_db()

    if QI_CONFIG_PATH.exists():
        load_config.cache_clear()
    config = copy.deepcopy(load_config())

    _step_dependencies(console, config)
    _step_data_sources(console, config)
    _step_metrics(console, config)
    _step_principles(console, config)
    _step_usage(console, config)
    _step_prompt_persona(console, config)

    # Persist
    save_config(config)
    console.print(Panel("[bold green]Setup complete![/bold green]", style="green"))

    _print_summary(console, config)


def _print_summary(console: Console, config: dict[str, Any]) -> None:
    table = Table(title="Configuration summary", show_lines=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    llm_r = config.get("llm-report", {})
    table.add_row("LLM enabled", str(llm_r.get("enabled", False)))
    if llm_r.get("enabled"):
        table.add_row("Report model", llm_r.get("model", ""))
        table.add_row("EOD model", config.get("llm-eod", {}).get("model", ""))

    qc = config.get("snr", {}).get("qc_db_path", "")
    table.add_row("QC DB path", qc or "(not set)")

    metrics = config.get("dci_metrics", {})
    table.add_row("Custom metrics", str(len(metrics)))

    prefs = config.get("prompt_preferences", {})
    table.add_row("AI persona", prefs.get("persona", "analyst"))
    table.add_row("Tone", prefs.get("tone", "sober"))

    table.add_row("Principles", str(get_principles_path(config)))

    console.print(table)
    console.print()
