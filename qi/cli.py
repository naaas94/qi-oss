"""CLI for QI - Quality Intelligence."""

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from qi import __version__
from qi.config import (
    DEFAULT_CONFIG,
    QI_CONFIG_PATH,
    QI_DB_PATH,
    QI_HOME,
    ensure_qi_home,
    ensure_principles_file,
    load_config,
    get_snr_qc_db_path,
    save_config,
)
from qi.db import init_db, save_dci, get_dci, get_latest_residual, save_imported_note, _row_to_dci
from qi.utils.time import parse_date

app = typer.Typer(
    name="qi",
    help="Quality Intelligence - Personal tracking and reporting CLI",
    no_args_is_help=True,
)
console = Console()
EXPORT_TABLES = (
    "dci",
    "notes_imported",
    "events",
    "weekly_retro",
    "artifacts",
    "relevance_digests",
    "llm_runs",
)


def _parse_date_or_exit(value: str, option_name: str) -> date:
    try:
        return parse_date(value, field_name=option_name)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


def _run_sync_pipeline(
    *,
    range_label: str,
    start_date: date,
    end_date: date,
    db_path: Path | None,
    run_eod: bool,
) -> None:
    from qi.capture.snr_db_import import import_from_qc_db
    from qi.processing.eod import run_eod_batch
    from qi.processing.heuristics import process_unprocessed_notes

    resolved_path = db_path if db_path else get_snr_qc_db_path()
    if resolved_path is None or not resolved_path.exists():
        console.print("[red]QuickCapture database not found for --sync.[/red]")
        console.print("Provide --db-path or set snr.qc_db_path in ~/.qi/config.toml")
        raise typer.Exit(1)

    console.print(f"[cyan]Syncing {range_label}: {start_date} to {end_date}[/cyan]")
    console.print("[cyan]Importing from QuickCapture DB...[/cyan]")
    imported, skipped = import_from_qc_db(resolved_path, start_date=start_date, end_date=end_date)
    console.print(f"  Imported: {imported}, Skipped: {skipped}")

    console.print("[cyan]Processing notes...[/cyan]")
    processed, events_created = process_unprocessed_notes()
    console.print(f"  Processed: {processed}, Events created: {events_created}")

    if run_eod:
        console.print("[cyan]Running EOD relevance...[/cyan]")
        eod_result = run_eod_batch(target_date=end_date)
        console.print(
            f"  EOD processed: {eod_result.processed}, Relevant: {eod_result.relevant}, Errors: {eod_result.errors}"
        )
    console.print()


@app.command()
def init():
    """Initialize QI - create config and database."""
    console.print(Panel("[bold]Initializing QI[/bold]", style="cyan"))

    # Create home directory
    ensure_qi_home()
    console.print(f"  [green]Created[/green] {QI_HOME}")

    # Create config if not exists
    if not QI_CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        console.print(f"  [green]Created[/green] {QI_CONFIG_PATH}")
    else:
        console.print(f"  [dim]Config already exists:[/dim] {QI_CONFIG_PATH}")

    config = load_config()

    # Create principles file if not exists
    principles_path, created_principles = ensure_principles_file(config)
    if created_principles:
        console.print(f"  [green]Created[/green] {principles_path}")
    else:
        console.print(f"  [dim]Principles file exists:[/dim] {principles_path}")

    # Initialize database
    created, migrations = init_db()
    if created:
        console.print(f"  [green]Created[/green] {QI_DB_PATH}")
    else:
        console.print(f"  [dim]Database exists:[/dim] {QI_DB_PATH}")

    if migrations:
        console.print(f"  [green]Applied[/green] {migrations} migration(s)")

    console.print("\n[green]QI initialized successfully![/green]")
    console.print(f"\nRun [bold]qi dci[/bold] to start your first daily check-in.")


@app.command()
def dci(
    quick: bool = typer.Option(False, "--quick", "-q", help="Quick mode: only core metrics"),
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Date for DCI (YYYY-MM-DD)"),
):
    """Interactive daily check-in."""
    from qi.capture.dci import prompt_dci, prompt_dci_quick
    from qi.db import ReadinessError, check_db_writable

    try:
        check_db_writable()
    except ReadinessError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    # Parse date
    target_date = date.today()
    if date_str:
        target_date = _parse_date_or_exit(date_str, "--date")

    # Check if DCI already exists
    existing = get_dci(target_date)
    if existing:
        console.print(f"[yellow]DCI already exists for {target_date}[/yellow]")
        if not typer.confirm("Do you want to overwrite it?"):
            raise typer.Exit(0)

    # Run appropriate prompt
    if quick:
        dci_data = prompt_dci_quick(target_date)
    else:
        dci_data = prompt_dci(target_date)

    # Save to database
    save_dci(dci_data)
    console.print(f"\n[green]DCI saved for {target_date}[/green]")


