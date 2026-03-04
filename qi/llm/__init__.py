"""LLM utilities for report narrative synthesis."""

from qi.llm.client import LLMClientError, OllamaClient
from qi.llm.prompts import PromptPackage, build_report_prompts
from qi.llm.render import render_narrative_markdown
from qi.llm.synthesis import synthesize_report_narrative
from qi.llm.validate import NarrativeSynthesisResult, synthesize_with_validation

__all__ = [
    "LLMClientError",
    "NarrativeSynthesisResult",
    "OllamaClient",
    "PromptPackage",
    "build_report_prompts",
    "render_narrative_markdown",
    "synthesize_report_narrative",
    "synthesize_with_validation",
]
