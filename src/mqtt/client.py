from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from paho.mqtt.reasoncodes import ReasonCode

from config import settings
from utils.backoff import get_reconnect_delay
from utils.logging_config import get_logger

log = get_logger(__name__)

MessageHandler = Callable[[str, bytes, int, bool], Awaitable[None]]


@dataclass
class Subscription:
    topic: str
    qos: int


class MqttManager:
    """paho-mqtt v2 기반 비동기 연결 관리자.

    - clean_start=False, session_expiry=3600 으로 세션 유지
    - 커스텀 백오프 + ±20% jitter 재연결
    - Subscribe 토픽은 재연결 시 자동 복원
    - on_message는 asyncio 루프로 안전 브리지
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._handler: MessageHandler | None = None
        self._subscriptions: list[Subscription] = []
        self._connect_attempt = 0
        self._should_run = True
        self._connected = asyncio.Event()

        self._client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv5,
            clean_session=None,
        )
        self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.on_subscribe = self._on_subscribe

    def set_message_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    def add_subscription(self, topic: str, qos: int) -> None:
        self._subscriptions.append(Subscription(topic=topic, qos=qos))

    async def start(self) -> None:
        self._should_run = True
        await self._connect_with_backoff()
        self._client.loop_start()

    async def stop(self) -> None:
        self._should_run = False
        try:
            for sub in self._subscriptions:
                self._client.unsubscribe(sub.topic)
        except Exception as exc:
            log.warning("unsubscribe_failed", error=str(exc))
        try:
            self._client.disconnect()
        except Exception as exc:
            log.warning("mqtt_disconnect_failed", error=str(exc))
        self._client.loop_stop()
        log.info("mqtt_stopped")

    def publish(
        self,
        topic: str,
        payload: bytes | str,
        qos: int = 2,
        retain: bool = False,
    ) -> mqtt.MQTTMessageInfo:
        return self._client.publish(topic, payload=payload, qos=qos, retain=retain)

    async def wait_connected(self, timeout: float | None = None) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _connect_with_backoff(self) -> None:
        while self._should_run:
            try:
                props = Properties(PacketTypes.CONNECT)
                props.SessionExpiryInterval = settings.mqtt_session_expiry_sec

                log.info(
                    "mqtt_connecting",
                    host=settings.mqtt_broker_host,
                    port=settings.mqtt_broker_port,
                    client_id=settings.mqtt_client_id,
                    attempt=self._connect_attempt + 1,
                )
                self._client.connect(
                    host=settings.mqtt_broker_host,
                    port=settings.mqtt_broker_port,
                    keepalive=settings.mqtt_keepalive_sec,
                    clean_start=False,
                    properties=props,
                )
                return
            except Exception as exc:
                delay = get_reconnect_delay(self._connect_attempt)
                log.warning(
                    "mqtt_connect_failed",
                    error=str(exc),
                    retry_in_sec=round(delay, 2),
                    attempt=self._connect_attempt + 1,
                )
                self._connect_attempt += 1
                await asyncio.sleep(delay)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata,
        flags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        if reason_code.is_failure:
            log.error("mqtt_connect_reject", reason=str(reason_code))
            return
        self._connect_attempt = 0
        log.info(
            "mqtt_connected",
            session_present=flags.session_present if hasattr(flags, "session_present") else None,
            reason=str(reason_code),
        )
        for sub in self._subscriptions:
            self._client.subscribe(sub.topic, qos=sub.qos)
            log.info("mqtt_subscribed", topic=sub.topic, qos=sub.qos)
        self._loop.call_soon_threadsafe(self._connected.set)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata,
        disconnect_flags,
        reason_code: ReasonCode,
        properties: Properties | None,
    ) -> None:
        self._loop.call_soon_threadsafe(self._connected.clear)
        log.warning(
            "mqtt_disconnected",
            reason=str(reason_code),
            will_retry=self._should_run,
        )
        if not self._should_run:
            return
        delay = get_reconnect_delay(self._connect_attempt)
        self._connect_attempt += 1
        log.info("mqtt_reconnect_scheduled", delay_sec=round(delay, 2))
        threading.Timer(delay, self._safe_reconnect).start()

    def _safe_reconnect(self) -> None:
        if not self._should_run:
            return
        try:
            self._client.reconnect()
        except Exception as exc:
            log.warning("mqtt_reconnect_failed", error=str(exc))

    def _on_subscribe(self, client, userdata, mid, reason_code_list, properties) -> None:
        log.debug("mqtt_subscribe_ack", mid=mid)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata,
        msg: mqtt.MQTTMessage,
    ) -> None:
        if self._handler is None:
            return
        coro = self._handler(msg.topic, msg.payload, msg.qos, msg.retain)
        asyncio.run_coroutine_threadsafe(coro, self._loop)
