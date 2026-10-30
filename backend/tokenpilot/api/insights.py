"""Insight analyze jobs, list/detail with resolved evidence, and status PATCH."""

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from tokenpilot.api.benchmarks import create_benchmark_record
from tokenpilot.db.database import Database, get_db
from tokenpilot.detectors.base import EvidenceRef, Severity
from tokenpilot.detectors.runner import REGISTRY
from tokenpilot.insights.evidence import resolve_evidence
from tokenpilot.insights.jobs import JobRepository, run_analysis_job
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.investigator.evidence import (
    build_bundle,
    disclosure_lines,
    is_contributor_model,
)
from tokenpilot.investigator.repository import FeedbackRepository, InvestigationRepository
from tokenpilot.investigator.service import run_investigation_job
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.benchmarks import (
    AlternativeSpec,
    BenchmarkCreate,
    BenchmarkOut,
    BenchmarkTaskSpec,
    ContextStrategy,
    InsightBenchmarkCreate,
    RetryPolicy,
    RunConfig,
)
from tokenpilot.schemas.common import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    InvalidCursorError,
    Page,
    Paged,
)
from tokenpilot.schemas.insights import (
    AnalyzeAccepted,
    AnalyzeRequest,
    FeedbackOut,
    FeedbackRequest,
    InsightDetail,
    InsightFilters,
    InsightOut,
    InsightStatus,
    InsightStatusUpdate,
    InvestigateAccepted,
    InvestigateRequest,
    InvestigationMode,
    InvestigationOut,
    InvestigationPreviewOut,
    JobOut,
    ResolvedEvidence,
    StatusNotSettableError,
)

router = APIRouter(prefix="/api/v1", tags=["insights"])


def _with_guidance(insight: InsightOut) -> InsightOut:
    detector = REGISTRY.get(insight.rule_id)
    guidance = detector.guidance if detector is not None else None
    return insight.model_copy(update={"rule_guidance": guidance})


def _evidence_refs(insight: InsightOut) -> list[EvidenceRef]:
    return [
        EvidenceRef(kind=ref.kind, id=ref.id, measurement=dict(ref.measurement))
        for ref in insight.evidence
    ]


@router.post("/insights/analyze", status_code=202)
def analyze(
    body: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
) -> AnalyzeAccepted:
    # Validate on the request thread before creating the job (unknown rule_ids → 422).
    with db.write() as conn:
        job = JobRepository(conn).create("analyze", body.model_dump())
    background_tasks.add_task(
        run_analysis_job, db, request.app.state.settings.db_path, job.id, body
    )
    return AnalyzeAccepted(job_id=job.id)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Annotated[Database, Depends(get_db)]) -> JobOut:
    with db.read() as conn:
        job = JobRepository(conn).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/insights")
def list_insights(
    db: Annotated[Database, Depends(get_db)],
    status: InsightStatus | None = None,
    severity: Severity | None = None,
    rule_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
) -> Paged[InsightOut]:
    filters = InsightFilters(
        status=status,
        severity=severity,
        rule_id=rule_id,
        project_id=project_id,
        session_id=session_id,
    )
    try:
        with db.read() as conn:
            page = InsightRepository(conn).list(filters, Page(limit=limit, cursor=cursor))
    except InvalidCursorError as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc
    return Paged[InsightOut](
        items=[_with_guidance(item) for item in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/insights/{insight_id}")
def get_insight(
    insight_id: str, db: Annotated[Database, Depends(get_db)]
) -> InsightDetail:
    with db.read() as conn:
        insight = InsightRepository(conn).get(insight_id)
        if insight is None:
            raise HTTPException(status_code=404, detail="insight not found")
        rows = resolve_evidence(conn, _evidence_refs(insight))
    return InsightDetail(insight=_with_guidance(insight), evidence_rows=rows)


@router.patch("/insights/{insight_id}")
def patch_insight(
    insight_id: str,
    body: InsightStatusUpdate,
    db: Annotated[Database, Depends(get_db)],
) -> InsightOut:
    if body.status == "tested":
        raise StatusNotSettableError(body.status)
    with db.write() as conn:
        insight = InsightRepository(conn).set_status(insight_id, body.status)
    if insight is None:
        raise HTTPException(status_code=404, detail="insight not found")
    return _with_guidance(insight)


@router.get("/insights/{insight_id}/investigation-preview", response_model=InvestigationPreviewOut)
def investigation_preview(
    insight_id: str,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    mode: InvestigationMode = "metadata_only",
) -> InvestigationPreviewOut | JSONResponse:
    settings = request.app.state.settings
    try:
        with db.read() as conn:
            bundle = build_bundle(conn, insight_id, mode, settings=settings)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="insight not found") from exc
    except PermissionError:
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "content_transmission_disabled",
                    "message": "content transmission or storage is disabled",
                    "details": None,
                }
            },
        )

    contains_content = mode == "with_excerpts"
    contributor_training = is_contributor_model(settings.investigator_model)
    return InvestigationPreviewOut(
        bundle=bundle.to_dict(),
        destination=settings.upstream_base_url,
        model=settings.investigator_model,
        contains_content=contains_content,
        contributor_training=contributor_training,
        disclosure_lines=disclosure_lines(
            destination=settings.upstream_base_url,
            model=settings.investigator_model,
            contains_content=contains_content,
            contributor_training=contributor_training,
        ),
    )


