"""Benchmark experiments, run enqueue, run detail, cancel, and compare."""

import json
import sqlite3
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tokenpilot.benchmarks.agent import PROMPT_TEMPLATES
from tokenpilot.benchmarks.runner import BenchmarkStore
from tokenpilot.benchmarks.worker import BenchmarkWorker
from tokenpilot.benchmarks.worktree import resolve_sha
from tokenpilot.db.database import Database, get_db
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.pricing.cost import quantize_money
from tokenpilot.savings.classify import ComparisonStatus, compare
from tokenpilot.schemas.benchmarks import (
    AlternativeSpec,
    BenchmarkCreate,
    BenchmarkDetail,
    BenchmarkOut,
    BenchmarkRunOut,
    CancelRunsResponse,
    CreateRunsRequest,
    cost_to_decimal,
    merge_variant_config,
)
from tokenpilot.schemas.common import Money
from tokenpilot.timeutil import utc_now_z

router = APIRouter(prefix="/api/v1", tags=["benchmarks"])

BASELINE_VARIANT = "baseline"


class CompareRequest(BaseModel):
    """`POST /api/v1/benchmarks/{id}/compare` body: the two variants to pair."""

    model_config = ConfigDict(extra="forbid")

    baseline_variant: str = Field(min_length=1)
    alternative_variant: str = Field(min_length=1)


class ComparisonOut(BaseModel):
    """One persisted `benchmark_comparisons` row, with its methodology."""

    id: str
    benchmark_id: str
    baseline_variant: str
    alternative_variant: str
    baseline_run_id: str
    alternative_run_id: str
    cost_delta: Money | None
    cost_delta_pct: Decimal | None
    correctness_preserved: bool | None
    comparison_status: ComparisonStatus
    methodology: dict[str, Any]
    reasons: list[str] = Field(default_factory=list)
    created_at: str


def _worker(request: Request) -> BenchmarkWorker:
    worker: BenchmarkWorker = request.app.state.benchmark_worker
    return worker


def _idempotency_keys(request: Request) -> dict[str, str]:
    keys: dict[str, str] = request.app.state.benchmark_idempotency
    return keys


def _out_payload(model: Any) -> Any:
    return model.model_dump(mode="json")


@router.post("/benchmarks", status_code=201, response_model=None)
def create_benchmark(
    body: BenchmarkCreate,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BenchmarkOut | JSONResponse:
    keys = _idempotency_keys(request)
    if idempotency_key and idempotency_key in keys:
        with db.read() as conn:
            replayed = BenchmarkStore(conn).get_benchmark(keys[idempotency_key])
        if replayed is not None:
            return JSONResponse(status_code=200, content=_out_payload(replayed))
    benchmark = create_benchmark_record(body, db)
    if idempotency_key:
        keys[idempotency_key] = benchmark.id
    return benchmark


def create_benchmark_record(
    body: BenchmarkCreate,
    db: Database,
    *,
    insight_id: str | None = None,
) -> BenchmarkOut:
    """Validate a benchmark definition and persist it, pinning `initial_git_sha`.

    Shared by `POST /benchmarks` and the insight → benchmark bridge; callers own
    idempotency handling.
    """
    with db.read() as conn:
        project = LedgerRepository(conn).get_project(body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if project.repository_path is None or Path(body.repository_path).resolve() != Path(
        project.repository_path
    ).resolve():
        raise HTTPException(
            status_code=422,
            detail="repository_path does not match the project's registered repository",
        )
    repository = Path(project.repository_path)
    try:
        initial_sha = resolve_sha(repository, body.initial_ref)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"cannot resolve initial_ref {body.initial_ref!r}: {exc}",
        ) from exc
    if body.baseline.prompt_template not in PROMPT_TEMPLATES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown prompt_template {body.baseline.prompt_template!r}",
        )
    benchmark_id = uuid.uuid4().hex
    with db.write() as conn:
        repository_ledger = LedgerRepository(conn)
        task_id = repository_ledger.create_task(
            project_id=project.id, external_task_id=f"benchmark-{benchmark_id}"
        )
        return BenchmarkStore(conn).create_benchmark(
            benchmark_id=benchmark_id,
            project_id=project.id,
            task_id=task_id,
            name=body.name,
            description=body.description,
            initial_git_sha=initial_sha,
            acceptance=body.acceptance,
            baseline=body.baseline,
            alternatives=body.alternatives,
            task_prompt=body.task_prompt,
            initial_ref=body.initial_ref,
            repeat_count=body.repeat_count,
            timeout_s=body.timeout_s,
            insight_id=insight_id,
        )


