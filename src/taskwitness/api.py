"""Stable Python API: verify any supported episode with one call.

    from taskwitness import judge
    result = judge(episode)
    if result.passed: ...
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from taskwitness.button import verify_button_press
from taskwitness.config import parse_config
from taskwitness.core import FAIL, PASS, UNKNOWN, EpisodeError
from taskwitness.oracle import verify_place

VERIFIERS: dict[str, Callable[..., dict[str, Any]]] = {
    "place": verify_place,
    "button_press": verify_button_press,
}


def verify_episode(episode: dict[str, Any], configs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch on `task.type` and return the evidence bundle.

    `configs` maps task type to a config object, as returned by `load_config`;
    task types missing from it use their defaults.
    """
    task = episode.get("task") if isinstance(episode, dict) else None
    task_type = task.get("type") if isinstance(task, dict) else None
    if task_type not in VERIFIERS:
        raise EpisodeError(f"unsupported task type {task_type!r}; supported: {sorted(VERIFIERS)}")
    cfg = (configs or {}).get(task_type)
    return VERIFIERS[task_type](episode, cfg)


@dataclass(frozen=True)
class Verdict:
    verdict: str
    reasons: list[str]
    bundle: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    @property
    def failed(self) -> bool:
        return self.verdict == FAIL

    @property
    def unknown(self) -> bool:
        return self.verdict == UNKNOWN


def judge(episode: dict[str, Any], config: dict[str, Any] | None = None) -> Verdict:
    """Verify an episode. `config` is a config document like the JSON config file."""
    bundle = verify_episode(episode, parse_config(config or {}))
    return Verdict(bundle["verdict"], bundle["reasons"], bundle)
