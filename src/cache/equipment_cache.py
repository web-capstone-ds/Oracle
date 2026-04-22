"""장비별 상태 캐시.

STATUS_UPDATE 수신 시 갱신. LOT_END 판정 시 recipe_id/operator_id 참조 및 R38c(비정상 전환).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock


@dataclass
class EquipmentState:
    equipment_id: str
    equipment_status: str = "IDLE"
    recipe_id: str = ""
    recipe_version: str = ""
    operator_id: str = ""
    lot_id: str | None = None
    uptime_sec: int = 0
    current_unit_count: int | None = None
    expected_total_units: int | None = None
    current_yield_pct: float | None = None
    last_status_time: datetime | None = None
    previous_status: str | None = None
    last_alarm_before_stop: str | None = None  # R38c 판정용: 직전 HW_ALARM code
    last_alarm_time: datetime | None = None
    status_transitions: list[tuple[str, str, datetime]] = field(default_factory=list)


class EquipmentCache:
    def __init__(self) -> None:
        self._lock = RLock()
        self._store: dict[str, EquipmentState] = {}

    def get(self, equipment_id: str) -> EquipmentState | None:
        with self._lock:
            return self._store.get(equipment_id)

    def get_or_create(self, equipment_id: str) -> EquipmentState:
        with self._lock:
            state = self._store.get(equipment_id)
            if state is None:
                state = EquipmentState(equipment_id=equipment_id)
                self._store[equipment_id] = state
            return state

    def update_status(
        self,
        equipment_id: str,
        status: str,
        recipe_id: str,
        recipe_version: str,
        operator_id: str,
        lot_id: str | None,
        uptime_sec: int,
        timestamp: datetime,
        current_unit_count: int | None = None,
        expected_total_units: int | None = None,
        current_yield_pct: float | None = None,
    ) -> tuple[str | None, str]:
        """상태를 갱신하고 (이전 상태, 현재 상태) 반환."""
        with self._lock:
            state = self.get_or_create(equipment_id)
            previous = state.equipment_status
            state.previous_status = previous
            state.equipment_status = status
            state.recipe_id = recipe_id
            state.recipe_version = recipe_version
            state.operator_id = operator_id
            state.lot_id = lot_id
            state.uptime_sec = uptime_sec
            state.current_unit_count = current_unit_count
            state.expected_total_units = expected_total_units
            state.current_yield_pct = current_yield_pct
            state.last_status_time = timestamp
            if previous != status:
                state.status_transitions.append((previous, status, timestamp))
                if len(state.status_transitions) > 50:
                    state.status_transitions = state.status_transitions[-50:]
            return previous, status

    def record_alarm(self, equipment_id: str, code: str, timestamp: datetime) -> None:
        with self._lock:
            state = self.get_or_create(equipment_id)
            state.last_alarm_before_stop = code
            state.last_alarm_time = timestamp

    def set_recipe(self, equipment_id: str, recipe_id: str, recipe_version: str) -> None:
        with self._lock:
            state = self.get_or_create(equipment_id)
            state.recipe_id = recipe_id
            state.recipe_version = recipe_version
