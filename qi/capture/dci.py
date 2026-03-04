"""Interactive DCI (Daily Check-In) capture."""

from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt

from qi.db import get_latest_residual
from qi.models import DCI

console = Console()


def prompt_float(prompt_text: str, default: float | None = None) -> float:
    """Prompt for a float value."""
    while True:
        try:
            if default is not None:
                value = FloatPrompt.ask(prompt_text, default=default)
            else:
                value = FloatPrompt.ask(prompt_text)
            if 0 <= value <= 10:
                return value
            console.print("[red]Please enter a value between 0 and 10[/red]")
        except ValueError:
            console.print("[red]Please enter a valid number[/red]")


def prompt_optional_str(prompt_text: str) -> str | None:
    """Prompt for an optional string (Enter to skip)."""
    value = Prompt.ask(f"{prompt_text} [dim](Enter to skip)[/dim]", default="")
    return value if value.strip() else None


def prompt_bool(prompt_text: str, default: bool = False) -> bool:
    """Prompt for a boolean value."""
    return Confirm.ask(prompt_text, default=default)


def prompt_int(prompt_text: str, default: int = 0) -> int:
    """Prompt for an integer value."""
    return IntPrompt.ask(prompt_text, default=default)


def prompt_dci_quick(target_date: date | None = None) -> DCI:
    """Quick DCI capture - only core metrics."""
    if target_date is None:
        target_date = date.today()

    console.print(Panel(f"[bold]Quick DCI for {target_date}[/bold]", style="cyan"))

    console.print("\n[bold cyan][1/1] Core Metrics[/bold cyan]")
    energy = prompt_float("  Energy (0-10)")
    mood = prompt_float("  Mood (0-10)")
    sleep = prompt_float("  Sleep (0-10)")

    dci = DCI(
        date=target_date,
        energy=energy,
        mood=mood,
        sleep=sleep,
    )

    return dci


def prompt_dci(target_date: date | None = None) -> DCI:
    """Full interactive DCI capture with stepped prompts."""
    if target_date is None:
        target_date = date.today()

    console.print(Panel(f"[bold]Daily Check-In for {target_date}[/bold]", style="cyan"))

    # Get residual from previous day
    prev_residual = get_latest_residual()

    # Section 1: Core Metrics
    console.print("\n[bold cyan][1/4] Core Metrics[/bold cyan]")
    energy = prompt_float("  Energy (0-10)")
    mood = prompt_float("  Mood (0-10)")
    sleep = prompt_float("  Sleep (0-10)")

    # Section 2: Focus & Reflection
    console.print("\n[bold cyan][2/3] Focus & Reflection[/bold cyan]")
    primary_focus = prompt_optional_str("  Primary focus today")
    one_win = prompt_optional_str("  One win")
    one_friction = prompt_optional_str("  One friction")
    comment = prompt_optional_str("  Any additional comment")

    # Section 3: Dynamic Metrics
    console.print("\n[bold cyan][3/3] Custom Metrics[/bold cyan]")
    skip_metrics = not prompt_bool("  Log custom metrics?", default=True)

    metrics = {}

    from qi.config import load_config
    config = load_config()
    dci_metrics = config.get("dci_metrics", {})

    if not skip_metrics:
        # Ask for dynamic metrics based on config
        for key, metric_def in dci_metrics.items():
            # Skip conditional metrics if the parent wasn't truthy
            cond_parent = metric_def.get("conditional_on")
            if cond_parent and not metrics.get(cond_parent):
                metrics[key] = None
                continue
            
            label_name = metric_def.get("label", key)
            label = f"  {key} ({label_name})"
            if metric_def["type"] == "bool":
                metrics[key] = prompt_bool(label + "?", default=False)
            elif metric_def["type"] == "int":
                metrics[key] = prompt_int(label, default=0)
            elif metric_def["type"] == "float":
                metrics[key] = prompt_float(label, default=0)
            elif metric_def["type"] == "str":
                val = prompt_optional_str(label)
                metrics[key] = val if val else None
    else:
        # Preserve "not logged" as explicit None instead of conflating with 0/False.
        for key, metric_def in dci_metrics.items():
            if metric_def.get("type") in {"bool", "int", "float", "str"}:
                metrics[key] = None

    # Handle residual
    residual: list[str] = []
    if prev_residual:
        console.print(f"\n[dim]Previous residual: {prev_residual}[/dim]")
        keep_residual = prompt_bool("  Keep previous residual?", default=True)
        if keep_residual:
            residual = prev_residual.copy()

    new_residual = prompt_optional_str("  Add new residual items (comma-separated)")
    if new_residual:
        residual.extend([r.strip() for r in new_residual.split(",") if r.strip()])

    # Create DCI
    dci = DCI(
        date=target_date,
        energy=energy,
        mood=mood,
        sleep=sleep,
        primary_focus=primary_focus,
        one_win=one_win,
        one_friction=one_friction,
        comment=comment,
        metrics=metrics,
        residual=residual,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="Ready to save DCI...", total=None)

    return dci
