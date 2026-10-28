-- TokenPilot schema v3 (Phase 2 deterministic insights).
-- P1: `insights` gains the rule identity, a stable dedupe key, measurements,
--     the impact currency and lifecycle timestamps; `jobs` tracks analysis
--     runs and `app_settings` stores runtime configuration.
-- Unique indexes allow any number of NULL keys in SQLite, so insight rows
-- written before this migration never collide with each other.

ALTER TABLE insights ADD COLUMN rule_id TEXT;
ALTER TABLE insights ADD COLUMN rule_version INTEGER;
ALTER TABLE insights ADD COLUMN dedupe_key TEXT;
ALTER TABLE insights ADD COLUMN measurements_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE insights ADD COLUMN impact_currency TEXT;
ALTER TABLE insights ADD COLUMN evidence_truncated INTEGER NOT NULL DEFAULT 0;
ALTER TABLE insights ADD COLUMN updated_at TEXT;
ALTER TABLE insights ADD COLUMN last_detected_at TEXT;

CREATE UNIQUE INDEX idx_insights_dedupe ON insights (dedupe_key);
CREATE INDEX idx_insights_session ON insights (session_id);
CREATE INDEX idx_insights_created ON insights (created_at, id);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
