"""DS Oracle 판정 엔진 오케스트레이터.

전체 파이프라인 배선 + Graceful Shutdown 책임:

    [MQTT 구독] ──► [Subscriber 라우터] ──► [RuleEngine 판정] ──► [Publisher 발행]
        │                  │                       │                   │
        └──► EquipmentCache, AlarmCounter, LotHistoryCache 갱신
                           │                       │
                           └──► Oracle DB (oracle_judgments INSERT)
                                                   │
                                                   └──► Historian DB (read-only 조회)

Shutdown 순서 (CLAUDE.md §12.2):
    1. MQTT 구독 해제 (신규 메시지 차단)
    2. 진행 중 판정 task 완료 대기 (shutdown_timeout_sec)
    3. DB 풀 close
    4. MQTT 연결 disconnect
"""

from __future__ import annotations

import asyncio

from cache.alarm_counter import AlarmCounterCache, R33_KEY
from cache.equipment_cache import EquipmentCache
from cache.lot_history import LotHistoryCache
from cache.rule_cache import DEFAULT_RECIPE, RuleCache
from config import settings
from db import rule_db
from db.pool import close_pools, open_pools
from engine.comment_generator import generate_ai_comment
from engine.rule_engine import JudgmentResult, RuleEngine
from models.events import HwAlarm, LotEnd, RecipeChanged, StatusUpdate
from models.judgment import Judgment
from models.oracle_analysis import build_oracle_analysis_payload
from mqtt.client import MqttManager
from mqtt.publisher import OraclePublisher
from mqtt.subscriber import Subscriber
from utils.backoff import get_timestamp_utc_ms
from utils.logging_config import get_logger

log = get_logger(__name__)


