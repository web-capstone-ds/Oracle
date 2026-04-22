"""비교 연산자 → RuleLevel 매핑 헬퍼."""

from __future__ import annotations

from cache.rule_cache import RuleThreshold
from models.judgment import RuleLevel


def evaluate_threshold(value: float, t: RuleThreshold) -> RuleLevel:
    """단일 값 vs 임계값 비교 → NORMAL/WARNING/CRITICAL.

    comparison_op 의미:
      gte     : 값이 클수록 나쁨 (critical_threshold <= value → CRITICAL)
      lte     : 값이 작을수록 나쁨 (critical_threshold >= value → CRITICAL)
      abs_gte : abs(값)이 클수록 나쁨
      eq      : value == 1.0 (플래그) 이면 CRITICAL (R31, R38c 용)
    """
    warn = t.warning_threshold
    crit = t.critical_threshold
    op = t.comparison_op

    if op == "eq":
        return RuleLevel.CRITICAL if value >= 1.0 else RuleLevel.NORMAL

    v = abs(value) if op == "abs_gte" else value

    if op in ("gte", "abs_gte"):
        if crit is not None and v >= crit:
            return RuleLevel.CRITICAL
        if warn is not None and v >= warn:
            return RuleLevel.WARNING
        return RuleLevel.NORMAL

    if op == "lte":
        # 값이 작을수록 나쁜 경우 — crit이 더 낮게 설정됨
        if crit is not None and v <= crit:
            return RuleLevel.CRITICAL
        if warn is not None and v <= warn:
            return RuleLevel.WARNING
        return RuleLevel.NORMAL

    return RuleLevel.NORMAL
