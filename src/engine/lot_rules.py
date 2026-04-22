"""LOT-level Rules — LOT_END 페이로드만으로 판정 가능.

- R23 yield_pct: 5단계 세분류 (EXCELLENT / NORMAL / WARNING / MARGINAL / CRITICAL)
- R24 lot_duration_sec: 24,000초 초과 시 CRITICAL
- R25 LOT Start/End 누적 차이: 인메모리 캐시 기반
- R35 동일 레시피 ABORTED 연속: 인메모리 캐시 기반

수율 5단계 (API §5.2, Oracle 작업명세서 §4.2.1):
  ≥98%  EXCELLENT → NORMAL
  95-98% NORMAL    → NORMAL
  90-95% WARNING   → WARNING
  80-90% MARGINAL  → WARNING   (← Oracle 핵심 감지 대상)
  <80%   CRITICAL  → DANGER
"""

from __future__ import annotations

from cache.lot_history import LotHistoryCache
from cache.rule_cache import RuleCache
from engine.thresholds import evaluate_threshold
from models.events import LotEnd
from models.judgment import RuleLevel, ViolatedRule


def evaluate_yield(lot: LotEnd, rule_cache: RuleCache, recipe_id: str) -> ViolatedRule | None:
    """R23: yield_pct 5단계 세분류."""
    yield_pct = float(lot.yield_pct)
    threshold = rule_cache.get_threshold(recipe_id, "R23")
    warn = threshold.warning_threshold if threshold else 95.0
    crit = threshold.critical_threshold if threshold else 90.0

    if yield_pct >= 98.0:
        grade = "EXCELLENT"
        level = RuleLevel.NORMAL
    elif yield_pct >= 95.0:
        grade = "NORMAL"
        level = RuleLevel.NORMAL
    elif yield_pct >= 90.0:
        grade = "WARNING"
        level = RuleLevel.WARNING
    elif yield_pct >= 80.0:
        grade = "MARGINAL"
        level = RuleLevel.WARNING
    else:
        grade = "CRITICAL"
        level = RuleLevel.CRITICAL

    if level == RuleLevel.NORMAL:
        return None

    desc = _yield_desc(yield_pct, grade)
    return ViolatedRule(
        rule_id="R23",
        parameter="yield_pct",
        actual_value=yield_pct,
        threshold={"warning": warn, "critical": crit},
        level=level,
        yield_grade=grade,
        description=desc,
    )


def evaluate_duration(lot: LotEnd, rule_cache: RuleCache, recipe_id: str) -> ViolatedRule | None:
    """R24: lot_duration_sec ≥ 24,000초 (≥ 6시간 40분) → CRITICAL."""
    threshold = rule_cache.get_threshold(recipe_id, "R24")
    crit = threshold.critical_threshold if threshold else 24000.0
    if crit is None or lot.lot_duration_sec < crit:
        return None
    return ViolatedRule(
        rule_id="R24",
        parameter="lot_duration_sec",
        actual_value=float(lot.lot_duration_sec),
        threshold={"warning": None, "critical": crit},
        level=RuleLevel.CRITICAL,
        description=(
            f"LOT 소요시간 {lot.lot_duration_sec}s ≥ {int(crit)}s — "
            "VISION_SCORE_ERR (LotController) 의심"
        ),
    )


def evaluate_start_end_diff(
    diff: int, rule_cache: RuleCache, recipe_id: str
) -> ViolatedRule | None:
    """R25: Start/End 누적 차이. diff는 양/음 모두 가능하므로 abs 비교."""
    threshold = rule_cache.get_threshold(recipe_id, "R25")
    if threshold is None:
        return None
    level = evaluate_threshold(abs(float(diff)), threshold)
    if level == RuleLevel.NORMAL:
        return None
    return ViolatedRule(
        rule_id="R25",
        parameter="lot_start_end_diff",
        actual_value=float(diff),
        threshold={
            "warning": threshold.warning_threshold,
            "critical": threshold.critical_threshold,
        },
        level=level,
        description=f"LOT Start/End 누적 차이 {diff} — {_level_label(level)} 구간",
    )


def evaluate_aborted_streak(
    history: LotHistoryCache,
    equipment_id: str,
    recipe_id: str,
    rule_cache: RuleCache,
) -> ViolatedRule | None:
    """R35: 동일 레시피 ABORTED 연속 횟수."""
    count = history.consecutive_aborted(equipment_id, recipe_id)
    if count <= 0:
        return None
    threshold = rule_cache.get_threshold(recipe_id, "R35")
    if threshold is None:
        return None
    level = evaluate_threshold(float(count), threshold)
    if level == RuleLevel.NORMAL:
        return None
    return ViolatedRule(
        rule_id="R35",
        parameter="aborted_consecutive_same_recipe",
        actual_value=float(count),
        threshold={
            "warning": threshold.warning_threshold,
            "critical": threshold.critical_threshold,
        },
        level=level,
        description=f"동일 레시피({recipe_id}) ABORTED {count}회 연속 — {_level_label(level)}",
    )


def _yield_desc(yield_pct: float, grade: str) -> str:
    if grade == "EXCELLENT":
        return f"수율 {yield_pct}% — EXCELLENT 구간 (≥98%)"
    if grade == "NORMAL":
        return f"수율 {yield_pct}% — NORMAL 구간 (95~98%)"
    if grade == "WARNING":
        return f"수율 {yield_pct}% — WARNING 구간 (90~95%). 불량 패턴 분석 필요"
    if grade == "MARGINAL":
        return f"수율 {yield_pct}% — MARGINAL 구간 (80~90%). 생산 중단 검토"
    return f"수율 {yield_pct}% — CRITICAL 구간 (<80%). 즉시 생산 중단"


def _level_label(level: RuleLevel) -> str:
    return "WARNING" if level == RuleLevel.WARNING else "CRITICAL"
