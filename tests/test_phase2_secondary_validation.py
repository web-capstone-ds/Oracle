"""Oracle v1.1 Phase 2 secondary validation tests."""

from __future__ import annotations

from engine.ewma_mad import compute_dynamic_threshold
from engine.feature_extractor import extract_features
from engine.isolation_forest import compute_anomaly_score
from engine.secondary_validator import (
    YIELD_RULES,
    combine_judgments,
    evaluate_ewma,
    evaluate_if,
    threshold_to_dict,
)
from models.judgment import Judgment, RuleLevel, ViolatedRule
from models.oracle_analysis import build_oracle_analysis_payload


def _rule(rule_id: str, level: RuleLevel) -> ViolatedRule:
    return ViolatedRule(
        rule_id=rule_id,
        parameter="p",
        actual_value=1.0,
        threshold={"warning": 1.0, "critical": 2.0},
        level=level,
        description="test",
    )


def test_ewma_higher_better_thresholds_and_judgment():
    dt = compute_dynamic_threshold(
        "Carsem_4X6",
        "yield_pct",
        history=[70.1, 68.5, 69.2, 67.8, 68.0],
        direction="higher_better",
    )
    assert dt.lot_basis == 5
    assert dt.normal_min is not None
    assert dt.warning_min is not None
    assert dt.warning_min < dt.normal_min < dt.ewma_mean
    assert evaluate_ewma(dt.ewma_mean, dt) == Judgment.NORMAL
    assert evaluate_ewma(dt.warning_min - 0.1, dt) == Judgment.DANGER


def test_feature_extractor_handles_fail_and_pass_drop_rows():
    features = extract_features(
        {"yield_pct": 96.2},
        [
            {"overall_result": "PASS", "inspection_detail": None, "takt_time_ms": 1000},
            {
                "overall_result": "FAIL",
                "inspection_detail": {
                    "side_result": [{"ErrorType": 52}],
                    "prs_result": [{"ErrorType": 11}],
                },
                "singulation": {
                    "chipping_top_um": 42.0,
                    "burr_height_um": 7.0,
                    "blade_wear_index": 0.65,
                },
                "takt_time_ms": 2000,
            },
        ],
        {"CAM_TIMEOUT_ERR": {"daily_count": 3}},
    )
    assert features.side_et52_rate_pct == 50.0
    assert features.prs_et11_rate_pct == 50.0
    assert features.chipping_top_avg_um == 42.0
    assert features.cam_timeout_daily_count == 3
    assert len(features.to_array()) == 9


def test_isolation_forest_scores_normal_lower_than_extreme():
    history = [[70.0, 1.0, 0.5, 10.0, 12.0, 2.0, 0.2, 1000.0, 0.0] for _ in range(10)]
    normal = compute_anomaly_score(history[0], recipe_id="IF_TEST", history_features=history)
    extreme = compute_anomaly_score(
        [20.0, 99.0, 88.0, 100.0, 120.0, 30.0, 1.0, 9000.0, 20.0],
        recipe_id="IF_TEST_EXTREME",
        history_features=history,
    )
    assert 0.0 <= normal <= 1.0
    assert 0.0 <= extreme <= 1.0
    assert extreme >= normal
    assert evaluate_if(0.49) == Judgment.NORMAL
    assert evaluate_if(0.5) == Judgment.WARNING
    assert evaluate_if(0.85) == Judgment.DANGER


def test_option_c_combines_yield_and_safety_rules():
    # Stable 4X6 production: primary R23 DANGER is overridden by EWMA NORMAL.
    assert (
        combine_judgments(
            primary_violated_rules=[_rule("R23", RuleLevel.CRITICAL)],
            ewma_judgment=Judgment.NORMAL,
            if_judgment=None,
            lot_basis=15,
        )
        == Judgment.NORMAL
    )

    # Safety rules are never overridden by EWMA.
    assert (
        combine_judgments(
            primary_violated_rules=[_rule("R16", RuleLevel.CRITICAL)],
            ewma_judgment=Judgment.NORMAL,
            if_judgment=None,
            lot_basis=28,
        )
        == Judgment.DANGER
    )

    # Seeding phase keeps first-pass yield judgment.
    assert (
        combine_judgments(
            primary_violated_rules=[_rule("R23", RuleLevel.CRITICAL)],
            ewma_judgment=Judgment.NORMAL,
            if_judgment=None,
            lot_basis=3,
        )
        == Judgment.DANGER
    )

    # IF contributes as safety-side composite anomaly evidence.
    assert (
        combine_judgments(
            primary_violated_rules=[],
            ewma_judgment=Judgment.NORMAL,
            if_judgment=Judgment.WARNING,
            lot_basis=20,
        )
        == Judgment.WARNING
    )


def test_yield_rules_classification_matches_phase2_spec():
    assert YIELD_RULES == {"R23", "R08", "R09", "R30", "R35"}


def test_phase2_payload_fields_are_active():
    dt = compute_dynamic_threshold(
        "Carsem_3X3",
        "yield_pct",
        history=[96.8, 96.2, 97.1, 96.5, 95.9],
        direction="higher_better",
    )
    payload = build_oracle_analysis_payload(
        message_id="m1",
        timestamp_iso="2026-01-22T17:42:15.456Z",
        equipment_id="DS-VIS-001",
        lot_id="LOT-1",
        recipe_id="Carsem_3X3",
        judgment=Judgment.NORMAL,
        yield_actual=96.8,
        yield_threshold=None,
        lot_basis=dt.lot_basis,
        ai_comment="ok",
        violated_rules=[],
        dynamic_threshold=threshold_to_dict(dt),
        isolation_forest_score=0.42,
        threshold_proposal={
            "metric": "yield_pct",
            "proposal_id": "prop-test",
            "lot_basis": dt.lot_basis,
        },
    )
    assert payload["yield_status"]["lot_basis"] == 5
    assert payload["isolation_forest_score"] == 0.42
    assert payload["threshold_proposal"]["proposal_id"] == "prop-test"

