"""Session list, detail and manual outcome."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from tokenpilot.db.database import Database, get_db
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.common import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    InvalidCursorError,
    Page,
    Paged,
)
from tokenpilot.schemas.sessions import (
    SessionDetail,
    SessionOutcome,
    SessionSummary,
    SessionUpdate,
)

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

MAX_DETAIL_EVENTS = 500


@router.get("")
def list_sessions(
    db: Annotated[Database, Depends(get_db)],
    project_id: str | None = None,
    outcome: SessionOutcome | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
) -> Paged[SessionSummary]:
    try:
        with db.read() as conn:
            return LedgerRepository(conn).list_sessions(
                project_id=project_id, outcome=outcome, page=Page(limit=limit, cursor=cursor)
            )
    except InvalidCursorError as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc


@router.get("/{session_id}")
def get_session(session_id: str, db: Annotated[Database, Depends(get_db)]) -> SessionDetail:
    with db.read() as conn:
        repository = LedgerRepository(conn)
        session = repository.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return SessionDetail(
            session=session,
            events=repository.session_events(session_id, MAX_DETAIL_EVENTS),
            by_model=repository.session_by_model(session_id),
            outcome=session.outcome,
            outcome_source=session.outcome_source,
        )


@router.patch("/{session_id}")
def update_session(
    session_id: str, body: SessionUpdate, db: Annotated[Database, Depends(get_db)]
) -> SessionSummary:
    with db.write() as conn:
        repository = LedgerRepository(conn)
        if not repository.set_session_outcome(session_id, body.outcome, "manual"):
            raise HTTPException(status_code=404, detail="session not found")
        session = repository.get_session(session_id)
    assert session is not None
    return session
