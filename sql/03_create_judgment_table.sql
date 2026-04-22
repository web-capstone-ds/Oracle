-- ─────────────────────────────────────────────────────────────
-- Oracle 판정 이력 테이블 (TimescaleDB Hypertable)
-- ─────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS oracle_judgments (
    time            TIMESTAMPTZ     NOT NULL,
    message_id      UUID            NOT NULL,
    equipment_id    TEXT            NOT NULL,
    lot_id          TEXT            NOT NULL,
    recipe_id       TEXT            NOT NULL,
    judgment        TEXT            NOT NULL,     -- NORMAL / WARNING / DANGER
    yield_actual    DOUBLE PRECISION NOT NULL,
    violated_rules  JSONB,
    ai_comment      TEXT,
    analysis_source TEXT            NOT NULL DEFAULT 'rule_based',
    payload_raw     JSONB
);

SELECT create_hypertable('oracle_judgments', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_oracle_eq_time
    ON oracle_judgments (equipment_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_recipe
    ON oracle_judgments (recipe_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_oracle_judgment
    ON oracle_judgments (judgment, time DESC);
