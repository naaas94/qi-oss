"""Monthly dossier report generation."""

from datetime import date

from qi.config import ensure_principles_file, load_config
from qi.db import (
    check_db_writable,
    delete_artifact_for_window,
    get_artifact_for_window,
    get_dci_range,
    get_events_in_range,
    get_relevance_digests_in_range,
    get_weekly_retros_in_range,
    link_llm_runs_to_artifact,
    save_artifact,
)
from qi.llm.synthesis import synthesize_report_narrative
from qi.models import Artifact
from qi.processing.features import compute_daily_series, compute_features, get_trend
from qi.reporting.render import (
    render_header,
    render_metrics_table,
    render_events_section,
    render_tokens_section,
    render_streak_section,
    render_footer,
    digests_to_dicts,
)
from qi.utils.time import get_month_bounds


def generate_monthly_dossier(
    target_date: date | None = None,
    force_disable_llm: bool = False,
    force_regenerate: bool = False,
) -> Artifact:
    """Generate monthly dossier report."""
    check_db_writable()
    ensure_principles_file(load_config())
    month_start, month_end = get_month_bounds(target_date)
    
    # Idempotency guard (skip when --force)
    existing_artifact = get_artifact_for_window("monthly_dossier", month_start, month_end)
    if existing_artifact:
        if force_regenerate:
            delete_artifact_for_window("monthly_dossier", month_start, month_end)
        else:
            from rich.console import Console
            Console().print(f"[yellow]Warning: Monthly dossier for {month_start.strftime('%B %Y')} already exists. Returning existing artifact.[/yellow]")
            return existing_artifact

    dcis = get_dci_range(month_start, month_end)
    events = get_events_in_range(month_start, month_end)
    # Compute features for the month
    features = compute_features(month_start, month_end, dcis=dcis, events=events)
    daily_series = compute_daily_series(month_start, month_end, dcis=dcis)
    digest_models = get_relevance_digests_in_range(month_start, month_end)
    digests = digests_to_dicts(digest_models)
    
    # Compute trends
    trends = {}
    if dcis:
        energies = [d.energy for d in dcis]
        moods = [d.mood for d in dcis]
        sleeps = [d.sleep for d in dcis]
        
        trends["energy_trend"] = get_trend(energies)
        trends["mood_trend"] = get_trend(moods)
        trends["sleep_trend"] = get_trend(sleeps)
    
    # Get weekly retros
    retros = get_weekly_retros_in_range(month_start, month_end)
    
    # Input snapshot
    input_snapshot = {
        "dci_count": len(dcis),
        "retro_count": len(retros),
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
    }
    
    # Render deterministic markdown sections
    md_parts = [
        render_header("Monthly Dossier", month_start, month_end),
        render_metrics_table(features),
        _render_trends_section(trends),
        render_events_section(features),
        render_tokens_section(features),
        _render_retros_summary(retros),
        render_streak_section(features),
    ]

    llm_markdown, llm_metadata = synthesize_report_narrative(
        report_type="monthly_dossier",
        window_start=month_start,
        window_end=month_end,
        input_snapshot=input_snapshot,
        features_snapshot=features,
        analysis_snapshot={"trends": trends},
        daily_series=daily_series,
        digests=digests,
        force_disable=force_disable_llm,
    )
    if llm_markdown:
        md_parts.append(llm_markdown)
    md_parts.append(render_footer())
    rendered_markdown = "\n".join(md_parts)
    
    # Create artifact
    artifact = Artifact(
        artifact_type="monthly_dossier",
        window_start=month_start,
        window_end=month_end,
        input_snapshot=input_snapshot,
        features_snapshot=features,
        output_json={"trends": trends, "llm": llm_metadata},
        rendered_markdown=rendered_markdown,
        prompt_version=llm_metadata.get("prompt_version"),
        model_id=llm_metadata.get("model_id"),
    )
    
    # Save artifact and link llm_runs to artifact
    artifact_id = save_artifact(artifact)
    run_ids = llm_metadata.get("llm_run_ids", [])
    if isinstance(run_ids, list):
        link_llm_runs_to_artifact(run_ids, artifact_id)
    
    return artifact


def _render_trends_section(trends: dict) -> str:
    """Render trends section."""
    lines = [
        "## Trends",
        "",
    ]
    
    trend_labels = {
        "energy_trend": "Energy",
        "mood_trend": "Mood",
        "sleep_trend": "Sleep",
    }
    
    for key, label in trend_labels.items():
        value = trends.get(key, "insufficient_data")
        emoji = _get_trend_emoji(value)
        lines.append(f"- {label}: {value} {emoji}")
    
    lines.append("")
    return "\n".join(lines)


def _get_trend_emoji(trend: str) -> str:
    """Get emoji for trend."""
    return {
        "improving": "📈",
        "stable": "➡️",
        "declining": "📉",
        "insufficient_data": "❓",
    }.get(trend, "")


def _render_retros_summary(retros: list) -> str:
    """Render weekly retros summary."""
    if not retros:
        return "## Weekly Retros\n\nNo weekly retros recorded this month.\n"
    
    lines = [
        "## Weekly Retros",
        "",
        f"Total retros: {len(retros)}",
        "",
    ]
    
    # Aggregate wins and frictions
    all_wins = []
    all_frictions = []
    commitments_met = 0
    commitments_total = 0
    
    for retro in retros:
        all_wins.extend(retro.wins)
        all_frictions.extend(retro.frictions)
        if retro.commitment_met is not None:
            commitments_total += 1
            if retro.commitment_met:
                commitments_met += 1
    
    lines.append(f"- Total wins recorded: {len(all_wins)}")
    lines.append(f"- Total frictions recorded: {len(all_frictions)}")
    if commitments_total > 0:
        lines.append(f"- Commitments met: {commitments_met}/{commitments_total}")
    
    lines.append("")
    return "\n".join(lines)
