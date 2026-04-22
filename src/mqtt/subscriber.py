"""MQTT 구독 라우터.

- ds/+/lot   (QoS 2) → LOT_END     → 1차 검증 트리거
- ds/+/alarm (QoS 2) → HW_ALARM    → 알람 카운터 보조
- ds/+/recipe(QoS 2) → RECIPE_CHANGED → Rule DB 캐시 갱신
- ds/+/status(QoS 1) → STATUS_UPDATE → 장비 상태 캐시

빈 페이로드 수신 시: ALARM_ACK retained-clear 신호 → 무시.
`oracle` ACL에 허용된 토픽만 구독한다. INSPECTION_RESULT(ds/+/result) 구독 안 함.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from models.events import HwAlarm, LotEnd, RecipeChanged, StatusUpdate, parse_event
from mqtt.client import MqttManager
from utils.logging_config import get_logger

log = get_logger(__name__)


SubscribeTopics: list[tuple[str, int]] = [
    ("ds/+/lot", 2),
    ("ds/+/alarm", 2),
    ("ds/+/recipe", 2),
    ("ds/+/status", 1),
]


LotEndHandler = Callable[[LotEnd, str], Awaitable[None]]
AlarmHandler = Callable[[HwAlarm, str], Awaitable[None]]
RecipeHandler = Callable[[RecipeChanged, str], Awaitable[None]]
StatusHandler = Callable[[StatusUpdate, str], Awaitable[None]]


class Subscriber:
    """토픽 세그먼트(lot/alarm/recipe/status) 별 핸들러 라우터."""

    def __init__(self, mqtt: MqttManager) -> None:
        self._mqtt = mqtt
        self._lot_end: LotEndHandler | None = None
        self._alarm: AlarmHandler | None = None
        self._recipe: RecipeHandler | None = None
        self._status: StatusHandler | None = None

    def on_lot_end(self, handler: LotEndHandler) -> None:
        self._lot_end = handler

    def on_alarm(self, handler: AlarmHandler) -> None:
        self._alarm = handler

    def on_recipe(self, handler: RecipeHandler) -> None:
        self._recipe = handler

    def on_status(self, handler: StatusHandler) -> None:
        self._status = handler

    def attach(self) -> None:
        for topic, qos in SubscribeTopics:
            self._mqtt.add_subscription(topic, qos)
        self._mqtt.set_message_handler(self._dispatch)

    async def _dispatch(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        if len(payload) == 0:
            log.debug("mqtt_empty_payload_ignored", topic=topic, retain=retain)
            return

        segment = _topic_segment(topic)
        equipment_id = _topic_equipment(topic)

        try:
            raw: dict[str, Any] = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            log.warning("mqtt_json_decode_failed", topic=topic, error=str(exc))
            return

        try:
            event = parse_event(raw)
        except Exception as exc:
            log.warning(
                "mqtt_event_parse_failed",
                topic=topic,
                event_type=raw.get("event_type"),
                error=str(exc),
            )
            return

        if event is None:
            log.debug("mqtt_event_unsupported", topic=topic, event_type=raw.get("event_type"))
            return

        log.info(
            "mqtt_event_received",
            topic=topic,
            segment=segment,
            event_type=event.event_type,
            equipment_id=equipment_id,
            qos=qos,
            retain=retain,
        )

        try:
            if isinstance(event, LotEnd) and self._lot_end:
                await self._lot_end(event, equipment_id)
            elif isinstance(event, HwAlarm) and self._alarm:
                await self._alarm(event, equipment_id)
            elif isinstance(event, RecipeChanged) and self._recipe:
                await self._recipe(event, equipment_id)
            elif isinstance(event, StatusUpdate) and self._status:
                await self._status(event, equipment_id)
        except Exception as exc:
            log.error(
                "mqtt_handler_exception",
                topic=topic,
                event_type=event.event_type,
                error=str(exc),
                exc_info=True,
            )


def _topic_equipment(topic: str) -> str:
    parts = topic.split("/")
    return parts[1] if len(parts) >= 3 else ""


def _topic_segment(topic: str) -> str:
    parts = topic.split("/")
    return parts[2] if len(parts) >= 3 else ""
