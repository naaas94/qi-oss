"""Markdown rendering for LLM narrative sections."""

from __future__ import annotations

from qi.llm.schema import NarrativeOutput


def render_narrative_markdown(
    narrative: NarrativeOutput,
    title: str = "LLM Narrative",
    principle_names: dict[int, str] | None = None,
) -> str:
    """Render validated narrative output as markdown."""
    lines = [
        f"## {title}",
        "",
        "### Summary",
        narrative.weekly_summary,
        "",
        "### Delta Narrative",
        narrative.delta_narrative,
        "",
        "### Principle Alignment",
    ]

    if narrative.principle_alignment:
        for item in narrative.principle_alignment:
            name = (
                principle_names.get(item.principle_id, f"Principle {item.principle_id}")
                if principle_names
                else f"Principle {item.principle_id}"
            )
            lines.append(f"- {name} ({item.status}): {item.note}")
    else:
        lines.append("- No principle alignment data.")

    lines.extend(
        [
            "",
            "### KR Progress",
        ]
    )
    if narrative.kr_progress:
        for item in narrative.kr_progress:
            lines.append(f"- {item.kr}: {item.assessment}")
    else:
        lines.append("- No KR progress data.")

    lines.extend(
        [
            "",
            "### Coaching Focus",
            narrative.coaching_focus,
            "",
            "### Next Experiment",
            narrative.next_experiment,
            "",
            "### Risks",
        ]
    )
    if narrative.risks:
        for risk in narrative.risks:
            lines.append(f"- {risk}")
    else:
        lines.append("- No explicit risks identified.")

    lines.extend(
        [
            "",
            f"### Confidence\n{narrative.confidence:.2f}",
            "",
        ]
    )
    return "\n".join(lines)
