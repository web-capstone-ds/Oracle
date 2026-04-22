"""Status Rules (R01, R38c).

- R01: Heartbeat 간격 — Oracle은 heartbeat 직접 구독 안 함. Historian 조회로 보정할 수 있으나
        v1.0에서는 Alarm Rules (R34)와 묶어 크래시 감지.
- R38c: 비정상 상태 전환 — RUN → STOP 이면서 HW_ALARM(CRITICAL) 선행 없음 → CRITICAL.

R38c 판정 기준 (API §3.3):
  IDLE → RUN       정상 (LOT 시작)
  RUN  → IDLE      정상 (LOT_END)
  RUN  → STOP + HW_ALARM(CRITICAL) 동반  → 정상
  RUN  → STOP + 선행 알람 없음           → 비정상 (R38c CRITICAL)
"""

from __future__ import annotations

from datetime import timedelta

from cache.equipment_cache import EquipmentCache
from cache.rule_cache import RuleCache
from models.judgment import RuleLevel, ViolatedRule


ALARM_GRACE_SEC = 60


def evaluate_abnormal_transition(
    cache: EquipmentCache,
    equipment_id: str,
    rule_cache: RuleCache,
    recipe_id: str,
) -> ViolatedRule | None:
    state = cache.get(equipment_id)
    if state is None or not state.status_transitions:
        return None

    last_run_to_stop = None
    for prev, nxt, ts in reversed(state.status_transitions):
        if prev == "RUN" and nxt == "STOP":
            last_run_to_stop = (prev, nxt, ts)
            break
    if last_run_to_stop is None:
        return None

    _, _, transition_time = last_run_to_stop

    # 선행 알람이 grace window 이내에 있으면 정상 전환으로 간주
    if state.last_alarm_time is not None:
        alarm_delta = transition_time - state.last_alarm_time
        if timedelta(0) <= alarm_delta <= timedelta(seconds=ALARM_GRACE_SEC):
            return None

    t = rule_cache.get_threshold(recipe_id, "R38c")
    return ViolatedRule(
        rule_id="R38c",
        parameter="status_abnormal_transition",
        actual_value=1.0,
        threshold={
            "warning": t.warning_threshold if t else None,
            "critical": t.critical_threshold if t else 1.0,
        },
        level=RuleLevel.CRITICAL,
        description="RUN → STOP 무경고 전환 감지 (선행 HW_ALARM 없음)",
    )
