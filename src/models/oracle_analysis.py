"""ORACLE_ANALYSIS 발행 DTO.

Oracle 작업명세서 §5 / API 명세서 v3.4 §9.4 기준.
- equipment_status 필드 미포함 (HEARTBEAT/CONTROL_CMD/ORACLE_ANALYSIS 제외 규칙).
- v1.0에서 threshold_proposal / isolation_forest_score 는 항상 null.
- yield_status.lot_basis = 0 (고정 임계값 사용 중).
- Mock 23~25와 필드 호환.
"""

from __future__ import annotations

from typing import Any

from cache.rule_cache import RuleThreshold
from models.judgment import Judgment, ViolatedRule


def build_oracle_analysis_payload(
    *,
    message_id: str,
    timestamp_iso: str,
    equipment_id: str,
    lot_id: str,
    recipe_id: str,
    judgment: Judgment,
    yield_actual: float,
    yield_threshold: RuleThreshold | None,
    lot_basis: int,
    ai_comment: str,
    violated_rules: list[ViolatedRule],
) -> dict[str, Any]:
    """Mock 23~25 구조 호환 ORACLE_ANALYSIS 페이로드 생성."""
    payload: dict[str, Any] = {
        "message_id": message_id,
        "event_type": "ORACLE_ANALYSIS",
        "timestamp": timestamp_iso,
        "equipment_id": equipment_id,
        "lot_id": lot_id,
        "recipe_id": recipe_id,
        "judgment": judgment.value,
        "yield_status": _yield_status(yield_actual, yield_threshold, lot_basis),
        "ai_comment": ai_comment,
        "threshold_proposal": None,
        "isolation_forest_score": None,
        "violated_rules": [v.to_payload() for v in violated_rules],
    }
    return payload


def _yield_status(
    actual: float,
    yield_threshold: RuleThreshold | None,
    lot_basis: int,
) -> dict[str, Any]:
    warn = yield_threshold.warning_threshold if yield_threshold else 95.0
    crit = yield_threshold.critical_threshold if yield_threshold else 90.0
    return {
        "actual": float(actual),
        "dynamic_threshold": {
            "normal_min": warn,
            "normal_max": 100.0,
            "warning_min": crit,
            "warning_max": warn,
        },
        "lot_basis": int(lot_basis),
    }
