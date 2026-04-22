-- ─────────────────────────────────────────────────────────────
-- 기본 임계값 시딩 — Carsem 14일 실측 기준
-- R38a(Isolation Forest), R38b(EWMA)는 2차 검증 전용이므로 제외.
-- 36개 Rule만 시딩 (R01~R37, R38c).
-- ─────────────────────────────────────────────────────────────

INSERT INTO rule_thresholds
    (recipe_id, rule_id, metric, warning_threshold, critical_threshold, comparison_op)
VALUES
    -- Heartbeat / 연결 상태
    ('__default__', 'R01', 'heartbeat_interval_sec',     9.0,       30.0,      'gte'),
    -- PRS (픽앤소트)
    ('__default__', 'R02', 'prs_xoffset_abs',            250.0,     300.0,     'abs_gte'),
    ('__default__', 'R03', 'prs_yoffset_abs',            250.0,     300.0,     'abs_gte'),
    ('__default__', 'R04', 'prs_toffset_abs',            8000.0,    10000.0,   'abs_gte'),
    ('__default__', 'R05', 'prs_et30_rate_pct',          1.0,       3.0,       'gte'),
    ('__default__', 'R06', 'prs_pass_rate_pct',          95.0,      90.0,      'lte'),
    ('__default__', 'R07', 'prs_et11_simultaneous',      1.0,       3.0,       'gte'),
    -- SIDE (측면 비전)
    ('__default__', 'R08', 'side_pass_rate_pct',         96.0,      90.0,      'lte'),
    ('__default__', 'R09', 'side_et52_rate_pct',         5.0,       50.0,      'gte'),
    ('__default__', 'R10', 'side_et52_consecutive',      5.0,       10.0,      'gte'),
    ('__default__', 'R11', 'side_et12_rate_pct',         1.0,       50.0,      'gte'),
    ('__default__', 'R12', 'side_et30_consecutive',      1.0,       3.0,       'gte'),
    -- Singulation (절삭 품질)
    ('__default__', 'R13', 'chipping_top_um',            40.0,      50.0,      'gte'),
    ('__default__', 'R14', 'chipping_bottom_um',         35.0,      45.0,      'gte'),
    ('__default__', 'R15', 'burr_height_um',             5.0,       8.0,       'gte'),
    ('__default__', 'R16', 'blade_wear_index',           0.70,      0.85,      'gte'),
    ('__default__', 'R17', 'spindle_load_pct',           70.0,      80.0,      'gte'),
    ('__default__', 'R18', 'cutting_water_flow_lpm',     1.5,       1.2,       'lte'),
    -- Process (검사 성능)
    ('__default__', 'R19', 'map_response_p95_ms',        2500.0,    3000.0,    'gte'),
    ('__default__', 'R20', 'map_camera_fps',             8.0,       6.0,       'lte'),
    ('__default__', 'R21', 'mapque_residual',            15.0,      30.0,      'gte'),
    ('__default__', 'R22', 'takt_time_ms',               2000.0,    3000.0,    'gte'),
    -- LOT 수율 / 관리
    ('__default__', 'R23', 'yield_pct',                  95.0,      90.0,      'lte'),
    ('__default__', 'R24', 'lot_duration_sec',           NULL,      24000.0,   'gte'),
    ('__default__', 'R25', 'lot_start_end_diff',         1.0,       5.0,       'gte'),
    -- 알람 카운터
    ('__default__', 'R26', 'cam_timeout_daily_count',    1.0,       3.0,       'gte'),
    ('__default__', 'R27', 'write_fail_consecutive',     1.0,       5.0,       'gte'),
    ('__default__', 'R28', 'vision_score_err_null',      1.0,       10.0,      'gte'),
    ('__default__', 'R29', 'light_pwr_low_consecutive',  1.0,       3.0,       'gte'),
    -- 레시피
    ('__default__', 'R30', 'new_recipe_fail_rate_pct',   10.0,      30.0,      'gte'),
    ('__default__', 'R31', 'numeric_recipe_id',          NULL,      1.0,       'eq'),
    ('__default__', 'R32', 'emap_size',                  100.0,     150.0,     'gte'),
    -- AggEx / 크래시
    ('__default__', 'R33', 'aggex_daily_count',          1.0,       5.0,       'gte'),
    ('__default__', 'R34', 'eap_disconnected_weekly',    1.0,       2.0,       'gte'),
    -- ABORTED 연속 / 블레이드
    ('__default__', 'R35', 'aborted_consecutive_same_recipe', 1.0,  2.0,       'gte'),
    ('__default__', 'R36', 'blade_usage_count',          20000.0,   25000.0,   'gte'),
    ('__default__', 'R37', 'inspection_duration_ms',     1500.0,    2000.0,    'gte'),
    -- 상태 전환 (R38c: CRITICAL 전용, NULL=비교 불필요 플래그)
    ('__default__', 'R38c','status_abnormal_transition', NULL,      1.0,       'eq')
ON CONFLICT (recipe_id, rule_id) DO NOTHING;
