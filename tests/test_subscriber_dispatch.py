"""Subscriber 라우터 단위 테스트.

검증 대상:
- 빈 페이로드 (ALARM_ACK retained clear) → 무시, 핸들러 호출 안 됨
- JSON 디코딩 실패 → 무시, 핸들러 호출 안 됨, 예외 미전파
- 미지원 event_type → 무시
- 토픽 세그먼트 → 핸들러 라우팅 (lot/alarm/recipe/status)
- 핸들러 내부 예외 → swallow + 로그 (전체 파이프라인 정지 금지)
"""

from __future__ import annotations

import json

import pytest

from models.events import HwAlarm, LotEnd, RecipeChanged, StatusUpdate
from mqtt.subscriber import Subscriber


class _FakeMqtt:
    def __init__(self) -> None:
        self.subs: list[tuple[str, int]] = []
        self.handler = None

    def add_subscription(self, topic: str, qos: int) -> None:
        self.subs.append((topic, qos))

    def set_message_handler(self, handler) -> None:
        self.handler = handler


def _attach() -> tuple[Subscriber, _FakeMqtt, dict]:
    fake = _FakeMqtt()
    sub = Subscriber(fake)
    captured: dict[str, list] = {"lot": [], "alarm": [], "recipe": [], "status": []}

    async def on_lot(ev: LotEnd, eq: str) -> None:
        captured["lot"].append((ev, eq))

    async def on_alarm(ev: HwAlarm, eq: str) -> None:
        captured["alarm"].append((ev, eq))

    async def on_recipe(ev: RecipeChanged, eq: str) -> None:
        captured["recipe"].append((ev, eq))

    async def on_status(ev: StatusUpdate, eq: str) -> None:
        captured["status"].append((ev, eq))

    sub.on_lot_end(on_lot)
    sub.on_alarm(on_alarm)
    sub.on_recipe(on_recipe)
    sub.on_status(on_status)
    sub.attach()
    return sub, fake, captured


def test_attach_registers_4_topics_with_correct_qos():
    """spec §3.1: status QoS 1, lot/alarm/recipe QoS 2."""
    _, fake, _ = _attach()
    qos_map = dict(fake.subs)
    assert qos_map["ds/+/lot"] == 2
    assert qos_map["ds/+/alarm"] == 2
    assert qos_map["ds/+/recipe"] == 2
    assert qos_map["ds/+/status"] == 1
    # ds/+/result 는 ACL 위반 — 구독 금지
    assert "ds/+/result" not in qos_map


@pytest.mark.asyncio
async def test_empty_payload_ignored():
    """ALARM_ACK retained clear (빈 페이로드) → 무시. 핸들러 미호출."""
    _, fake, captured = _attach()
    await fake.handler("ds/DS-VIS-001/alarm", b"", 2, True)
    assert captured["alarm"] == []


@pytest.mark.asyncio
async def test_invalid_json_swallowed():
    """JSON 디코딩 실패 → 핸들러 미호출, 예외 미전파."""
    _, fake, captured = _attach()
    await fake.handler("ds/DS-VIS-001/lot", b"not-json", 2, False)
    assert captured["lot"] == []


@pytest.mark.asyncio
async def test_unsupported_event_type_ignored():
    """이벤트 정의서에 없는 event_type → 무시."""
    _, fake, captured = _attach()
    body = json.dumps(
        {
            "message_id": "00000000-0000-0000-0000-000000000001",
            "event_type": "UNKNOWN_EVENT",
            "timestamp": "2026-01-22T17:00:00.000Z",
            "equipment_id": "DS-VIS-001",
        }
    ).encode("utf-8")
    await fake.handler("ds/DS-VIS-001/lot", body, 2, False)
    assert captured["lot"] == []


@pytest.mark.asyncio
async def test_lot_end_routed_to_lot_handler():
    """LOT_END → on_lot 핸들러 호출, equipment_id 토픽 세그먼트 추출."""
    _, fake, captured = _attach()
    body = json.dumps(
        {
            "message_id": "00000000-0000-0000-0000-000000000099",
            "event_type": "LOT_END",
            "timestamp": "2026-01-22T17:42:15.123Z",
            "equipment_id": "DS-VIS-001",
            "equipment_status": "IDLE",
            "lot_id": "LOT-20260122-001",
            "lot_status": "COMPLETED",
            "total_units": 2792,
            "pass_count": 2686,
            "fail_count": 106,
            "yield_pct": 96.2,
            "lot_duration_sec": 4920,
        }
    ).encode("utf-8")
    await fake.handler("ds/DS-VIS-001/lot", body, 2, False)

    assert len(captured["lot"]) == 1
    event, eq = captured["lot"][0]
    assert eq == "DS-VIS-001"
    assert event.lot_id == "LOT-20260122-001"
    assert event.yield_pct == 96.2


@pytest.mark.asyncio
async def test_handler_exception_does_not_propagate():
    """핸들러 내부 예외 → swallow. 다음 메시지 처리 가능."""
    fake = _FakeMqtt()
    sub = Subscriber(fake)
    calls = []

    async def boom(ev, eq):
        calls.append("boom")
        raise RuntimeError("simulated handler failure")

    sub.on_lot_end(boom)
    sub.attach()

    body = json.dumps(
        {
            "message_id": "00000000-0000-0000-0000-000000000099",
            "event_type": "LOT_END",
            "timestamp": "2026-01-22T17:42:15.123Z",
            "equipment_id": "DS-VIS-001",
            "equipment_status": "IDLE",
            "lot_id": "LOT-X",
            "lot_status": "COMPLETED",
            "total_units": 100,
            "pass_count": 96,
            "fail_count": 4,
            "yield_pct": 96.0,
            "lot_duration_sec": 60,
        }
    ).encode("utf-8")
    # 예외가 외부로 전파되면 await 가 raise — 통과만으로 검증 충분
    await fake.handler("ds/DS-VIS-001/lot", body, 2, False)
    assert calls == ["boom"]
