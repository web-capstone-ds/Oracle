"""ai_comment generator interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from models.judgment import Judgment, ViolatedRule


@dataclass(frozen=True)
class CommentContext:
    judgment: Judgment
    lot_id: str
    yield_pct: float
    violated_rules: list[ViolatedRule]
    yield_grade: str | None
    fail_top_reason: str | None
    marginal_count: int
    recipe_id: str


class CommentGenerator(Protocol):
    def generate(self, ctx: CommentContext) -> str:
        ...

