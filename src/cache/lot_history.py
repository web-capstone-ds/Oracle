"""LOT 이력 캐시 — R25(Start/End 불균형), R35(동일 레시피 ABORTED 연속).

LOT_END만 직접 구독하므로 Start 카운트는 인접 이벤트(STATUS_UPDATE IDLE→RUN 전환 등)로 간접 유추한다.
v1.0에서는 Oracle이 LOT Start 이벤트를 직접 보지 않으므로 Start 카운트는 Historian lot_ends 총합과
현재 관측된 LOT_END 개수의 차이로 보정 조회한다(O5). 이 캐시는 LOT_END 적재만 책임진다.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock


@dataclass
class LotRecord:
    lot_id: str
    recipe_id: str
    lot_status: str
    yield_pct: float
    timestamp: datetime


@dataclass
class LotHistoryEntry:
    equipment_id: str
    end_count: int = 0
    recent: deque[LotRecord] = field(default_factory=lambda: deque(maxlen=20))
    recent_aborted_by_recipe: dict[str, int] = field(default_factory=dict)


class LotHistoryCache:
    def __init__(self, max_recent: int = 20) -> None:
        self._lock = RLock()
        self._by_equipment: dict[str, LotHistoryEntry] = {}
        self._max_recent = max_recent

    def append(
        self,
        equipment_id: str,
        lot_id: str,
        recipe_id: str,
        lot_status: str,
        yield_pct: float,
        timestamp: datetime,
    ) -> LotHistoryEntry:
        with self._lock:
            entry = self._by_equipment.setdefault(
                equipment_id,
                LotHistoryEntry(
                    equipment_id=equipment_id,
                    recent=deque(maxlen=self._max_recent),
                ),
            )
            entry.end_count += 1
            entry.recent.append(
                LotRecord(
                    lot_id=lot_id,
                    recipe_id=recipe_id,
                    lot_status=lot_status,
                    yield_pct=yield_pct,
                    timestamp=timestamp,
                )
            )

            if lot_status == "ABORTED":
                entry.recent_aborted_by_recipe[recipe_id] = (
                    entry.recent_aborted_by_recipe.get(recipe_id, 0) + 1
                )
            else:
                entry.recent_aborted_by_recipe.pop(recipe_id, None)
            return entry

    def consecutive_aborted(self, equipment_id: str, recipe_id: str) -> int:
        with self._lock:
            entry = self._by_equipment.get(equipment_id)
            if entry is None:
                return 0
            return entry.recent_aborted_by_recipe.get(recipe_id, 0)

    def get(self, equipment_id: str) -> LotHistoryEntry | None:
        with self._lock:
            return self._by_equipment.get(equipment_id)
