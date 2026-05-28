"""MARGINAL unit detection for LOT reports.

Phase 1 is intentionally conservative: PASS rows usually have dropped detail
payloads, so this detector only observes parameters present in the fetched
Historian rows.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from cache.rule_cache import RuleThreshold
from models.lot_report import MarginalParameterStat, MarginalUnitInfo


PARAMETER_RULES: dict[str, str] = {
    "chipping_top_um": "R13",
    "chipping_bottom_um": "R14",
    "burr_height_um": "R15",
    "blade_wear_index": "R16",
    "x_offset_um": "R02",
    "y_offset_um": "R03",
}

SINGULATION_EXTRACTORS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "chipping_top_um": lambda r: r.get("chipping_top_um"),
    "chipping_bottom_um": lambda r: r.get("chipping_bottom_um"),
    "burr_height_um": lambda r: r.get("burr_height_um"),
    "blade_wear_index": lambda r: r.get("blade_wear_index"),
}


def detect_marginal_units(
    records: list[Any],
    thresholds: dict[str, RuleThreshold],
    *,
    top_n: int = 3,
) -> MarginalUnitInfo:
    marginal_units: set[str] = set()
    param_counts: dict[str, int] = defaultdict(int)
    total_units = len(records)

    for index, rec in enumerate(records):
        unit_id = str(_get(rec, "unit_id") or f"row-{index}")
        singulation = _get(rec, "singulation") or {}

        for param, extractor in SINGULATION_EXTRACTORS.items():
            _maybe_count_marginal(
                param_counts, marginal_units, unit_id, param, extractor(singulation), thresholds
            )

        detail = _get(rec, "inspection_detail") or {}
        for slot in detail.get("prs_result", []) or []:
            _maybe_count_marginal(
                param_counts, marginal_units, unit_id, "x_offset_um", slot.get("XOffset"), thresholds
            )
            _maybe_count_marginal(
                param_counts, marginal_units, unit_id, "y_offset_um", slot.get("YOffset"), thresholds
            )

    marginal_count = len(marginal_units)
    ratio = round(marginal_count / total_units * 100, 2) if total_units else 0.0
    top_parameters = [
        MarginalParameterStat(
            parameter=name,
            marginal_range=_format_range(name, thresholds),
            count=count,
        )
        for name, count in sorted(param_counts.items(), key=lambda item: item[1], reverse=True)[
            :top_n
        ]
    ]
    return MarginalUnitInfo(
        count=marginal_count,
        ratio_pct=ratio,
        top_parameters=top_parameters,
    )


def _maybe_count_marginal(
    counts: dict[str, int],
    units: set[str],
    unit_id: str,
    param: str,
    raw_value: Any,
    thresholds: dict[str, RuleThreshold],
) -> None:
    value = _to_float(raw_value)
    if value is None:
        return
    threshold = thresholds.get(PARAMETER_RULES[param])
    if threshold is None or threshold.marginal_min is None or threshold.marginal_max is None:
        return
    abs_value = abs(value)
    if threshold.marginal_min <= abs_value < threshold.marginal_max:
        units.add(unit_id)
        counts[param] += 1


def _format_range(param: str, thresholds: dict[str, RuleThreshold]) -> str:
    threshold = thresholds.get(PARAMETER_RULES[param])
    if threshold is None or threshold.marginal_min is None or threshold.marginal_max is None:
        return ""
    return f"{threshold.marginal_min:g}~{threshold.marginal_max:g}"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)

