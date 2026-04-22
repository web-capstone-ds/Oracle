"""알람 카운터 캐시 (R26 / R27 / R28 / R29 / R33 / R34).

- daily_count: UTC 자정 기준 리셋
- weekly_count: ISO 주간 기준 리셋 (R34 EAP_DISCONNECTED)
- consecutive: 동일 알람 연속 발생 (정상 상태 전환으로 clear)

R33: hw_error_code=VISION_SCORE_ERR + hw_error_detail에 LotController 키워드 포함
     (AggregateException 케이스만 별도 카운트)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from threading import RLock


@dataclass
class AlarmCounter:
    daily_count: int = 0
    weekly_count: int = 0
    consecutive: int = 0
    last_daily_date: date | None = None
    last_weekly_week: tuple[int, int] | None = None


@dataclass
class EquipmentAlarmCounters:
    equipment_id: str
    counters: dict[str, AlarmCounter] = field(default_factory=dict)


R33_KEY = "VISION_SCORE_ERR_AGGEX"


class AlarmCounterCache:
    def __init__(self) -> None:
        self._lock = RLock()
        self._by_equipment: dict[str, EquipmentAlarmCounters] = {}

    def _get(self, equipment_id: str, code: str) -> AlarmCounter:
        eq = self._by_equipment.setdefault(
            equipment_id, EquipmentAlarmCounters(equipment_id=equipment_id)
        )
        return eq.counters.setdefault(code, AlarmCounter())

    def increment(self, equipment_id: str, code: str, at: datetime) -> AlarmCounter:
        with self._lock:
            counter = self._get(equipment_id, code)
            self._roll_windows(counter, at)
            counter.daily_count += 1
            counter.weekly_count += 1
            counter.consecutive += 1
            return counter

    def record_aggex(self, equipment_id: str, at: datetime) -> AlarmCounter:
        """R33 전용 카운터 — hw_error_code=VISION_SCORE_ERR + LotController 키워드."""
        return self.increment(equipment_id, R33_KEY, at)

    def reset_consecutive(self, equipment_id: str, code: str) -> None:
        with self._lock:
            counter = self._get(equipment_id, code)
            counter.consecutive = 0

    def snapshot(self, equipment_id: str, code: str, at: datetime | None = None) -> AlarmCounter:
        with self._lock:
            counter = self._get(equipment_id, code)
            if at is not None:
                self._roll_windows(counter, at)
            return AlarmCounter(
                daily_count=counter.daily_count,
                weekly_count=counter.weekly_count,
                consecutive=counter.consecutive,
                last_daily_date=counter.last_daily_date,
                last_weekly_week=counter.last_weekly_week,
            )

    def seed(
        self,
        equipment_id: str,
        code: str,
        daily_count: int,
        weekly_count: int,
        at: datetime,
    ) -> None:
        """서버 재시작 후 Historian 보정값 주입용."""
        with self._lock:
            counter = self._get(equipment_id, code)
            self._roll_windows(counter, at)
            counter.daily_count = max(counter.daily_count, daily_count)
            counter.weekly_count = max(counter.weekly_count, weekly_count)

    def _roll_windows(self, counter: AlarmCounter, at: datetime) -> None:
        at_utc = at.astimezone(timezone.utc) if at.tzinfo else at.replace(tzinfo=timezone.utc)
        today = at_utc.date()
        iso_year, iso_week, _ = at_utc.isocalendar()

        if counter.last_daily_date != today:
            counter.daily_count = 0
            counter.last_daily_date = today
        if counter.last_weekly_week != (iso_year, iso_week):
            counter.weekly_count = 0
            counter.last_weekly_week = (iso_year, iso_week)
