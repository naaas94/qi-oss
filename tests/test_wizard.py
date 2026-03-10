"""Tests for the setup wizard module."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import qi.config as config_module
from qi.config import DEFAULT_CONFIG
from qi.wizard import (
    _step_data_sources,
    _step_dependencies,
    _step_metrics,
    _step_principles,
    _step_prompt_persona,
    _step_usage,
    _strip_code_fences,
    _valid_toml_key,
    run_wizard,
)


@pytest.fixture()
def wizard_home(monkeypatch, tmp_path):
    qi_home = tmp_path / ".qi"
    qi_home.mkdir()
    monkeypatch.setattr(config_module, "QI_HOME", qi_home)
    monkeypatch.setattr(config_module, "QI_DB_PATH", qi_home / "qi.db")
    monkeypatch.setattr(config_module, "QI_CONFIG_PATH", qi_home / "config.toml")
    monkeypatch.setattr(config_module, "QI_PRINCIPLES_PATH", qi_home / "principles.md")
    if hasattr(config_module.load_config, "cache_clear"):
        config_module.load_config.cache_clear()
    return qi_home


# ── Helpers ─────────────────────────────────────────────────────────────


class TestValidTomlKey:
    def test_valid_keys(self):
        assert _valid_toml_key("training_done")
        assert _valid_toml_key("habit_1")
        assert _valid_toml_key("_private")

    def test_invalid_keys(self):
        assert not _valid_toml_key("has space")
        assert not _valid_toml_key("1starts_with_digit")
        assert not _valid_toml_key("")
        assert not _valid_toml_key("has-dash")


class TestStripCodeFences:
    def test_strips_leading_and_trailing(self):
        text = "```markdown\n# Heading\nBody\n```"
        assert _strip_code_fences(text) == "# Heading\nBody"

    def test_returns_clean_text_unchanged(self):
        assert _strip_code_fences("# Heading\nBody") == "# Heading\nBody"


# ── Step 1: Dependencies ───────────────────────────────────────────────


class TestStepDependencies:
    def test_disable_llm(self, wizard_home):
        console = MagicMock()
        console.input.return_value = ""
        config = copy.deepcopy(DEFAULT_CONFIG)
        with patch("qi.wizard._confirm", return_value=False):
            _step_dependencies(console, config)
        assert config["llm-report"]["enabled"] is False
        assert config["llm-eod"]["enabled"] is False

    def test_enable_llm_no_ollama(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with (
            patch("qi.wizard._confirm", return_value=True),
            patch("qi.wizard._fetch_ollama_models", return_value=None),
        ):
            _step_dependencies(console, config)
        assert config["llm-report"]["enabled"] is True

    def test_enable_llm_with_models(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with (
            patch("qi.wizard._confirm", return_value=True),
            patch("qi.wizard._fetch_ollama_models", return_value=["llama3:8b", "qwen3:30b"]),
            patch("qi.wizard._pick_model", side_effect=["qwen3:30b", "llama3:8b"]),
        ):
            _step_dependencies(console, config)
        assert config["llm-report"]["model"] == "qwen3:30b"
        assert config["llm-eod"]["model"] == "llama3:8b"


# ── Step 2: Data sources ──────────────────────────────────────────────


class TestStepDataSources:
    def test_skip(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with patch("qi.wizard._menu", return_value="skip"):
            _step_data_sources(console, config)
        assert config["snr"]["qc_db_path"] == ""

    def test_set_qc_path(self, wizard_home, tmp_path):
        db_file = tmp_path / "qc.db"
        db_file.touch()
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with (
            patch("qi.wizard._menu", return_value="snr"),
            patch("qi.wizard._input", return_value=str(db_file)),
        ):
            _step_data_sources(console, config)
        assert config["snr"]["qc_db_path"] == str(db_file)


# ── Step 3: Metrics ───────────────────────────────────────────────────


class TestStepMetrics:
    def test_keep_defaults(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with (
            patch("qi.wizard._confirm", return_value=True),
            patch("qi.wizard._menu", return_value="done"),
        ):
            _step_metrics(console, config)
        assert "habit_1" in config["dci_metrics"]

    def test_add_metric_directly(self, wizard_home):
        """Test the _add_metric helper with mocked inputs."""
        from qi.wizard import _add_metric

        console = MagicMock()
        metrics: dict[str, Any] = {}
        menu_calls = iter(["bool", "count"])
        with (
            patch("qi.wizard._input", side_effect=["training_done", "Training done?"]),
            patch("qi.wizard._menu", side_effect=lambda *a, **kw: next(menu_calls)),
        ):
            _add_metric(console, metrics)
        assert "training_done" in metrics
        assert metrics["training_done"]["type"] == "bool"
        assert metrics["training_done"]["aggregate"] == "count"


# ── Step 4: Principles ────────────────────────────────────────────────


class TestStepPrinciples:
    def test_keep_template(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with patch("qi.wizard._menu", return_value="keep"):
            _step_principles(console, config)
        assert (wizard_home / "principles.md").exists()

    def test_edit_choice(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with (
            patch("qi.wizard._menu", return_value="edit"),
            patch("qi.wizard.typer.edit") as mock_edit,
        ):
            _step_principles(console, config)
        mock_edit.assert_called_once()


# ── Step 5: Usage ─────────────────────────────────────────────────────


class TestStepUsage:
    def test_produces_next_steps(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with patch("qi.wizard._menu", return_value="weekly"):
            _step_usage(console, config)
        console.print.assert_any_call("  Run [bold]qi dci[/bold] daily.")


# ── Step 6: Prompt persona ────────────────────────────────────────────


class TestStepPromptPersona:
    def test_skip_customization(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        with patch("qi.wizard._confirm", return_value=False):
            _step_prompt_persona(console, config)
        assert config["prompt_preferences"]["persona"] == "analyst"

    def test_set_persona_and_tone(self, wizard_home):
        console = MagicMock()
        config = copy.deepcopy(DEFAULT_CONFIG)
        confirm_calls = iter([True, False])
        menu_calls = iter(["coach", "supportive", "moderate"])
        with (
            patch("qi.wizard._confirm", side_effect=lambda *a, **kw: next(confirm_calls)),
            patch("qi.wizard._menu", side_effect=lambda *a, **kw: next(menu_calls)),
        ):
            _step_prompt_persona(console, config)
        assert config["prompt_preferences"]["persona"] == "coach"
        assert config["prompt_preferences"]["tone"] == "supportive"
        assert config["prompt_preferences"]["strictness"] == "moderate"


# ── Full wizard (integration) ─────────────────────────────────────────


class TestRunWizard:
    def test_full_wizard_minimal_options(self, wizard_home, monkeypatch):
        """Wizard should create config.toml and principles.md with minimal choices."""
        console = MagicMock()

        monkeypatch.setattr("qi.wizard.init_db", lambda: (True, 0))

        with (
            patch("qi.wizard._step_dependencies"),
            patch("qi.wizard._step_data_sources"),
            patch("qi.wizard._step_metrics"),
            patch("qi.wizard._step_principles"),
            patch("qi.wizard._step_usage"),
            patch("qi.wizard._step_prompt_persona"),
        ):
            run_wizard(console)

        assert (wizard_home / "config.toml").exists()
