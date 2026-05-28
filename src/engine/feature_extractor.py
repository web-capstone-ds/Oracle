"""Feature extraction for Phase 2 secondary validation."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LotFeatureVector:
    yield_pct: float
    side_et52_rate_pct: float
    prs_et11_rate_pct: float
    chipping_top_avg_um: float
    chipping_top_p95_um: float
    burr_height_avg_um: float
    blade_wear_index_avg: float
    takt_p95_ms: float
    cam_timeout_daily_count: int

    def to_array(self) -> list[float]:
        return [
            self.yield_pct,
            self.side_et52_rate_pct,
            self.prs_et11_rate_pct,
            self.chipping_top_avg_um,
            self.chipping_top_p95_um,
            self.burr_height_avg_um,
            self.blade_wear_index_avg,
            self.takt_p95_ms,
            float(self.cam_timeout_daily_count),
        ]

    def to_db_params(self) -> dict[str, float | int]:
        return {
            "side_et52_rate_pct": self.side_et52_rate_pct,
            "prs_et11_rate_pct": self.prs_et11_rate_pct,
            "chipping_top_avg_um": self.chipping_top_avg_um,
            "chipping_top_p95_um": self.chipping_top_p95_um,
            "burr_height_avg_um": self.burr_height_avg_um,
            "blade_wear_index_avg": self.blade_wear_index_avg,
            "takt_p95_ms": self.takt_p95_ms,
            "cam_timeout_daily_count": self.cam_timeout_daily_count,
        }


def extract_features(
    lot_end_event: Any,
    inspection_records: list[Any],
    alarm_counter: dict[str, Any] | None = None,
) -> LotFeatureVector:
    total = len(inspection_records)
    fail_records = [r for r in inspection_records if _get(r, "overall_result") == "FAIL"]

    et52_count = 0
    et11_count = 0
    chipping_tops: list[float] = []
    burrs: list[float] = []
    blade_wears: list[float] = []
    takts: list[float] = []

    for rec in inspection_records:
        takt = _to_float(_get(rec, "takt_time_ms"))
        if takt is not None:
            takts.append(takt)

    for rec in fail_records:
        detail = _get(rec, "inspection_detail") or {}
        for slot in detail.get("side_result", []) or []:
            if _safe_int(slot.get("ErrorType")) == 52:
                et52_count += 1
        for slot in detail.get("prs_result", []) or []:
            if _safe_int(slot.get("ErrorType")) == 11:
                et11_count += 1

        sing = _get(rec, "singulation") or {}
        _append_float(chipping_tops, sing.get("chipping_top_um"))
        _append_float(burrs, sing.get("burr_height_um"))
        _append_float(blade_wears, sing.get("blade_wear_index"))

    alarm_counter = alarm_counter or {}
    cam_timeout = alarm_counter.get("CAM_TIMEOUT_ERR", {})
    if not isinstance(cam_timeout, dict):
        cam_timeout = {}

    return LotFeatureVector(
        yield_pct=float(_get(lot_end_event, "yield_pct") or 0.0),
        side_et52_rate_pct=round(et52_count / total * 100, 2) if total else 0.0,
        prs_et11_rate_pct=round(et11_count / total * 100, 2) if total else 0.0,
        chipping_top_avg_um=round(statistics.mean(chipping_tops), 2) if chipping_tops else 0.0,
        chipping_top_p95_um=round(_percentile(chipping_tops, 95), 2) if chipping_tops else 0.0,
        burr_height_avg_um=round(statistics.mean(burrs), 2) if burrs else 0.0,
        blade_wear_index_avg=round(statistics.mean(blade_wears), 3) if blade_wears else 0.0,
        takt_p95_ms=round(_percentile(takts, 95), 1) if takts else 0.0,
        cam_timeout_daily_count=int(cam_timeout.get("daily_count", 0) or 0),
    )


def _percentile(data: list[float], p: int) -> float:
    if not data:
        return 0.0
    ordered = sorted(data)
    k = (len(ordered) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def _append_float(values: list[float], value: Any) -> None:
    converted = _to_float(value)
    if converted is not None:
        values.append(converted)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)

