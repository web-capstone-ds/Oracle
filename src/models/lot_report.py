"""LOT report DTOs for ORACLE_ANALYSIS v1.1 Phase 1."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LotReportSummary(_ReportModel):
    total_units: int
    pass_count: int
    fail_count: int
    marginal_count: int
    yield_pct: float
    duration_sec: int
    uph: int


class FailDistributionItem(_ReportModel):
    error_type: int
    code: str
    count: int
    ratio_pct: float
    description: str


class MarginalParameterStat(_ReportModel):
    parameter: str
    marginal_range: str
    count: int


class MarginalUnitInfo(_ReportModel):
    count: int
    ratio_pct: float
    top_parameters: list[MarginalParameterStat]


class Recommendation(_ReportModel):
    priority: str
    action: str
    basis: str


class ReportTransparency(_ReportModel):
    rule_db_version: str
    lot_basis: int
    basis_note: str


class LotReport(_ReportModel):
    summary: LotReportSummary
    fail_distribution: list[FailDistributionItem]
    marginal_units: MarginalUnitInfo
    recommendations: list[Recommendation]
    transparency: ReportTransparency