@router.get("/benchmarks")
def list_benchmarks(db: Annotated[Database, Depends(get_db)]) -> list[BenchmarkOut]:
    with db.read() as conn:
        return BenchmarkStore(conn).list_benchmarks()


@router.get("/benchmarks/{benchmark_id}")
def get_benchmark(
    benchmark_id: str, db: Annotated[Database, Depends(get_db)]
) -> BenchmarkDetail:
    with db.read() as conn:
        store = BenchmarkStore(conn)
        benchmark = store.get_benchmark(benchmark_id)
        if benchmark is None:
            raise HTTPException(status_code=404, detail="benchmark not found")
        return BenchmarkDetail(
            **benchmark.model_dump(), runs=store.list_runs(benchmark_id)
        )


@router.post("/benchmarks/{benchmark_id}/runs", status_code=202)
def start_runs(
    benchmark_id: str,
    body: CreateRunsRequest,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
) -> list[BenchmarkRunOut]:
    with db.read() as conn:
        benchmark = BenchmarkStore(conn).get_benchmark(benchmark_id)
    if benchmark is None:
        raise HTTPException(status_code=404, detail="benchmark not found")
    specs: dict[str, AlternativeSpec | None] = {BASELINE_VARIANT: None}
    specs.update({spec.name: spec for spec in benchmark.alternatives})
    unknown = [name for name in body.variants if name not in specs]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown variants: {', '.join(unknown)}"
        )
    merged: dict[str, dict[str, Any]] = {}
    for name in body.variants:
        try:
            merged[name] = merge_variant_config(benchmark.baseline, specs[name])
        except ValidationError as exc:
            raise HTTPException(
                status_code=422, detail=f"variant {name!r} config is invalid: {exc}"
            ) from exc
        template = merged[name].get("prompt_template")
        if template not in PROMPT_TEMPLATES:
            raise HTTPException(
                status_code=422, detail=f"unknown prompt_template {template!r}"
            )
    repeat_count = body.repeat_count or benchmark.repeat_count or 1
    worker = _worker(request)
    runs: list[BenchmarkRunOut] = []
    with db.write() as conn:
        store = BenchmarkStore(conn)
        for repeat_index in range(repeat_count):
            for name in body.variants:
                runs.append(
                    store.create_run(
                        benchmark_id,
                        name,
                        str(merged[name]["model_id"]),
                        merged[name],
                        repeat_index,
                    )
                )
    for run in runs:
        worker.enqueue(run.id)
    return runs


@router.post("/benchmarks/{benchmark_id}/compare", status_code=201)
def compare_variants(
    benchmark_id: str,
    body: CompareRequest,
    db: Annotated[Database, Depends(get_db)],
) -> ComparisonOut:
    with db.read() as conn:
        store = BenchmarkStore(conn)
        benchmark = store.get_benchmark(benchmark_id)
        runs = store.list_runs(benchmark_id) if benchmark is not None else []
    if benchmark is None:
        raise HTTPException(status_code=404, detail="benchmark not found")
    known = {BASELINE_VARIANT} | {spec.name for spec in benchmark.alternatives}
    for name in (body.baseline_variant, body.alternative_variant):
        if name not in known:
            raise HTTPException(status_code=404, detail=f"unknown variant {name!r}")
    if body.baseline_variant == body.alternative_variant:
        raise HTTPException(
            status_code=422,
            detail="baseline_variant and alternative_variant must differ",
        )
    baseline = [run for run in runs if run.variant_name == body.baseline_variant]
    alternative = [run for run in runs if run.variant_name == body.alternative_variant]
    for name, variant_runs in (
        (body.baseline_variant, baseline),
        (body.alternative_variant, alternative),
    ):
        if not variant_runs:
            raise HTTPException(
                status_code=422, detail=f"variant {name!r} has no runs to compare"
            )
    result = compare(benchmark, baseline, alternative)
    comparison_id = uuid.uuid4().hex
    created_at = utc_now_z()
    methodology_json = {**result.methodology, "reasons": result.reasons}
    with db.write() as conn:
        conn.execute(
            "INSERT INTO benchmark_comparisons (id, benchmark_id, baseline_run_id, "
            "alternative_run_id, cost_delta, cost_delta_pct, correctness_preserved, "
            "comparison_status, methodology_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                comparison_id,
                benchmark_id,
                baseline[0].id,
                alternative[0].id,
                (
                    None
                    if result.cost_delta is None
                    else float(quantize_money(result.cost_delta))
                ),
                None if result.cost_delta_pct is None else float(result.cost_delta_pct),
                (
                    None
                    if result.correctness_preserved is None
                    else int(result.correctness_preserved)
                ),
                result.comparison_status,
                json.dumps(methodology_json, sort_keys=True),
                created_at,
            ),
        )
        if benchmark.insight_id:
            # A persisted comparison is the proof the recommendation was tested.
            conn.execute(
                "UPDATE insights SET status = 'tested', updated_at = ? WHERE id = ?",
                (created_at, benchmark.insight_id),
            )
    return ComparisonOut(
        id=comparison_id,
        benchmark_id=benchmark_id,
        baseline_variant=body.baseline_variant,
        alternative_variant=body.alternative_variant,
        baseline_run_id=baseline[0].id,
        alternative_run_id=alternative[0].id,
        cost_delta=result.cost_delta,
        cost_delta_pct=result.cost_delta_pct,
        correctness_preserved=result.correctness_preserved,
        comparison_status=result.comparison_status,
        methodology=result.methodology,
        reasons=result.reasons,
        created_at=created_at,
    )


