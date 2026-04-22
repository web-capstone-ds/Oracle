-- ─────────────────────────────────────────────────────────────
-- Oracle 판정 엔진 Rule DB 스키마
-- Task O4 (Oracle_작업명세서 §6)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rule_thresholds (
    id                  SERIAL          PRIMARY KEY,
    recipe_id           TEXT            NOT NULL,
    rule_id             TEXT            NOT NULL,
    metric              TEXT            NOT NULL,
    warning_threshold   DOUBLE PRECISION,
    critical_threshold  DOUBLE PRECISION,
    comparison_op       TEXT            NOT NULL DEFAULT 'gte',
    enabled             BOOLEAN         NOT NULL DEFAULT true,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    approved_by         TEXT,
    lot_basis           INTEGER         NOT NULL DEFAULT 0,
    UNIQUE (recipe_id, rule_id)
);

CREATE INDEX IF NOT EXISTS idx_rule_thresholds_recipe
    ON rule_thresholds (recipe_id);
CREATE INDEX IF NOT EXISTS idx_rule_thresholds_rule
    ON rule_thresholds (rule_id);


CREATE TABLE IF NOT EXISTS rule_change_history (
    id              SERIAL          PRIMARY KEY,
    changed_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    recipe_id       TEXT            NOT NULL,
    rule_id         TEXT            NOT NULL,
    metric          TEXT            NOT NULL,
    old_warning     DOUBLE PRECISION,
    new_warning     DOUBLE PRECISION,
    old_critical    DOUBLE PRECISION,
    new_critical    DOUBLE PRECISION,
    approved_by     TEXT,
    change_source   TEXT            NOT NULL DEFAULT 'manual',
    ai_basis        TEXT
);

CREATE INDEX IF NOT EXISTS idx_rule_change_recipe_rule
    ON rule_change_history (recipe_id, rule_id, changed_at DESC);
