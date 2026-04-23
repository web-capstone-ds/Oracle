"""LOT-level Rule 판정 단위 테스트 — Mock 09/10 시나리오 + 수율 5단계."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cache.lot_history import LotHistoryCache
from cache.rule_cache import DEFAULT_RECIPE, RuleCache, RuleThreshold
from engine import lot_rules
from models.events import LotEnd
from models.judgment import RuleLevel


def _cache() -> RuleCache:
    cache = RuleCache(ttl_seconds=600)
    cache.put(
        DEFAULT_RECIPE,
        [
            RuleThreshold("R23", "yield_pct", 95.0, 90.0, "lte"),
            RuleThreshold("R24", "lot_duration_sec", None, 24000.0, "gte"),
            RuleThreshold("R25", "lot_start_end_diff", 1.0, 5.0, "gte"),
            RuleThreshold("R35", "aborted_consecutive_same_recipe", 1.0, 2.0, "gte"),
        ],
    )
    return cache


def _lot(yield_pct: float, lot_status: str = "COMPLETED", duration: int = 4920) -> LotEnd:
    return LotEnd(
        message_id="00000000-0000-0000-0000-000000000001",
        event_type="LOT_END",
        timestamp=datetime.now(timezone.utc),
        equipment_id="DS-VIS-001",
        equipment_status="IDLE",
        lot_id="LOT-TEST-001",
        lot_status=lot_status,  # type: ignore[arg-type]
        total_units=2792,
        pass_count=int(2792 * yield_pct / 100),
        fail_count=2792 - int(2792 * yield_pct / 100),
        yield_pct=yield_pct,
        lot_duration_sec=duration,
    )


@pytest.mark.parametrize(
    "yield_pct,expected_grade,expected_level",
    [
        (98.5, "EXCELLENT", None),  # NORMAL → no violation
        (96.2, "NORMAL", None),     # Mock 09 정상 LOT
        (93.0, "WARNING", RuleLevel.WARNING),
        (85.0, "MARGINAL", RuleLevel.WARNING),
        (75.0, "CRITICAL", RuleLevel.CRITICAL),
    ],
)
def test_yield_grade_mapping(yield_pct, expected_grade, expected_level):
    cache = _cache()
    v = lot_rules.evaluate_yield(_lot(yield_pct), cache, DEFAULT_RECIPE)
    if expected_level is None:
        assert v is None  # NORMAL 구간은 violation 미생성
    else:
        assert v is not None
        assert v.level == expected_level
        assert v.yield_grade == expected_grade


def test_lot_duration_critical():
    cache = _cache()
    v = lot_rules.evaluate_duration(_lot(96.0, duration=24500), cache, DEFAULT_RECIPE)
    assert v is not None
    assert v.level == RuleLevel.CRITICAL


def test_aborted_streak_warning():
    cache = _cache()
    history = LotHistoryCache()
    ts = datetime.now(timezone.utc)
    history.append("DS-VIS-001", "L1", "Carsem_3X3", "ABORTED", 60.0, ts)
    v = lot_rules.evaluate_aborted_streak(history, "DS-VIS-001", "Carsem_3X3", cache)
    assert v is not None
    assert v.level == RuleLevel.WARNING


def test_aborted_streak_critical():
    cache = _cache()
    history = LotHistoryCache()
    ts = datetime.now(timezone.utc)
    history.append("DS-VIS-001", "L1", "Carsem_3X3", "ABORTED", 60.0, ts)
    history.append("DS-VIS-001", "L2", "Carsem_3X3", "ABORTED", 55.0, ts)
    v = lot_rules.evaluate_aborted_streak(history, "DS-VIS-001", "Carsem_3X3", cache)
    assert v is not None
    assert v.level == RuleLevel.CRITICAL
