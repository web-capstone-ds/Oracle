"""Rule DB CRUD.

- 레시피별 임계값 조회 (RuleThreshold 객체 반환)
- 판정 이력 INSERT (oracle_judgments)
- 임계값 변경 이력 (2차 검증 활성화 시 사용)
"""

from __future__ import annotations

import json
from datetime import datetime

from cache.rule_cache import RuleThreshold
from db.pool import oracle_pool
from utils.logging_config import get_logger

log = get_logger(__name__)


async def load_thresholds(recipe_id: str) -> list[RuleThreshold]:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT rule_id, metric, warning_threshold, critical_threshold,
                       comparison_op, enabled, lot_basis, approved_by
                FROM rule_thresholds
                WHERE recipe_id = %s AND enabled = true
                """,
                (recipe_id,),
            )
            rows = await cur.fetchall()
    return [
        RuleThreshold(
            rule_id=r[0],
            metric=r[1],
            warning_threshold=r[2],
            critical_threshold=r[3],
            comparison_op=r[4],
            enabled=r[5],
            lot_basis=r[6] or 0,
            approved_by=r[7],
        )
        for r in rows
    ]


async def insert_judgment(
    *,
    time: datetime,
    message_id: str,
    equipment_id: str,
    lot_id: str,
    recipe_id: str,
    judgment: str,
    yield_actual: float,
    violated_rules: list[dict],
    ai_comment: str,
    payload_raw: dict,
    analysis_source: str = "rule_based",
) -> None:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO oracle_judgments
                    (time, message_id, equipment_id, lot_id, recipe_id,
                     judgment, yield_actual, violated_rules, ai_comment,
                     analysis_source, payload_raw)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb)
                """,
                (
                    time,
                    message_id,
                    equipment_id,
                    lot_id,
                    recipe_id,
                    judgment,
                    yield_actual,
                    json.dumps(violated_rules, ensure_ascii=False),
                    ai_comment,
                    analysis_source,
                    json.dumps(payload_raw, ensure_ascii=False),
                ),
            )
        await conn.commit()
