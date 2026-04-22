"""Alarm-level Rules (R26~R29, R33, R34) + 연쇄 감지.

카운터 출처:
- 인메모리 AlarmCounterCache (실시간 누적)
- Historian 보정 조회 (재시작 직후, 일 단위 보정)

R33 주의: hw_error_code=VISION_SCORE_ERR 중 hw_error_detail에 "LotController" 키워드를
          포함하는 AggregateException 케이스만 별도 카운트 (AlarmCounterCache.R33_KEY).
"""

from __future__ import annotations

from datetime import datetime

from cache.alarm_counter import AlarmCounterCache, R33_KEY
from cache.rule_cache import RuleCache
from db import historian_queries
from db.historian_queries import HistorianUnavailable
from engine.thresholds import evaluate_threshold
from models.judgment import RuleLevel, ViolatedRule
from utils.logging_config import get_logger

log = get_logger(__name__)


async def evaluate_alarm_rules(
    *,
    equipment_id: str,
    alarm_counter: AlarmCounterCache,
    rule_cache: RuleCache,
    recipe_id: str,
    at: datetime,
) -> list[ViolatedRule]:
    """알람 카운터 기반 Rules 판정.

    카운터가 0이면 Historian 보정 조회로 채운다 (서버 재시작 후 대비).
    """
    results: list[ViolatedRule] = []

    # R26: CAM_TIMEOUT_ERR 당일 카운트
    cam = alarm_counter.snapshot(equipment_id, "CAM_TIMEOUT_ERR", at)
    if cam.daily_count == 0:
        try:
            cam_today = await historian_queries.count_cam_timeout_today(equipment_id)
            if cam_today > 0:
                alarm_counter.seed(equipment_id, "CAM_TIMEOUT_ERR", cam_today, 0, at)
                cam = alarm_counter.snapshot(equipment_id, "CAM_TIMEOUT_ERR", at)
        except HistorianUnavailable:
            pass
    _eval_counter(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R26",
        parameter="cam_timeout_daily_count",
        value=float(cam.daily_count),
        desc_tpl="CAM_TIMEOUT_ERR 당일 {v:.0f}건 — {label}",
    )

    # R27: WRITE_FAIL 연속
    wf = alarm_counter.snapshot(equipment_id, "WRITE_FAIL", at)
    _eval_counter(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R27",
        parameter="write_fail_consecutive",
        value=float(wf.consecutive),
        desc_tpl="WRITE_FAIL 연속 {v:.0f}건 — {label}",
    )

    # R28: VISION_SCORE_ERR (NULL/HALCON #4056) 연속
    vne = alarm_counter.snapshot(equipment_id, "VISION_SCORE_ERR", at)
    _eval_counter(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R28",
        parameter="vision_score_err_null",
        value=float(vne.consecutive),
        desc_tpl="VISION_SCORE_ERR(NULL) 연속 {v:.0f}건 — {label}",
    )

    # R29: LIGHT_PWR_LOW 연속
    lp = alarm_counter.snapshot(equipment_id, "LIGHT_PWR_LOW", at)
    _eval_counter(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R29",
        parameter="light_pwr_low_consecutive",
        value=float(lp.consecutive),
        desc_tpl="LIGHT_PWR_LOW 연속 {v:.0f}건 — {label}",
    )

    # R33: AggEx 당일 카운트 (VISION_SCORE_ERR + LotController)
    aggex = alarm_counter.snapshot(equipment_id, R33_KEY, at)
    if aggex.daily_count == 0:
        try:
            agg_today = await historian_queries.count_aggex_today(equipment_id)
            if agg_today > 0:
                alarm_counter.seed(equipment_id, R33_KEY, agg_today, 0, at)
                aggex = alarm_counter.snapshot(equipment_id, R33_KEY, at)
        except HistorianUnavailable:
            pass
    _eval_counter(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R33",
        parameter="aggex_daily_count",
        value=float(aggex.daily_count),
        desc_tpl="AggregateException(LotController) 당일 {v:.0f}건 — {label}",
    )

    # R34: EAP_DISCONNECTED 주간 카운트
    eapd = alarm_counter.snapshot(equipment_id, "EAP_DISCONNECTED", at)
    if eapd.weekly_count == 0:
        try:
            eapd_week = await historian_queries.count_eap_disconnected_week(equipment_id)
            if eapd_week > 0:
                alarm_counter.seed(equipment_id, "EAP_DISCONNECTED", 0, eapd_week, at)
                eapd = alarm_counter.snapshot(equipment_id, "EAP_DISCONNECTED", at)
        except HistorianUnavailable:
            pass
    _eval_counter(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R34",
        parameter="eap_disconnected_weekly",
        value=float(eapd.weekly_count),
        desc_tpl="EAP_DISCONNECTED 주간 {v:.0f}건 — {label}",
    )

    return results


def apply_chain_escalation(violations: list[ViolatedRule]) -> None:
    """연쇄 패턴 감지 — 단일 Rule 위반이 아닌 연쇄 열화 패턴을 1단계 상향.

    Oracle 작업명세서 §12.3 기반:
      - LIGHT_PWR_LOW (R29) + SIDE ET=52 (R09/R10) → 조명 열화 유발 SIDE 저하
      - CAM_TIMEOUT (R26) + MAP fps 저하 (R20) → I/O 포화
      - WRITE_FAIL (R27) + LOT Start/End 불균형 (R25) → LOT_END 누락
      - AggEx (R33) + Heartbeat 중단 (R01) + EAP_DISCONNECTED (R34) → EAP 크래시

    연쇄 발견 시 위반된 Rule들 중 WARNING 등급을 CRITICAL로 상향.
    `violated_rules[].description`에 연쇄 근거를 덧붙인다.
    """
    ids = {v.rule_id for v in violations}

    chains = [
        ({"R29", "R09"}, "LIGHT_PWR_LOW → SIDE ET=52 비율 상승 연쇄"),
        ({"R29", "R10"}, "LIGHT_PWR_LOW → SIDE ET=52 연속 연쇄"),
        ({"R26", "R20"}, "CAM_TIMEOUT → MAP fps 저하 연쇄 (I/O 포화)"),
        ({"R27", "R25"}, "WRITE_FAIL → LOT_END 누락 연쇄"),
        ({"R33", "R01"}, "AggEx → Heartbeat 중단 연쇄 (EAP 크래시 의심)"),
        ({"R33", "R34"}, "AggEx → EAP_DISCONNECTED 연쇄"),
    ]
    for chain_ids, reason in chains:
        if chain_ids.issubset(ids):
            for v in violations:
                if v.rule_id in chain_ids and v.level == RuleLevel.WARNING:
                    v.level = RuleLevel.CRITICAL
                    v.description = f"{v.description} [연쇄 상향: {reason}]"
                    v.extras.setdefault("escalated_by", reason)


def _eval_counter(
    results: list[ViolatedRule],
    *,
    rule_cache: RuleCache,
    recipe_id: str,
    rule_id: str,
    parameter: str,
    value: float,
    desc_tpl: str,
) -> None:
    if value <= 0:
        return
    t = rule_cache.get_threshold(recipe_id, rule_id)
    if t is None:
        return
    level = evaluate_threshold(value, t)
    if level == RuleLevel.NORMAL:
        return
    label = "WARNING" if level == RuleLevel.WARNING else "CRITICAL"
    results.append(
        ViolatedRule(
            rule_id=rule_id,
            parameter=parameter,
            actual_value=value,
            threshold={"warning": t.warning_threshold, "critical": t.critical_threshold},
            level=level,
            description=desc_tpl.format(v=value, label=label),
        )
    )
