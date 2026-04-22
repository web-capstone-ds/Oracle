"""4종 구독 이벤트 DTO (pydantic).

Oracle은 LOT_END / HW_ALARM / RECIPE_CHANGED / STATUS_UPDATE만 구독한다.
INSPECTION_RESULT는 Historian TSDB 경유 조회 (직접 구독 안 함).

JSON 필드명은 모두 snake_case. (inspection_detail 내부만 PascalCase이나
이 모듈은 LOT_END/ALARM/RECIPE/STATUS만 다루므로 snake_case로 일원화.)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: str
    event_type: str
    timestamp: datetime
    equipment_id: str


class LotEnd(_Base):
    event_type: Literal["LOT_END"]
    equipment_status: str = "IDLE"
    lot_id: str
    lot_status: Literal["COMPLETED", "ABORTED", "ERROR"]
    total_units: int
    pass_count: int
    fail_count: int
    yield_pct: float
    lot_duration_sec: int


class ExceptionDetail(BaseModel):
    model_config = ConfigDict(extra="allow")
    module: str | None = None
    exception_type: str | None = None
    stack_trace_hash: str | None = None


class HwAlarm(_Base):
    event_type: Literal["HW_ALARM"]
    equipment_status: str
    alarm_level: Literal["CRITICAL", "WARNING", "INFO"]
    hw_error_code: str
    hw_error_source: str
    hw_error_detail: str
    exception_detail: ExceptionDetail | None = None
    auto_recovery_attempted: bool = False
    requires_manual_intervention: bool = False
    burst_id: str | None = None
    burst_count: int | None = None


class RecipeChanged(_Base):
    event_type: Literal["RECIPE_CHANGED"]
    equipment_status: str = "IDLE"
    previous_recipe_id: str
    previous_recipe_version: str
    new_recipe_id: str
    new_recipe_version: str
    changed_by: str


class StatusUpdate(_Base):
    event_type: Literal["STATUS_UPDATE"]
    equipment_status: Literal["RUN", "IDLE", "STOP"]
    lot_id: str
    recipe_id: str
    recipe_version: str
    operator_id: str
    uptime_sec: int
    current_unit_count: int | None = None
    expected_total_units: int | None = None
    current_yield_pct: float | None = None


def parse_event(raw: dict[str, Any]) -> _Base | None:
    event_type = raw.get("event_type")
    if event_type == "LOT_END":
        return LotEnd.model_validate(raw)
    if event_type == "HW_ALARM":
        return HwAlarm.model_validate(raw)
    if event_type == "RECIPE_CHANGED":
        return RecipeChanged.model_validate(raw)
    if event_type == "STATUS_UPDATE":
        return StatusUpdate.model_validate(raw)
    return None
