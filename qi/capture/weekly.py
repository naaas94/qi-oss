"""Interactive weekly retrospective capture."""

from datetime import date

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt

from qi.models import OneChange, WeeklyRetro
from qi.utils.time import get_week_bounds

console = Console()


def prompt_list(prompt_text: str, min_items: int = 1, max_items: int = 5) -> list[str]:
    """Prompt for a list of items."""
    items = []
    console.print(f"[dim]Enter up to {max_items} items (Enter empty to stop)[/dim]")

    while len(items) < max_items:
        item_number = len(items) + 1
        required = len(items) < min_items

        if required:
            item = Prompt.ask(f"  {prompt_text} {item_number}")
        else:
            item = Prompt.ask(
                f"  {prompt_text} {item_number} [dim](Enter to skip)[/dim]",
                default="",
            )

        item = item.strip()
        if not item:
            if required:
                console.print(f"[yellow]Please enter at least {min_items} item(s)[/yellow]")
                continue
            break

        items.append(item)

    return items


def prompt_scoreboard() -> dict[str, int | float]:
    """Prompt for weekly scoreboard values."""
    console.print("\n[bold]Scoreboard[/bold] [dim](Enter values for the week)[/dim]")
    scoreboard: dict[str, int | float] = {}
    while True:
        name = Prompt.ask("  Metric name [dim](e.g. habit_days, focus_blocks; Enter to finish)[/dim]", default="")
        if not name or not name.strip():
            if not scoreboard:
                console.print("[yellow]Enter at least one metric.[/yellow]")
                continue
            break
        name = name.strip().replace(" ", "_").lower() or "metric"
        value = IntPrompt.ask(f"    {name}", default=0)
        scoreboard[name] = value
    return scoreboard


def prompt_minimums() -> dict[str, int | float]:
    """Prompt for weekly minimum targets."""
    console.print("\n[bold]Minimums for next week[/bold] [dim](Enter target for each metric)[/dim]")
    minimums: dict[str, int | float] = {}
    while True:
        name = Prompt.ask("  Metric name [dim](Enter to finish)[/dim]", default="")
        if not name or not name.strip():
            break
        name = name.strip().replace(" ", "_").lower() or "metric"
        value = IntPrompt.ask(f"    Min {name}", default=0)
        minimums[name] = value
    return minimums


def prompt_one_change() -> OneChange:
    """Prompt for the one change commitment."""
    console.print("\n[bold]One Change[/bold] [dim](your commitment for next week)[/dim]")
    
    title = Prompt.ask("  What is the one change?")
    mechanism = Prompt.ask("  How will you implement it?")
    measurement = Prompt.ask("  How will you measure success?")
    
    return OneChange(title=title, mechanism=mechanism, measurement=measurement)


def prompt_weekly_retro(week_date: date | None = None) -> WeeklyRetro:
    """Full interactive weekly retrospective."""
    week_start, week_end = get_week_bounds(week_date)
    
    console.print(Panel(
        f"[bold]Weekly Retrospective[/bold]\n"
        f"Week of {week_start} to {week_end}",
        style="cyan"
    ))
    
    # Scoreboard
    scoreboard = prompt_scoreboard()
    
    # Wins
    console.print("\n[bold cyan]Wins[/bold cyan]")
    wins = prompt_list("Win", min_items=1, max_items=5)
    
    # Frictions
    console.print("\n[bold cyan]Frictions[/bold cyan]")
    frictions = prompt_list("Friction", min_items=1, max_items=5)
    
    # Root cause
    console.print("\n[bold cyan]Root Cause Analysis[/bold cyan]")
    root_cause = Prompt.ask("  What was the root cause of main friction?", default="")
    root_cause = root_cause if root_cause else None
    
    # One change
    one_change = prompt_one_change()
    
    # Minimums
    minimums = prompt_minimums()
    
    # Previous commitment check
    console.print("\n[bold cyan]Previous Commitment[/bold cyan]")
    had_commitment = Confirm.ask("  Did you have a commitment from last week?", default=False)
    commitment_met = None
    if had_commitment:
        commitment_met = Confirm.ask("  Did you meet it?", default=False)
    
    retro = WeeklyRetro(
        week_start=week_start,
        scoreboard=scoreboard,
        wins=wins,
        frictions=frictions,
        root_cause=root_cause,
        one_change=one_change,
        minimums=minimums,
        commitment_met=commitment_met,
    )
    
    return retro
