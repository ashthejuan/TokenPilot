"""Project and savings report endpoints (Task 5.2)."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from tokenpilot.db.database import Database, get_db
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.reports.project_report import (
    build_project_report,
    build_savings_report,
    render_markdown,
)
from tokenpilot.schemas.reports import ProjectReport, SavingsReport
from tokenpilot.timeutil import to_utc_z

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

ReportFormat = Literal["json", "markdown"]


def _utc_bound(value: datetime | None, name: str) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise RequestValidationError(
            [
                {
                    "loc": ("query", name),
                    "msg": "timestamp must include a UTC offset",
                    "type": "naive_datetime",
                }
            ]
        )
    return to_utc_z(value)


@router.get("/project/{project_id}", response_model=None)
def get_project_report(
    project_id: str,
    db: Annotated[Database, Depends(get_db)],
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    format: Annotated[ReportFormat, Query()] = "json",
) -> ProjectReport | Response:
    started_from = _utc_bound(from_, "from")
    started_to = _utc_bound(to, "to")
    with db.read() as conn:
        project = LedgerRepository(conn).get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        report = build_project_report(
            conn, project, started_from=started_from, started_to=started_to
        )
    if format == "markdown":
        return Response(
            content=render_markdown(report),
            media_type="text/markdown; charset=utf-8",
        )
    return report


@router.get("/savings")
def get_savings_report(
    db: Annotated[Database, Depends(get_db)],
    project_id: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> SavingsReport:
    started_from = _utc_bound(from_, "from")
    started_to = _utc_bound(to, "to")
    with db.read() as conn:
        if project_id is not None:
            project = LedgerRepository(conn).get_project(project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="project not found")
        return build_savings_report(
            conn,
            project_id=project_id,
            started_from=started_from,
            started_to=started_to,
        )
