ALTER TABLE rule_thresholds
    ADD COLUMN IF NOT EXISTS marginal_min DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS marginal_max DOUBLE PRECISION;

UPDATE rule_thresholds SET marginal_min = 40.0, marginal_max = 50.0
    WHERE rule_id = 'R13' AND recipe_id = '__default__';
UPDATE rule_thresholds SET marginal_min = 35.0, marginal_max = 45.0
    WHERE rule_id = 'R14' AND recipe_id = '__default__';
UPDATE rule_thresholds SET marginal_min = 6.0, marginal_max = 8.0
    WHERE rule_id = 'R15' AND recipe_id = '__default__';
UPDATE rule_thresholds SET marginal_min = 250.0, marginal_max = 300.0
    WHERE rule_id = 'R02' AND recipe_id = '__default__';
UPDATE rule_thresholds SET marginal_min = 250.0, marginal_max = 300.0
    WHERE rule_id = 'R03' AND recipe_id = '__default__';
UPDATE rule_thresholds SET marginal_min = 0.60, marginal_max = 0.70
    WHERE rule_id = 'R16' AND recipe_id = '__default__';

