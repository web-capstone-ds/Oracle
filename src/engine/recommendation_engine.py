"""Rule-based recommendation generation for LOT reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from models.judgment import RuleLevel, ViolatedRule
from models.lot_report import FailDistributionItem, MarginalUnitInfo, Recommendation
from utils.logging_config import get_logger

log = get_logger(__name__)


PRIORITY_ORDER = {"URGENT": 1, "HIGH": 2, "MEDIUM": 3, "LOW": 4}


class RecommendationEngine:
    def __init__(self, rules_path: Path | None = None, max_recommendations: int = 5) -> None:
        self._rules_path = rules_path
        self._max = max_recommendations

    def generate(
        self,
        *,
        violated_rules: list[ViolatedRule],
        fail_distribution: list[FailDistributionItem],
        marginal_units: MarginalUnitInfo,
        context: dict[str, Any],
    ) -> list[Recommendation]:
        recommendations = self._generate_builtin(
            violated_rules=violated_rules,
            fail_distribution=fail_distribution,
            marginal_units=marginal_units,
            context=context,
        )
        unique = _unique_recommendations(recommendations)
        unique.sort(key=lambda rec: PRIORITY_ORDER.get(rec.priority, 99))
        return unique[: self._max]

    def _generate_builtin(
        self,
        *,
        violated_rules: list[ViolatedRule],
        fail_distribution: list[FailDistributionItem],
        marginal_units: MarginalUnitInfo,
        context: dict[str, Any],
    ) -> list[Recommendation]:
        rules_by_id = {rule.rule_id: rule for rule in violated_rules}
        out: list[Recommendation] = []

        r23 = rules_by_id.get("R23")
        if r23 and r23.level == RuleLevel.CRITICAL:
            out.append(
                Recommendation(
                    priority="URGENT",
                    action="즉시 생산 중단, 레시피 재확인",
                    basis=f"수율 {context.get('yield_pct', 0):.1f}% - CRITICAL 구간",
                )
            )
        elif r23:
            out.append(
                Recommendation(
                    priority="HIGH",
                    action="불량 패턴 확인 및 다음 LOT 전 조건 점검",
                    basis=f"수율 {context.get('yield_pct', 0):.1f}% - R23 {r23.level.value}",
                )
            )

        et12 = _find_error_type(fail_distribution, 12)
        if et12 and et12.count >= 50 and "R16" in rules_by_id:
            blade_wear = rules_by_id["R16"].actual_value
            out.append(
                Recommendation(
                    priority="HIGH",
                    action="블레이드 교체 검토",
                    basis=f"chipping {et12.count}건 + blade_wear {blade_wear} (R16)",
                )
            )

        top = fail_distribution[0] if fail_distribution else None
        if top and top.error_type == 52 and top.ratio_pct >= 80.0:
            out.append(
                Recommendation(
                    priority="HIGH",
                    action="해당 레시피 Teaching 재수행",
                    basis=f"SIDE 알고리즘 실패 ET=52 {top.ratio_pct:.1f}%",
                )
            )

        x_offset = _find_marginal_param(marginal_units, "x_offset_um")
        if x_offset and x_offset.count >= 10:
            out.append(
                Recommendation(
                    priority="MEDIUM",
                    action="PRS 정렬 보정",
                    basis=f"x_offset MARGINAL {x_offset.count}건 누적",
                )
            )

        for rule_id in ("R26", "R29", "R31", "R38c"):
            rule = rules_by_id.get(rule_id)
            if not rule:
                continue
            if rule_id == "R26":
                out.append(
                    Recommendation(
                        priority="MEDIUM",
                        action="카메라 점검 및 광원 확인",
                        basis=rule.description,
                    )
                )
            elif rule_id == "R29":
                out.append(
                    Recommendation(
                        priority="HIGH",
                        action="측면 조명 모듈 점검",
                        basis=rule.description,
                    )
                )
            elif rule_id == "R31":
                out.append(
                    Recommendation(
                        priority="LOW",
                        action="DS 측 레시피 ID 정체 확인 요청",
                        basis=f"recipe_id={context.get('recipe_id', '')}",
                    )
                )
            elif rule_id == "R38c":
                out.append(
                    Recommendation(
                        priority="URGENT",
                        action="장비 즉시 점검",
                        basis="RUN -> STOP 무경고 전환 감지",
                    )
                )

        return out


def _find_error_type(
    fail_distribution: list[FailDistributionItem],
    error_type: int,
) -> FailDistributionItem | None:
    return next((item for item in fail_distribution if item.error_type == error_type), None)


def _find_marginal_param(
    marginal_units: MarginalUnitInfo,
    parameter: str,
):
    return next((item for item in marginal_units.top_parameters if item.parameter == parameter), None)


def _unique_recommendations(recommendations: list[Recommendation]) -> list[Recommendation]:
    seen: set[tuple[str, str]] = set()
    out: list[Recommendation] = []
    for rec in recommendations:
        key = (rec.priority, rec.action)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out

