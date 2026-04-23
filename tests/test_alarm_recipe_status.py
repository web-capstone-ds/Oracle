"""Alarm/Recipe/Status Rule 판정 단위 테스트."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from cache.alarm_counter import AlarmCounterCache
from cache.equipment_cache import EquipmentCache
from cache.rule_cache import DEFAULT_RECIPE, RuleCache, RuleThreshold
from engine import alarm_rules, recipe_rules, status_rules
from models.judgment import RuleLevel


def _cache() -> RuleCache:
    cache = RuleCache(ttl_seconds=600)
    cache.put(
        DEFAULT_RECIPE,
        [
            RuleThreshold("R26", "cam_timeout_daily_count", 1.0, 3.0, "gte"),
            RuleThreshold("R29", "light_pwr_low_consecutive", 1.0, 3.0, "gte"),
            RuleThreshold("R31", "numeric_recipe_id", None, 1.0, "eq"),
            RuleThreshold("R38c", "status_abnormal_transition", None, 1.0, "eq"),
        ],
    )
    return cache


def test_numeric_recipe_id_critical():
    v = recipe_rules.evaluate_numeric_recipe_id("446275", _cache())
    assert v is not None
    assert v.level == RuleLevel.CRITICAL


def test_numeric_recipe_id_normal():
    v = recipe_rules.evaluate_numeric_recipe_id("Carsem_3X3", _cache())
    assert v is None


def test_abnormal_transition_run_to_stop_no_alarm():
    cache = _cache()
    eq = EquipmentCache()
    ts = datetime.now(timezone.utc)
    eq.update_status("DS-VIS-001", "RUN", "Carsem_3X3", "v1", "OP1", "L1", 100, ts)
    eq.update_status("DS-VIS-001", "STOP", "Carsem_3X3", "v1", "OP1", "L1", 110, ts + timedelta(seconds=1))
    v = status_rules.evaluate_abnormal_transition(eq, "DS-VIS-001", cache, DEFAULT_RECIPE)
    assert v is not None
    assert v.level == RuleLevel.CRITICAL


def test_normal_transition_run_to_stop_with_preceding_alarm():
    cache = _cache()
    eq = EquipmentCache()
    ts = datetime.now(timezone.utc)
    eq.update_status("DS-VIS-001", "RUN", "Carsem_3X3", "v1", "OP1", "L1", 100, ts)
    eq.record_alarm("DS-VIS-001", "VISION_SCORE_ERR", ts + timedelta(seconds=2))
    eq.update_status("DS-VIS-001", "STOP", "Carsem_3X3", "v1", "OP1", "L1", 110, ts + timedelta(seconds=10))
    v = status_rules.evaluate_abnormal_transition(eq, "DS-VIS-001", cache, DEFAULT_RECIPE)
    assert v is None


@pytest.mark.asyncio
async def test_cam_timeout_critical_via_alarm_counter():
    cache = _cache()
    counter = AlarmCounterCache()
    ts = datetime.now(timezone.utc)
    for _ in range(4):
        counter.increment("DS-VIS-001", "CAM_TIMEOUT_ERR", ts)
    violations = await alarm_rules.evaluate_alarm_rules(
        equipment_id="DS-VIS-001",
        alarm_counter=counter,
        rule_cache=cache,
        recipe_id=DEFAULT_RECIPE,
        at=ts,
    )
    r26 = [v for v in violations if v.rule_id == "R26"]
    assert r26 and r26[0].level == RuleLevel.CRITICAL


def test_chain_escalation_lightpwr_side_et52():
    from models.judgment import ViolatedRule

    violations = [
        ViolatedRule(
            rule_id="R29",
            parameter="light_pwr_low_consecutive",
            actual_value=2.0,
            threshold={"warning": 1.0, "critical": 3.0},
            level=RuleLevel.WARNING,
            description="LIGHT_PWR_LOW 연속 2건 — WARNING",
        ),
        ViolatedRule(
            rule_id="R09",
            parameter="side_et52_rate_pct",
            actual_value=12.0,
            threshold={"warning": 5.0, "critical": 50.0},
            level=RuleLevel.WARNING,
            description="SIDE ET=52 비율 12.0% — WARNING",
        ),
    ]
    alarm_rules.apply_chain_escalation(violations)
    assert all(v.level == RuleLevel.CRITICAL for v in violations)
    assert all(v.extras.get("escalated_by") for v in violations)
