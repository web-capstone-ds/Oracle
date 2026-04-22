"""판정 등급 및 위반 Rule DTO."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Judgment(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    DANGER = "DANGER"


_SEVERITY_ORDER = {Judgment.NORMAL: 0, Judgment.WARNING: 1, Judgment.DANGER: 2}


def worst(*judgments: Judgment) -> Judgment:
    if not judgments:
        return Judgment.NORMAL
    return max(judgments, key=_SEVERITY_ORDER.get)


class RuleLevel(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


def level_to_judgment(level: RuleLevel) -> Judgment:
    if level == RuleLevel.CRITICAL:
        return Judgment.DANGER
    if level == RuleLevel.WARNING:
        return Judgment.WARNING
    return Judgment.NORMAL


@dataclass
class ViolatedRule:
    rule_id: str
    parameter: str
    actual_value: float | None
    threshold: dict[str, float | None]  # {"warning": x, "critical": y}
    level: RuleLevel
    description: str
    yield_grade: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rule_id": self.rule_id,
            "parameter": self.parameter,
            "actual_value": self.actual_value,
            "threshold": self.threshold,
            "level": self.level.value,
            "description": self.description,
        }
        if self.yield_grade:
            payload["yield_grade"] = self.yield_grade
        if self.extras:
            payload.update(self.extras)
        return payload
