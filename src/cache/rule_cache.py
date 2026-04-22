"""Rule DB 임계값 캐시.

- recipe_id별 독립 캐시. 미등록 레시피는 __default__로 폴백.
- TTL 기반 만료 (기본 300초). RECIPE_CHANGED 수신 시 즉시 무효화.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import RLock


DEFAULT_RECIPE = "__default__"


@dataclass(frozen=True)
class RuleThreshold:
    rule_id: str
    metric: str
    warning_threshold: float | None
    critical_threshold: float | None
    comparison_op: str  # gte / lte / abs_gte / eq
    enabled: bool = True
    lot_basis: int = 0
    approved_by: str | None = None


@dataclass
class _CacheEntry:
    thresholds: dict[str, RuleThreshold]  # rule_id → threshold
    loaded_at: float


class RuleCache:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._lock = RLock()
        self._ttl = ttl_seconds
        self._entries: dict[str, _CacheEntry] = {}

    def put(self, recipe_id: str, thresholds: list[RuleThreshold]) -> None:
        with self._lock:
            self._entries[recipe_id] = _CacheEntry(
                thresholds={t.rule_id: t for t in thresholds},
                loaded_at=time.monotonic(),
            )

    def get(self, recipe_id: str) -> dict[str, RuleThreshold] | None:
        with self._lock:
            entry = self._entries.get(recipe_id)
            if entry is None:
                return None
            if time.monotonic() - entry.loaded_at > self._ttl:
                self._entries.pop(recipe_id, None)
                return None
            return dict(entry.thresholds)

    def invalidate(self, recipe_id: str) -> None:
        with self._lock:
            self._entries.pop(recipe_id, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def get_threshold(
        self,
        recipe_id: str,
        rule_id: str,
    ) -> RuleThreshold | None:
        """레시피 미등록 시 __default__ 폴백 포함 — 상위에서 2번 호출하지 않도록."""
        thresholds = self.get(recipe_id)
        if thresholds and rule_id in thresholds:
            return thresholds[rule_id]
        defaults = self.get(DEFAULT_RECIPE)
        if defaults and rule_id in defaults:
            return defaults[rule_id]
        return None
