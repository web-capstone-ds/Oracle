"""실제 EAP Mock 데이터 ↔ Oracle 모델 호환성 회귀 테스트.

목적:
- DS-Document/EAP_mock_data/ 의 27개 Mock 중 Oracle이 구독하는 4종(LOT_END, HW_ALARM,
  RECIPE_CHANGED, STATUS_UPDATE) Mock이 `models.events.parse_event` 로 무리 없이
  파싱되는지 검증한다.
- Mock JSON 의 underscore-prefixed 메타키(_source, _note 등)는 pydantic extra=allow
  로 흡수되어야 한다.
- 비-구독 이벤트(HEARTBEAT, INSPECTION_RESULT, CONTROL_CMD, ORACLE_ANALYSIS) Mock 은
  parse_event 가 None 을 반환하여 무시 — 이것도 회귀 검증 대상.

Mock 디렉토리 부재 시(저장소만 단독 체크아웃) skip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.events import HwAlarm, LotEnd, RecipeChanged, StatusUpdate, parse_event

MOCK_DIR = (
    Path(__file__).resolve().parent.parent.parent / "DS-Document" / "EAP_mock_data"
)


def _mock(filename: str) -> dict:
    path = MOCK_DIR / filename
    if not path.exists():
        pytest.skip(f"Mock 파일 부재 (인접 저장소 미존재): {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Oracle 구독 4종 — parse_event 가 정확한 DTO 인스턴스를 반환해야 함 ──────


@pytest.mark.parametrize(
    "filename,expected_cls,expected_event_type",
    [
        ("02_status_run.json", StatusUpdate, "STATUS_UPDATE"),
        ("03_status_idle.json", StatusUpdate, "STATUS_UPDATE"),
        ("09_lot_end_normal.json", LotEnd, "LOT_END"),
        ("10_lot_end_aborted.json", LotEnd, "LOT_END"),
        ("11_alarm_cam_timeout.json", HwAlarm, "HW_ALARM"),
        ("12_alarm_write_image_fail.json", HwAlarm, "HW_ALARM"),
        ("13_alarm_vision_null_object.json", HwAlarm, "HW_ALARM"),
        ("14_alarm_light_param_err.json", HwAlarm, "HW_ALARM"),
        ("15_alarm_side_vision_fail.json", HwAlarm, "HW_ALARM"),
        ("16_alarm_lot_start_fail.json", HwAlarm, "HW_ALARM"),
        ("17_alarm_eap_disconnected.json", HwAlarm, "HW_ALARM"),
        ("18_recipe_changed_normal.json", RecipeChanged, "RECIPE_CHANGED"),
        ("19_recipe_changed_new_4x6.json", RecipeChanged, "RECIPE_CHANGED"),
        ("20_recipe_changed_446275.json", RecipeChanged, "RECIPE_CHANGED"),
    ],
)
def test_subscribed_event_mocks_parse(filename, expected_cls, expected_event_type):
    raw = _mock(filename)
    event = parse_event(raw)
    assert event is not None, f"{filename} 파싱 실패"
    assert isinstance(event, expected_cls), (
        f"{filename}: expected {expected_cls.__name__}, got {type(event).__name__}"
    )
    assert event.event_type == expected_event_type
    assert event.equipment_id  # non-empty
    assert event.message_id


# ── 비-구독 이벤트 — parse_event 가 None 반환해야 함 (라우터에서 안전 무시) ──


@pytest.mark.parametrize(
    "filename",
    [
        "01_heartbeat.json",            # HEARTBEAT - Oracle 구독 안 함
        "04_inspection_pass.json",      # INSPECTION_RESULT - Historian 경유
        "05_inspection_fail_side_et52.json",
        "06_inspection_fail_side_et12.json",
        "07_inspection_fail_prs_offset.json",
        "08_inspection_fail_side_mixed.json",
        "21_control_emergency_stop.json",  # CONTROL_CMD - MES 책임
        "22_control_status_query.json",
        "23_oracle_normal.json",            # ORACLE_ANALYSIS - 자기 발행
        "24_oracle_warning.json",
        "25_oracle_danger.json",
        "26_control_alarm_ack.json",
        "27_control_alarm_ack_burst.json",
    ],
)
def test_non_subscribed_event_mocks_return_none(filename):
    """이벤트 정의서 §9: Oracle은 4종만 구독. 그 외 event_type 은 무시."""
    raw = _mock(filename)
    assert parse_event(raw) is None


# ── 특정 시나리오 보강 검증 ─────────────────────────────────────────────


def test_mock09_normal_lot_fields():
    """Mock 09: yield 96.2% / COMPLETED / total_units=2792 (Carsem 실측)."""
    event = parse_event(_mock("09_lot_end_normal.json"))
    assert isinstance(event, LotEnd)
    assert event.yield_pct == 96.2
    assert event.lot_status == "COMPLETED"
    assert event.total_units == 2792


def test_mock10_aborted_fields():
    """Mock 10: yield 94.2% / ABORTED."""
    event = parse_event(_mock("10_lot_end_aborted.json"))
    assert isinstance(event, LotEnd)
    assert event.lot_status == "ABORTED"
    assert event.yield_pct == 94.2


def test_mock20_numeric_recipe_id_446275():
    """Mock 20: 숫자형 레시피 ID 446275 → R31 트리거 대상."""
    event = parse_event(_mock("20_recipe_changed_446275.json"))
    assert isinstance(event, RecipeChanged)
    assert event.new_recipe_id == "446275"


def test_mock11_cam_timeout_critical_alarm():
    """Mock 11: CAM_TIMEOUT_ERR + alarm_level=CRITICAL → R26/R38c 보조."""
    event = parse_event(_mock("11_alarm_cam_timeout.json"))
    assert isinstance(event, HwAlarm)
    assert event.hw_error_code == "CAM_TIMEOUT_ERR"
    assert event.alarm_level == "CRITICAL"


def test_mock_metadata_keys_absorbed():
    """Mock 의 _source / _note / _v34_note 같은 메타키는 extra=allow 로 흡수."""
    event = parse_event(_mock("02_status_run.json"))
    assert isinstance(event, StatusUpdate)
    # 모델 정의 필드는 정상 추출
    assert event.recipe_id == "Carsem_3X3"
    assert event.equipment_status == "RUN"
