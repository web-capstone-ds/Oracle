"""Rule DB CRUD.

- 레시피별 임계값 조회 (RuleThreshold 객체 반환)
- 판정 이력 INSERT (oracle_judgments)
- 임계값 변경 이력 (2차 검증 활성화 시 사용)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from cache.rule_cache import RuleThreshold
from db.pool import oracle_pool
from utils.logging_config import get_logger

log = get_logger(__name__)


async def load_thresholds(recipe_id: str) -> list[RuleThreshold]:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    """
                    SELECT rule_id, metric, warning_threshold, critical_threshold,
                           comparison_op, enabled, lot_basis, approved_by,
                           marginal_min, marginal_max
                    FROM rule_thresholds
                    WHERE recipe_id = %s AND enabled = true
                    """,
                    (recipe_id,),
                )
            except Exception:
                await conn.rollback()
                await cur.execute(
                    """
                    SELECT rule_id, metric, warning_threshold, critical_threshold,
                           comparison_op, enabled, lot_basis, approved_by,
                           NULL::double precision AS marginal_min,
                           NULL::double precision AS marginal_max
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
            marginal_min=r[8],
            marginal_max=r[9],
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


async def update_threshold(
    *,
    recipe_id: str,
    rule_id: str,
    new_warning: float | None,
    new_critical: float | None,
    approved_by: str,
    lot_basis: int,
) -> None:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE rule_thresholds
                SET warning_threshold = %s,
                    critical_threshold = %s,
                    approved_by = %s,
                    lot_basis = %s,
                    updated_at = NOW()
                WHERE recipe_id = %s AND rule_id = %s
                """,
                (new_warning, new_critical, approved_by, lot_basis, recipe_id, rule_id),
            )
        await conn.commit()


async def insert_change_history(
    *,
    recipe_id: str,
    rule_id: str,
    metric: str,
    old_warning: float | None,
    new_warning: float | None,
    old_critical: float | None = None,
    new_critical: float | None = None,
    approved_by: str | None,
    change_source: str,
    ai_basis: str | None,
) -> None:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO rule_change_history
                    (recipe_id, rule_id, metric, old_warning, new_warning,
                     old_critical, new_critical, approved_by, change_source, ai_basis)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    recipe_id,
                    rule_id,
                    metric,
                    old_warning,
                    new_warning,
                    old_critical,
                    new_critical,
                    approved_by,
                    change_source,
                    ai_basis,
                ),
            )
        await conn.commit()


async def insert_threshold_proposal(proposal: dict[str, Any]) -> None:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO threshold_proposals
                    (proposal_id, recipe_id, rule_id, metric, current_warning,
                     current_critical, proposed_warning, proposed_critical,
                     lot_basis, basis)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (proposal_id) DO NOTHING
                """,
                (
                    proposal["proposal_id"],
                    proposal["recipe_id"],
                    proposal["rule_id"],
                    proposal["metric"],
                    proposal.get("current_warning"),
                    proposal.get("current_critical"),
                    proposal.get("proposed_warning"),
                    proposal.get("proposed_critical"),
                    proposal["lot_basis"],
                    proposal.get("basis"),
                ),
            )
        await conn.commit()


async def load_threshold_proposal(proposal_id: str) -> dict[str, Any] | None:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT proposal_id, recipe_id, rule_id, metric, current_warning,
                       current_critical, proposed_warning, proposed_critical,
                       lot_basis, basis, status
                FROM threshold_proposals
                WHERE proposal_id = %s
                """,
                (proposal_id,),
            )
            row = await cur.fetchone()
    if row is None:
        return None
    return {
        "proposal_id": row[0],
        "recipe_id": row[1],
        "rule_id": row[2],
        "metric": row[3],
        "current_warning": row[4],
        "current_critical": row[5],
        "proposed_warning": row[6],
        "proposed_critical": row[7],
        "lot_basis": row[8],
        "basis": row[9],
        "status": row[10],
    }


async def mark_threshold_proposal_processed(
    proposal_id: str,
    *,
    status: str,
    processed_by: str | None,
) -> None:
    pool = oracle_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE threshold_proposals
                SET status = %s, processed_at = NOW(), processed_by = %s
                WHERE proposal_id = %s AND status = 'pending'
                """,
                (status, processed_by, proposal_id),
            )
        await conn.commit()