class OracleApp:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

        self.equipment_cache = EquipmentCache()
        self.alarm_counter = AlarmCounterCache()
        self.lot_history = LotHistoryCache()
        self.rule_cache = RuleCache(ttl_seconds=settings.rule_cache_ttl_sec)

        self.mqtt = MqttManager(loop=loop)
        self.subscriber = Subscriber(self.mqtt)
        self.publisher = OraclePublisher(self.mqtt)

        self.engine = RuleEngine(
            equipment_cache=self.equipment_cache,
            alarm_counter=self.alarm_counter,
            lot_history=self.lot_history,
            rule_cache=self.rule_cache,
        )

        self._pending: set[asyncio.Task] = set()
        self._stopping = False

    # ──────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────
    async def start(self) -> None:
        await open_pools()
        # __default__ Rule DB 초기 로드 (실패 시 캐시 비어있음 → 판정 시 lazy 재시도)
        try:
            defaults = await rule_db.load_thresholds(DEFAULT_RECIPE)
            self.rule_cache.put(DEFAULT_RECIPE, defaults)
            log.info("rule_cache_default_loaded", count=len(defaults))
        except Exception as exc:
            log.error("rule_cache_default_load_failed", error=str(exc))

        self.subscriber.on_lot_end(self._on_lot_end)
        self.subscriber.on_alarm(self._on_alarm)
        self.subscriber.on_recipe(self._on_recipe)
        self.subscriber.on_status(self._on_status)
        self.subscriber.attach()

        await self.mqtt.start()
        log.info("oracle_app_started")

    async def stop(self) -> None:
        self._stopping = True
        log.info("oracle_app_stopping", pending=len(self._pending))

        # 1. MQTT 구독 해제 + 연결 종료
        await self.mqtt.stop()

        # 2. 진행 중 판정 task 완료 대기
        if self._pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._pending, return_exceptions=True),
                    timeout=settings.shutdown_timeout_sec,
                )
            except asyncio.TimeoutError:
                log.error(
                    "shutdown_pending_timeout",
                    pending=len(self._pending),
                    timeout_sec=settings.shutdown_timeout_sec,
                )

        # 3. DB 풀 close
        await close_pools()
        log.info("oracle_app_stopped")

    # ──────────────────────────────────────────────────
    # MQTT 이벤트 핸들러
    # ──────────────────────────────────────────────────
    async def _on_status(self, event: StatusUpdate, equipment_id: str) -> None:
        prev, curr = self.equipment_cache.update_status(
            equipment_id=equipment_id,
            status=event.equipment_status,
            recipe_id=event.recipe_id,
            recipe_version=event.recipe_version,
            operator_id=event.operator_id,
            lot_id=event.lot_id,
            uptime_sec=event.uptime_sec,
            timestamp=event.timestamp,
            current_unit_count=event.current_unit_count,
            expected_total_units=event.expected_total_units,
            current_yield_pct=event.current_yield_pct,
        )
        if prev != curr:
            log.info(
                "equipment_status_transition",
                equipment_id=equipment_id,
                prev=prev,
                curr=curr,
            )

    async def _on_alarm(self, event: HwAlarm, equipment_id: str) -> None:
        self.alarm_counter.increment(equipment_id, event.hw_error_code, event.timestamp)
        if (
            event.hw_error_code == "VISION_SCORE_ERR"
            and "LotController" in (event.hw_error_detail or "")
        ):
            self.alarm_counter.record_aggex(equipment_id, event.timestamp)
        # R38c 판정 보조: 직전 알람 timestamp 기록
        if event.alarm_level == "CRITICAL":
            self.equipment_cache.record_alarm(
                equipment_id, event.hw_error_code, event.timestamp
            )

    async def _on_recipe(self, event: RecipeChanged, equipment_id: str) -> None:
        violations = await self.engine.on_recipe_changed(event)
        if not violations:
            return
        # RECIPE_CHANGED만으로도 R31 즉시 발행 가능
        log.warning(
            "recipe_change_violations",
            equipment_id=equipment_id,
            new_recipe_id=event.new_recipe_id,
            count=len(violations),
            rule_ids=[v.rule_id for v in violations],
        )

    async def _on_lot_end(self, event: LotEnd, equipment_id: str) -> None:
        if self._stopping:
            log.warning("lot_end_dropped_stopping", lot_id=event.lot_id)
            return

        task = asyncio.create_task(self._judge_and_publish(event, equipment_id))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    # ──────────────────────────────────────────────────
    # 판정 + 발행 파이프라인
    # ──────────────────────────────────────────────────
    async def _judge_and_publish(self, lot: LotEnd, equipment_id: str) -> None:
        try:
            result: JudgmentResult = await self.engine.judge_lot_end(lot)
        except Exception as exc:
            log.error(
                "judgment_failed",
                lot_id=lot.lot_id,
                equipment_id=equipment_id,
                error=str(exc),
                exc_info=True,
            )
            return

        ai_comment = generate_ai_comment(
            judgment=result.judgment,
            lot_id=result.lot_id,
            yield_pct=result.yield_pct,
            violated_rules=result.violated_rules,
            yield_grade=result.yield_grade,
        )
        yield_threshold = self.rule_cache.get_threshold(result.recipe_id, "R23")
        payload = build_oracle_analysis_payload(
            message_id=result.message_id,
            timestamp_iso=get_timestamp_utc_ms(),
            equipment_id=result.equipment_id,
            lot_id=result.lot_id,
            recipe_id=result.recipe_id,
            judgment=result.judgment,
            yield_actual=result.yield_pct,
            yield_threshold=yield_threshold,
            lot_basis=yield_threshold.lot_basis if yield_threshold else 0,
            ai_comment=ai_comment,
            violated_rules=result.violated_rules,
        )

        # 발행 (QoS 2 + Retained=true)
        try:
            self.publisher.publish_analysis(equipment_id, payload)
        except Exception as exc:
            log.error("publish_failed", lot_id=lot.lot_id, error=str(exc))

        # 판정 이력 INSERT (실패해도 판정 자체는 발행됨)
        try:
            await rule_db.insert_judgment(
                time=lot.timestamp,
                message_id=result.message_id,
                equipment_id=result.equipment_id,
                lot_id=result.lot_id,
                recipe_id=result.recipe_id,
                judgment=result.judgment.value,
                yield_actual=result.yield_pct,
                violated_rules=[v.to_payload() for v in result.violated_rules],
                ai_comment=ai_comment,
                payload_raw=payload,
            )
        except Exception as exc:
            log.error("judgment_insert_failed", lot_id=lot.lot_id, error=str(exc))

        # WARNING/DANGER 알람 카운터 reset 정책: 정상 LOT 완료 시 consecutive 카운터 정리
        if result.judgment == Judgment.NORMAL:
            for code in ("WRITE_FAIL", "VISION_SCORE_ERR", "LIGHT_PWR_LOW", R33_KEY):
                self.alarm_counter.reset_consecutive(equipment_id, code)
