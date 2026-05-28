"""Oracle v1.1 Phase 1 LOT report tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from cache.alarm_counter import AlarmCounterCache
from cache.equipment_cache import EquipmentCache
from cache.lot_history import LotHistoryCache
from cache.rule_cache import RuleCache
from cache.rule_cache import RuleThreshold
from engine.comment import get_comment_generator
from engine.comment.base import CommentContext
from engine.comment.template_generator import TemplateCommentGenerator
from engine.fail_aggregator import aggregate_fail_distribution
from engine.marginal_detector import detect_marginal_units
from engine.recommendation_engine import RecommendationEngine
from engine.rule_engine import RuleEngine
from models.events import LotEnd
from models.judgment import Judgment, RuleLevel, ViolatedRule
from models.lot_report import (
    FailDistributionItem,
    LotReport,
    LotReportSummary,
    MarginalUnitInfo,
    Recommendation,
    ReportTransparency,
)
from models.oracle_analysis import build_oracle_analysis_payload


def test_payload_includes_lot_report_null_by_default():
    payload = build_oracle_analysis_payload(
        message_id="00000000-0000-0000-0000-000000000101",
        timestamp_iso="2026-01-22T17:42:15.456Z",
        equipment_id="DS-VIS-001",
        lot_id="LOT-1",
        recipe_id="Carsem_3X3",
        judgment=Judgment.NORMAL,
        yield_actual=99.0,
        yield_threshold=None,
        lot_basis=0,
        ai_comment="ok",
        violated_rules=[],
    )
    assert "lot_report" in payload
    assert payload["lot_report"] is None


def test_payload_serializes_full_lot_report():
    report = LotReport(
        summary=LotReportSummary(
            total_units=100,
            pass_count=95,
            fail_count=5,
            marginal_count=2,
            yield_pct=95.0,
            duration_sec=3600,
            uph=100,
        ),
        fail_distribution=[
            FailDistributionItem(
                error_type=52,
                code="SIDE_VISION_FAIL",
                count=5,
                ratio_pct=100.0,
                description="SIDE 알고리즘 실패",
            )
        ],
        marginal_units=MarginalUnitInfo(count=2, ratio_pct=2.0, top_parameters=[]),
        recommendations=[
            Recommendation(
                priority="HIGH",
                action="해당 레시피 Teaching 재수행",
                basis="SIDE 알고리즘 실패 ET=52 100.0%",
            )
        ],
        transparency=ReportTransparency(
            rule_db_version="v2.4",
            lot_basis=0,
            basis_note="고정 임계값 사용 중. 2차 검증 미활성 (Phase 2 예정)",
        ),
    )
    payload = build_oracle_analysis_payload(
        message_id="00000000-0000-0000-0000-000000000102",
        timestamp_iso="2026-01-22T17:42:15.456Z",
        equipment_id="DS-VIS-001",
        lot_id="LOT-1",
        recipe_id="Carsem_3X3",
        judgment=Judgment.WARNING,
        yield_actual=95.0,
        yield_threshold=None,
        lot_basis=0,
        ai_comment="ok",
        violated_rules=[],
        lot_report=report,
    )
    parsed = json.loads(json.dumps(payload, ensure_ascii=False))
    assert parsed["lot_report"]["summary"]["marginal_count"] == 2
    assert parsed["lot_report"]["fail_distribution"][0]["error_type"] == 52
    assert parsed["lot_report"]["transparency"]["lot_basis"] == 0


def test_fail_aggregator_counts_error_types_and_limits_top_n():
    records = [
        {"overall_result": "PASS", "inspection_detail": None},
        {
            "overall_result": "FAIL",
            "inspection_detail": {
                "prs_result": [{"ErrorType": 11}, {"ErrorType": 1}],
                "side_result": [{"ErrorType": 52}, {"ErrorType": 52}],
            },
        },
        {
            "overall_result": "FAIL",
            "inspection_detail": {
                "prs_result": [{"ErrorType": 12}],
                "side_result": [{"ErrorType": 52}],
            },
        },
    ]
    result = aggregate_fail_distribution(records, top_n=2)
    assert [item.error_type for item in result] == [52, 11]
    assert result[0].count == 3
    assert result[0].ratio_pct == 150.0


def test_marginal_detector_deduplicates_units_and_sorts_parameters():
    thresholds = {
        "R02": RuleThreshold("R02", "x", 300.0, 400.0, "abs_gte", marginal_min=250.0, marginal_max=300.0),
        "R13": RuleThreshold("R13", "chip", 50.0, 60.0, "gte", marginal_min=40.0, marginal_max=50.0),
    }
    records = [
        {
            "unit_id": "U1",
            "inspection_detail": {"prs_result": [{"XOffset": 260}]},
            "singulation": {"chipping_top_um": 42.0},
        },
        {
            "unit_id": "U2",
            "inspection_detail": {"prs_result": [{"XOffset": 270}]},
            "singulation": {},
        },
    ]
    result = detect_marginal_units(records, thresholds)
    assert result.count == 2
    assert result.ratio_pct == 100.0
    assert result.top_parameters[0].parameter == "x_offset_um"
    assert result.top_parameters[0].count == 2


def test_recommendation_engine_prioritizes_and_deduplicates():
    violation = ViolatedRule(
        rule_id="R23",
        parameter="yield_pct",
        actual_value=70.0,
        threshold={"warning": 95.0, "critical": 90.0},
        level=RuleLevel.CRITICAL,
        description="수율 위험",
    )
    fail_distribution = [
        FailDistributionItem(
            error_type=52,
            code="SIDE_VISION_FAIL",
            count=10,
            ratio_pct=100.0,
            description="SIDE 알고리즘 실패",
        )
    ]
    recommendations = RecommendationEngine().generate(
        violated_rules=[violation],
        fail_distribution=fail_distribution,
        marginal_units=MarginalUnitInfo(count=0, ratio_pct=0.0, top_parameters=[]),
        context={"yield_pct": 70.0, "recipe_id": "RCP"},
    )
    assert [rec.priority for rec in recommendations][:2] == ["URGENT", "HIGH"]
    assert len(recommendations) == len({rec.action for rec in recommendations})


def test_comment_generator_factory_and_unknown(monkeypatch):
    monkeypatch.delenv("COMMENT_GENERATOR", raising=False)
    assert isinstance(get_comment_generator(), TemplateCommentGenerator)

    monkeypatch.setenv("COMMENT_GENERATOR", "unknown")
    with pytest.raises(ValueError):
        get_comment_generator()


def test_template_comment_uses_top_fail_reason():
    text = TemplateCommentGenerator().generate(
        CommentContext(
            judgment=Judgment.WARNING,
            lot_id="LOT-1",
            yield_pct=91.3,
            violated_rules=[
                ViolatedRule(
                    rule_id="R23",
                    parameter="yield_pct",
                    actual_value=91.3,
                    threshold={"warning": 95.0, "critical": 90.0},
                    level=RuleLevel.WARNING,
                    description="주의",
                )
            ],
            yield_grade="WARNING",
            fail_top_reason="측면 칩핑 기준 초과",
            marginal_count=3,
            recipe_id="Carsem_3X3",
        )
    )
    assert "주요 원인: 측면 칩핑 기준 초과" in text


def test_rule_engine_builds_report_and_aborted_summary_only():
    rule_cache = RuleCache()
    engine = RuleEngine(
        equipment_cache=EquipmentCache(),
        alarm_counter=AlarmCounterCache(),
        lot_history=LotHistoryCache(),
        rule_cache=rule_cache,
    )
    thresholds = {
        "R02": RuleThreshold(
            "R02",
            "x",
            300.0,
            400.0,
            "abs_gte",
            marginal_min=250.0,
            marginal_max=300.0,
        )
    }
    lot = LotEnd(
        message_id="m1",
        event_type="LOT_END",
        timestamp=datetime.now(timezone.utc),
        equipment_id="DS-VIS-001",
        lot_id="LOT-1",
        lot_status="COMPLETED",
        total_units=2,
        pass_count=0,
        fail_count=2,
        yield_pct=0.0,
        lot_duration_sec=60,
    )
    report = engine._build_lot_report(
        lot=lot,
        records=[
            {
                "unit_id": "U1",
                "overall_result": "FAIL",
                "inspection_detail": {
                    "prs_result": [{"ErrorType": 52, "XOffset": 260}],
                    "side_result": [{"ErrorType": 52}],
                },
                "singulation": {},
            },
            {
                "unit_id": "U2",
                "overall_result": "FAIL",
                "inspection_detail": {
                    "prs_result": [{"ErrorType": 52, "XOffset": 270}],
                    "side_result": [{"ErrorType": 52}],
                },
                "singulation": {},
            },
        ],
        thresholds=thresholds,
        violated_rules=[],
        judgment=Judgment.DANGER,
        yield_grade="CRITICAL",
        recipe_id="Carsem_3X3",
        historian_available=True,
    )
    assert report is not None
    assert report.summary.uph == 120
    assert report.fail_distribution[0].error_type == 52
    assert report.marginal_units.count == 2
    assert report.recommendations[0].action == "해당 레시피 Teaching 재수행"

    aborted = lot.model_copy(update={"lot_status": "ABORTED"})
    aborted_report = engine._build_lot_report(
        lot=aborted,
        records=[],
        thresholds=thresholds,
        violated_rules=[],
        judgment=Judgment.DANGER,
        yield_grade="CRITICAL",
        recipe_id="Carsem_3X3",
        historian_available=True,
    )
    assert aborted_report is not None
    assert aborted_report.fail_distribution == []
    assert aborted_report.recommendations == []
