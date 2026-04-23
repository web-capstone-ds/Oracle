"""OraclePublisher 단위 테스트.

검증 대상:
- ds/{equipment_id}/oracle 토픽 생성 정확성
- QoS=2, Retained=true 파라미터 전달
- 한글 ai_comment UTF-8 보존 (ensure_ascii=False)
- JSON 직렬화 결과가 bytes 이며 다시 파싱 가능
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from cache.rule_cache import RuleThreshold
from models.judgment import Judgment, RuleLevel, ViolatedRule
from models.oracle_analysis import build_oracle_analysis_payload
from mqtt.publisher import OraclePublisher


@dataclass
class _PublishCall:
    topic: str
    payload: bytes
    qos: int
    retain: bool


class _FakeMqtt:
    def __init__(self) -> None:
        self.calls: list[_PublishCall] = []

    def publish(self, topic, payload, qos=2, retain=False):
        self.calls.append(
            _PublishCall(topic=topic, payload=payload, qos=qos, retain=retain)
        )

        class _Info:
            mid = 1

        return _Info()


def _payload_with_korean_comment() -> dict:
    yt = RuleThreshold("R23", "yield_pct", 95.0, 90.0, "lte")
    return build_oracle_analysis_payload(
        message_id="11111111-2222-3333-4444-555555555555",
        timestamp_iso="2026-01-22T17:42:15.456Z",
        equipment_id="DS-VIS-001",
        lot_id="LOT-20260122-001",
        recipe_id="Carsem_3X3",
        judgment=Judgment.DANGER,
        yield_actual=68.5,
        yield_threshold=yt,
        lot_basis=0,
        ai_comment="LOT 위험. 즉시 점검 + 작업 중단 권고.",
        violated_rules=[
            ViolatedRule(
                rule_id="R23",
                parameter="yield_pct",
                actual_value=68.5,
                threshold={"warning": 95.0, "critical": 90.0},
                level=RuleLevel.CRITICAL,
                yield_grade="CRITICAL",
                description="수율 68.5% — CRITICAL 구간 (<80%). 즉시 생산 중단",
            )
        ],
    )


def test_publisher_topic_and_qos_retain():
    """ds/{eq}/oracle, QoS 2, Retained=true 파라미터 정확 전달."""
    fake = _FakeMqtt()
    OraclePublisher(fake).publish_analysis("DS-VIS-001", _payload_with_korean_comment())

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.topic == "ds/DS-VIS-001/oracle"
    assert call.qos == 2
    assert call.retain is True


def test_publisher_payload_utf8_korean_preserved():
    """ai_comment 한글이 \\uXXXX 이스케이프 없이 UTF-8 바이트로 보존."""
    fake = _FakeMqtt()
    OraclePublisher(fake).publish_analysis("DS-VIS-001", _payload_with_korean_comment())

    body = fake.calls[0].payload
    assert isinstance(body, bytes)
    text = body.decode("utf-8")
    assert "위험" in text
    assert "수율" in text
    assert "\\u" not in text  # ASCII escape 금지


def test_publisher_payload_round_trip_json():
    """발행된 bytes 를 다시 파싱하면 원 페이로드와 동일."""
    fake = _FakeMqtt()
    payload = _payload_with_korean_comment()
    OraclePublisher(fake).publish_analysis("DS-VIS-001", payload)

    parsed = json.loads(fake.calls[0].payload.decode("utf-8"))
    assert parsed["event_type"] == "ORACLE_ANALYSIS"
    assert parsed["judgment"] == "DANGER"
    assert parsed["lot_id"] == "LOT-20260122-001"
    assert parsed["violated_rules"][0]["rule_id"] == "R23"
    # equipment_status 제외 규칙 (CLAUDE.md §1.4)
    assert "equipment_status" not in parsed


def test_publisher_topic_per_equipment():
    """장비별 토픽 분리 — 4대 동시 운영 시 N개의 다른 토픽으로 발행."""
    fake = _FakeMqtt()
    pub = OraclePublisher(fake)
    payload = _payload_with_korean_comment()
    for eq in ("DS-VIS-001", "DS-VIS-002", "DS-VIS-003", "DS-VIS-004"):
        pub.publish_analysis(eq, payload)
    assert [c.topic for c in fake.calls] == [
        "ds/DS-VIS-001/oracle",
        "ds/DS-VIS-002/oracle",
        "ds/DS-VIS-003/oracle",
        "ds/DS-VIS-004/oracle",
    ]
