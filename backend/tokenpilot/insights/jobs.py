"""Analysis job storage. The job row is the only shared state between the
request that accepts the work and the background task that runs it.

A restart must never leave a job `running` forever (P6), so the lifespan fails
every unfinished job with `interrupted by restart`.
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from tokenpilot.db.connection import connect
from tokenpilot.db.database import Database
from tokenpilot.detectors.facts import AnalysisScope
from tokenpilot.detectors.runner import run_detectors
from tokenpilot.schemas.insights import AnalyzeRequest, JobOut, JobStatus
from tokenpilot.security import redact_text
from tokenpilot.timeutil import utc_now_z

__all__ = ["INTERRUPTED_ERROR", "JobKind", "JobRepository", "run_analysis_job"]

JobKind = Literal["analyze", "investigate"]
INTERRUPTED_ERROR = "interrupted by restart"

_JOB_COLUMNS = (
    "id, kind, status, params_json, result_json, error, created_at, started_at, finished_at"
)


def _to_out(row: sqlite3.Row) -> JobOut:
    values: dict[str, Any] = dict(row)
    values["params"] = json.loads(values.pop("params_json"))
    result = values.pop("result_json")
    values["result"] = json.loads(result) if result else None
    return JobOut.model_validate(values)


class JobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, kind: JobKind, params: dict[str, Any]) -> JobOut:
        job_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO jobs (id, kind, status, params_json, created_at) "
            "VALUES (?, ?, 'queued', ?, ?)",
            (job_id, kind, json.dumps(params, sort_keys=True), utc_now_z()),
        )
        job = self.get(job_id)
        assert job is not None
        return job

    def start(self, job_id: str) -> JobOut | None:
        return self._transition(job_id, "running", "queued", started_at=utc_now_z())

    def succeed(self, job_id: str, result: dict[str, Any]) -> JobOut | None:
        return self._transition(
            job_id,
            "succeeded",
            "running",
            result_json=json.dumps(result, sort_keys=True),
            finished_at=utc_now_z(),
        )

    def fail(self, job_id: str, error: str) -> JobOut | None:
        # Redact here as well as at the call site: a job error is user-visible.
        return self._transition(
            job_id,
            "failed",
            "running",
            error=redact_text(error),
            finished_at=utc_now_z(),
        )

    def get(self, job_id: str) -> JobOut | None:
        row = self._conn.execute(
            f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return None if row is None else _to_out(row)

    def recover_interrupted(self) -> int:
        """Fail every queued/running job left behind by a previous process."""
        cursor = self._conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, finished_at = ? "
            "WHERE status IN ('queued', 'running')",
            (INTERRUPTED_ERROR, utc_now_z()),
        )
        return cursor.rowcount

    def _transition(
        self, job_id: str, status: JobStatus, expected: JobStatus, **fields: Any
    ) -> JobOut | None:
        """Move a job only from `expected`; None when it is missing or already moved on."""
        columns: dict[str, Any] = {"status": status, **fields}
        assignments = ", ".join(f"{column} = ?" for column in columns)
        cursor = self._conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ? AND status = ?",
            [*columns.values(), job_id, expected],
        )
        if cursor.rowcount != 1:
            return None
        return self.get(job_id)


def run_analysis_job(
    db: Database, db_path: Path, job_id: str, req: AnalyzeRequest
) -> None:
    """Start the job, run detectors on a separate read connection (P5), then succeed or fail."""
    with db.write() as conn:
        started = JobRepository(conn).start(job_id)
    if started is None:
        return

    read_conn = None
    try:
        read_conn = connect(db_path)
        now = datetime.now(UTC)
        scope = AnalysisScope(project_id=req.project_id, session_id=req.session_id)
        # rule_ids is already validated as RuleId literals on the request thread.
        rule_ids: list[str] | None = (
            [str(rule_id) for rule_id in req.rule_ids] if req.rule_ids is not None else None
        )
        result = run_detectors(read_conn, db, scope, rule_ids, now)
        with db.write() as conn:
            JobRepository(conn).succeed(
                job_id,
                {
                    "created": result.created,
                    "updated": result.updated,
                    "by_rule": result.by_rule,
                },
            )
    except Exception as exc:
        with db.write() as conn:
            JobRepository(conn).fail(job_id, f"{type(exc).__name__}: {exc}")
    finally:
        if read_conn is not None:
            read_conn.close()
