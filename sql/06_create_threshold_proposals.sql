CREATE TABLE IF NOT EXISTS threshold_proposals (
    proposal_id       TEXT             PRIMARY KEY,
    created_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    recipe_id         TEXT             NOT NULL,
    rule_id           TEXT             NOT NULL,
    metric            TEXT             NOT NULL,
    current_warning   DOUBLE PRECISION,
    current_critical  DOUBLE PRECISION,
    proposed_warning  DOUBLE PRECISION,
    proposed_critical DOUBLE PRECISION,
    lot_basis         INTEGER          NOT NULL,
    basis             TEXT,
    status            TEXT             NOT NULL DEFAULT 'pending',
    processed_at      TIMESTAMPTZ,
    processed_by      TEXT
);

CREATE INDEX IF NOT EXISTS idx_proposals_status
    ON threshold_proposals (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proposals_recipe_rule
    ON threshold_proposals (recipe_id, rule_id, created_at DESC);

