"""Unit-level Rule 집계/판정 — chipping, blade_wear, SIDE ET=52 시나리오."""

from __future__ import annotations

from datetime import datetime, timezone

from cache.rule_cache import DEFAULT_RECIPE, RuleCache, RuleThreshold
from db.historian_queries import InspectionRow
from engine import unit_rules
from models.judgment import RuleLevel


def _cache() -> RuleCache:
    cache = RuleCache(ttl_seconds=600)
    cache.put(
        DEFAULT_RECIPE,
        [
            RuleThreshold("R08", "side_pass_rate_pct", 96.0, 90.0, "lte"),
            RuleThreshold("R09", "side_et52_rate_pct", 5.0, 50.0, "gte"),
            RuleThreshold("R13", "chipping_top_um", 40.0, 50.0, "gte"),
            RuleThreshold("R16", "blade_wear_index", 0.70, 0.85, "gte"),
        ],
    )
    return cache


def _row(detail=None, sing=None) -> InspectionRow:
    return InspectionRow(
        time=datetime.now(timezone.utc),
        overall_result="FAIL" if detail else "PASS",
        fail_reason_code="ET52" if detail else None,
        fail_count=1 if detail else 0,
        total_inspected_count=8,
        takt_time_ms=1620,
        inspection_duration_ms=1500,
        algorithm_version="1.4.2",
        inspection_detail=detail,
        singulation=sing,
        geometric=None,
    )


def test_side_et52_full_fail_critical():
    """Mock 05 시나리오: ET=52 전수 FAIL → R09 CRITICAL."""
    rows = [
        _row(
            detail={
                "prs_result": [],
                "side_result": [{"ErrorType": 52, "InspectionResult": 0}] * 8,
            }
        )
        for _ in range(10)
    ]
    agg = unit_rules.aggregate_inspections(rows)
    violations = unit_rules.evaluate_unit_rules(agg, _cache(), DEFAULT_RECIPE)
    r09 = [v for v in violations if v.rule_id == "R09"]
    assert r09 and r09[0].level == RuleLevel.CRITICAL


def test_chipping_top_critical():
    """R13: chipping_top_um = 55 → CRITICAL."""
    v = unit_rules.evaluate_singulation_value(
        rule_id="R13",
        parameter="chipping_top_um",
        value=55.0,
        rule_cache=_cache(),
        recipe_id=DEFAULT_RECIPE,
        desc_tpl="Chipping(top) 최대 {v:.1f}μm — {label}",
    )
    assert v is not None
    assert v.level == RuleLevel.CRITICAL


def test_blade_wear_warning():
    """R16: blade_wear_index = 0.75 → WARNING."""
    v = unit_rules.evaluate_singulation_value(
        rule_id="R16",
        parameter="blade_wear_index",
        value=0.75,
        rule_cache=_cache(),
        recipe_id=DEFAULT_RECIPE,
        desc_tpl="Blade wear {v:.2f} — {label}",
    )
    assert v is not None
    assert v.level == RuleLevel.WARNING
