"""Phase 2 secondary validation orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from db import lot_history
from engine.ewma_mad import DynamicThreshold, compute_dynamic_threshold
from engine.feature_extractor import LotFeatureVector, extract_features
from engine.isolation_forest import compute_anomaly_score
from models.judgment import Judgment, RuleLevel, ViolatedRule


YIELD_RULES = {"R23", "R08", "R09", "R30", "R35"}
_SEVERITY = {Judgment.NORMAL: 0, Judgment.WARNING: 1, Judgment.DANGER: 2}


@dataclass(frozen=True)
class SecondaryResult:
    judgment: Judgment
    ewma_judgment: Judgment | None
    if_judgment: Judgment | None
    dynamic_threshold: dict[str, Any] | None
    isolation_forest_score: float | None
    threshold_proposal: dict[str, Any] | None
    learning_status: str
    lot_basis: int
    features: LotFeatureVector


async def validate_secondary(
    lot_end_event: Any,
    inspection_records: list[Any],
    alarm_counter: dict[str, Any],
    *,
    recipe_id: str,
) -> SecondaryResult:
    features = extract_features(lot_end_event, inspection_records, alarm_counter)
    lot_count = await lot_history.count_recipe_lots(recipe_id)

    if lot_count < 5:
        return SecondaryResult(
            judgment=Judgment.NORMAL,
            ewma_judgment=None,
            if_judgment=None,
            dynamic_threshold=None,
            isolation_forest_score=None,
            threshold_proposal=None,
            learning_status="seeding",
            lot_basis=lot_count,
            features=features,
        )

    yield_history = await lot_history.get_recipe_history(recipe_id, "yield_pct", limit=50)
    dt = compute_dynamic_threshold(
        recipe_id,
        "yield_pct",
        history=yield_history,
        direction="higher_better",
    )
    ewma_judgment = evaluate_ewma(float(_get(lot_end_event, "yield_pct") or 0.0), dt)
    dynamic_threshold = threshold_to_dict(dt)
    proposal = build_threshold_proposal(recipe_id, "R23", dt)

    if lot_count < 10:
        return SecondaryResult(
            judgment=ewma_judgment,
            ewma_judgment=ewma_judgment,
            if_judgment=None,
            dynamic_threshold=dynamic_threshold,
            isolation_forest_score=None,
            threshold_proposal=proposal,
            learning_status="ewma_active",
            lot_basis=lot_count,
            features=features,
        )

    history_features = await lot_history.get_recipe_history_features(recipe_id, limit=100)
    if_score = compute_anomaly_score(
        features.to_array(),
        recipe_id=recipe_id,
        history_features=history_features,
    )
    if_judgment = evaluate_if(if_score)
    secondary_judgment = max(ewma_judgment, if_judgment, key=_severity)
    return SecondaryResult(
        judgment=secondary_judgment,
        ewma_judgment=ewma_judgment,
        if_judgment=if_judgment,
        dynamic_threshold=dynamic_threshold,
        isolation_forest_score=if_score,
        threshold_proposal=proposal,
        learning_status="full",
        lot_basis=lot_count,
        features=features,
    )


def combine_judgments(
    primary_violated_rules: list[ViolatedRule],
    ewma_judgment: Judgment | None,
    if_judgment: Judgment | None,
    lot_basis: int,
) -> Judgment:
    safety_judgment = Judgment.NORMAL
    for rule in primary_violated_rules:
        if rule.rule_id not in YIELD_RULES:
            safety_judgment = max(safety_judgment, _rule_to_judgment(rule), key=_severity)
    if if_judgment is not None:
        safety_judgment = max(safety_judgment, if_judgment, key=_severity)

    if lot_basis >= 5 and ewma_judgment is not None:
        yield_judgment = ewma_judgment
    else:
        yield_judgment = Judgment.NORMAL
        for rule in primary_violated_rules:
            if rule.rule_id in YIELD_RULES:
                yield_judgment = max(yield_judgment, _rule_to_judgment(rule), key=_severity)

    return max(safety_judgment, yield_judgment, key=_severity)


def evaluate_ewma(actual: float, dt: DynamicThreshold) -> Judgment:
    if dt.normal_min is None or actual >= dt.normal_min:
        return Judgment.NORMAL
    if dt.warning_min is None or actual >= dt.warning_min:
        return Judgment.WARNING
    return Judgment.DANGER


def evaluate_if(score: float) -> Judgment:
    if score < 0.5:
        return Judgment.NORMAL
    if score < 0.85:
        return Judgment.WARNING
    return Judgment.DANGER


def threshold_to_dict(dt: DynamicThreshold) -> dict[str, Any]:
    return {
        "normal_min": _round_or_none(dt.normal_min),
        "normal_max": _round_or_none(dt.normal_max),
        "warning_min": _round_or_none(dt.warning_min),
        "warning_max": _round_or_none(dt.warning_max),
    }


def build_threshold_proposal(
    recipe_id: str,
    rule_id: str,
    dt: DynamicThreshold,
    *,
    current_warning: float | None = None,
    current_critical: float | None = None,
) -> dict[str, Any]:
    proposed_warning = dt.normal_min if dt.normal_min is not None else dt.warning_max
    proposed_critical = dt.warning_min if dt.warning_min is not None else dt.warning_max
    return {
        "metric": dt.metric,
        "recipe_id": recipe_id,
        "rule_id": rule_id,
        "current_warning": current_warning,
        "current_critical": current_critical,
        "proposed_warning": _round_or_none(proposed_warning),
        "proposed_critical": _round_or_none(proposed_critical),
        "basis": f"{dt.lot_basis} LOT EWMA μ={dt.ewma_mean:.2f}, σ={dt.ewma_std:.2f}",
        "lot_basis": dt.lot_basis,
        "proposal_id": f"prop-{uuid.uuid4().hex[:12]}",
    }


def _rule_to_judgment(rule: ViolatedRule) -> Judgment:
    if rule.level == RuleLevel.CRITICAL:
        return Judgment.DANGER
    if rule.level == RuleLevel.WARNING:
        return Judgment.WARNING
    return Judgment.NORMAL


def _severity(judgment: Judgment) -> int:
    return _SEVERITY[judgment]


def _round_or_none(value: float | None) -> float | None:
    return round(float(value), 2) if value is not None else None


def _get(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)

