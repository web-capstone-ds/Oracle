"""ORACLE_ANALYSIS 발행기.

- Topic: ds/{equipment_id}/oracle
- QoS: 2 (정확히 1회 전달)
- Retained: true (모바일 재연결 시 마지막 판정 즉시 복원)

ACL 정책상 oracle 계정은 ds/+/oracle 만 publish 허용.
"""

from __future__ import annotations

import json
from typing import Any

from mqtt.client import MqttManager
from utils.logging_config import get_logger

log = get_logger(__name__)


class OraclePublisher:
    def __init__(self, mqtt: MqttManager) -> None:
        self._mqtt = mqtt

    def publish_analysis(self, equipment_id: str, payload: dict[str, Any]) -> None:
        topic = f"ds/{equipment_id}/oracle"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        info = self._mqtt.publish(topic, body, qos=2, retain=True)
        log.info(
            "oracle_analysis_published",
            topic=topic,
            qos=2,
            retain=True,
            judgment=payload.get("judgment"),
            lot_id=payload.get("lot_id"),
            message_id=payload.get("message_id"),
            mid=getattr(info, "mid", None),
        )