def _comparison_from_row(
    row: sqlite3.Row, variants_by_run_id: dict[str, str]
) -> ComparisonOut:
    stored: dict[str, Any] = (
        json.loads(row["methodology_json"]) if row["methodology_json"] else {}
    )
    reasons = stored.pop("reasons", [])
    return ComparisonOut(
        id=row["id"],
        benchmark_id=row["benchmark_id"],
        baseline_variant=variants_by_run_id[row["baseline_run_id"]],
        alternative_variant=variants_by_run_id[row["alternative_run_id"]],
        baseline_run_id=row["baseline_run_id"],
        alternative_run_id=row["alternative_run_id"],
        cost_delta=cost_to_decimal(row["cost_delta"]),
        cost_delta_pct=cost_to_decimal(row["cost_delta_pct"]),
        correctness_preserved=(
            None
            if row["correctness_preserved"] is None
            else bool(row["correctness_preserved"])
        ),
        comparison_status=row["comparison_status"],
        methodology=stored,
        reasons=reasons,
        created_at=row["created_at"],
    )


@router.get("/benchmarks/{benchmark_id}/comparisons")
def list_comparisons(
    benchmark_id: str, db: Annotated[Database, Depends(get_db)]
) -> list[ComparisonOut]:
    with db.read() as conn:
        store = BenchmarkStore(conn)
        if store.get_benchmark(benchmark_id) is None:
            raise HTTPException(status_code=404, detail="benchmark not found")
        variants_by_run_id = {
            run.id: run.variant_name for run in store.list_runs(benchmark_id)
        }
        rows = conn.execute(
            "SELECT id, benchmark_id, baseline_run_id, alternative_run_id, "
            "cost_delta, cost_delta_pct, correctness_preserved, comparison_status, "
            "methodology_json, created_at FROM benchmark_comparisons "
            "WHERE benchmark_id = ? ORDER BY created_at DESC, rowid DESC",
            (benchmark_id,),
        ).fetchall()
        return [
            _comparison_from_row(row, variants_by_run_id) for row in rows
        ]


@router.get("/benchmark-runs/{run_id}")
def get_run(run_id: str, db: Annotated[Database, Depends(get_db)]) -> BenchmarkRunOut:
    with db.read() as conn:
        run = BenchmarkStore(conn).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="benchmark run not found")
    return run


@router.get("/benchmark-runs/{run_id}/patch", response_class=PlainTextResponse)
def get_run_patch(run_id: str, db: Annotated[Database, Depends(get_db)]) -> PlainTextResponse:
    with db.read() as conn:
        run = BenchmarkStore(conn).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="benchmark run not found")
    if not run.patch_path:
        raise HTTPException(status_code=404, detail="benchmark run has no patch")
    try:
        text = Path(run.patch_path).read_bytes().decode("utf-8", errors="replace")
    except OSError:
        raise HTTPException(status_code=404, detail="patch file not found") from None
    return PlainTextResponse(text)


@router.post("/benchmarks/{benchmark_id}/cancel")
def cancel_benchmark(
    benchmark_id: str,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
) -> CancelRunsResponse:
    with db.read() as conn:
        store = BenchmarkStore(conn)
        if store.get_benchmark(benchmark_id) is None:
            raise HTTPException(status_code=404, detail="benchmark not found")
    worker = _worker(request)
    cancelled: list[str] = []
    with db.write() as conn:
        store = BenchmarkStore(conn)
        for run in store.list_runs(benchmark_id):
            if run.run_status not in ("queued", "running"):
                continue
            worker.cancel(run.id)
            cancelled.append(run.id)
            if run.run_status == "queued":
                store.update_run(
                    run.id,
                    run_status="completed",
                    outcome="cancelled",
                    error="cancelled",
                    completed_at=utc_now_z(),
                    eligible=0,
                )
    return CancelRunsResponse(cancelled_run_ids=cancelled)