def _upstream_key_configured(settings: object) -> bool:
    api_key = getattr(settings, "upstream_api_key", None)
    if api_key is None:
        return False
    return bool(api_key.get_secret_value().strip())


@router.post("/insights/{insight_id}/investigate", status_code=202, response_model=None)
def investigate_insight(
    insight_id: str,
    body: InvestigateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
) -> InvestigateAccepted | JSONResponse:
    settings = request.app.state.settings
    with db.read() as conn:
        insight = InsightRepository(conn).get(insight_id)
    if insight is None:
        raise HTTPException(status_code=404, detail="insight not found")

    if body.mode == "with_excerpts" and not (
        settings.allow_content_transmission and settings.store_content
    ):
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "content_transmission_disabled",
                    "message": "content transmission or storage is disabled",
                    "details": None,
                }
            },
        )

    if not _upstream_key_configured(settings):
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "upstream_not_configured",
                    "message": "upstream API key is not configured",
                    "details": None,
                }
            },
        )

    params = {"insight_id": insight_id, "mode": body.mode}
    with db.write() as conn:
        job = JobRepository(conn).create("investigate", params)

    background_tasks.add_task(
        run_investigation_job,
        db,
        settings.db_path,
        settings,
        job.id,
        transport=getattr(request.app.state, "upstream_transport", None),
    )
    return InvestigateAccepted(job_id=job.id)


@router.get("/insights/{insight_id}/investigations")
def list_investigations(
    insight_id: str, db: Annotated[Database, Depends(get_db)]
) -> list[InvestigationOut]:
    with db.read() as conn:
        if InsightRepository(conn).get(insight_id) is None:
            raise HTTPException(status_code=404, detail="insight not found")
        return InvestigationRepository(conn).list_for_insight(insight_id)


@router.post("/insights/{insight_id}/feedback", status_code=201)
def post_feedback(
    insight_id: str,
    body: FeedbackRequest,
    db: Annotated[Database, Depends(get_db)],
) -> FeedbackOut:
    with db.write() as conn:
        if InsightRepository(conn).get(insight_id) is None:
            raise HTTPException(status_code=404, detail="insight not found")
        return FeedbackRepository(conn).add(
            insight_id=insight_id,
            verdict=body.verdict,
            implemented=body.implemented,
            note=body.note,
        )


_SUPPORTED_VARIABLES = frozenset(
    {"context_strategy", "model_id", "retry_policy", "temperature"}
)
_MAX_TASK_SPEC_BYTES = 64 * 1024


class _BridgeError(Exception):
    """A bridge request the API answers with a structured 422 (or 404)."""

    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _bridge_error_response(exc: _BridgeError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": None,
            }
        },
    )


def _validation_message(exc: ValidationError) -> str:
    """Field locations and messages only: never echo the input value."""
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
        parts.append(f"{location}: {error.get('msg', 'invalid value')}")
    return "; ".join(parts)


