"""Configuration management for QI."""

import copy
import functools
import os
import re
from pathlib import Path
from typing import Any

try:
    import tomllib as tomli
except ImportError:
    import tomli  # type: ignore

import tomli_w

# Default paths
QI_HOME = Path(os.environ.get("QI_HOME", Path.home() / ".qi"))
QI_DB_PATH = QI_HOME / "qi.db"
QI_CONFIG_PATH = QI_HOME / "config.toml"
QI_PRINCIPLES_PATH = QI_HOME / "principles.md"

DEFAULT_PRINCIPLES_TEMPLATE = """# Guiding Principles

## 1. Sustain physical health as a non-negotiable baseline
Training, nutrition, medical checks.

## 2. Consolidate a stable professional role
Skill acquisition, focus, output quality.

## 3. Maintain cognitive hygiene
Inputs, environments, habits consciously curated.

## 4. Achieve financial stabilization
Order over optimization.

## 5. Invest deliberately in social bonds
Entanglement chosen, not avoided or clung to.

## 6. Introduce joy and novelty
Travel, experiences, pleasure - framed and integrated.

## 7. Learn explicitly from errors
Retrospectives, observability, adjustment.

# OKRs (Objectives and Key Responsibilities)

## Current Quarter
- KR1: [Your first OKR]
- KR2: [Your second OKR]
- KR3: [Your third OKR]
"""

DEFAULT_CONFIG = {
    "general": {
        "week_start_day": "monday",
        "timezone": "local",
    },
    "dci": {
        "quick_mode_fields": ["energy", "mood", "sleep"],
    },
    "dci_metrics": {
        # Example metrics only. Add your own in ~/.qi/config.toml (type: bool|float|str, label, aggregate: count|rate|sum, optional conditional_on).
        "habit_1": {"type": "bool", "label": "Habit 1 done?", "aggregate": "count"},
        "habit_2": {"type": "bool", "label": "Habit 2 done?", "aggregate": "count"},
        "optional_note": {"type": "str", "label": "Optional note", "aggregate": "count"},
    },
    "snr": {
        "qc_db_path": "",  # Path to QuickCapture DB (leave empty if not using external QC)
    },
    "llm": {
        "enabled": True,
        "model": "qwen3:30b",
        "eod_model": "qwen3:8b",
        "base_url": "http://localhost:11434",
        "temperature": 0.4,
        "eod_temperature": 0.3,
        "eod_concurrency": 7,
        "timeout_seconds": 1200,
        "principles_path": "principles.md",
    },
}


def ensure_qi_home() -> Path:
    """Create QI home directory if it doesn't exist."""
    QI_HOME.mkdir(parents=True, exist_ok=True)
    return QI_HOME


@functools.lru_cache()
def load_config() -> dict[str, Any]:
    """Load configuration from TOML file."""
    if not QI_CONFIG_PATH.exists():
        return copy.deepcopy(DEFAULT_CONFIG)

    with open(QI_CONFIG_PATH, "rb") as f:
        config = tomli.load(f)

    # Merge with defaults
    merged = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in config.items():
        if isinstance(value, dict) and key in merged:
            merged[key].update(value)
        else:
            merged[key] = value

    return merged


def save_config(config: dict[str, Any]) -> None:
    """Save configuration to TOML file."""
    ensure_qi_home()
    with open(QI_CONFIG_PATH, "wb") as f:
        tomli_w.dump(config, f)
    load_config.cache_clear()


def get_config_value(key: str, default: Any = None) -> Any:
    """Get a config value by dot-separated key path."""
    config = load_config()
    keys = key.split(".")
    value = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    return value


def get_snr_qc_db_path() -> Path | None:
    """Get the configured SnR QuickCapture database path."""
    path_str = get_config_value("snr.qc_db_path", "")
    if path_str:
        return Path(path_str).expanduser()
    return None


def get_principles_path(config: dict[str, Any] | None = None) -> Path:
    """Resolve principles markdown path from config."""
    cfg = config or load_config()
    llm_cfg = cfg.get("llm", {})
    path_str = llm_cfg.get("principles_path", "principles.md")
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = QI_HOME / path
    return path


def ensure_principles_file(config: dict[str, Any] | None = None) -> tuple[Path, bool]:
    """Ensure the principles markdown file exists. Returns (path, created)."""
    ensure_qi_home()
    path = get_principles_path(config)
    if path.exists():
        return path, False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_PRINCIPLES_TEMPLATE, encoding="utf-8")
    return path, True


def read_principles_markdown(config: dict[str, Any] | None = None) -> str | None:
    """Read principles markdown if available."""
    path = get_principles_path(config)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def parse_principle_names(md: str) -> dict[int, str]:
    """Extract principle_id -> name from principles markdown (e.g. ## 1. Name)."""
    pattern = r"^## (\d+)\.\s+(.+)$"
    return {
        int(m.group(1)): m.group(2).strip()
        for m in re.finditer(pattern, md, re.MULTILINE)
    }
