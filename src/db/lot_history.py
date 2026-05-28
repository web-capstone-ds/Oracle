"""LOT history series storage for Phase 2 secondary validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db.pool import oracle_pool
from engine.feature_extractor import LotFeatureVector
from utils.logging_config import get_logger

log = get_logger(__name__)

FEATURE_COLUMNS = [
    "yield_pct",
    "side_et52_rate_pct",
    "prs_et11_rate_pct",
    "chipping_top_avg_um",
    "chipping_top_p95_um",
    "burr_height_avg_um",
    "blade_wear_index_avg",
    "takt_p95_ms",
    "cam_timeout_daily_count",
]


async def get_recipe_history(
    recipe_id: str,
    metric: str,
    *,
    limit: int = 50,
    exclude_aborted: bool = True,
) -> list[float]:
    if metric not in FEATURE_COLUMNS:
        raise ValueError(f"Unsupported history metric: {metric}")
    sql = f"""
        SELECT {metric}
        FROM lot_history_series
        WHERE recipe_id = %s
          AND {metric} IS NOT NULL
        ORDER BY lot_end_time DESC
        LIMIT %s
    """
    rows = await _fetch(sql, (recipe_id, limit))
    return [float(r[0]) for r in rows]


async def get_recipe_history_features(recipe_id: str, *, limit: int = 100) -> list[list[float]]:
    cols = ", ".join(FEATURE_COLUMNS)
    rows = await _fetch(
        f"""
        SELECT {cols}
        FROM lot_history_series
        WHERE recipe_id = %s
        ORDER BY lot_end_time DESC
        LIMIT %s
        """,
        (recipe_id, limit),
    )
    return [[float(v or 0.0) for v in row] for row in rows]


async def count_recipe_lots(recipe_id: str) -> int:
    rows = await _fetch(
        "SELECT COUNT(*) FROM lot_history_series WHERE recipe_id = %s",
        (recipe_id,),
    )
    return int(rows[0][0]) if rows else 0


async def insert_lot_history(
    *,
    lot_id: str,
    equipment_id: str,
    recipe_id: str,
    lot_end_time: datetime,
    yield_pct: float,
    total_units: int,
    fail_count: int,
    lot_duration_sec: int,
    features: LotFeatureVector,
) -> None:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO lot_history_series
                    (lot_id, equipment_id, recipe_id, lot_end_time, yield_pct,
                     total_units, fail_count, lot_duration_sec,
                     side_et52_rate_pct, prs_et11_rate_pct,
                     chipping_top_avg_um, chipping_top_p95_um,
                     burr_height_avg_um, blade_wear_index_avg,
                     takt_p95_ms, cam_timeout_daily_count)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (lot_id, equipment_id) DO NOTHING
                """,
                (
                    lot_id,
                    equipment_id,
                    recipe_id,
                    lot_end_time,
                    yield_pct,
                    total_units,
                    fail_count,
                    lot_duration_sec,
                    features.side_et52_rate_pct,
                    features.prs_et11_rate_pct,
                    features.chipping_top_avg_um,
                    features.chipping_top_p95_um,
                    features.burr_height_avg_um,
                    features.blade_wear_index_avg,
                    features.takt_p95_ms,
                    features.cam_timeout_daily_count,
                ),
            )
        await conn.commit()


async def _fetch(sql: str, params: tuple[Any, ...]) -> list[tuple]:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

