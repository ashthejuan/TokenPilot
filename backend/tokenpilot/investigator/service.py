"""Investigation worker: bundle → Meta → validate (one retry) → persist."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from tokenpilot.config import Settings
from tokenpilot.db.connection import connect
from tokenpilot.db.database import Database
from tokenpilot.insights.jobs import JobRepository
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.investigator.client import MetaClient, UsageFields
from tokenpilot.investigator.evidence import (
    EvidenceBundle,
    build_bundle,
    disclosure_lines,
    is_contributor_model,
)
from tokenpilot.investigator.repository import InvestigationRepository
from tokenpilot.investigator.schema import (
    PROMPT_VERSION,
    InvestigationOutput,
    ValidationIssue,
    investigation_json_schema,
    load_system_prompt,
)
from tokenpilot.investigator.usage import record_investigator_usage
from tokenpilot.investigator.validate import validate_output
from tokenpilot.schemas.insights import InvestigationMode, InvestigationOut
from tokenpilot.security import redact_text
from tokenpilot.timeutil import utc_now_z

logger = logging.getLogger("tokenpilot.investigator")

__all__ = ["investigate", "run_investigation_job"]


def investigate(
    db: Database,
    db_path: Path,
    settings: Settings,
    insight_id: str,
    mode: InvestigationMode,
    *,
    http_client: httpx.Client | None = None,
    transport: httpx.BaseTransport | None = None,
) -> InvestigationOut:
    """Run one investigation: always persist a row; never fabricate on HTTP failure."""
    investigation_id = uuid.uuid4().hex
    model = settings.investigator_model
    contains_content = mode == "with_excerpts"
    contributor_training = is_contributor_model(model)
    request_disclosure: dict[str, Any] = {
        "destination": settings.upstream_base_url,
        "model": model,
        "contains_content": contains_content,
        "contributor_training": contributor_training,
        "disclosure_lines": disclosure_lines(
            destination=settings.upstream_base_url,
            model=model,
            contains_content=contains_content,
            contributor_training=contributor_training,
        ),
    }

    owns_client = False
    client_http = http_client
    if client_http is None and transport is not None:
        client_http = httpx.Client(transport=transport)
        owns_client = True

    try:
        return _investigate_body(
            db,
            db_path,
            settings,
            insight_id,
            mode,
            investigation_id=investigation_id,
            model=model,
            request_disclosure=request_disclosure,
            http_client=client_http,
        )
    finally:
        if owns_client and client_http is not None:
            client_http.close()


def _investigate_body(
    db: Database,
    db_path: Path,
    settings: Settings,
    insight_id: str,
    mode: InvestigationMode,
    *,
    investigation_id: str,
    model: str,
    request_disclosure: dict[str, Any],
    http_client: httpx.Client | None,
) -> InvestigationOut:
    read_conn = None
    try:
        read_conn = connect(db_path)
        bundle = build_bundle(
            read_conn,
            insight_id,
            mode,
            settings=settings,
            investigation_id=investigation_id,
        )
    except Exception as exc:
        return _persist_failed(
            db,
            investigation_id=investigation_id,
            insight_id=insight_id,
            model=model,
            mode=mode,
            request_disclosure=request_disclosure,
            error=exc,
        )
    finally:
        if read_conn is not None:
            read_conn.close()

    system = load_system_prompt()
    user_message = _user_message(bundle)
    schema = investigation_json_schema()
    client = MetaClient(settings, http_client=http_client)

    try:
        parsed, usage = client.complete_structured(
            system=system,
            user=user_message,
            schema=schema,
            model=model,
        )
        _safe_record_usage(db, settings, investigation_id, model, usage)

        out, issues = _parse_and_validate(parsed, bundle)
        if issues:
            retry_user = _append_validation_issues(user_message, issues)
            parsed, usage = client.complete_structured(
                system=system,
                user=retry_user,
                schema=schema,
                model=model,
            )
            _safe_record_usage(db, settings, investigation_id, model, usage)
            out, issues = _parse_and_validate(parsed, bundle)
    except Exception as exc:
        return _persist_failed(
            db,
            investigation_id=investigation_id,
            insight_id=insight_id,
            model=model,
            mode=mode,
            request_disclosure=request_disclosure,
            error=exc,
        )

    if out is None or issues or out.verdict == "insufficient_evidence":
        error_msgs = [_issue_text(i) for i in issues]
        if out is not None and out.verdict == "insufficient_evidence" and not issues:
            error_msgs = ["verdict: insufficient_evidence"]
        result = out.model_dump() if out is not None else None
        with db.write() as conn:
            return InvestigationRepository(conn).save(
                id=investigation_id,
                insight_id=insight_id,
                model=model,
                prompt_version=PROMPT_VERSION,
                mode=mode,
                request_disclosure=request_disclosure,
                status="insufficient_evidence",
                result=result,
                validation_errors=error_msgs or ["invalid investigation output"],
                created_at=utc_now_z(),
            )

    result = out.model_dump()
    now = utc_now_z()
    with db.write() as conn:
        saved = InvestigationRepository(conn).save(
            id=investigation_id,
            insight_id=insight_id,
            model=model,
            prompt_version=PROMPT_VERSION,
            mode=mode,
            request_disclosure=request_disclosure,
            status="completed",
            result=result,
            validation_errors=None,
            created_at=now,
        )
        InsightRepository(conn).apply_investigation(
            insight_id,
            root_cause_hypothesis=out.root_cause_hypothesis,
            recommendation=out.recommendation.model_dump(),
            investigator_model=model,
            now=now,
        )
        return saved


def run_investigation_job(
    db: Database,
    db_path: Path,
    settings: Settings,
    job_id: str,
    *,
    http_client: httpx.Client | None = None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Start the job, run ``investigate``, then succeed with ``investigation_id`` or fail."""
    with db.write() as conn:
        started = JobRepository(conn).start(job_id)
        if started is None:
            return
        params = started.params
    insight_id = str(params["insight_id"])
    raw_mode = params.get("mode", "metadata_only")
    mode: InvestigationMode = (
        raw_mode if raw_mode in ("metadata_only", "with_excerpts") else "metadata_only"
    )

    try:
        result = investigate(
            db,
            db_path,
            settings,
            insight_id,
            mode,
            http_client=http_client,
            transport=transport,
        )
        with db.write() as conn:
            JobRepository(conn).succeed(job_id, {"investigation_id": result.id})
    except Exception as exc:
        with db.write() as conn:
            JobRepository(conn).fail(job_id, f"{type(exc).__name__}: {exc}")


