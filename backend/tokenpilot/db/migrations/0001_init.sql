-- TokenPilot schema v1.
-- PRD §8 columns verbatim, plus the Phase 1-4 additions listed in
-- docs/superpowers/plans/2026-10-27-tokenpilot-mvp.md (Task 0.2).
-- All timestamps are ISO 8601 UTC strings. Money is REAL rounded to 10 dp
-- by the cost engine; NULL always means "unknown", never zero.

CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    repository_path TEXT,
    default_currency TEXT NOT NULL DEFAULT 'USD',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects (id) ON DELETE SET NULL,
    external_session_id TEXT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    outcome TEXT NOT NULL DEFAULT 'unknown',
    outcome_source TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions (id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    task_type TEXT,
    outcome TEXT NOT NULL DEFAULT 'unknown',
    outcome_source TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE insights (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects (id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions (id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks (id) ON DELETE SET NULL,
    detector_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    root_cause_hypothesis TEXT,
    confidence REAL,
    estimated_impact REAL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    recommendation_json TEXT,
    investigator_model TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE pricing_versions (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    input_price_per_million REAL,
    output_price_per_million REAL,
    cached_input_price REAL,
    pricing_source TEXT,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE benchmarks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    task_id TEXT REFERENCES tasks (id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    initial_git_sha TEXT,
    acceptance_config_json TEXT,
    baseline_config_json TEXT,
    created_at TEXT NOT NULL,
    description TEXT,
    task_spec_json TEXT,
    alternative_configs_json TEXT,
    repeat_count INTEGER,
    timeout_s INTEGER,
    insight_id TEXT REFERENCES insights (id) ON DELETE SET NULL
);

CREATE TABLE benchmark_runs (
    id TEXT PRIMARY KEY,
    benchmark_id TEXT NOT NULL REFERENCES benchmarks (id) ON DELETE CASCADE,
    variant_name TEXT NOT NULL,
    model_id TEXT,
    config_json TEXT,
    run_status TEXT NOT NULL,
    outcome TEXT,
    total_cost REAL,
    total_tokens INTEGER,
    request_count INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    test_exit_code INTEGER,
    test_results_json TEXT,
    patch_path TEXT,
    worktree_path TEXT,
    started_at TEXT,
    completed_at TEXT,
    repeat_index INTEGER,
    error TEXT,
    eligible INTEGER
);

CREATE TABLE benchmark_comparisons (
    id TEXT PRIMARY KEY,
    benchmark_id TEXT NOT NULL REFERENCES benchmarks (id) ON DELETE CASCADE,
    baseline_run_id TEXT NOT NULL REFERENCES benchmark_runs (id) ON DELETE CASCADE,
    alternative_run_id TEXT NOT NULL REFERENCES benchmark_runs (id) ON DELETE CASCADE,
    cost_delta REAL,
    cost_delta_pct REAL,
    correctness_preserved BOOLEAN,
    comparison_status TEXT NOT NULL,
    methodology_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE usage_events (
    id TEXT PRIMARY KEY,
    source_event_id TEXT,
    idempotency_key TEXT NOT NULL,
    project_id TEXT REFERENCES projects (id) ON DELETE SET NULL,
    session_id TEXT REFERENCES sessions (id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks (id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    cached_tokens INTEGER CHECK (cached_tokens IS NULL OR cached_tokens >= 0),
    reasoning_tokens INTEGER CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
    usage_source TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    retry_group_id TEXT,
    request_fingerprint TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    retry_source TEXT,
    attempt INTEGER CHECK (attempt IS NULL OR attempt >= 1),
    error_category TEXT,
    benchmark_run_id TEXT REFERENCES benchmark_runs (id) ON DELETE SET NULL,
    raw_event_json TEXT
);

CREATE TABLE cost_records (
    id TEXT PRIMARY KEY,
    usage_event_id TEXT NOT NULL REFERENCES usage_events (id) ON DELETE CASCADE,
    pricing_version_id TEXT REFERENCES pricing_versions (id) ON DELETE SET NULL,
    estimated_cost REAL,
    reported_cost REAL,
    billed_cost REAL,
    currency TEXT,
    cost_basis TEXT NOT NULL,
    calculated_at TEXT NOT NULL
);

CREATE TABLE attribution_changes (
    id TEXT PRIMARY KEY,
    usage_event_id TEXT NOT NULL REFERENCES usage_events (id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT,
    changed_at TEXT NOT NULL
);

CREATE TABLE content_excerpts (
    id TEXT PRIMARY KEY,
    usage_event_id TEXT NOT NULL REFERENCES usage_events (id) ON DELETE CASCADE,
    role TEXT,
    sha256 TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE investigations (
    id TEXT PRIMARY KEY,
    insight_id TEXT NOT NULL REFERENCES insights (id) ON DELETE CASCADE,
    model TEXT,
    prompt_version TEXT,
    mode TEXT NOT NULL,
    request_disclosure_json TEXT,
    status TEXT NOT NULL,
    result_json TEXT,
    validation_errors_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE recommendation_feedback (
    id TEXT PRIMARY KEY,
    insight_id TEXT NOT NULL REFERENCES insights (id) ON DELETE CASCADE,
    verdict TEXT NOT NULL,
    implemented INTEGER,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_usage_events_idempotency_key
    ON usage_events (idempotency_key);
CREATE INDEX idx_usage_events_project_started
    ON usage_events (project_id, started_at);
CREATE INDEX idx_usage_events_session_started
    ON usage_events (session_id, started_at);
CREATE INDEX idx_usage_events_model ON usage_events (model_id);
CREATE INDEX idx_usage_events_retry_group ON usage_events (retry_group_id);
CREATE INDEX idx_usage_events_fingerprint ON usage_events (request_fingerprint);
CREATE INDEX idx_usage_events_benchmark_run ON usage_events (benchmark_run_id);
CREATE INDEX idx_cost_records_event_calculated
    ON cost_records (usage_event_id, calculated_at);
CREATE INDEX idx_pricing_versions_lookup
    ON pricing_versions (provider, model_id, valid_from);
CREATE INDEX idx_sessions_project ON sessions (project_id);
CREATE INDEX idx_tasks_project ON tasks (project_id);
CREATE INDEX idx_insights_status ON insights (status, severity);
CREATE INDEX idx_investigations_insight ON investigations (insight_id);
CREATE INDEX idx_benchmark_runs_benchmark ON benchmark_runs (benchmark_id, variant_name);

-- raw_event_json is the sanitized original payload: once written it never changes.
CREATE TRIGGER usage_events_raw_event_immutable
BEFORE UPDATE OF raw_event_json ON usage_events
WHEN OLD.raw_event_json IS NOT NULL AND NEW.raw_event_json IS NOT OLD.raw_event_json
BEGIN
    SELECT RAISE(ABORT, 'raw_event_json is immutable');
END;
