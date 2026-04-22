"""Historian TSDB 조회 모듈 — read-only.

Historian 작업명세서 §3.3 / §4.2 기반. 5종 기본 쿼리 + 2종 보정 쿼리.

정책:
- Historian DB 장애 시 Oracle은 크래시하지 않고 "판정 스킵" 하여 다음 LOT 대기.
- PASS drop 정책에 의해 inspection_detail / singulation 등은 FAIL 레코드에서만 NULL 아님.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from db.pool import historian_pool
from utils.logging_config import get_logger

log = get_logger(__name__)


class HistorianUnavailable(RuntimeError):
    """Historian 접근 실패. 판정 스킵 신호."""


@dataclass
class InspectionRow:
    time: datetime
    overall_result: str
    fail_reason_code: str | None
    fail_count: int
    total_inspected_count: int
    takt_time_ms: int | None
    inspection_duration_ms: int | None
    algorithm_version: str | None
    inspection_detail: dict[str, Any] | None  # PascalCase 유지
    singulation: dict[str, Any] | None
    geometric: dict[str, Any] | None


async def fetch_lot_inspection_results(
    lot_id: str,
    equipment_id: str,
) -> list[InspectionRow]:
    """O5-1: LOT별 INSPECTION_RESULT 일괄 조회.

    Unit-level Rule 판정 원시 데이터. PASS 레코드는 detail 그룹이 NULL.
    """
    sql = """
        SELECT time, overall_result, fail_reason_code, fail_count,
               total_inspected_count, takt_time_ms, inspection_duration_ms,
               algorithm_version, inspection_detail, singulation, geometric
        FROM inspection_results
        WHERE lot_id = %s AND equipment_id = %s
        ORDER BY time ASC
    """
    rows = await _fetch(sql, (lot_id, equipment_id))
    return [
        InspectionRow(
            time=r[0],
            overall_result=r[1],
            fail_reason_code=r[2],
            fail_count=r[3],
            total_inspected_count=r[4],
            takt_time_ms=r[5],
            inspection_duration_ms=r[6],
            algorithm_version=r[7],
            inspection_detail=r[8],
            singulation=r[9],
            geometric=r[10],
        )
        for r in rows
    ]


async def fetch_recent_yields(
    recipe_id: str,
    limit: int = 28,
) -> list[tuple[datetime, float, str]]:
    """O5-2: 레시피별 최근 N LOT 수율 시계열.

    (time, yield_pct, lot_status) 튜플 리스트. 최신순.
    2차 검증 EWMA 입력이 되며, v1.0에서는 통계 참조용.
    """
    sql = """
        SELECT time, yield_pct, lot_status
        FROM lot_ends
        WHERE recipe_id = %s
        ORDER BY time DESC
        LIMIT %s
    """
    rows = await _fetch(sql, (recipe_id, limit))
    return [(r[0], float(r[1]), r[2]) for r in rows]


async def fetch_avg_total_units(recipe_id: str, limit: int = 3) -> float | None:
    """O5-3: 레시피별 최근 N LOT 평균 total_units.

    expected_total_units 계산 참조.
    """
    sql = """
        SELECT AVG(total_units)
        FROM (
            SELECT total_units
            FROM lot_ends
            WHERE recipe_id = %s
            ORDER BY time DESC
            LIMIT %s
        ) t
    """
    rows = await _fetch(sql, (recipe_id, limit))
    if not rows or rows[0][0] is None:
        return None
    return float(rows[0][0])


async def fetch_error_type_distribution(
    recipe_id: str,
    since: datetime | None = None,
) -> dict[str, int]:
    """O5-4: 레시피별 ET 분포 통계.

    fail_reason_code 별 집계. v1.0에서는 R05/R09 보조 참조용.
    """
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=7)
    sql = """
        SELECT COALESCE(fail_reason_code, 'UNKNOWN'), COUNT(*)
        FROM inspection_results
        WHERE recipe_id = %s
          AND overall_result = 'FAIL'
          AND time >= %s
        GROUP BY fail_reason_code
    """
    rows = await _fetch(sql, (recipe_id, since))
    return {r[0]: int(r[1]) for r in rows}


async def fetch_alarm_history(
    equipment_id: str,
    since: datetime,
) -> list[dict[str, Any]]:
    """O5-5: 장비별 알람 이력 조회."""
    sql = """
        SELECT time, hw_error_code, hw_error_detail, alarm_level,
               auto_recovery_attempted, burst_id, burst_count
        FROM hw_alarms
        WHERE equipment_id = %s
          AND time >= %s
        ORDER BY time DESC
    """
    rows = await _fetch(sql, (equipment_id, since))
    return [
        {
            "time": r[0],
            "hw_error_code": r[1],
            "hw_error_detail": r[2],
            "alarm_level": r[3],
            "auto_recovery_attempted": r[4],
            "burst_id": r[5],
            "burst_count": r[6],
        }
        for r in rows
    ]


async def count_cam_timeout_today(equipment_id: str) -> int:
    """O7 보정: R26 — 당일 CAM_TIMEOUT_ERR 카운트."""
    sql = """
        SELECT COUNT(*) FROM hw_alarms
        WHERE equipment_id = %s
          AND hw_error_code = 'CAM_TIMEOUT_ERR'
          AND time > NOW() - INTERVAL '1 day'
    """
    rows = await _fetch(sql, (equipment_id,))
    return int(rows[0][0]) if rows else 0


async def count_aggex_today(equipment_id: str) -> int:
    """O7 보정: R33 — VISION_SCORE_ERR 중 LotController 케이스 (AggEx)."""
    sql = """
        SELECT COUNT(*) FROM hw_alarms
        WHERE equipment_id = %s
          AND hw_error_code = 'VISION_SCORE_ERR'
          AND hw_error_detail LIKE '%%LotController%%'
          AND time > NOW() - INTERVAL '1 day'
    """
    rows = await _fetch(sql, (equipment_id,))
    return int(rows[0][0]) if rows else 0


async def count_eap_disconnected_week(equipment_id: str) -> int:
    """O7 보정: R34 — 주간 EAP_DISCONNECTED 카운트."""
    sql = """
        SELECT COUNT(*) FROM hw_alarms
        WHERE equipment_id = %s
          AND hw_error_code = 'EAP_DISCONNECTED'
          AND time > NOW() - INTERVAL '7 days'
    """
    rows = await _fetch(sql, (equipment_id,))
    return int(rows[0][0]) if rows else 0


async def recipe_has_history(recipe_id: str) -> bool:
    """RECIPE_CHANGED 수신 시 신규 레시피 판정 — R30 플래그."""
    sql = "SELECT 1 FROM lot_ends WHERE recipe_id = %s LIMIT 1"
    rows = await _fetch(sql, (recipe_id,))
    return len(rows) > 0


async def _fetch(sql: str, params: tuple) -> list[tuple]:
    try:
        pool = historian_pool()
    except RuntimeError as exc:
        raise HistorianUnavailable(str(exc)) from exc
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return list(await cur.fetchall())
    except Exception as exc:
        log.error("historian_query_failed", error=str(exc), sql=sql.split()[0])
        raise HistorianUnavailable(str(exc)) from exc
