"""ai_comment 템플릿 생성기.

1차 검증에서는 AI 모델 없이 판정 등급 + 위반 Rule 요약을 자연어로 합성한다.
Oracle 작업명세서 §5.4 규칙을 따른다.
"""

from __future__ import annotations

from models.judgment import Judgment, RuleLevel, ViolatedRule


def generate_ai_comment(
    *,
    judgment: Judgment,
    lot_id: str,
    yield_pct: float,
    violated_rules: list[ViolatedRule],
    yield_grade: str | None,
) -> str:
    if judgment == Judgment.NORMAL:
        grade = f" ({yield_grade})" if yield_grade else ""
        return (
            f"LOT {lot_id} 정상 완료. 수율 {yield_pct:.1f}%{grade}, 전 Rule 정상 범위."
        )

    rules_str = ", ".join(_unique_preserve_order(r.rule_id for r in violated_rules))
    grade_label = _yield_label(yield_grade, yield_pct)

    if judgment == Judgment.WARNING:
        return (
            f"LOT {lot_id} 주의. 수율 {yield_pct:.1f}%{grade_label}. "
            f"위반 Rule: {rules_str}. 오퍼레이터 확인 필요."
        )

    # DANGER
    chain_notes = [
        v.extras.get("escalated_by")
        for v in violated_rules
        if v.extras and v.extras.get("escalated_by")
    ]
    chain_part = ""
    if chain_notes:
        chain_part = " 연쇄 패턴 감지: " + " / ".join(_unique_preserve_order(chain_notes)) + "."
    crit_count = sum(1 for v in violated_rules if v.level == RuleLevel.CRITICAL)
    return (
        f"LOT {lot_id} 위험. 수율 {yield_pct:.1f}%{grade_label}. "
        f"위반 Rule: {rules_str} (CRITICAL {crit_count}건).{chain_part} "
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
