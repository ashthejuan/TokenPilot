"""Benchmark run execution: worktree, agent, acceptance tests, scoring.

A run moves queued → running → completed/failed. The outcome comes only from
the acceptance command and the required-test list (FR-10): the model's `done`
message never decides. `execute_run` commits after every phase on the
connection it is given, so that connection must be a dedicated one from
:func:`tokenpilot.db.connection.connect` — never a `Database.write()`
connection, whose lock the gateway needs while the agent is calling it.
"""

import asyncio
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from tokenpilot.benchmarks.agent import (
    AgentCancelled,
    AgentGatewayError,
    AgentTimeout,
    run_agent,
)
from tokenpilot.benchmarks.agent_tools import AgentTools
from tokenpilot.benchmarks.sandbox import SandboxResult, run_sandboxed
from tokenpilot.benchmarks.worktree import (
    Worktree,
    create_worktree,
    export_patch,
    remove_worktree,
)
from tokenpilot.pricing.cost import latest_cost_sql, quantize_money
from tokenpilot.schemas.benchmarks import (
    AcceptanceConfig,
    AlternativeSpec,
    BenchmarkOut,
    BenchmarkRunOut,
    RunConfig,
    RunOutcome,
    RunStatus,
    cost_to_decimal,
)
from tokenpilot.security import redact_text
from tokenpilot.timeutil import parse_utc_z, utc_now_z

logger = logging.getLogger("tokenpilot.benchmarks")

INTERRUPTED_BY_RESTART = "interrupted_by_restart"
DEFAULT_TIMEOUT_S = 300
_ERROR_CHARS = 2000

_BENCHMARK_COLUMNS = (
    "id, project_id, task_id, name, initial_git_sha, acceptance_config_json, "
    "baseline_config_json, created_at, description, task_spec_json, "
    "alternative_configs_json, repeat_count, timeout_s"
)
_RUN_COLUMNS = (
    "id, benchmark_id, variant_name, model_id, config_json, run_status, outcome, "
    "total_cost, total_tokens, request_count, retry_count, duration_ms, "
    "test_exit_code, test_results_json, patch_path, worktree_path, started_at, "
    "completed_at, repeat_index, error, eligible"
)
_RUN_UPDATE_COLUMNS = frozenset(
    {
        "variant_name",
        "model_id",
        "config_json",
        "run_status",
        "outcome",
        "total_cost",
        "total_tokens",
        "request_count",
        "retry_count",
        "duration_ms",
        "test_exit_code",
        "test_results_json",
        "patch_path",
        "worktree_path",
        "started_at",
        "completed_at",
        "repeat_index",
        "error",
        "eligible",
    }
)


@dataclass(frozen=True)
class RunUsage:
    request_count: int
    retry_count: int
    total_tokens: int | None
    total_cost: Decimal | None
    unknown_cost_events: int
    currency: str | None


def aggregate_run_usage(conn: sqlite3.Connection, run_id: str) -> RunUsage:
    """Sum the ledger events tagged with `run_id`.

    `total_cost` stays None when any event's cost is unknown (never 0), and
    `total_tokens` likewise when any event lacks token counts.
    """
    rows = conn.execute(
        f"WITH {latest_cost_sql} "
        "SELECT u.input_tokens, u.output_tokens, u.attempt, "
        "lc.estimated_cost, lc.currency FROM usage_events u "
        "LEFT JOIN latest_costs lc ON lc.usage_event_id = u.id "
        "WHERE u.benchmark_run_id = ?",
        (run_id,),
    ).fetchall()
    unknown = sum(1 for row in rows if row["estimated_cost"] is None)
    total_cost: Decimal | None = None
    if unknown == 0 and rows:
        total_cost = quantize_money(
            sum((Decimal(str(row["estimated_cost"])) for row in rows), Decimal(0))
        )
    total_tokens: int | None = None
    if rows and all(
        row["input_tokens"] is not None and row["output_tokens"] is not None
        for row in rows
    ):
        total_tokens = sum(row["input_tokens"] + row["output_tokens"] for row in rows)
    currencies = {row["currency"] for row in rows if row["currency"] is not None}
    return RunUsage(
        request_count=len(rows),
        retry_count=sum(
            1 for row in rows if row["attempt"] is not None and row["attempt"] > 1
        ),
        total_tokens=total_tokens,
        total_cost=total_cost,
        unknown_cost_events=unknown,
        currency=currencies.pop() if len(currencies) == 1 else None,
    )


