"""ai_comment 템플릿 생성기.

1차 검증에서는 AI 모델 없이 판정 등급 + 위반 Rule 요약을 자연어로 합성한다.
Oracle 작업명세서 §5.4 규칙을 따른다.
"""

from __future__ import annotations

from engine.comment.base import CommentContext
from engine.comment.template_generator import TemplateCommentGenerator
from models.judgment import Judgment, RuleLevel, ViolatedRule


def generate_ai_comment(
    *,
    judgment: Judgment,
    lot_id: str,
    yield_pct: float,
    violated_rules: list[ViolatedRule],
    yield_grade: str | None,
) -> str:
    return TemplateCommentGenerator().generate(
        CommentContext(
            judgment=judgment,
            lot_id=lot_id,
            yield_pct=yield_pct,
            violated_rules=violated_rules,
            yield_grade=yield_grade,
            fail_top_reason=None,
            marginal_count=0,
            recipe_id="",
        )
    )


def _yield_label(grade: str | None, yield_pct: float) -> str:
    if grade in ("MARGINAL", "CRITICAL", "WARNING"):
        return f" ({grade})"
    if yield_pct < 80.0:
        return " (CRITICAL <80%)"
    if yield_pct < 90.0:
        return " (MARGINAL 80~90%)"
    if yield_pct < 95.0:
        return " (WARNING 90~95%)"
    return ""


def _unique_preserve_order(items):
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out