def _user_message(bundle: EvidenceBundle) -> str:
    return json.dumps(bundle.to_dict(), sort_keys=True, default=str)


def _append_validation_issues(user_message: str, issues: list[ValidationIssue]) -> str:
    lines = "\n".join(f"- {_issue_text(issue)}" for issue in issues)
    return (
        f"{user_message}\n\n"
        "Your previous answer failed validation. Fix these issues and reply again "
        "using only evidence from the bundle:\n"
        f"{lines}"
    )


def _issue_text(issue: ValidationIssue) -> str:
    if issue.path:
        return f"{issue.code}: {issue.message} (at {issue.path})"
    return f"{issue.code}: {issue.message}"


def _parse_and_validate(
    parsed: dict[str, Any], bundle: EvidenceBundle
) -> tuple[InvestigationOutput | None, list[ValidationIssue]]:
    try:
        out = InvestigationOutput.model_validate(parsed)
    except ValidationError as exc:
        issues = [
            ValidationIssue(
                code="schema_invalid",
                message=err.get("msg", "invalid"),
                path=".".join(str(p) for p in err.get("loc", ())),
            )
            for err in exc.errors()
        ]
        return None, issues
    return out, validate_output(out, bundle)


def _safe_record_usage(
    db: Database,
    settings: Settings,
    investigation_id: str,
    model: str,
    usage: UsageFields,
) -> None:
    try:
        with db.write() as conn:
            record_investigator_usage(
                conn,
                investigation_id=investigation_id,
                model=model,
                usage=usage,
                provider=settings.upstream_provider,
            )
    except Exception as exc:
        logger.warning(
            "investigator usage write failed for %s: %s",
            investigation_id,
            redact_text(f"{type(exc).__name__}: {exc}"),
        )


def _persist_failed(
    db: Database,
    *,
    investigation_id: str,
    insight_id: str,
    model: str,
    mode: InvestigationMode,
    request_disclosure: dict[str, Any],
    error: BaseException,
) -> InvestigationOut:
    message = redact_text(f"{type(error).__name__}: {error}")
    with db.write() as conn:
        return InvestigationRepository(conn).save(
            id=investigation_id,
            insight_id=insight_id,
            model=model,
            prompt_version=PROMPT_VERSION,
            mode=mode,
            request_disclosure=request_disclosure,
            status="failed",
            result=None,
            validation_errors=[message],
            created_at=utc_now_z(),
        )
