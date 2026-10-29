"""Investigation and recommendation-feedback storage.

Callers own the transaction. An investigation row is inserted once when a run
finishes; feedback rows are append-only.
"""

import json
import sqlite3
import uuid
from typing import Any

from tokenpilot.schemas.insights import (
    FeedbackOut,
    FeedbackVerdict,
    InvestigationMode,
    InvestigationOut,
    InvestigationStatus,
)
from tokenpilot.security import redact_text
from tokenpilot.timeutil import utc_now_z

_INVESTIGATION_COLUMNS = (
    "id, insight_id, model, prompt_version, mode, request_disclosure_json, status, "
    "result_json, validation_errors_json, created_at"
)

_FEEDBACK_COLUMNS = "id, insight_id, verdict, implemented, note, created_at"


def _json_or_none(value: dict[str, Any] | list[str] | None) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True)


def _loads_or_none(raw: str | None) -> Any:
    return None if raw is None else json.loads(raw)


def _investigation_out(row: sqlite3.Row) -> InvestigationOut:
    values: dict[str, Any] = dict(row)
    values["request_disclosure"] = _loads_or_none(values.pop("request_disclosure_json"))
    values["result"] = _loads_or_none(values.pop("result_json"))
    values["validation_errors"] = _loads_or_none(values.pop("validation_errors_json"))
    return InvestigationOut.model_validate(values)


def _feedback_out(row: sqlite3.Row) -> FeedbackOut:
    values: dict[str, Any] = dict(row)
    implemented = values["implemented"]
    values["implemented"] = None if implemented is None else bool(implemented)
    return FeedbackOut.model_validate(values)


class InvestigationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(
        self,
        *,
        id: str,
        insight_id: str,
        model: str | None,
        prompt_version: str | None,
        mode: InvestigationMode,
        request_disclosure: dict[str, Any] | None,
        status: InvestigationStatus,
        result: dict[str, Any] | None,
        validation_errors: list[str] | None,
        created_at: str,
    ) -> InvestigationOut:
        """Insert one finished investigation run."""
        self._conn.execute(
            "INSERT INTO investigations ("
            "id, insight_id, model, prompt_version, mode, request_disclosure_json, "
            "status, result_json, validation_errors_json, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id,
                insight_id,
                model,
                prompt_version,
                mode,
                _json_or_none(request_disclosure),
                status,
                _json_or_none(result),
                _json_or_none(validation_errors),
                created_at,
            ),
        )
        row = self._conn.execute(
            f"SELECT {_INVESTIGATION_COLUMNS} FROM investigations WHERE id = ?", (id,)
        ).fetchone()
        assert row is not None
        return _investigation_out(row)

    def list_for_insight(self, insight_id: str) -> list[InvestigationOut]:
        rows = self._conn.execute(
            f"SELECT {_INVESTIGATION_COLUMNS} FROM investigations "
            "WHERE insight_id = ? ORDER BY created_at DESC, id DESC",
            (insight_id,),
        ).fetchall()
        return [_investigation_out(row) for row in rows]


class FeedbackRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(
        self,
        *,
        insight_id: str,
        verdict: FeedbackVerdict,
        implemented: bool | None,
        note: str | None,
    ) -> FeedbackOut:
        """Append one feedback row; redact free-text notes before storage."""
        feedback_id = uuid.uuid4().hex
        created_at = utc_now_z()
        stored_note = None if note is None else redact_text(note)
        implemented_int = None if implemented is None else int(implemented)
        self._conn.execute(
            "INSERT INTO recommendation_feedback ("
            "id, insight_id, verdict, implemented, note, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (feedback_id, insight_id, verdict, implemented_int, stored_note, created_at),
        )
        row = self._conn.execute(
            f"SELECT {_FEEDBACK_COLUMNS} FROM recommendation_feedback WHERE id = ?",
            (feedback_id,),
        ).fetchone()
        assert row is not None
        return _feedback_out(row)