def _count(pattern: str, text: str) -> int:
    return sum(int(match) for match in re.findall(pattern, text))


def parse_pytest_results(
    stdout: str,
    stderr: str,
    exit_code: int,
    required_pass: list[str],
    collected: Collection[str] | None,
) -> dict[str, Any]:
    """Score required nodeids from `-q` output plus a `--collect-only` listing.

    `-q` never names passing tests, so presence comes from the collect-only run:
    a required nodeid that is absent there is `missing`, never silently passed.
    """
    text = f"{stdout}\n{stderr}"
    failed_nodes = set(re.findall(r"^FAILED (\S+)", text, re.MULTILINE))
    failed_nodes.update(re.findall(r"^ERROR (\S+)", text, re.MULTILINE))
    required: dict[str, str] = {}
    for nodeid in required_pass:
        if nodeid in failed_nodes:
            required[nodeid] = "failed"
        elif collected is not None and nodeid not in collected:
            required[nodeid] = "missing"
        elif exit_code == 0:
            required[nodeid] = "passed"
        else:
            required[nodeid] = "failed"
    return {
        "passed": _count(r"(\d+) passed", text),
        "failed": _count(r"(\d+) failed", text),
        "errors": _count(r"(\d+) errors?", text),
        "required": required,
    }


def parse_collect_only(output: str) -> set[str]:
    """Nodeids from `pytest --collect-only -q`: lines shaped like `path::test`."""
    found = set()
    for line in output.splitlines():
        stripped = line.strip()
        if "::" in stripped and " " not in stripped:
            found.add(stripped)
    return found


def resolve_acceptance_command(command: list[str]) -> list[str]:
    """Resolve `cmd[0] == "python"` to this interpreter when `python` is absent.

    The stored task spec stays verbatim; only the executed argv is substituted.
    """
    if command[0] == "python" and shutil.which("python") is None:
        return [sys.executable, *command[1:]]
    return list(command)