@app.command("import-snr")
def import_snr(
    file_path: Path = typer.Argument(..., help="Path to SnR QC JSONL export file"),
    since: Optional[str] = typer.Option(None, "--since", help="Only import notes from last N days (e.g., '7d')"),
):
    """Import notes from SnR QC JSONL export."""
    from qi.capture.snr_import import import_snr_jsonl

    # Parse since parameter
    since_days = None
    if since:
        if since.endswith("d"):
            try:
                since_days = int(since[:-1])
            except ValueError:
                console.print(f"[red]Invalid --since format: {since}. Use e.g., '7d'[/red]")
                raise typer.Exit(1)
        else:
            console.print(f"[red]Invalid --since format: {since}. Use e.g., '7d'[/red]")
            raise typer.Exit(1)

    try:
        imported, skipped = import_snr_jsonl(file_path, since_days)
        console.print(f"\n[green]Import complete![/green]")
        console.print(f"  Imported: {imported}")
        console.print(f"  Skipped: {skipped}")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command("import-snr-db")
def import_snr_db(
    db_path: Optional[Path] = typer.Argument(None, help="Path to QC DB (uses config snr.qc_db_path if not provided)"),
    week: Optional[str] = typer.Option(None, "--week", "-w", help="Import week containing date (YYYY-MM-DD)"),
    since: Optional[str] = typer.Option(None, "--since", "-s", help="Import last N days (e.g., '7d')"),
    start: Optional[str] = typer.Option(None, "--start", help="Start date (YYYY-MM-DD)"),
    end: Optional[str] = typer.Option(None, "--end", help="End date (YYYY-MM-DD)"),
):
    """Import notes from SnR QuickCapture database."""
    from qi.capture.snr_db_import import import_from_qc_db
    from qi.utils.time import get_week_bounds

    # Resolve DB path from argument or config
    resolved_path = db_path
    if resolved_path is None:
        resolved_path = get_snr_qc_db_path()
    
    if resolved_path is None or not resolved_path.exists():
        console.print("[red]QuickCapture database not found.[/red]")
        console.print("Provide a path argument or set snr.qc_db_path in ~/.qi/config.toml")
        raise typer.Exit(1)

    # Parse date range options
    start_date: date | None = None
    end_date: date | None = None
    since_days: int | None = None

    if week:
        week_date = _parse_date_or_exit(week, "--week")
        start_date, end_date = get_week_bounds(week_date)
        console.print(f"[cyan]Importing week: {start_date} to {end_date}[/cyan]")
    elif since:
        if since.endswith("d"):
            try:
                since_days = int(since[:-1])
                console.print(f"[cyan]Importing last {since_days} days[/cyan]")
            except ValueError:
                console.print(f"[red]Invalid --since format: {since}. Use e.g., '7d'[/red]")
                raise typer.Exit(1)
        else:
            console.print(f"[red]Invalid --since format: {since}. Use e.g., '7d'[/red]")
            raise typer.Exit(1)
    elif start or end:
        if start:
            start_date = _parse_date_or_exit(start, "--start")
        if end:
            end_date = _parse_date_or_exit(end, "--end")
        if start_date and end_date:
            console.print(f"[cyan]Importing range: {start_date} to {end_date}[/cyan]")
        elif start_date:
            console.print(f"[cyan]Importing from: {start_date}[/cyan]")
        elif end_date:
            console.print(f"[cyan]Importing until: {end_date}[/cyan]")
    else:
        console.print("[cyan]Importing all notes (no date filter)[/cyan]")

    try:
        imported, skipped = import_from_qc_db(
            resolved_path,
            start_date=start_date,
            end_date=end_date,
            since_days=since_days,
        )
        console.print(f"\n[green]Import complete![/green]")
        console.print(f"  Imported: {imported}")
        console.print(f"  Skipped: {skipped}")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command()
def process():
    """Process imported notes with heuristic classifier."""
    from qi.processing.heuristics import process_unprocessed_notes

    console.print("[cyan]Processing unprocessed notes...[/cyan]")
    processed, events_created = process_unprocessed_notes()
    
    console.print(f"\n[green]Processing complete![/green]")
    console.print(f"  Notes processed: {processed}")
    console.print(f"  Events created: {events_created}")


