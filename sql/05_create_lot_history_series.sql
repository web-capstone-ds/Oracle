CREATE TABLE IF NOT EXISTS lot_history_series (
    id                      SERIAL           PRIMARY KEY,
    lot_id                  TEXT             NOT NULL,
    equipment_id            TEXT             NOT NULL,
    recipe_id               TEXT             NOT NULL,
    lot_end_time            TIMESTAMPTZ      NOT NULL,
    yield_pct               DOUBLE PRECISION NOT NULL,
    total_units             INTEGER          NOT NULL,
    fail_count              INTEGER          NOT NULL,
    lot_duration_sec        INTEGER          NOT NULL,
    side_et52_rate_pct      DOUBLE PRECISION,
    prs_et11_rate_pct       DOUBLE PRECISION,
    chipping_top_avg_um     DOUBLE PRECISION,
    chipping_top_p95_um     DOUBLE PRECISION,
    burr_height_avg_um      DOUBLE PRECISION,
    blade_wear_index_avg    DOUBLE PRECISION,
    takt_p95_ms             DOUBLE PRECISION,
    cam_timeout_daily_count INTEGER,
    created_at              TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    UNIQUE (lot_id, equipment_id)
);

SELECT create_hypertable('lot_history_series', 'lot_end_time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_lot_history_recipe_time
    ON lot_history_series (recipe_id, lot_end_time DESC);
CREATE INDEX IF NOT EXISTS idx_lot_history_equipment_time
    ON lot_history_series (equipment_id, lot_end_time DESC);

