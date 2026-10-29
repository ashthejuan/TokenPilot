"""Insight analyze jobs, list/detail with resolved evidence, and status PATCH."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from tokenpilot.db.database import Database, get_db
from tokenpilot.detectors.base import EvidenceRef, Severity
from tokenpilot.detectors.runner import REGISTRY
from tokenpilot.insights.evidence import resolve_evidence
from tokenpilot.insights.jobs import JobRepository, run_analysis_job
from tokenpilot.insights.repository import InsightRepository
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
    InsightDetail,
    InsightFilters,
    InsightOut,
    InsightStatus,
    InsightStatusUpdate,
    JobOut,
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
