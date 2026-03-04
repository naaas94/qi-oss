"""Weekly digest report generation."""

from datetime import date

from qi.config import ensure_principles_file, load_config
from qi.db import (
    check_db_writable,
    delete_artifact_for_window,
    get_artifact_for_window,
    get_dci_range,
    get_events_in_range,
    get_relevance_digests_in_range,
    link_llm_runs_to_artifact,
    save_artifact,
)
from qi.llm.synthesis import synthesize_report_narrative
from qi.models import Artifact
from qi.processing.features import compute_daily_series, compute_delta, compute_features
from qi.reporting.render import (
    render_header,
    render_metrics_table,
    render_events_section,
    render_tokens_section,
    render_delta_section,
    render_streak_section,
    render_footer,
    digests_to_dicts,
)
from qi.utils.time import get_week_bounds, get_previous_week_bounds


def generate_weekly_digest(
    target_date: date | None = None,
    force_disable_llm: bool = False,
    force_regenerate: bool = False,
) -> Artifact:
    """Generate weekly digest report."""
    check_db_writable()
    ensure_principles_file(load_config())
    week_start, week_end = get_week_bounds(target_date)
    
    # Idempotency guard (skip when --force)
    existing_artifact = get_artifact_for_window("weekly_digest", week_start, week_end)
    if existing_artifact:
        if force_regenerate:
            delete_artifact_for_window("weekly_digest", week_start, week_end)
        else:
            from rich.console import Console
            Console().print(f"[yellow]Warning: Weekly digest for {week_start} already exists. Returning existing artifact.[/yellow]")
            return existing_artifact

    prev_start, prev_end = get_previous_week_bounds(target_date)
    
    # Fetch once to avoid duplicate DCI/event queries in report generation.
    dcis = get_dci_range(week_start, week_end)
    events = get_events_in_range(week_start, week_end)
    previous_dcis = get_dci_range(prev_start, prev_end)
    previous_events = get_events_in_range(prev_start, prev_end)

    # Compute features for current and previous week
    current_features = compute_features(week_start, week_end, dcis=dcis, events=events)
    previous_features = compute_features(
        prev_start,
        prev_end,
        dcis=previous_dcis,
        events=previous_events,
    )
    
    # Compute deltas
    deltas = compute_delta(current_features, previous_features)
    daily_series = compute_daily_series(week_start, week_end, dcis=dcis)
    digest_models = get_relevance_digests_in_range(week_start, week_end)
    digests = digests_to_dicts(digest_models)
    
    # Get input data for snapshot
    input_snapshot = {
        "dci_count": len(dcis),
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
    }
    
    # Render deterministic markdown sections
    md_parts = [
        render_header("Weekly Digest", week_start, week_end),
        render_metrics_table(current_features),
        render_events_section(current_features),
        render_tokens_section(current_features),
        render_delta_section(deltas),
        render_streak_section(current_features),
    ]

    llm_markdown, llm_metadata = synthesize_report_narrative(
        report_type="weekly_digest",
        window_start=week_start,
        window_end=week_end,
        input_snapshot=input_snapshot,
        features_snapshot=current_features,
        analysis_snapshot={"deltas": deltas},
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
        artifact_type="weekly_digest",
        window_start=week_start,
        window_end=week_end,
        input_snapshot=input_snapshot,
        features_snapshot=current_features,
        output_json={"deltas": deltas, "llm": llm_metadata},
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
