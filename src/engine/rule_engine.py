"""Rule 판정 엔진 — LOT_END 트리거 오케스트레이터.

흐름:
  1. LOT_END 수신
  2. equipment_cache에서 recipe_id / operator_id 추출 (없으면 Historian 폴백)
  3. Rule DB 캐시 로드 (레시피별, __default__ 폴백)
  4. LOT-level Rules 판정 (R23, R24, R25, R35)
  5. Historian에서 LOT INSPECTION_RESULT 전량 조회
  6. Unit-level Rules 집계 + 판정 (R02~R22, R36/R37, Singulation R13~R15)
  7. Alarm/Recipe/Status Rules 판정 (O7에서 구현, 여기서 호출)
  8. 최고 심각도 채택 → Judgment 결정
  9. ORACLE_ANALYSIS 발행 (Publisher는 O8)

2차 검증 호출 포인트는 주석으로 표시됨 (O9 스텁).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from cache.alarm_counter import AlarmCounterCache
from cache.equipment_cache import EquipmentCache
from cache.lot_history import LotHistoryCache
from cache.rule_cache import DEFAULT_RECIPE, RuleCache
from db import historian_queries, rule_db
from db.historian_queries import HistorianUnavailable
from engine import alarm_rules, lot_rules, recipe_rules, status_rules, unit_rules
from models.events import LotEnd, RecipeChanged
from models.judgment import Judgment, ViolatedRule, level_to_judgment, worst
from utils.logging_config import get_logger

log = get_logger(__name__)


@dataclass
class JudgmentResult:
    message_id: str
    equipment_id: str
    lot_id: str
    recipe_id: str
    yield_pct: float
    judgment: Judgment
    violated_rules: list[ViolatedRule] = field(default_factory=list)
    yield_grade: str | None = None


class RuleEngine:
    def __init__(
        self,
        *,
        equipment_cache: EquipmentCache,
        alarm_counter: AlarmCounterCache,
        lot_history: LotHistoryCache,
        rule_cache: RuleCache,
    ) -> None:
        self.equipment_cache = equipment_cache
        self.alarm_counter = alarm_counter
        self.lot_history = lot_history
        self.rule_cache = rule_cache

    # ──────────────────────────────────────────────────────
    # Rule 캐시 로드 (RECIPE_CHANGED / LOT_END 호출)
    # ──────────────────────────────────────────────────────
    async def ensure_recipe_loaded(self, recipe_id: str) -> None:
        if self.rule_cache.get(recipe_id) is None:
            thresholds = await rule_db.load_thresholds(recipe_id)
            if thresholds:
                self.rule_cache.put(recipe_id, thresholds)
        if self.rule_cache.get(DEFAULT_RECIPE) is None:
            defaults = await rule_db.load_thresholds(DEFAULT_RECIPE)
            self.rule_cache.put(DEFAULT_RECIPE, defaults)

    async def on_recipe_changed(self, event: RecipeChanged) -> list[ViolatedRule]:
        """RECIPE_CHANGED 수신 시: 캐시 무효화 + R30/R31 즉시 평가."""
        self.rule_cache.invalidate(event.new_recipe_id)
        await self.ensure_recipe_loaded(event.new_recipe_id)
        violations: list[ViolatedRule] = []

        # R31: 숫자형 레시피 ID — 즉시 CRITICAL
        v = recipe_rules.evaluate_numeric_recipe_id(event.new_recipe_id, self.rule_cache)
        if v is not None:
            violations.append(v)

        # R30: 신규 레시피 플래그
        try:
            has_history = await historian_queries.recipe_has_history(event.new_recipe_id)
        except HistorianUnavailable:
            has_history = True  # 판단 불가 시 기존 레시피로 간주 (보수적)
        if not has_history:
            v = recipe_rules.evaluate_new_recipe_flag(event.new_recipe_id, self.rule_cache)
            if v is not None:
                violations.append(v)

        self.equipment_cache.set_recipe(
            event.equipment_id, event.new_recipe_id, event.new_recipe_version
        )
        return violations

    # ──────────────────────────────────────────────────────
    # LOT_END 메인 판정
    # ──────────────────────────────────────────────────────
    async def judge_lot_end(self, lot: LotEnd) -> JudgmentResult:
        equipment_id = lot.equipment_id
        state = self.equipment_cache.get(equipment_id)
        recipe_id = state.recipe_id if state and state.recipe_id else self._fallback_recipe(lot)

        # LOT 이력 캐시 갱신 (R25/R35)
        self.lot_history.append(
            equipment_id=equipment_id,
            lot_id=lot.lot_id,
            recipe_id=recipe_id,
            lot_status=lot.lot_status,
            yield_pct=lot.yield_pct,
            timestamp=lot.timestamp,
        )

        await self.ensure_recipe_loaded(recipe_id)

        violations: list[ViolatedRule] = []
        yield_grade: str | None = None

        # ── LOT-level Rules ─────────────────────────────
        v = lot_rules.evaluate_yield(lot, self.rule_cache, recipe_id)
        if v is not None:
            violations.append(v)
            yield_grade = v.yield_grade
        elif float(lot.yield_pct) >= 98.0:
            yield_grade = "EXCELLENT"
        else:
            yield_grade = "NORMAL"

        v = lot_rules.evaluate_duration(lot, self.rule_cache, recipe_id)
        if v is not None:
            violations.append(v)

        v = lot_rules.evaluate_aborted_streak(
            self.lot_history, equipment_id, recipe_id, self.rule_cache
        )
        if v is not None:
            violations.append(v)

        # R25: Start/End 누적 차이는 Historian 보정 쿼리 필요 → O7 alarm_rules와 묶어 처리
        # (인메모리에서는 End만 집계, 보정은 Historian lot_ends ↔ status 전환 비교)

        # ── Unit-level Rules ────────────────────────────
        try:
            rows = await historian_queries.fetch_lot_inspection_results(lot.lot_id, equipment_id)
            agg = unit_rules.aggregate_inspections(rows)
            violations.extend(unit_rules.evaluate_unit_rules(agg, self.rule_cache, recipe_id))
        except HistorianUnavailable as exc:
            log.warning(
                "historian_unavailable_unit_rules_skipped",
                lot_id=lot.lot_id,
                error=str(exc),
            )

        # ── Alarm / Status Rules ────────────────────────
        violations.extend(
            await alarm_rules.evaluate_alarm_rules(
                equipment_id=equipment_id,
                alarm_counter=self.alarm_counter,
                rule_cache=self.rule_cache,
                recipe_id=recipe_id,
                at=lot.timestamp,
            )
        )
        v = status_rules.evaluate_abnormal_transition(
            self.equipment_cache, equipment_id, self.rule_cache, recipe_id
        )
        if v is not None:
            violations.append(v)

        # ── 2차 검증 호출 포인트 (v1.0 미구현) ──────────
        # from engine.ewma_mad import compute_dynamic_threshold  # noqa: E501
        # from engine.isolation_forest import compute_anomaly_score  # noqa: E501
        # dynamic_threshold = compute_dynamic_threshold(recipe_id, "yield_pct")
        # iso_score = compute_anomaly_score(feature_vector)

        # ── 연쇄 감지: LIGHT_PWR_LOW + SIDE ET=52 상승 → 1단계 상향 ──
        alarm_rules.apply_chain_escalation(violations)

        # ── 최고 심각도 채택 ─────────────────────────────
        judgment = worst(*(level_to_judgment(v.level) for v in violations)) if violations else Judgment.NORMAL

        return JudgmentResult(
            message_id=str(uuid.uuid4()),
            equipment_id=equipment_id,
            lot_id=lot.lot_id,
            recipe_id=recipe_id,
            yield_pct=float(lot.yield_pct),
            judgment=judgment,
            violated_rules=violations,
            yield_grade=yield_grade,
        )

    def _fallback_recipe(self, lot: LotEnd) -> str:
        """STATUS 캐시 미존재 시 — Historian 보정 없이 __default__ 사용."""
        log.warning(
            "recipe_id_missing_fallback_default",
            lot_id=lot.lot_id,
            equipment_id=lot.equipment_id,
        )
        return DEFAULT_RECIPE
