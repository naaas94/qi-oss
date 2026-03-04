"""Tests for configuration management."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from qi import config as config_module


@pytest.fixture
def temp_config_home(monkeypatch, tmp_path):
    """Point QI_HOME and related paths to a temp directory."""
    qi_home = tmp_path / "qi_home"
    qi_home.mkdir()
    monkeypatch.setattr(config_module, "QI_HOME", qi_home)
    monkeypatch.setattr(config_module, "QI_DB_PATH", qi_home / "qi.db")
    monkeypatch.setattr(config_module, "QI_CONFIG_PATH", qi_home / "config.toml")
    monkeypatch.setattr(config_module, "QI_PRINCIPLES_PATH", qi_home / "principles.md")
    # Clear load_config cache so tests see patched paths
    if hasattr(config_module.load_config, "cache_clear"):
        config_module.load_config.cache_clear()
    yield qi_home


class TestLoadConfig:
    """Tests for load_config."""

    def test_missing_config_returns_defaults(self, temp_config_home):
        """When config.toml does not exist, load_config returns DEFAULT_CONFIG copy."""
        assert not (temp_config_home / "config.toml").exists()
        config = config_module.load_config()
        assert config is not None
        assert config["general"]["week_start_day"] == "monday"
        assert config["dci"]["quick_mode_fields"] == ["energy", "mood", "sleep"]
        assert config["llm"]["model"] == "qwen3:30b"
        assert config["llm"]["enabled"] is True
        assert "habit_1" in config["dci_metrics"]
        assert config["dci_metrics"]["habit_1"]["aggregate"] == "count"

    def test_existing_config_merges_with_defaults(self, temp_config_home):
        """Existing config.toml is merged with defaults (shallow merge per top-level key)."""
        config_toml = temp_config_home / "config.toml"
        config_toml.write_text(
            "[llm]\n"
            "model = \"custom:7b\"\n"
            "enabled = false\n",
            encoding="utf-8",
        )
        config_module.load_config.cache_clear()
        config = config_module.load_config()
        assert config["llm"]["model"] == "custom:7b"
        assert config["llm"]["enabled"] is False
        # Unmentioned keys still from defaults
        assert config["llm"]["base_url"] == "http://localhost:11434"
        assert config["general"]["week_start_day"] == "monday"

    def test_dci_metrics_structure_in_default(self, temp_config_home):
        """Default dci_metrics has expected keys and types."""
        config = config_module.load_config()
        dci_metrics = config["dci_metrics"]
        assert "habit_1" in dci_metrics
        assert dci_metrics["habit_1"]["type"] == "bool"
        assert dci_metrics["habit_2"]["aggregate"] == "count"
        assert dci_metrics["optional_note"]["type"] == "str"


class TestPaths:
    """Tests for path resolution."""

    def test_qi_db_path_under_qi_home(self, temp_config_home):
        """QI_DB_PATH is QI_HOME / qi.db."""
        assert config_module.QI_DB_PATH == temp_config_home / "qi.db"

    def test_qi_config_path_under_qi_home(self, temp_config_home):
        """QI_CONFIG_PATH is QI_HOME / config.toml."""
        assert config_module.QI_CONFIG_PATH == temp_config_home / "config.toml"


class TestEnsureQiHome:
    """Tests for ensure_qi_home."""

    def test_creates_directory(self, monkeypatch, tmp_path):
        """ensure_qi_home creates the directory if missing."""
        path = tmp_path / "nested" / "qi"
        assert not path.exists()
        monkeypatch.setattr(config_module, "QI_HOME", path)
        result = config_module.ensure_qi_home()
        assert result == path
        assert path.exists()
        assert path.is_dir()

    def test_idempotent_when_exists(self, temp_config_home):
        """ensure_qi_home returns QI_HOME when directory already exists."""
        result = config_module.ensure_qi_home()
        assert result == temp_config_home
        assert temp_config_home.exists()


class TestGetConfigValue:
    """Tests for get_config_value."""

    def test_dot_path_returns_value(self, temp_config_home):
        """get_config_value resolves dot-separated keys."""
        val = config_module.get_config_value("llm.model")
        assert val == "qwen3:30b"

    def test_missing_key_returns_default(self, temp_config_home):
        """get_config_value returns default for missing key."""
        assert config_module.get_config_value("nonexistent.key", "fallback") == "fallback"
        assert config_module.get_config_value("llm.missing_key", 42) == 42


class TestGetPrinciplesPath:
    """Tests for get_principles_path."""

    def test_relative_path_resolved_against_qi_home(self, temp_config_home):
        """Relative principles_path is resolved against QI_HOME."""
        path = config_module.get_principles_path(config_module.load_config())
        assert path == temp_config_home / "principles.md"

    def test_absolute_path_unchanged(self, temp_config_home):
        """Absolute principles_path in config is used as-is (expanduser only)."""
        config = config_module.load_config()
        config["llm"] = {**config["llm"], "principles_path": "/absolute/principles.md"}
        path = config_module.get_principles_path(config)
        assert path.is_absolute()
        assert path.name == "principles.md"
        assert "absolute" in str(path)


class TestParsePrincipleNames:
    """Tests for parse_principle_names."""

    def test_extracts_numbered_headers(self):
        """Parses ## N. Title into {N: 'Title'}."""
        md = "## 1. First principle\n\n## 2. Second\n"
        result = config_module.parse_principle_names(md)
        assert result == {1: "First principle", 2: "Second"}

    def test_empty_string_returns_empty_dict(self):
        """Empty markdown returns empty dict."""
        assert config_module.parse_principle_names("") == {}