def _load_task_spec(
    body: InsightBenchmarkCreate, allowed_roots: list[Path]
) -> BenchmarkTaskSpec:
    if body.task_spec_path is not None and body.task_spec is not None:
        raise _BridgeError(
            "task_spec_conflict",
            "provide either task_spec_path or task_spec, not both",
        )
    if body.task_spec_path is not None:
        path = Path(body.task_spec_path).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise _BridgeError(
                "task_spec_not_found", f"cannot read task_spec_path: {exc}"
            ) from exc
        roots = [root.resolve() for root in allowed_roots]
        if not any(resolved.is_relative_to(root) for root in roots):
            raise _BridgeError(
                "task_spec_path_outside_allowed_roots",
                "task_spec_path must be inside the project repository or the "
                "TokenPilot data directory",
            )
        try:
            if resolved.stat().st_size > _MAX_TASK_SPEC_BYTES:
                raise _BridgeError(
                    "task_spec_too_large",
                    f"task_spec_path exceeds {_MAX_TASK_SPEC_BYTES} bytes",
                )
            raw = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise _BridgeError(
                "task_spec_not_found", f"cannot read task_spec_path: {exc}"
            ) from exc
        try:
            data: Any = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise _BridgeError("invalid_task_spec", f"task_spec_path is not YAML: {exc}") from exc
    elif body.task_spec is not None:
        data = body.task_spec
    else:
        raise _BridgeError(
            "task_spec_required",
            "provide task_spec_path or task_spec: a benchmark needs a task prompt "
            "and acceptance criteria",
        )
    if not isinstance(data, dict):
        raise _BridgeError("invalid_task_spec", "task spec must be an object")
    try:
        return BenchmarkTaskSpec.model_validate(data)
    except ValidationError as exc:
        raise _BridgeError(
            "invalid_task_spec", f"task spec is invalid: {_validation_message(exc)}"
        ) from exc


def _observed_model(
    conn: sqlite3.Connection, insight: InsightOut, evidence_rows: list[ResolvedEvidence]
) -> str:
    for row in evidence_rows:
        event = getattr(row, "event", None)
        if event is not None and event.model_id:
            return str(event.model_id)
    if insight.session_id:
        row = conn.execute(
            "SELECT model_id FROM usage_events WHERE session_id = ? "
            "ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (insight.session_id,),
        ).fetchone()
        if row is not None and row["model_id"]:
            return str(row["model_id"])
    raise _BridgeError(
        "missing_baseline_model",
        "the insight's session has no recorded model; create the benchmark manually",
    )


def _session_context_strategy(
    conn: sqlite3.Connection, session_id: str | None
) -> ContextStrategy:
    if not session_id:
        return "full_repo"
    row = conn.execute(
        "SELECT metadata_json FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return "full_repo"
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, ValueError):
        return "full_repo"
    value = metadata.get("context_strategy") if isinstance(metadata, dict) else None
    return value if value in ("full_repo", "targeted") else "full_repo"


def _context_files(spec: BenchmarkTaskSpec) -> list[str]:
    for alternative in spec.alternatives:
        if alternative.context_files:
            return list(alternative.context_files)
    return []


def _alternative_model(spec: BenchmarkTaskSpec, baseline_model: str) -> str | None:
    candidates: list[str] = []
    if spec.baseline is not None:
        candidates.append(spec.baseline.model_id)
    for alternative in spec.alternatives:
        value = alternative.changes.get("model_id")
        if isinstance(value, str):
            candidates.append(value)
    for candidate in candidates:
        if candidate and candidate != baseline_model:
            return candidate
    return None


