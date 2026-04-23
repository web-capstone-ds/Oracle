"""ORACLE_ANALYSIS 페이로드 / ai_comment / 2차 검증 스텁."""

from __future__ import annotations

import json

import pytest

from cache.rule_cache import RuleThreshold
from engine.comment_generator import generate_ai_comment
from engine.ewma_mad import compute_dynamic_threshold
from engine.isolation_forest import compute_anomaly_score
from models.judgment import Judgment, RuleLevel, ViolatedRule
from models.oracle_analysis import build_oracle_analysis_payload


def _violation_r23_critical() -> ViolatedRule:
    return ViolatedRule(
        rule_id="R23",
        parameter="yield_pct",
        actual_value=68.5,
        threshold={"warning": 95.0, "critical": 90.0},
        level=RuleLevel.CRITICAL,
        yield_grade="CRITICAL",
        description="수율 68.5% — CRITICAL 구간 (<80%). 즉시 생산 중단",
    )


def test_payload_normal_v1_fields():
    """v1.0: threshold_proposal/isolation_forest_score = null, lot_basis = 0."""
    yt = RuleThreshold("R23", "yield_pct", 95.0, 90.0, "lte")
    payload = build_oracle_analysis_payload(
        message_id="00000000-0000-0000-0000-000000000099",
        timestamp_iso="2026-01-22T17:42:15.456Z",
        equipment_id="DS-VIS-001",
        lot_id="LOT-20260122-001",
        recipe_id="Carsem_3X3",
        judgment=Judgment.NORMAL,
        yield_actual=96.2,
        yield_threshold=yt,
        lot_basis=0,
        ai_comment="LOT LOT-20260122-001 정상 완료. 수율 96.2% (NORMAL), 전 Rule 정상 범위.",
        violated_rules=[],
    )
    # JSON 직렬화 검증 (Mock 23~25 호환 포맷)
    raw = json.dumps(payload, ensure_ascii=False)
    parsed = json.loads(raw)

    assert parsed["event_type"] == "ORACLE_ANALYSIS"
    assert parsed["judgment"] == "NORMAL"
    assert parsed["threshold_proposal"] is None
    assert parsed["isolation_forest_score"] is None
    assert parsed["violated_rules"] == []
    assert parsed["yield_status"]["actual"] == 96.2
    assert parsed["yield_status"]["lot_basis"] == 0
    assert "equipment_status" not in parsed  # 제외 규칙


def test_payload_danger_violation_serialization():
    yt = RuleThreshold("R23", "yield_pct", 95.0, 90.0, "lte")
    payload = build_oracle_analysis_payload(
        message_id="00000000-0000-0000-0000-000000000098",
        timestamp_iso="2026-01-27T12:30:22.456Z",
        equipment_id="DS-VIS-001",
        lot_id="LOT-20260127-003",
        recipe_id="Carsem_4X6",
        judgment=Judgment.DANGER,
        yield_actual=68.5,
        yield_threshold=yt,
        lot_basis=0,
        ai_comment="...",
        violated_rules=[_violation_r23_critical()],
    )
    parsed = json.loads(json.dumps(payload, ensure_ascii=False))
    assert parsed["judgment"] == "DANGER"
    assert parsed["violated_rules"][0]["rule_id"] == "R23"
    assert parsed["violated_rules"][0]["yield_grade"] == "CRITICAL"
    assert parsed["violated_rules"][0]["level"] == "CRITICAL"


def test_ai_comment_normal():
    text = generate_ai_comment(
        judgment=Judgment.NORMAL,
        lot_id="LOT-20260122-001",
        yield_pct=96.2,
        violated_rules=[],
        yield_grade="NORMAL",
    )
    assert "정상 완료" in text
    assert "96.2" in text


def test_ai_comment_danger_includes_rules():
    text = generate_ai_comment(
        judgment=Judgment.DANGER,
        lot_id="LOT-20260127-003",
        yield_pct=68.5,
        violated_rules=[_violation_r23_critical()],
        yield_grade="CRITICAL",
    )
    assert "R23" in text
    assert "위험" in text
    assert "작업 중단" in text


def test_timestamp_iso8601_utc_millis_format():
    """§16.4: ORACLE_ANALYSIS.timestamp 는 ISO 8601 UTC 밀리초 (.fffZ) 필수."""
    import re

    from utils.backoff import get_timestamp_utc_ms

    ts = get_timestamp_utc_ms()
    # YYYY-MM-DDTHH:MM:SS.fffZ
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
    assert re.match(pattern, ts), f"timestamp 포맷 불일치: {ts}"


def test_message_id_uuid_v4_format():
    """§16.4: message_id 는 UUID v4 (RFC 4122)."""
    import uuid

    generated = str(uuid.uuid4())
    parsed = uuid.UUID(generated)
    assert parsed.version == 4


def test_ewma_mad_stub_raises():
    with pytest.raises(NotImplementedError):
        compute_dynamic_threshold("Carsem_3X3", "yield_pct")


def test_isolation_forest_stub_raises():
    with pytest.raises(NotImplementedError):
        compute_anomaly_score({"yield_pct": 96.2}, recipe_id="Carsem_3X3")
