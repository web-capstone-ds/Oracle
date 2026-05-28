"""Deterministic template ai_comment generator."""

from __future__ import annotations

from engine.comment.base import CommentContext
from models.judgment import Judgment, RuleLevel


class TemplateCommentGenerator:
    def generate(self, ctx: CommentContext) -> str:
        if ctx.judgment == Judgment.NORMAL:
            grade = f" ({ctx.yield_grade})" if ctx.yield_grade else ""
            return (
                f"LOT {ctx.lot_id} 정상 완료. 수율 {ctx.yield_pct:.1f}%{grade}, "
                "전 Rule 정상 범위."
            )

        rules_str = ", ".join(_unique_preserve_order(r.rule_id for r in ctx.violated_rules))
        grade_label = _yield_label(ctx.yield_grade, ctx.yield_pct)
        reason = f" 주요 원인: {ctx.fail_top_reason}." if ctx.fail_top_reason else ""

        if ctx.judgment == Judgment.WARNING:
            return (
                f"LOT {ctx.lot_id} 주의. 수율 {ctx.yield_pct:.1f}%{grade_label}. "
                f"위반 Rule: {rules_str}.{reason} 오퍼레이터 확인 필요."
            )

        chain_notes = [
            v.extras.get("escalated_by")
            for v in ctx.violated_rules
            if v.extras and v.extras.get("escalated_by")
        ]
        chain_part = ""
        if chain_notes:
            chain_part = " 연쇄 패턴 감지: " + " / ".join(
                _unique_preserve_order(chain_notes)
            ) + "."
        crit_count = sum(1 for v in ctx.violated_rules if v.level == RuleLevel.CRITICAL)
        return (
            f"LOT {ctx.lot_id} 위험. 수율 {ctx.yield_pct:.1f}%{grade_label}. "
            f"위반 Rule: {rules_str} (CRITICAL {crit_count}건).{reason}{chain_part} "
            "즉시 점검 + 작업 중단 권고."
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

