"""Tests for CLI entrypoints and subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from qi.cli import app


runner = CliRunner()


@pytest.fixture
def cli_temp_home(monkeypatch, tmp_path):
    """Point QI to a temp directory for CLI tests."""
    qi_home = tmp_path / "qi"
    qi_home.mkdir()
    import qi.config as config_module
    import qi.db as db_module
    import qi.cli as cli_module
    monkeypatch.setattr(config_module, "QI_HOME", qi_home)
    monkeypatch.setattr(config_module, "QI_DB_PATH", qi_home / "qi.db")
    monkeypatch.setattr(config_module, "QI_CONFIG_PATH", qi_home / "config.toml")
    monkeypatch.setattr(config_module, "QI_PRINCIPLES_PATH", qi_home / "principles.md")
    monkeypatch.setattr(db_module, "QI_HOME", qi_home)
    monkeypatch.setattr(db_module, "QI_DB_PATH", qi_home / "qi.db")
    # CLI imports these at load time; patch so init/write go to temp dir
    monkeypatch.setattr(cli_module, "QI_HOME", qi_home)
    monkeypatch.setattr(cli_module, "QI_DB_PATH", qi_home / "qi.db")
    monkeypatch.setattr(cli_module, "QI_CONFIG_PATH", qi_home / "config.toml")
    if hasattr(config_module.load_config, "cache_clear"):
        config_module.load_config.cache_clear()
    yield qi_home


class TestSubcommandsExist:
    """Expected top-level and grouped commands are registered."""

    def test_help_lists_commands(self):
        """--help lists known top-level commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        out = result.stdout
        assert "init" in out
        assert "dci" in out
        assert "version" in out
        assert "stats" in out
        assert "week" in out
        assert "report" in out
        assert "principles" in out
        assert "export" in out

    def test_report_help_lists_weekly_and_monthly(self):
        """report --help lists weekly and monthly."""
        result = runner.invoke(app, ["report", "--help"])
        assert result.exit_code == 0
        assert "weekly" in result.stdout
        assert "monthly" in result.stdout

    def test_principles_help_lists_edit(self):
        """principles --help lists edit."""
        result = runner.invoke(app, ["principles", "--help"])
        assert result.exit_code == 0
        assert "edit" in result.stdout


class TestVersion:
    """Version command."""

    def test_version_exits_zero(self):
        """qi version runs and exits 0."""
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "version" in result.stdout.lower() or "__version__" in result.stdout


class TestInit:
    """Init command."""

    def test_init_creates_config_and_db(self, cli_temp_home):
        """qi init creates config.toml, principles.md, and qi.db."""
        assert not (cli_temp_home / "config.toml").exists()
        assert not (cli_temp_home / "qi.db").exists()

        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0

        assert (cli_temp_home / "config.toml").exists()
        assert (cli_temp_home / "principles.md").exists()
        assert (cli_temp_home / "qi.db").exists()

    def test_init_idempotent(self, cli_temp_home):
        """Second qi init does not fail."""
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0


class TestStats:
    """Stats command (no sync, no external deps)."""

    def test_stats_exits_zero_with_empty_db(self, cli_temp_home):
        """qi stats runs with empty DB and exits 0."""
        # Ensure DB exists
        from qi.db import init_db
        init_db()
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        # May show "insufficient data" or a table
        assert "Stats" in result.stdout or "days" in result.stdout.lower() or "Metric" in result.stdout

    def test_stats_with_days_option(self, cli_temp_home):
        """qi stats --days 3 runs."""
        from qi.db import init_db
        init_db()
        result = runner.invoke(app, ["stats", "--days", "3"])
        assert result.exit_code == 0


class TestExport:
    """Export command."""

    def test_export_succeeds_with_output_path(self, cli_temp_home):
        """Export to a file path creates the file."""
        from qi.db import init_db
        init_db()
        out_path = cli_temp_home / "export.jsonl"
        result = runner.invoke(app, ["export", "--output", str(out_path)])
        assert result.exit_code == 0
        assert out_path.exists()
        # Empty DB may yield empty file or only headers; content is JSONL lines
        text = out_path.read_text()
        if text.strip():
            assert "{" in text or '"' in text

    def test_export_with_format_jsonl(self, cli_temp_home):
        """Export with --format jsonl runs successfully."""
        from qi.db import init_db
        init_db()
        out_path = cli_temp_home / "out.jsonl"
        result = runner.invoke(app, ["export", "-f", "jsonl", "-o", str(out_path)])
        assert result.exit_code == 0
        assert out_path.exists()


class TestProcess:
    """Process command (heuristic pipeline)."""

    def test_process_exits_zero(self, cli_temp_home):
        """qi process runs and exits 0."""
        from qi.db import init_db
        init_db()
        result = runner.invoke(app, ["process"])
        assert result.exit_code == 0
        assert "processed" in result.stdout.lower() or "Processing" in result.stdout
