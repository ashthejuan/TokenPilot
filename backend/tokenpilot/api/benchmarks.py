"""Benchmark experiments, run enqueue, run detail, and cancel."""

import subprocess
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from tokenpilot.benchmarks.agent import PROMPT_TEMPLATES
from tokenpilot.benchmarks.runner import BenchmarkStore
from tokenpilot.benchmarks.worker import BenchmarkWorker
from tokenpilot.benchmarks.worktree import resolve_sha
from tokenpilot.db.database import Database, get_db
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.benchmarks import (
    AlternativeSpec,
    BenchmarkCreate,
    BenchmarkDetail,
    BenchmarkOut,
    BenchmarkRunOut,
    CancelRunsResponse,
    CreateRunsRequest,
    merge_variant_config,
)
from tokenpilot.timeutil import utc_now_z

router = APIRouter(prefix="/api/v1", tags=["benchmarks"])

BASELINE_VARIANT = "baseline"


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
        benchmark = BenchmarkStore(conn).create_benchmark(
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
        )
    if idempotency_key:
        keys[idempotency_key] = benchmark.id
    return benchmark


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


@router.get("/benchmark-runs/{run_id}")
def get_run(run_id: str, db: Annotated[Database, Depends(get_db)]) -> BenchmarkRunOut:
    with db.read() as conn:
        run = BenchmarkStore(conn).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="benchmark run not found")
    return run


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
