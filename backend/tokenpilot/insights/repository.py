"""Insight storage: upsert by dedupe key, list, read, status changes.

Callers own the transaction. A re-run updates the row for the same
`finding.dedupe_key`; it never touches `status` (P3) and never exceeds
`MAX_EVIDENCE` refs (P17).
"""

import json
import sqlite3
import uuid
from decimal import Decimal
from typing import Any, Literal

from tokenpilot.detectors.base import MAX_EVIDENCE, EvidenceRef, Finding
from tokenpilot.schemas.common import Page, Paged, decode_cursor, encode_cursor
from tokenpilot.schemas.insights import InsightFilters, InsightOut, InsightStatus
from tokenpilot.timeutil import utc_now_z

_INSIGHT_COLUMNS = (
    "id, project_id, session_id, task_id, detector_type, rule_id, rule_version, severity, "
    "status, title, summary, confidence, estimated_impact, impact_currency, evidence_json, "
    "evidence_truncated, measurements_json, root_cause_hypothesis, recommendation_json, "
    "investigator_model, created_at, updated_at, last_detected_at"
)


def _evidence_json(refs: list[EvidenceRef]) -> str:
    return json.dumps(
        [{"kind": ref.kind, "id": ref.id, "measurement": ref.measurement} for ref in refs],
        sort_keys=True,
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    # `str()` keeps REAL storage on its shortest repr (`0.22`, not the binary expansion).
    return None if value is None else Decimal(str(value))


def _to_out(row: sqlite3.Row) -> InsightOut:
    values: dict[str, Any] = dict(row)
    values["evidence"] = json.loads(values.pop("evidence_json"))
    values["measurements"] = json.loads(values.pop("measurements_json"))
    recommendation = values.pop("recommendation_json")
    values["recommendation"] = json.loads(recommendation) if recommendation else None
    values["estimated_impact"] = _decimal_or_none(values["estimated_impact"])
    return InsightOut.model_validate(values)


class InsightRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, finding: Finding, now: str) -> Literal["created", "updated"]:
        """Insert the finding, or refresh the row that owns its dedupe key."""
        if (finding.estimated_impact is None) != (finding.impact_currency is None):
            # A money value without its currency (or the reverse) is meaningless.
            raise ValueError("estimated_impact and impact_currency must be set together")
        evidence = finding.evidence[:MAX_EVIDENCE]
        data: dict[str, Any] = {
            "detector_type": finding.rule_id,
            "rule_id": finding.rule_id,
            "rule_version": finding.rule_version,
            "severity": finding.severity,
            "title": finding.title,
            "summary": finding.summary,
            "confidence": finding.confidence,
            "estimated_impact": (
                None if finding.estimated_impact is None else float(finding.estimated_impact)
            ),
            "impact_currency": finding.impact_currency,
            "evidence_json": _evidence_json(evidence),
            "evidence_truncated": len(finding.evidence) - len(evidence),
            "measurements_json": json.dumps(finding.measurements, sort_keys=True),
            "updated_at": now,
            "last_detected_at": now,
        }
        key = finding.dedupe_key
        exists = self._conn.execute(
            "SELECT 1 FROM insights WHERE dedupe_key = ?", (key,)
        ).fetchone()
        if exists is not None:
            # `status` and the Phase 3 investigation fields are deliberately untouched.
            assignments = ", ".join(f"{column} = ?" for column in data)
            self._conn.execute(
                f"UPDATE insights SET {assignments} WHERE dedupe_key = ?",
                [*data.values(), key],
            )
            return "updated"

        row: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "project_id": finding.scope.project_id,
            "session_id": finding.scope.session_id,
            "task_id": finding.scope.task_id,
            "dedupe_key": key,
            "status": "new",
            "created_at": now,
            **data,
        }
        columns = ", ".join(row)
        placeholders = ", ".join("?" for _ in row)
        self._conn.execute(
            f"INSERT INTO insights ({columns}) VALUES ({placeholders})", list(row.values())
        )
        return "created"

    def get(self, insight_id: str) -> InsightOut | None:
        row = self._conn.execute(
            f"SELECT {_INSIGHT_COLUMNS} FROM insights WHERE id = ?", (insight_id,)
        ).fetchone()
        return None if row is None else _to_out(row)

    def list(self, f: InsightFilters, page: Page) -> Paged[InsightOut]:
        clauses: list[str] = []
        params: list[Any] = []
        equals = {
            "status": f.status,
            "severity": f.severity,
            "rule_id": f.rule_id,
            "project_id": f.project_id,
            "session_id": f.session_id,
        }
        for column, value in equals.items():
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if page.cursor is not None:
            cursor_created, cursor_id = decode_cursor(page.cursor)
            clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
            params.extend([cursor_created, cursor_created, cursor_id])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT {_INSIGHT_COLUMNS} FROM insights {where} "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            [*params, page.limit + 1],
        ).fetchall()
        items = [_to_out(row) for row in rows[: page.limit]]
        has_more = len(rows) > page.limit
        next_cursor = encode_cursor(items[-1].created_at, items[-1].id) if has_more else None
        return Paged[InsightOut](items=items, next_cursor=next_cursor)

    def set_status(self, insight_id: str, status: InsightStatus) -> InsightOut | None:
        cursor = self._conn.execute(
            "UPDATE insights SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now_z(), insight_id),
        )
        if cursor.rowcount != 1:
            return None
        return self.get(insight_id)

    def apply_investigation(
        self,
        insight_id: str,
        *,
        root_cause_hypothesis: str,
        recommendation: dict,
        investigator_model: str,
        now: str,
    ) -> InsightOut | None:
        """Write investigator fields onto an existing insight; leave detector columns alone."""
        cursor = self._conn.execute(
            "UPDATE insights SET root_cause_hypothesis = ?, recommendation_json = ?, "
            "investigator_model = ?, updated_at = ? WHERE id = ?",
            (
                root_cause_hypothesis,
                json.dumps(recommendation, sort_keys=True),
                investigator_model,
                now,
                insight_id,
            ),
        )
        if cursor.rowcount != 1:
            return None
        return self.get(insight_id)
