-- TokenPilot schema v2 (Phase 1 telemetry ledger).
-- D2: projects are addressable by slug.
-- D3: callers send their own task ids; tasks keep them per project.
-- D4: session identity is (source, external_session_id).
-- D5: cost_records explain a NULL cost; usage_events keep the HTTP status;
--     a pricing row is unique per (provider, model_id, valid_from).
-- Unique indexes allow many NULLs in SQLite, so rows without these values
-- never collide with each other.

ALTER TABLE projects ADD COLUMN slug TEXT;
ALTER TABLE tasks ADD COLUMN external_task_id TEXT;
ALTER TABLE cost_records ADD COLUMN reason TEXT;
ALTER TABLE usage_events ADD COLUMN http_status INTEGER;

CREATE UNIQUE INDEX idx_projects_slug ON projects (slug);
CREATE UNIQUE INDEX idx_tasks_project_external
    ON tasks (project_id, external_task_id);
CREATE UNIQUE INDEX idx_sessions_source_external
    ON sessions (source, external_session_id);
CREATE UNIQUE INDEX idx_pricing_versions_unique
    ON pricing_versions (provider, model_id, valid_from);
