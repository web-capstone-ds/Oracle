"""RuleEngine 통합 시나리오 — Mock 09(NORMAL) / Mock 10(WARNING) / Mock 05 기반(DANGER).

Historian 호출은 monkeypatch 로 stub 한다 (DB 미기동 환경에서도 통과).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cache.alarm_counter import AlarmCounterCache
from cache.equipment_cache import EquipmentCache
from cache.lot_history import LotHistoryCache
from cache.rule_cache import DEFAULT_RECIPE, RuleCache, RuleThreshold
from db import historian_queries
from db.historian_queries import InspectionRow
from engine.rule_engine import RuleEngine
from models.events import LotEnd
from models.judgment import Judgment


def _full_default_cache() -> RuleCache:
    cache = RuleCache(ttl_seconds=600)
    cache.put(
        DEFAULT_RECIPE,
        [
            RuleThreshold("R23", "yield_pct", 95.0, 90.0, "lte"),
            RuleThreshold("R24", "lot_duration_sec", None, 24000.0, "gte"),
            RuleThreshold("R25", "lot_start_end_diff", 1.0, 5.0, "gte"),
            RuleThreshold("R35", "aborted_consecutive_same_recipe", 1.0, 2.0, "gte"),
            RuleThreshold("R09", "side_et52_rate_pct", 5.0, 50.0, "gte"),
            RuleThreshold("R08", "side_pass_rate_pct", 96.0, 90.0, "lte"),
            RuleThreshold("R22", "takt_time_ms", 2000.0, 3000.0, "gte"),
            RuleThreshold("R37", "inspection_duration_ms", 1500.0, 2000.0, "gte"),
            RuleThreshold("R26", "cam_timeout_daily_count", 1.0, 3.0, "gte"),
            RuleThreshold("R29", "light_pwr_low_consecutive", 1.0, 3.0, "gte"),
            RuleThreshold("R38c", "status_abnormal_transition", None, 1.0, "eq"),
        ],
    )
    return cache


def _engine() -> RuleEngine:
    eq = EquipmentCache()
    # 레시피 캐시는 __default__ 만 시드하므로 equipment 의 recipe_id 도 동일하게 맞춘다.
    # (RuleEngine.ensure_recipe_loaded 가 미존재 레시피에 대해 DB 호출을 시도하기 때문)
    eq.update_status(
        "DS-VIS-001",
        "RUN",
        DEFAULT_RECIPE,
        "v1",
        "OP1",
        "L1",
        100,
        datetime.now(timezone.utc),
    )
    return RuleEngine(
        equipment_cache=eq,
        alarm_counter=AlarmCounterCache(),
        lot_history=LotHistoryCache(),
        rule_cache=_full_default_cache(),
    )


def _lot(yield_pct: float, status: str = "COMPLETED") -> LotEnd:
    return LotEnd(
        message_id="00000000-0000-0000-0000-000000000010",
        event_type="LOT_END",
        timestamp=datetime.now(timezone.utc),
        equipment_id="DS-VIS-001",
        equipment_status="IDLE",
        lot_id="LOT-INT-001",
        lot_status=status,  # type: ignore[arg-type]
        total_units=2792,
        pass_count=int(2792 * yield_pct / 100),
        fail_count=2792 - int(2792 * yield_pct / 100),
        yield_pct=yield_pct,
        lot_duration_sec=4920,
    )


def _patch_historian_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty(*args, **kwargs):
        return []

    async def _zero(*args, **kwargs):
        return 0

    monkeypatch.setattr(historian_queries, "fetch_lot_inspection_results", _empty)
    monkeypatch.setattr(historian_queries, "count_cam_timeout_today", _zero)
    monkeypatch.setattr(historian_queries, "count_aggex_today", _zero)
    monkeypatch.setattr(historian_queries, "count_eap_disconnected_week", _zero)


@pytest.mark.asyncio
async def test_mock09_normal_lot(monkeypatch):
    """Mock 09: yield 96.2% COMPLETED → NORMAL."""
    _patch_historian_empty(monkeypatch)
    engine = _engine()
    result = await engine.judge_lot_end(_lot(96.2, "COMPLETED"))
    assert result.judgment == Judgment.NORMAL
    assert result.violated_rules == []
    assert result.yield_grade in ("EXCELLENT", "NORMAL")


@pytest.mark.asyncio
async def test_mock10_aborted_warning(monkeypatch):
    """Mock 10: ABORTED yield 94.2% → WARNING (R23 90~95%, R35 1회)."""
    _patch_historian_empty(monkeypatch)
    engine = _engine()
    result = await engine.judge_lot_end(_lot(94.2, "ABORTED"))
    assert result.judgment == Judgment.WARNING
    rule_ids = {v.rule_id for v in result.violated_rules}
    assert "R23" in rule_ids  # WARNING 구간 진입
    assert "R35" in rule_ids  # ABORTED 1회 → WARNING


@pytest.mark.asyncio
async def test_side_et52_full_fail_danger(monkeypatch):
    """Mock 05 기반: SIDE ET=52 전수 FAIL → DANGER (R09 CRITICAL)."""

    rows = [
        InspectionRow(
            time=datetime.now(timezone.utc),
            overall_result="FAIL",
            fail_reason_code="ET52",
            fail_count=8,
            total_inspected_count=8,
            takt_time_ms=1620,
            inspection_duration_ms=1500,
            algorithm_version="1.4.2",
            inspection_detail={
                "prs_result": [],
                "side_result": [{"ErrorType": 52, "InspectionResult": 0}] * 8,
            },
            singulation=None,
            geometric=None,
        )
        for _ in range(20)
    ]

    async def _rows(*_a, **_kw):
        return rows

    async def _zero(*_a, **_kw):
        return 0

    monkeypatch.setattr(historian_queries, "fetch_lot_inspection_results", _rows)
    monkeypatch.setattr(historian_queries, "count_cam_timeout_today", _zero)
    monkeypatch.setattr(historian_queries, "count_aggex_today", _zero)
    monkeypatch.setattr(historian_queries, "count_eap_disconnected_week", _zero)

    engine = _engine()
    # 수율은 정상이지만 SIDE 검사가 전수 FAIL → R09 CRITICAL → DANGER
    result = await engine.judge_lot_end(_lot(96.0, "COMPLETED"))
    assert result.judgment == Judgment.DANGER
    assert any(v.rule_id == "R09" for v in result.violated_rules)


@pytest.mark.asyncio
async def test_historian_unavailable_fallback(monkeypatch):
    """Historian 장애 시 Unit-level Rules 스킵 + 판정 자체는 진행 → 크래시 금지."""

    async def _raise(*_a, **_kw):
        raise historian_queries.HistorianUnavailable("simulated outage")

    async def _zero(*_a, **_kw):
        return 0

    monkeypatch.setattr(historian_queries, "fetch_lot_inspection_results", _raise)
    monkeypatch.setattr(historian_queries, "count_cam_timeout_today", _zero)
    monkeypatch.setattr(historian_queries, "count_aggex_today", _zero)
    monkeypatch.setattr(historian_queries, "count_eap_disconnected_week", _zero)

    engine = _engine()
    result = await engine.judge_lot_end(_lot(96.0, "COMPLETED"))
    # Historian 장애에도 LOT-level 판정은 정상 — 수율 96.0% → NORMAL
    assert result.judgment == Judgment.NORMAL
