"""Unit-level Rules — Historian INSPECTION_RESULT 집계 후 판정.

대상 Rule:
- PRS: R02(XOffset), R03(YOffset), R04(TOffset), R05(ET=30율), R06(Pass율), R07(ET=11 동시슬롯)
- SIDE: R08(Pass율), R09(ET=52율), R10(ET=52 연속), R11(ET=12 발생), R12(ET=30 연속)
- Singulation: R13(chipping_top), R14(chipping_bottom), R15(burr), R16(blade_wear), R17(spindle), R18(water)
- Process: R22(takt_time P95), R37(inspection_duration P95)

PascalCase 유지: inspection_detail.prs_result[]/side_result[] 필드는 PascalCase 원본 키 사용.
PASS drop 정책: PASS 레코드에서는 inspection_detail/singulation이 None. FAIL 레코드만 집계 대상.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from cache.rule_cache import RuleCache
from db.historian_queries import InspectionRow
from engine.thresholds import evaluate_threshold
from models.judgment import RuleLevel, ViolatedRule


@dataclass
class LotAggregates:
    """LOT 전체 INSPECTION_RESULT에서 집계된 지표."""
    total_rows: int = 0
    fail_rows: int = 0

    prs_pass: int = 0
    prs_fail: int = 0
    prs_et11_rows: int = 0
    prs_et11_simultaneous_max: int = 0
    prs_et30_rows: int = 0
    prs_xoffset_abs_max: float = 0.0
    prs_yoffset_abs_max: float = 0.0
    prs_toffset_abs_max: float = 0.0

    side_pass: int = 0
    side_fail: int = 0
    side_et52_rows: int = 0
    side_et52_consecutive_max: int = 0
    side_et12_rows: int = 0
    side_et30_consecutive_max: int = 0

    chipping_top_max: float = 0.0
    chipping_bottom_max: float = 0.0
    burr_height_max: float = 0.0

    takt_times: list[int] = None  # type: ignore[assignment]
    inspection_durations: list[int] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.takt_times is None:
            self.takt_times = []
        if self.inspection_durations is None:
            self.inspection_durations = []


def aggregate_inspections(rows: Iterable[InspectionRow]) -> LotAggregates:
    agg = LotAggregates()

    side_et52_streak = 0
    side_et30_streak = 0

    for row in rows:
        agg.total_rows += 1
        if row.overall_result == "FAIL":
            agg.fail_rows += 1

        if row.takt_time_ms is not None:
            agg.takt_times.append(int(row.takt_time_ms))
        if row.inspection_duration_ms is not None:
            agg.inspection_durations.append(int(row.inspection_duration_ms))

        detail = row.inspection_detail or {}
        prs_slots: list[dict[str, Any]] = detail.get("prs_result", []) or []
        side_slots: list[dict[str, Any]] = detail.get("side_result", []) or []

        et11_slot_count_this_row = 0
        for slot in prs_slots:
            et = _safe_int(slot.get("ErrorType"))
            ok = _safe_int(slot.get("InspectionResult"))
            agg.prs_xoffset_abs_max = max(
                agg.prs_xoffset_abs_max, abs(float(slot.get("XOffset", 0) or 0))
            )
            agg.prs_yoffset_abs_max = max(
                agg.prs_yoffset_abs_max, abs(float(slot.get("YOffset", 0) or 0))
            )
            agg.prs_toffset_abs_max = max(
                agg.prs_toffset_abs_max, abs(float(slot.get("TOffset", 0) or 0))
            )
            if ok == 1:
                agg.prs_pass += 1
            else:
                agg.prs_fail += 1
            if et == 11:
                et11_slot_count_this_row += 1
            if et == 30:
                agg.prs_et30_rows += 1
        if et11_slot_count_this_row > 0:
            agg.prs_et11_rows += 1
            agg.prs_et11_simultaneous_max = max(
                agg.prs_et11_simultaneous_max, et11_slot_count_this_row
            )

        # SIDE — ET=52/12/30 슬롯 단위 검사
        row_has_et52 = False
        row_has_et30 = False
        for slot in side_slots:
            et = _safe_int(slot.get("ErrorType"))
            ok = _safe_int(slot.get("InspectionResult"))
            if ok == 1:
                agg.side_pass += 1
            else:
                agg.side_fail += 1
            if et == 52:
                agg.side_et52_rows += 1
                row_has_et52 = True
            if et == 12:
                agg.side_et12_rows += 1
            if et == 30:
                row_has_et30 = True

        side_et52_streak = side_et52_streak + 1 if row_has_et52 else 0
        side_et30_streak = side_et30_streak + 1 if row_has_et30 else 0
        agg.side_et52_consecutive_max = max(agg.side_et52_consecutive_max, side_et52_streak)
        agg.side_et30_consecutive_max = max(agg.side_et30_consecutive_max, side_et30_streak)

        sing = row.singulation or {}
        if sing:
            agg.chipping_top_max = max(
                agg.chipping_top_max, float(sing.get("chipping_top_um", 0) or 0)
            )
            agg.chipping_bottom_max = max(
                agg.chipping_bottom_max, float(sing.get("chipping_bottom_um", 0) or 0)
            )
            agg.burr_height_max = max(
                agg.burr_height_max, float(sing.get("burr_height_um", 0) or 0)
            )

    return agg


def evaluate_unit_rules(
    agg: LotAggregates,
    rule_cache: RuleCache,
    recipe_id: str,
) -> list[ViolatedRule]:
    """집계된 LotAggregates에 대해 Unit-level Rule 전체 평가."""
    results: list[ViolatedRule] = []

    # ── PRS ────────────────────────────────────────────────
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R02",
        parameter="prs_xoffset_abs",
        value=agg.prs_xoffset_abs_max,
        desc_tpl="PRS XOffset 최대 절대값 {v:.0f} — {label}",
    )
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R03",
        parameter="prs_yoffset_abs",
        value=agg.prs_yoffset_abs_max,
        desc_tpl="PRS YOffset 최대 절대값 {v:.0f} — {label}",
    )
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R04",
        parameter="prs_toffset_abs",
        value=agg.prs_toffset_abs_max,
        desc_tpl="PRS TOffset 최대 절대값 {v:.0f} — {label}",
    )
    prs_total_slots = agg.prs_pass + agg.prs_fail
    if prs_total_slots > 0:
        prs_et30_rate = (agg.prs_et30_rows / agg.total_rows) * 100.0 if agg.total_rows else 0.0
        prs_pass_rate = (agg.prs_pass / prs_total_slots) * 100.0
        _eval_simple(
            results,
            rule_cache=rule_cache,
            recipe_id=recipe_id,
            rule_id="R05",
            parameter="prs_et30_rate_pct",
            value=prs_et30_rate,
            desc_tpl="PRS ET=30 발생률 {v:.2f}% — {label}",
        )
        _eval_simple(
            results,
            rule_cache=rule_cache,
            recipe_id=recipe_id,
            rule_id="R06",
            parameter="prs_pass_rate_pct",
            value=prs_pass_rate,
            desc_tpl="PRS Pass율 {v:.2f}% — {label}",
        )
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R07",
        parameter="prs_et11_simultaneous",
        value=float(agg.prs_et11_simultaneous_max),
        desc_tpl="PRS ET=11 동시 슬롯 최대 {v:.0f}개 — {label}",
    )

    # ── SIDE ───────────────────────────────────────────────
    side_total_slots = agg.side_pass + agg.side_fail
    if side_total_slots > 0:
        side_pass_rate = (agg.side_pass / side_total_slots) * 100.0
        side_et52_rate = (agg.side_et52_rows / side_total_slots) * 100.0
        side_et12_rate = (agg.side_et12_rows / side_total_slots) * 100.0
        _eval_simple(
            results,
            rule_cache=rule_cache,
            recipe_id=recipe_id,
            rule_id="R08",
            parameter="side_pass_rate_pct",
            value=side_pass_rate,
            desc_tpl="SIDE Pass율 {v:.2f}% — {label}",
        )
        _eval_simple(
            results,
            rule_cache=rule_cache,
            recipe_id=recipe_id,
            rule_id="R09",
            parameter="side_et52_rate_pct",
            value=side_et52_rate,
            desc_tpl="SIDE ET=52 비율 {v:.2f}% — {label}"
            + (" (Teaching 미완성 의심)" if side_et52_rate > 50 else ""),
        )
        _eval_simple(
            results,
            rule_cache=rule_cache,
            recipe_id=recipe_id,
            rule_id="R11",
            parameter="side_et12_rate_pct",
            value=side_et12_rate,
            desc_tpl="SIDE ET=12 비율 {v:.2f}% — {label}",
        )
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R10",
        parameter="side_et52_consecutive",
        value=float(agg.side_et52_consecutive_max),
        desc_tpl="SIDE ET=52 연속 {v:.0f}건 — {label}",
    )
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R12",
        parameter="side_et30_consecutive",
        value=float(agg.side_et30_consecutive_max),
        desc_tpl="SIDE ET=30 연속 {v:.0f}건 — {label}",
    )

    # ── Singulation (FAIL 레코드 한정) ──────────────────────
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R13",
        parameter="chipping_top_um",
        value=agg.chipping_top_max,
        desc_tpl="Chipping(top) 최대 {v:.1f}μm — {label}",
    )
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R14",
        parameter="chipping_bottom_um",
        value=agg.chipping_bottom_max,
        desc_tpl="Chipping(bottom) 최대 {v:.1f}μm — {label}",
    )
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id="R15",
        parameter="burr_height_um",
        value=agg.burr_height_max,
        desc_tpl="Burr height 최대 {v:.1f}μm — {label}",
    )

    # ── Process P95 ─────────────────────────────────────────
    if agg.takt_times:
        p95 = _percentile(agg.takt_times, 95)
        _eval_simple(
            results,
            rule_cache=rule_cache,
            recipe_id=recipe_id,
            rule_id="R22",
            parameter="takt_time_ms",
            value=float(p95),
            desc_tpl="takt_time P95 {v:.0f}ms — {label}",
        )
    if agg.inspection_durations:
        p95d = _percentile(agg.inspection_durations, 95)
        _eval_simple(
            results,
            rule_cache=rule_cache,
            recipe_id=recipe_id,
            rule_id="R37",
            parameter="inspection_duration_ms",
            value=float(p95d),
            desc_tpl="inspection_duration P95 {v:.0f}ms — {label}",
        )

    return results


def evaluate_singulation_value(
    *,
    rule_id: str,
    parameter: str,
    value: float,
    rule_cache: RuleCache,
    recipe_id: str,
    desc_tpl: str,
) -> ViolatedRule | None:
    """O6 단위 테스트 / 외부 호출용 편의 함수."""
    results: list[ViolatedRule] = []
    _eval_simple(
        results,
        rule_cache=rule_cache,
        recipe_id=recipe_id,
        rule_id=rule_id,
        parameter=parameter,
        value=value,
        desc_tpl=desc_tpl,
    )
    return results[0] if results else None


def _eval_simple(
    results: list[ViolatedRule],
    *,
    rule_cache: RuleCache,
    recipe_id: str,
    rule_id: str,
    parameter: str,
    value: float,
    desc_tpl: str,
) -> None:
    threshold = rule_cache.get_threshold(recipe_id, rule_id)
    if threshold is None:
        return
    level = evaluate_threshold(value, threshold)
    if level == RuleLevel.NORMAL:
        return
    label = "WARNING" if level == RuleLevel.WARNING else "CRITICAL"
    results.append(
        ViolatedRule(
            rule_id=rule_id,
            parameter=parameter,
            actual_value=value,
            threshold={
                "warning": threshold.warning_threshold,
                "critical": threshold.critical_threshold,
            },
            level=level,
            description=desc_tpl.format(v=value, label=label),
        )
    )


def _safe_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _percentile(values: list[int], pct: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[k]
