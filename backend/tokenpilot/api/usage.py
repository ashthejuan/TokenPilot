"""Usage event ingestion and query."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import Field, TypeAdapter, ValidationError

from tokenpilot.db.database import Database, get_db
from tokenpilot.ledger.ingest import ingest_event
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.common import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    InvalidCursorError,
    Page,
    Paged,
)
from tokenpilot.schemas.usage import (
    EventFilters,
    EventStatus,
    IngestItemResult,
    IngestResponse,
    UsageEvent,
    UsageEventIn,
)
from tokenpilot.timeutil import to_utc_z

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])

MAX_BATCH = 500
_BATCH = TypeAdapter(Annotated[list[UsageEventIn], Field(min_length=1, max_length=MAX_BATCH)])

# The body is parsed by hand so a bad item reports `loc: ["body", <index>, <field>]`
# (a union-typed body would bury the index). This keeps the OpenAPI schema accurate.
_BODY_SCHEMA = UsageEventIn.model_json_schema()
_REQUEST_BODY_DOC: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "oneOf": [
                        _BODY_SCHEMA,
                        {
                            "type": "array",
                            "items": _BODY_SCHEMA,
                            "minItems": 1,
                            "maxItems": MAX_BATCH,
                        },
                    ]
                }
            }
        },
    }
}


def _parse_body(payload: Any) -> list[UsageEventIn]:
    try:
        if isinstance(payload, list):
            return _BATCH.validate_python(payload)
        if isinstance(payload, dict):
            return [UsageEventIn.model_validate(payload)]
    except ValidationError as exc:
        errors = [
            {**error, "loc": ("body", *error["loc"])}
            for error in exc.errors(include_url=False, include_context=False)
        ]
        raise RequestValidationError(errors) from exc
    raise RequestValidationError(
        [{"loc": ("body",), "msg": "body must be an event object or a list of events",
          "type": "invalid_body"}]
    )


@router.post(
    "/events",
    status_code=201,
    response_model=IngestResponse,
    openapi_extra=_REQUEST_BODY_DOC,
)
def post_events(
    payload: Annotated[Any, Body()], db: Annotated[Database, Depends(get_db)]
) -> IngestResponse:
    events = _parse_body(payload)
    # One transaction: any failure (a bad project ref, say) writes nothing.
    with db.write() as conn:
        results = [ingest_event(conn, event, "api") for event in events]
    return IngestResponse(
        results=[IngestItemResult(id=r.event.id, duplicate=not r.created) for r in results]
    )


@router.get("/events")
def list_events(
    db: Annotated[Database, Depends(get_db)],
    project_id: str | None = None,
    session_id: str | None = None,
    model_id: str | None = None,
    provider: str | None = None,
    status: EventStatus | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
) -> Paged[UsageEvent]:
    filters = EventFilters(
        project_id=project_id,
        session_id=session_id,
        model_id=model_id,
        provider=provider,
        status=status,
        started_from=_utc_bound(from_, "from"),
        started_to=_utc_bound(to, "to"),
    )
    try:
        with db.read() as conn:
            return LedgerRepository(conn).query_events(filters, Page(limit=limit, cursor=cursor))
    except InvalidCursorError as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc


@router.get("/events/{event_id}")
def get_event(event_id: str, db: Annotated[Database, Depends(get_db)]) -> UsageEvent:
    with db.read() as conn:
        event = LedgerRepository(conn).get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="usage event not found")
    return event


def _utc_bound(value: datetime | None, name: str) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise RequestValidationError(
            [{"loc": ("query", name), "msg": "timestamp must include a UTC offset",
              "type": "naive_datetime"}]
        )
    return to_utc_z(value)