@app.command()
def eod(
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Date to process (YYYY-MM-DD), default today"),
    sync: bool = typer.Option(False, "--sync", help="Import from QC DB + heuristic process before EOD relevance"),
    db_path: Optional[Path] = typer.Option(None, "--db-path", help="QC DB path (for --sync, uses config if not provided)"),
):
    """Run end-of-day relevance and digest batch."""
    from qi.processing.eod import run_eod_batch

    target_date = date.today()
    if date_str:
        target_date = _parse_date_or_exit(date_str, "--date")

    if sync:
        _run_sync_pipeline(
            range_label="date",
            start_date=target_date,
            end_date=target_date,
            db_path=db_path,
            run_eod=False,
        )

    console.print("[cyan]Running EOD relevance batch...[/cyan]")
    result = run_eod_batch(target_date=target_date)
    console.print("\n[green]EOD batch complete![/green]")
    console.print(f"  Items processed: {result.processed}")
    console.print(f"  Relevant items: {result.relevant}")
    console.print(f"  Errors: {result.errors}")
    if result.error_messages:
        for message in result.error_messages[:5]:
            console.print(f"  [yellow]- {message}[/yellow]")


@app.command()
def week(
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Date within target week (YYYY-MM-DD)"),
):
    """Interactive weekly retrospective."""
    from qi.capture.weekly import prompt_weekly_retro
    from qi.db import save_weekly_retro

    # Parse date
    target_date = None
    if date_str:
        target_date = _parse_date_or_exit(date_str, "--date")

    retro = prompt_weekly_retro(target_date)
    save_weekly_retro(retro)
    console.print(f"\n[green]Weekly retro saved for week of {retro.week_start}[/green]")


@app.command()
def stats(
    tokens: bool = typer.Option(False, "--tokens", help="Show token aggregates"),
    days: int = typer.Option(7, "--days", "-d", help="Number of days to analyze"),
):
    """Show trend statistics."""
    from qi.processing.features import compute_features
    from qi.utils.time import get_n_days_ago

    end_date = date.today()
    start_date = get_n_days_ago(days - 1, end_date)

    features = compute_features(start_date, end_date)

    # Create stats table
    table = Table(title=f"Stats for last {days} days")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    # Core metrics
    if features.get("energy_mean") is not None:
        table.add_row("Energy (mean)", f"{features['energy_mean']:.1f}")
    if features.get("mood_mean") is not None:
        table.add_row("Mood (mean)", f"{features['mood_mean']:.1f}")
    if features.get("sleep_mean") is not None:
        table.add_row("Sleep (mean)", f"{features['sleep_mean']:.1f}")

    table.add_row("DCI streak", str(features.get("dci_streak", 0)))
    if features.get("habit_streak", 0) > 0:
        table.add_row("Habit streak", str(features.get("habit_streak", 0)))

    # Event counts
    table.add_row("Wins", str(features.get("win_count", 0)))
    table.add_row("Frictions", str(features.get("friction_count", 0)))
    table.add_row("Insights", str(features.get("insight_count", 0)))

    if tokens:
        table.add_section()
        added = False
        for k, v in features.items():
            if k.endswith("_total"):
                table.add_row(f"{k.replace('_total', '')} (total)", str(v))
                added = True
            elif k.endswith("_rate"):
                table.add_row(f"{k.replace('_rate', '')} (rate)", f"{v:.0%}")
                added = True
            elif k.endswith("_count") and k not in ("win_count", "friction_count", "insight_count", "compulsion_event_count", "dci_count", "event_count"):
                table.add_row(f"{k.replace('_count', '')} (count)", str(v))
                added = True
        
        if not added:
            table.add_row("Custom metrics", "None tracked")

    console.print(table)


@app.command()
def residuals():
    """Show residual items from the most recent DCI."""
    items = get_latest_residual()
    if not items:
        console.print("[dim]No residual items.[/dim]")
        return
    for i, item in enumerate(items, 1):
        console.print(f"  {i}. {item}")