def _benchmark_from_row(row: sqlite3.Row) -> BenchmarkOut:
    task_spec = json.loads(row["task_spec_json"]) if row["task_spec_json"] else {}
    return BenchmarkOut(
        id=row["id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        name=row["name"],
        description=row["description"],
        initial_git_sha=row["initial_git_sha"],
        acceptance=AcceptanceConfig.model_validate(
            json.loads(row["acceptance_config_json"])
        ),
        baseline=RunConfig.model_validate(json.loads(row["baseline_config_json"])),
        alternatives=[
            AlternativeSpec.model_validate(item)
            for item in (json.loads(row["alternative_configs_json"] or "[]"))
        ],
        task_prompt=task_spec.get("task_prompt", ""),
        initial_ref=task_spec.get("initial_ref", "main"),
        repeat_count=row["repeat_count"],
        timeout_s=row["timeout_s"],
        created_at=row["created_at"],
    )


def _run_from_row(row: sqlite3.Row, usage: RunUsage) -> BenchmarkRunOut:
    test_results = json.loads(row["test_results_json"]) if row["test_results_json"] else None
    return BenchmarkRunOut(
        id=row["id"],
        benchmark_id=row["benchmark_id"],
        variant_name=row["variant_name"],
        model_id=row["model_id"],
        config=json.loads(row["config_json"]) if row["config_json"] else {},
        run_status=row["run_status"],
        outcome=row["outcome"],
        total_cost=cost_to_decimal(row["total_cost"]),
        currency=usage.currency,
        unknown_cost_events=usage.unknown_cost_events,
        total_tokens=row["total_tokens"],
        request_count=row["request_count"],
        retry_count=row["retry_count"],
        duration_ms=row["duration_ms"],
        test_exit_code=row["test_exit_code"],
        test_results=test_results,
        patch_path=row["patch_path"],
        worktree_path=row["worktree_path"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        repeat_index=row["repeat_index"],
        error=row["error"],
        eligible=row["eligible"],
    )


class BenchmarkStore:
    """SQL for benchmarks and runs. The caller owns commits."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_benchmark(
        self,
        *,
        benchmark_id: str,
        project_id: str,
        task_id: str,
        name: str,
        description: str | None,
        initial_git_sha: str,
        acceptance: AcceptanceConfig,
        baseline: RunConfig,
        alternatives: list[AlternativeSpec],
        task_prompt: str,
        initial_ref: str,
        repeat_count: int,
        timeout_s: int,
    ) -> BenchmarkOut:
        self._conn.execute(
            "INSERT INTO benchmarks (id, project_id, task_id, name, initial_git_sha, "
            "acceptance_config_json, baseline_config_json, created_at, description, "
            "task_spec_json, alternative_configs_json, repeat_count, timeout_s) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                benchmark_id,
                project_id,
                task_id,
                name,
                initial_git_sha,
                json.dumps(acceptance.model_dump(mode="json"), sort_keys=True),
                json.dumps(baseline.model_dump(mode="json"), sort_keys=True),
                utc_now_z(),
                description,
                json.dumps(
                    {"task_prompt": task_prompt, "initial_ref": initial_ref},
                    sort_keys=True,
                ),
                json.dumps(
                    [spec.model_dump(mode="json") for spec in alternatives],
                    sort_keys=True,
                ),
                repeat_count,
                timeout_s,
            ),
        )
        benchmark = self.get_benchmark(benchmark_id)
        assert benchmark is not None
        return benchmark

    def get_benchmark(self, benchmark_id: str) -> BenchmarkOut | None:
        row = self._conn.execute(
            f"SELECT {_BENCHMARK_COLUMNS} FROM benchmarks WHERE id = ?", (benchmark_id,)
        ).fetchone()
        return _benchmark_from_row(row) if row is not None else None

    def list_benchmarks(self) -> list[BenchmarkOut]:
        rows = self._conn.execute(
            f"SELECT {_BENCHMARK_COLUMNS} FROM benchmarks ORDER BY created_at, id"
        ).fetchall()
        return [_benchmark_from_row(row) for row in rows]

    def create_run(
        self,
        benchmark_id: str,
        variant_name: str,
        model_id: str,
        config: dict[str, Any],
        repeat_index: int,
    ) -> BenchmarkRunOut:
        run_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO benchmark_runs (id, benchmark_id, variant_name, model_id, "
            "config_json, run_status, repeat_index) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
            (
                run_id,
                benchmark_id,
                variant_name,
                model_id,
                json.dumps(config, sort_keys=True),
                repeat_index,
            ),
        )
        run = self.get_run(run_id)
        assert run is not None
        return run

    def get_run(self, run_id: str) -> BenchmarkRunOut | None:
        row = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM benchmark_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return _run_from_row(row, aggregate_run_usage(self._conn, run_id))

    def list_runs(self, benchmark_id: str) -> list[BenchmarkRunOut]:
        rows = self._conn.execute(
            f"SELECT {_RUN_COLUMNS} FROM benchmark_runs WHERE benchmark_id = ? "
            "ORDER BY rowid",
            (benchmark_id,),
        ).fetchall()
        return [
            _run_from_row(row, aggregate_run_usage(self._conn, row["id"])) for row in rows
        ]

    def update_run(self, run_id: str, **fields: Any) -> None:
        unknown = set(fields) - _RUN_UPDATE_COLUMNS
        if unknown:
            raise ValueError(f"unknown benchmark_runs columns: {sorted(unknown)}")
        assignments = ", ".join(f"{column} = ?" for column in fields)
        self._conn.execute(
            f"UPDATE benchmark_runs SET {assignments} WHERE id = ?",
            [*fields.values(), run_id],
        )

    def recover_interrupted(self) -> int:
        """Fail runs a dead process left behind; neither queued nor running survives it."""
        cursor = self._conn.execute(
            "UPDATE benchmark_runs SET run_status = 'failed', outcome = 'inconclusive', "
            "error = ?, completed_at = ?, eligible = 0 "
            "WHERE run_status IN ('queued', 'running')",
            (INTERRUPTED_BY_RESTART, utc_now_z()),
        )
        return cursor.rowcount


def _redacted_error(exc: BaseException) -> str:
    return redact_text(f"{type(exc).__name__}: {exc}")[:_ERROR_CHARS]


def _cancelled_between_steps(cancel: threading.Event | None) -> bool:
    return cancel is not None and cancel.is_set()


@dataclass(frozen=True)
class _PhaseOutcome:
    run_status: RunStatus
    outcome: RunOutcome
    error: str | None
    test_exit_code: int | None = None
    test_results: dict[str, Any] | None = None


def execute_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    gateway_url: str,
    local_token: str,
    data_dir: Path,
    transport: httpx.AsyncBaseTransport | None = None,
    cancel: threading.Event | None = None,
    keep_worktrees: bool = False,
) -> BenchmarkRunOut:
    """Run one queued benchmark run to a terminal state. See the module docstring
    for the connection contract. Only a missing run raises; every other failure
    is recorded on the run."""
    store = BenchmarkStore(conn)
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(f"unknown benchmark run {run_id!r}")
    benchmark = store.get_benchmark(run.benchmark_id)
    assert benchmark is not None
    started_at = utc_now_z()
    store.update_run(
        run_id, run_status="running", started_at=started_at, worktree_path=None
    )
    conn.commit()

    worktree: Worktree | None = None
    try:
        try:
            repository = _resolve_repository(conn, benchmark.project_id)
            worktree = _create_checked_worktree(
                repository, benchmark.initial_git_sha, run_id, data_dir
            )
            store.update_run(run_id, worktree_path=str(worktree.path))
            conn.commit()
            outcome = _execute_phases(
                run,
                benchmark,
                worktree,
                gateway_url=gateway_url,
                local_token=local_token,
                transport=transport,
                cancel=cancel,
            )
        except AgentCancelled:
            outcome = _PhaseOutcome("completed", "cancelled", "cancelled")
        except AgentTimeout as exc:
            outcome = _PhaseOutcome("completed", "timed_out", _redacted_error(exc))
        except (AgentGatewayError, ValueError) as exc:
            outcome = _PhaseOutcome("failed", "inconclusive", _redacted_error(exc))
        except Exception as exc:  # a run must never escape unrecorded
            outcome = _PhaseOutcome("failed", "inconclusive", _redacted_error(exc))
    finally:
        _export_and_cleanup(store, conn, run_id, worktree, data_dir, keep_worktrees)
    return _finish(
        store,
        conn,
        run_id,
        started_at,
        outcome.run_status,
        outcome.outcome,
        outcome.error,
        test_exit_code=outcome.test_exit_code,
        test_results=outcome.test_results,
    )


def _execute_phases(
    run: BenchmarkRunOut,
    benchmark: BenchmarkOut,
    worktree: Worktree,
    *,
    gateway_url: str,
    local_token: str,
    transport: httpx.AsyncBaseTransport | None,
    cancel: threading.Event | None,
) -> _PhaseOutcome:
    """Agent loop then acceptance tests. Infrastructure failures raise; the
    model's behavior only ever reaches `passed`/`failed` via the test results."""
    timeout_s = benchmark.timeout_s or DEFAULT_TIMEOUT_S
    config = RunConfig.model_validate(run.config)
    asyncio.run(
        run_agent(
            benchmark.task_prompt,
            config,
            AgentTools(worktree.path),
            gateway_url,
            run.id,
            task_id=benchmark.task_id,
            local_token=local_token,
            transport=transport,
            timeout_s=float(timeout_s),
            cancel=cancel,
        )
    )
    if _cancelled_between_steps(cancel):
        return _PhaseOutcome("completed", "cancelled", "cancelled")

    test_result = run_sandboxed(
        resolve_acceptance_command(benchmark.acceptance.command),
        cwd=worktree.path,
        timeout_s=timeout_s,
    )
    if _cancelled_between_steps(cancel):
        return _PhaseOutcome("completed", "cancelled", "cancelled")
    if test_result.timed_out:
        return _PhaseOutcome(
            "completed",
            "timed_out",
            f"acceptance command timed out after {timeout_s}s",
        )
    collected = _collect_nodeids(worktree.path, benchmark, timeout_s)
    results = parse_pytest_results(
        test_result.stdout_tail,
        test_result.stderr_tail,
        test_result.exit_code or 0,
        benchmark.acceptance.required_pass,
        collected,
    )
    required_ok = all(status == "passed" for status in results["required"].values())
    if test_result.exit_code == 0 and required_ok:
        return _PhaseOutcome(
            "completed", "passed", None,
            test_exit_code=test_result.exit_code, test_results=results,
        )
    return _PhaseOutcome(
        "completed", "failed", _failure_reason(test_result, results),
        test_exit_code=test_result.exit_code, test_results=results,
    )


def _resolve_repository(conn: sqlite3.Connection, project_id: str) -> Path:
    """The runner enforces the registered-project clause: the repo comes from
    the project's `repository_path`, never from the run or task payload."""
    row = conn.execute(
        "SELECT repository_path FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise FileNotFoundError(f"project {project_id!r} no longer exists")
    if not row["repository_path"]:
        raise FileNotFoundError(f"project {project_id!r} has no repository_path")
    repository = Path(row["repository_path"])
    if not repository.is_dir():
        raise FileNotFoundError(f"repository {repository} is not a directory")
    return repository


def _create_checked_worktree(
    repository: Path, initial_git_sha: str | None, run_id: str, data_dir: Path
) -> Worktree:
    if not initial_git_sha:
        raise ValueError("benchmark has no pinned initial_git_sha")
    try:
        worktree = create_worktree(
            repository, initial_git_sha, run_id, data_dir=data_dir
        )
    except subprocess.CalledProcessError as exc:
        raise OSError(f"worktree creation failed: {exc.stderr.strip()}") from exc
    if worktree.sha != initial_git_sha:
        remove_worktree(worktree)
        raise OSError(
            f"worktree checked out {worktree.sha}, expected {initial_git_sha}"
        )
    return worktree


def _collect_nodeids(
    worktree_path: Path, benchmark: BenchmarkOut, timeout_s: int
) -> set[str] | None:
    """Best-effort `--collect-only` listing so missing required tests are caught."""
    if not benchmark.acceptance.required_pass:
        return set()
    command = resolve_acceptance_command(benchmark.acceptance.command)
    python, rest = command[0], command[1:]
    if rest[:2] != ["-m", "pytest"]:
        return None
    try:
        collected = run_sandboxed(
            [python, "-m", "pytest", "--collect-only", "-q"],
            cwd=worktree_path,
            timeout_s=min(timeout_s, 120),
        )
    except Exception as exc:  # supplementary evidence only
        logger.warning("collect-only run failed: %s", _redacted_error(exc))
        return None
    if collected.timed_out or collected.exit_code not in (0, 5):
        return None
    # Exit 5 ("no tests collected") still yields a valid, possibly empty, listing.
    return parse_collect_only(collected.stdout_tail)


def _failure_reason(result: SandboxResult, results: dict[str, Any]) -> str:
    missing = sorted(
        nodeid
        for nodeid, status in results["required"].items()
        if status == "missing"
    )
    if missing:
        return f"required tests missing: {', '.join(missing)}"
    failing = sorted(
        nodeid
        for nodeid, status in results["required"].items()
        if status != "passed"
    )
    if failing:
        return f"required tests not passed: {', '.join(failing)}"
    return f"acceptance command exited {result.exit_code}"


def _finish(
    store: BenchmarkStore,
    conn: sqlite3.Connection,
    run_id: str,
    started_at: str,
    run_status: RunStatus,
    outcome: RunOutcome,
    error: str | None,
    *,
    test_exit_code: int | None = None,
    test_results: dict[str, Any] | None = None,
) -> BenchmarkRunOut:
    usage = aggregate_run_usage(conn, run_id)
    completed_at = utc_now_z()
    duration_ms = int(
        (parse_utc_z(completed_at) - parse_utc_z(started_at)).total_seconds() * 1000
    )
    store.update_run(
        run_id,
        run_status=run_status,
        outcome=outcome,
        error=error[:_ERROR_CHARS] if error else None,
        test_exit_code=test_exit_code,
        test_results_json=(
            json.dumps(test_results, sort_keys=True) if test_results is not None else None
        ),
        total_cost=float(usage.total_cost) if usage.total_cost is not None else None,
        total_tokens=usage.total_tokens,
        request_count=usage.request_count,
        retry_count=usage.retry_count,
        duration_ms=duration_ms,
        completed_at=completed_at,
        eligible=(
            1 if run_status == "completed" and outcome not in ("cancelled", "inconclusive")
            else 0
        ),
    )
    conn.commit()
    finished = store.get_run(run_id)
    assert finished is not None
    return finished


def _export_and_cleanup(
    store: BenchmarkStore,
    conn: sqlite3.Connection,
    run_id: str,
    worktree: Worktree | None,
    data_dir: Path,
    keep_worktrees: bool,
) -> None:
    """Export the patch, then remove the worktree unless it is retained.
    Best-effort: cleanup failures are logged and never flip the recorded outcome."""
    if worktree is None:
        return
    try:
        patch_path = export_patch(worktree, data_dir=data_dir)
    except Exception as exc:  # outcome already recorded
        logger.warning("patch export failed for run %s: %s", run_id, _redacted_error(exc))
    else:
        store.update_run(run_id, patch_path=str(patch_path))
        conn.commit()
    if keep_worktrees:
        return
    try:
        remove_worktree(worktree)
    except Exception as exc:  # disk cleanup must not fail the run
        logger.warning(
            "worktree removal failed for run %s: %s", run_id, _redacted_error(exc)
        )
    else:
        store.update_run(run_id, worktree_path=None)
        conn.commit()