def _build_alternative(
    variable: str, baseline: RunConfig, spec: BenchmarkTaskSpec
) -> AlternativeSpec:
    if variable == "context_strategy":
        strategy: ContextStrategy = (
            "targeted" if baseline.context_strategy == "full_repo" else "full_repo"
        )
        return AlternativeSpec(
            name="targeted-context" if strategy == "targeted" else "full-repo-context",
            changes={"context_strategy": strategy},
            context_files=_context_files(spec) if strategy == "targeted" else [],
        )
    if variable == "model_id":
        model = _alternative_model(spec, baseline.model_id)
        if model is None:
            raise _BridgeError(
                "missing_alternative_value",
                "the task spec names no different model; create the benchmark manually",
            )
        return AlternativeSpec(name="alternative-model", changes={"model_id": model})
    if variable == "retry_policy":
        current = baseline.retry_policy.max_retries
        next_retries = 0 if current > 0 else 1
        return AlternativeSpec(
            name="no-retries" if next_retries == 0 else "one-retry",
            changes={"retry_policy": RetryPolicy(max_retries=next_retries).model_dump()},
        )
    if variable == "temperature":
        current_temperature = baseline.temperature
        next_temperature = 0.0 if current_temperature is None or current_temperature > 0 else 0.7
        return AlternativeSpec(
            name=f"temperature-{next_temperature:g}",
            changes={"temperature": next_temperature},
        )
    raise _BridgeError(
        "unsupported_variable",
        f"variable {variable!r} cannot be mapped to a benchmark config; "
        "create the benchmark manually",
    )


def _recommendation_variable(insight: InsightOut) -> str:
    recommendation = insight.recommendation
    if not isinstance(recommendation, dict):
        raise _BridgeError(
            "missing_recommendation",
            "the insight has no recommendation; investigate it first or "
            "create the benchmark manually",
        )
    variable = recommendation.get("variable_to_change")
    if not isinstance(variable, str) or not variable:
        raise _BridgeError(
            "missing_recommendation",
            "the recommendation has no variable_to_change; create the benchmark manually",
        )
    return variable


def _create_benchmark_from_insight(
    insight_id: str, body: InsightBenchmarkCreate, db: Database, data_dir: Path
) -> BenchmarkOut:
    with db.read() as conn:
        insight = InsightRepository(conn).get(insight_id)
        if insight is None:
            raise _BridgeError("not_found", "insight not found", status=404)
        # Reject an unsupported variable before any other missing input: the plan
        # pins this code for "any other variable".
        variable = _recommendation_variable(insight)
        if variable not in _SUPPORTED_VARIABLES:
            raise _BridgeError(
                "unsupported_variable",
                f"variable {variable!r} cannot be mapped to a benchmark config; "
                "create the benchmark manually",
            )
        if insight.project_id is None:
            raise _BridgeError(
                "insight_not_attributed",
                "the insight has no project; attribute its events before creating a benchmark",
            )
        project = LedgerRepository(conn).get_project(insight.project_id)
        if project is None:
            raise _BridgeError("project_not_found", "the insight's project no longer exists")
        if project.repository_path is None:
            raise _BridgeError(
                "project_has_no_repository",
                "register a repository path on the project before creating a benchmark",
            )
        evidence_rows = resolve_evidence(conn, _evidence_refs(insight))
        model = _observed_model(conn, insight, evidence_rows)
        context_strategy = _session_context_strategy(conn, insight.session_id)

    spec = _load_task_spec(body, [Path(project.repository_path), data_dir])
    task_baseline = spec.baseline or RunConfig(model_id=model, max_steps=12)
    baseline = task_baseline.model_copy(
        update={"model_id": model, "context_strategy": context_strategy}
    )
    alternative = _build_alternative(variable, baseline, spec)
    name = (spec.name or insight.title)[:200]
    create = BenchmarkCreate(
        project_id=project.id,
        repository_path=project.repository_path,
        name=name,
        description=spec.description or insight.summary,
        task_prompt=spec.task_prompt,
        initial_ref=spec.initial_ref,
        acceptance=spec.acceptance,
        timeout_s=spec.timeout_s,
        repeat_count=body.repeat_count or spec.repeat_count or 1,
        baseline=baseline,
        alternatives=[alternative],
    )
    return create_benchmark_record(create, db, insight_id=insight.id)


@router.post("/insights/{insight_id}/benchmark", status_code=201, response_model=None)
def create_benchmark_from_insight(
    insight_id: str,
    body: InsightBenchmarkCreate,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
) -> BenchmarkOut | JSONResponse:
    try:
        return _create_benchmark_from_insight(
            insight_id, body, db, Path(request.app.state.settings.data_dir)
        )
    except _BridgeError as exc:
        return _bridge_error_response(exc)