@app.command()
def export(
    format: str = typer.Option("jsonl", "--format", "-f", help="Export format (jsonl)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Export all data for backup."""
    from qi.db import get_db

    if format != "jsonl":
        console.print(f"[red]Unsupported format: {format}. Use 'jsonl'[/red]")
        raise typer.Exit(1)

    console.print("[yellow]WARNING: This export contains highly sensitive personal data (mood, energy, notes, custom metrics).[/yellow]")
    console.print("[yellow]Do not share this file or sync it to public cloud storage without encryption.[/yellow]")

    if output is None:
        output = Path(f"qi_export_{date.today().isoformat()}.jsonl")

    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        with open(output, "w", encoding="utf-8") as f:
            for table in EXPORT_TABLES:
                try:
                    if table not in EXPORT_TABLES:
                        raise ValueError(f"Unsupported table: {table}")
                    if table == "dci":
                        cursor = conn.execute("SELECT * FROM dci")
                        for row in cursor:
                            dci = _row_to_dci(row)
                            record = {
                                "id": row["id"],
                                "date": dci.date.isoformat(),
                                "created_at": row["created_at"],
                                "energy": dci.energy,
                                "mood": dci.mood,
                                "sleep": dci.sleep,
                                "primary_focus": dci.primary_focus,
                                "one_win": dci.one_win,
                                "one_friction": dci.one_friction,
                                "comment": dci.comment,
                                "residual": dci.residual,
                                "metrics": dci.metrics,
                                "_table": "dci",
                            }
                            if "relevance_processed" in row.keys():
                                record["relevance_processed"] = row["relevance_processed"]
                            f.write(json.dumps(record) + "\n")
                    else:
                        query = f'SELECT * FROM "{table}"'
                        cursor = conn.execute(query)
                        columns = [desc[0] for desc in cursor.description]
                        for row in cursor:
                            record = dict(zip(columns, row))
                            record["_table"] = table
                            f.write(json.dumps(record) + "\n")
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not export {table}: {e}[/yellow]")

    console.print(f"[green]Exported to {output}[/green]")


@app.command()
def version():
    """Show version information."""
    console.print(f"QI version {__version__}")


# Principles subcommand group
principles_app = typer.Typer(help="Manage guiding principles and KRs")
app.add_typer(principles_app, name="principles")


@principles_app.command("edit")
def principles_edit():
    """Open principles markdown in your editor."""
    config = load_config()
    principles_path, created = ensure_principles_file(config)

    if created:
        console.print(f"[green]Created[/green] {principles_path}")

    edited = typer.edit(filename=str(principles_path))
    if edited is None:
        console.print(f"[dim]No changes saved.[/dim] {principles_path}")
        return

    console.print(f"[green]Updated[/green] {principles_path}")


# Report subcommand group
report_app = typer.Typer(help="Generate reports")
app.add_typer(report_app, name="report")


@report_app.command("weekly")
def report_weekly(
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Date within target week"),
    sync: bool = typer.Option(False, "--sync", help="Import from QC DB + process before report"),
    db_path: Optional[Path] = typer.Option(None, "--db-path", help="QC DB path (for --sync, uses config if not provided)"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Disable LLM narrative synthesis for this run"),
    force: bool = typer.Option(False, "--force", help="Regenerate report even if one exists for the window"),
):
    """Generate weekly digest report."""
    from qi.reporting.weekly import generate_weekly_digest
    from qi.utils.time import get_week_bounds

    target_date = None
    if date_str:
        target_date = _parse_date_or_exit(date_str, "--date")

    # Sync: import + process before generating report
    if sync:
        week_start, week_end = get_week_bounds(target_date)
        _run_sync_pipeline(
            range_label="week",
            start_date=week_start,
            end_date=week_end,
            db_path=db_path,
            run_eod=True,
        )

    try:
        report = generate_weekly_digest(target_date, force_disable_llm=no_llm, force_regenerate=force)
    except Exception as exc:  # noqa: BLE001
        from qi.db import ReadinessError
        if isinstance(exc, ReadinessError):
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        raise
    llm_meta = report.output_json.get("llm", {})
    if llm_meta.get("error"):
        console.print(f"[yellow]LLM narrative skipped: {llm_meta['error']}[/yellow]")
    console.print(report.rendered_markdown)


@report_app.command("monthly")
def report_monthly(
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Date within target month"),
    sync: bool = typer.Option(False, "--sync", help="Import from QC DB + process before report"),
    db_path: Optional[Path] = typer.Option(None, "--db-path", help="QC DB path (for --sync, uses config if not provided)"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Disable LLM narrative synthesis for this run"),
    force: bool = typer.Option(False, "--force", help="Regenerate report even if one exists for the window"),
):
    """Generate monthly dossier report."""
    from qi.reporting.monthly import generate_monthly_dossier
    from qi.utils.time import get_month_bounds

    target_date = None
    if date_str:
        target_date = _parse_date_or_exit(date_str, "--date")

    # Sync: import + process before generating report
    if sync:
        month_start, month_end = get_month_bounds(target_date)
        _run_sync_pipeline(
            range_label="month",
            start_date=month_start,
            end_date=month_end,
            db_path=db_path,
            run_eod=True,
        )

    try:
        report = generate_monthly_dossier(target_date, force_disable_llm=no_llm, force_regenerate=force)
    except Exception as exc:  # noqa: BLE001
        from qi.db import ReadinessError
        if isinstance(exc, ReadinessError):
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        raise
    llm_meta = report.output_json.get("llm", {})
    if llm_meta.get("error"):
        console.print(f"[yellow]LLM narrative skipped: {llm_meta['error']}[/yellow]")
    console.print(report.rendered_markdown)


if __name__ == "__main__":
    app()
