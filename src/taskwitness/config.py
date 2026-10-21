"""Oracle configuration files.

Thresholds should be fixed *before* an experiment and never tuned on its results.
A config file makes that explicit and auditable: its digest goes into every
evaluation report, so anyone can check the thresholds were not changed afterwards.

    {"place": {"settle_window_s": 1.5}, "button_press": {"min_hold_s": 0.08}}
"""

from __future__ import annotations

import json
import math
from dataclasses import fields
from pathlib import Path
from typing import Any

from taskwitness.button import ButtonPressConfig
from taskwitness.core import TaskWitnessError, sha256_of
from taskwitness.oracle import PlaceOracleConfig

CONFIG_TYPES: dict[str, type] = {"place": PlaceOracleConfig, "button_press": ButtonPressConfig}


class ConfigError(TaskWitnessError):
    """Raised when a config document is malformed."""


def parse_config(doc: Any) -> dict[str, Any]:
    """Validate a config document and build one config object per task type."""
    if not isinstance(doc, dict):
        raise ConfigError("config must be a JSON object keyed by task type")
    unknown = set(doc) - set(CONFIG_TYPES)
    if unknown:
        raise ConfigError(f"unknown task type(s) in config: {sorted(unknown)}; known: {sorted(CONFIG_TYPES)}")
    out = {}
    for task_type, cls in CONFIG_TYPES.items():
        overrides = doc.get(task_type, {})
        if not isinstance(overrides, dict):
            raise ConfigError(f"config.{task_type} must be an object")
        known = {f.name: f for f in fields(cls)}
        for key, value in overrides.items():
            if key not in known:
                raise ConfigError(f"unknown field config.{task_type}.{key}; known: {sorted(known)}")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ConfigError(f"config.{task_type}.{key} must be a finite number")
            if value < 0:
                raise ConfigError(f"config.{task_type}.{key} must not be negative")
            if known[key].type == "int" and value != int(value):
                raise ConfigError(f"config.{task_type}.{key} must be an integer")
        out[task_type] = cls(**{k: (int(v) if known[k].type == "int" else float(v)) for k, v in overrides.items()})
    return out


def load_config(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return parse_config({})
    with Path(path).open(encoding="utf-8") as fh:
        try:
            return parse_config(json.load(fh))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: invalid JSON: {exc}") from None


def config_digest(configs: dict[str, Any]) -> str:
    from dataclasses import asdict

    return sha256_of({k: asdict(v) for k, v in sorted(configs.items())})
