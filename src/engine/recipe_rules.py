"""Recipe-level Rules (R30, R31, R32).

- R30: 신규 레시피 플래그 — Historian 이력 미존재. v1.0에서는 WARNING으로 표시.
- R31: 숫자형 레시피 ID — 정규식 ^\\d+$ 매칭 시 CRITICAL.
- R32: EMAP 크기 — EMAP 메타데이터 연동 필요. v1.0에서는 스텁.
"""

from __future__ import annotations

import re

from cache.rule_cache import RuleCache
from models.judgment import RuleLevel, ViolatedRule


_NUMERIC_RECIPE = re.compile(r"^\d+$")


def evaluate_numeric_recipe_id(recipe_id: str, rule_cache: RuleCache) -> ViolatedRule | None:
    if not _NUMERIC_RECIPE.match(recipe_id):
        return None
    t = rule_cache.get_threshold(recipe_id, "R31")
    warn = t.warning_threshold if t else None
    crit = t.critical_threshold if t else 1.0
    return ViolatedRule(
        rule_id="R31",
        parameter="numeric_recipe_id",
        actual_value=1.0,
        threshold={"warning": warn, "critical": crit},
        level=RuleLevel.CRITICAL,
        description=f"숫자형 레시피 ID '{recipe_id}' 수신 — DS 측 확인 필요",
    )


def evaluate_new_recipe_flag(recipe_id: str, rule_cache: RuleCache) -> ViolatedRule | None:
    """신규 레시피 (Historian 이력 없음) — Teaching 모니터링 대상.

    v1.0에서는 WARNING으로 플래그만 남기고, Fail율 추적은 다음 LOT_END에서 수행.
    """
    t = rule_cache.get_threshold(recipe_id, "R30")
    return ViolatedRule(
        rule_id="R30",
        parameter="new_recipe_fail_rate_pct",
        actual_value=0.0,
        threshold={
            "warning": t.warning_threshold if t else 10.0,
            "critical": t.critical_threshold if t else 30.0,
        },
        level=RuleLevel.WARNING,
        description=f"신규 레시피 '{recipe_id}' — Teaching 50 Strip 모니터링 시작",
    )


def evaluate_emap_size(recipe_id: str, emap_size: int, rule_cache: RuleCache) -> ViolatedRule | None:
    """R32: EMAP 메타데이터 수신 시 호출. v1.0 경로에서는 일반적으로 미호출."""
    if emap_size <= 0:
        return None
    t = rule_cache.get_threshold(recipe_id, "R32")
    if t is None:
        return None
    from engine.thresholds import evaluate_threshold

    level = evaluate_threshold(float(emap_size), t)
    if level == RuleLevel.NORMAL:
        return None
    label = "WARNING" if level == RuleLevel.WARNING else "CRITICAL"
    return ViolatedRule(
        rule_id="R32",
        parameter="emap_size",
        actual_value=float(emap_size),
        threshold={"warning": t.warning_threshold, "critical": t.critical_threshold},
        level=level,
        description=f"EMAP 크기 {emap_size}개 — {label} (정상 46개 기준)",
    )
