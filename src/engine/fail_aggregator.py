"""Fail distribution aggregation for LOT reports."""

from __future__ import annotations

from collections import Counter
from typing import Any

from models.lot_report import FailDistributionItem


ERROR_TYPE_DESCRIPTIONS = {
    1: ("PASS", "정상"),
    11: ("DIMENSION_OUT_OF_SPEC", "PRS 픽업 오프셋 초과"),
    12: ("CHIPPING_EXCEED", "측면 칩핑 기준 초과"),
    15: ("X_AXIS_DEVIATION", "X축 과편차"),
    17: ("COMPLEX_DEVIATION", "복합 편차"),
    30: ("CAM_TIMEOUT", "카메라 응답 지연"),
    52: ("SIDE_VISION_FAIL", "SIDE 알고리즘 실패"),
}


def aggregate_fail_distribution(
    records: list[Any],
    *,
    top_n: int = 5,
) -> list[FailDistributionItem]:
    et_counter: Counter[int] = Counter()
    total_fail = 0

    for rec in records:
        if _get(rec, "overall_result") != "FAIL":
            continue
        total_fail += 1
        detail = _get(rec, "inspection_detail") or {}
        for slot in detail.get("prs_result", []) or []:
            _count_error_type(et_counter, slot)
        for slot in detail.get("side_result", []) or []:
            _count_error_type(et_counter, slot)

    if total_fail == 0:
        return []

    items: list[FailDistributionItem] = []
    for et, count in et_counter.most_common(top_n):
        code, desc = ERROR_TYPE_DESCRIPTIONS.get(et, (f"ET_{et}", f"ErrorType {et}"))
        items.append(
            FailDistributionItem(
                error_type=et,
                code=code,
                count=count,
                ratio_pct=round(count / total_fail * 100, 1),
                description=desc,
            )
        )
    return items


def _count_error_type(counter: Counter[int], slot: dict[str, Any]) -> None:
    try:
        et = int(slot.get("ErrorType"))
    except (TypeError, ValueError):
        return
    if et != 1:
        counter[et] += 1


def _get(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)

