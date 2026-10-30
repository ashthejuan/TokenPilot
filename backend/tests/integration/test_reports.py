"""Project and savings reports (Task 5.2, FR-11 / FR-12)."""

import json
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from tokenpilot.benchmarks.runner import BenchmarkStore
from tokenpilot.config import Settings
from tokenpilot.db.connection import connect
from tokenpilot.detectors.base import Finding, Scope
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.schemas.benchmarks import AcceptanceConfig, AlternativeSpec, RunConfig

EVENTS = "/api/v1/usage/events"
PROJECTS = "/api/v1/projects"
REPORT_PROJECT = "/api/v1/reports/project"
REPORT_SAVINGS = "/api/v1/reports/savings"
# fake-small input is "0.25" per 1M tokens: 4M tokens = $1.
ONE_DOLLAR = 4_000_000

BASE_CONFIG = {
    "model_id": "fake-large",
    "context_strategy": "full_repo",
    "max_steps": 12,
    "retry_policy": {"max_retries": 2},
    "temperature": None,
    "prompt_template": "fix_v1",
    "context_files": [],
}
ALT_CONFIG = {**BASE_CONFIG, "context_strategy": "targeted"}


def _create_project(client: TestClient, headers: dict[str, str], name: str = "demo") -> str:
    response = client.post(PROJECTS, json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _post_events(
    client: TestClient, headers: dict[str, str], *events: dict[str, Any]
) -> list[str]:
    response = client.post(EVENTS, json=list(events), headers=headers)
    assert response.status_code == 201, response.text
    return [item["id"] for item in response.json()["results"]]


def _make_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "provider": "fake",
        "model_id": "fake-small",
        "started_at": "2026-10-29T10:00:00Z",
        "usage_source": "provider",
        "status": "success",
        "input_tokens": ONE_DOLLAR,
        "output_tokens": 0,
    }
    event.update(overrides)
    return event


def _seed_insight(
    settings: Settings,
    *,
    project_id: str,
    estimated_impact: Decimal | None,
    rule_id: str = "retry_amplification",
    status: str = "new",
    recommendation: dict[str, Any] | None = None,
    created_at: str = "2026-10-29T12:00:00.000Z",
) -> str:
    conn = connect(settings.db_path)
    try:
        repository = InsightRepository(conn)
        finding = Finding(
            rule_id=rule_id,  # type: ignore[arg-type]
            rule_version=1,
            anchor=f"project:{project_id}:{rule_id}:{created_at}",
            severity="medium",
            confidence=0.8,
            title=f"{rule_id} finding",
            summary="Detected waste.",
            scope=Scope(project_id=project_id),
            evidence=[],
            measurements={},
            estimated_impact=estimated_impact,
            impact_currency=None if estimated_impact is None else "USD",
        )
        assert repository.upsert(finding, created_at) == "created"
        row = conn.execute(
            "SELECT id FROM insights WHERE dedupe_key = ?", (finding.dedupe_key,)
        ).fetchone()
        insight_id = str(row["id"])
        if status != "new":
            conn.execute(
                "UPDATE insights SET status = ?, updated_at = ? WHERE id = ?",
                (status, created_at, insight_id),
            )
        if recommendation is not None:
            repository.apply_investigation(
                insight_id,
                root_cause_hypothesis="Hypothesis",
                recommendation=recommendation,
                investigator_model="test-model",
                now=created_at,
            )
        conn.commit()
        return insight_id
    finally:
        conn.close()


def _seed_benchmark_with_comparison(
    settings: Settings,
    *,
    project_id: str,
    comparison_id: str,
    status: str,
    cost_delta: float,
    created_at: str = "2026-10-29T13:00:00.000Z",
    benchmark_name: str = "discount bug",
) -> str:
    conn = connect(settings.db_path)
    try:
        task_id = f"task-{comparison_id}"
        conn.execute(
            "INSERT INTO tasks (id, project_id, title, created_at) VALUES (?, ?, ?, ?)",
            (task_id, project_id, "discount bug", created_at),
        )
        store = BenchmarkStore(conn)
        benchmark = store.create_benchmark(
            benchmark_id=f"bench-{comparison_id}",
            project_id=project_id,
            task_id=task_id,
            name=benchmark_name,
            description=None,
            initial_git_sha="abc123",
            acceptance=AcceptanceConfig(
                command=["python", "-m", "pytest", "-q"],
                required_pass=["tests/test_discounts.py::test_x"],
                min_success_rate=1.0,
            ),
            baseline=RunConfig.model_validate(BASE_CONFIG),
            alternatives=[
                AlternativeSpec(
                    name="targeted-context",
                    changes={"context_strategy": "targeted"},
                    context_files=["invoicing/discounts.py"],
                )
            ],
            task_prompt="fix the discount bug",
            initial_ref="main",
            repeat_count=1,
            timeout_s=300,
        )
        base_run = store.create_run(
            benchmark.id, "baseline", "fake-large", BASE_CONFIG, 0
        )
        alt_run = store.create_run(
            benchmark.id, "targeted-context", "fake-large", ALT_CONFIG, 0
        )
        conn.execute(
            "INSERT INTO benchmark_comparisons (id, benchmark_id, baseline_run_id, "
            "alternative_run_id, cost_delta, cost_delta_pct, correctness_preserved, "
            "comparison_status, methodology_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                comparison_id,
                benchmark.id,
                base_run.id,
                alt_run.id,
                cost_delta,
                60.0,
                1 if status == "verified" else 0,
                status,
                json.dumps(
                    {"low_sample": True, "reasons": [f"{status} by test seed"]},
                    sort_keys=True,
                ),
                created_at,
            ),
        )
        conn.commit()
        return benchmark.id
    finally:
        conn.close()


def test_report_separates_savings_kinds(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    project_id = _create_project(client, auth_headers)
    _seed_insight(
        settings,
        project_id=project_id,
        estimated_impact=Decimal("0.50"),
        recommendation={
            "action": "Cut retries",
            "variable_to_change": "retry_policy",
            "expected_direction": "lower_cost",
            "validation_procedure": "Benchmark the change.",
        },
    )
    _seed_benchmark_with_comparison(
        settings,
        project_id=project_id,
        comparison_id="cmp-measured",
        status="measured",
        cost_delta=0.18,
        benchmark_name="measured-bench",
    )
    _seed_benchmark_with_comparison(
        settings,
        project_id=project_id,
        comparison_id="cmp-verified",
        status="verified",
        cost_delta=0.22,
        benchmark_name="verified-bench",
    )
    # Incomparable comparisons map to savings_kind "potential" but must NOT
    # enter the insight-driven potential money bucket.
    _seed_benchmark_with_comparison(
        settings,
        project_id=project_id,
        comparison_id="cmp-incomparable",
        status="incomparable",
        cost_delta=0.99,
        benchmark_name="incomparable-bench",
    )

    report = client.get(f"{REPORT_PROJECT}/{project_id}", headers=auth_headers)
    assert report.status_code == 200, report.text
    body = report.json()
    savings = body["savings"]
    assert savings["potential"] == 0.5
    assert savings["benchmark"] == 0.18
    assert savings["verified"] == 0.22
    assert savings["realized"] is None
    # Kinds stay separate — never summed into a single total.
    assert "total" not in savings
    assert savings["potential"] + savings["benchmark"] + savings["verified"] != savings.get(
        "total", object()
    )

    bench_names = {row["name"] for row in body["benchmarks"]}
    assert "incomparable-bench" in bench_names
    assert "measured-bench" in bench_names
    assert "verified-bench" in bench_names

    savings_resp = client.get(
        REPORT_SAVINGS, params={"project_id": project_id}, headers=auth_headers
    )
    assert savings_resp.status_code == 200, savings_resp.text
    kinds = savings_resp.json()
    assert kinds["potential"] == 0.5
    assert kinds["benchmark"] == 0.18
    assert kinds["verified"] == 0.22
    assert kinds["realized"] is None
    assert "total" not in kinds


def test_report_includes_coverage_and_limitations(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project_id = _create_project(client, auth_headers, "coverage")
    _post_events(
        client,
        auth_headers,
        _make_event(
            source_event_id="priced",
            project_id=project_id,
            started_at="2026-10-29T10:00:00Z",
        ),
        _make_event(
            source_event_id="unknown",
            project_id=project_id,
            started_at="2026-10-29T11:00:00Z",
            input_tokens=None,
            usage_source="unavailable",
        ),
    )

    response = client.get(
        f"{REPORT_PROJECT}/{project_id}",
        params={"from": "2026-10-29T00:00:00Z", "to": "2026-10-30T00:00:00Z"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["period"]["from"] == "2026-10-29T00:00:00.000Z"
    assert body["period"]["to"] == "2026-10-30T00:00:00.000Z"
    assert body["cost_basis"] == "simulated"
    assert body["currency"] == "USD"
    assert body["spend_total"] == 1.0
    assert body["unknown_cost_events"] == 1
    assert body["coverage"]["priced_pct"] == 50.0
    assert body["coverage"]["attributed_pct"] == 100.0
    assert "Realized savings are not measured in this version" in body["limitations"]
    assert any("no pricing" in line.lower() for line in body["limitations"])
    assert body["savings"]["realized"] is None


def test_failed_cheaper_alt_not_in_verified_savings(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    project_id = _create_project(client, auth_headers, "failed-alt")
    # Cheaper alternative that failed correctness → comparison_status=measured.
    # Cost delta is positive but must land in benchmark, never verified (FR-11).
    _seed_benchmark_with_comparison(
        settings,
        project_id=project_id,
        comparison_id="cmp-failed-cheaper",
        status="measured",
        cost_delta=0.19,
        benchmark_name="failed-cheaper",
    )

    response = client.get(f"{REPORT_PROJECT}/{project_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    savings = response.json()["savings"]
    assert savings["verified"] in (0, 0.0, None) or Decimal(str(savings["verified"])) == 0
    assert savings["benchmark"] == 0.19
    assert savings["realized"] is None

    savings_resp = client.get(
        REPORT_SAVINGS, params={"project_id": project_id}, headers=auth_headers
    )
    assert savings_resp.status_code == 200, savings_resp.text
    kinds = savings_resp.json()
    assert kinds["verified"] in (0, 0.0, None) or Decimal(str(kinds["verified"])) == 0
    assert kinds["benchmark"] == 0.19


def test_markdown_header_has_period_basis_coverage(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project_id = _create_project(client, auth_headers, "markdown")
    _post_events(
        client,
        auth_headers,
        _make_event(source_event_id="a", project_id=project_id),
    )

    response = client.get(
        f"{REPORT_PROJECT}/{project_id}",
        params={
            "from": "2026-10-29T00:00:00Z",
            "to": "2026-10-30T00:00:00Z",
            "format": "markdown",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert "text/markdown" in response.headers["content-type"]
    text = response.text
    header = "\n".join(text.splitlines()[:12])
    assert "2026-10-29" in header
    assert "2026-10-30" in header
    assert "cost basis" in header.lower() or "Cost basis" in header
    assert "simulated" in header.lower() or "estimated" in header.lower()
    assert "coverage" in header.lower()
    assert "estimated" in header.lower() or "actual" in header.lower()


def test_tested_insight_excluded_from_potential(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    """FR-11: potential savings count untested recommendations only."""
    project_id = _create_project(client, auth_headers, "tested-potential")
    _seed_insight(
        settings,
        project_id=project_id,
        estimated_impact=Decimal("0.40"),
        status="new",
        recommendation={
            "action": "Cut retries",
            "variable_to_change": "retry_policy",
            "expected_direction": "lower_cost",
            "validation_procedure": "Benchmark the change.",
        },
    )
    _seed_insight(
        settings,
        project_id=project_id,
        estimated_impact=Decimal("0.75"),
        status="tested",
        rule_id="context_bloat",
        recommendation={
            "action": "Narrow context",
            "variable_to_change": "context_strategy",
            "expected_direction": "lower_cost",
            "validation_procedure": "Already benchmarked.",
        },
    )

    report = client.get(f"{REPORT_PROJECT}/{project_id}", headers=auth_headers)
    assert report.status_code == 200, report.text
    assert report.json()["savings"]["potential"] == 0.4

    savings_resp = client.get(
        REPORT_SAVINGS, params={"project_id": project_id}, headers=auth_headers
    )
    assert savings_resp.status_code == 200, savings_resp.text
    assert savings_resp.json()["potential"] == 0.4


def test_markdown_includes_methodology_and_body_sections(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    project_id = _create_project(client, auth_headers, "md-method")
    _seed_insight(
        settings,
        project_id=project_id,
        estimated_impact=Decimal("0.12"),
        recommendation={
            "action": "Cut retries",
            "variable_to_change": "retry_policy",
            "expected_direction": "lower_cost",
            "validation_procedure": "Benchmark the change.",
        },
    )
    _seed_benchmark_with_comparison(
        settings,
        project_id=project_id,
        comparison_id="cmp-md-method",
        status="verified",
        cost_delta=0.22,
        benchmark_name="method-bench",
    )

    response = client.get(
        f"{REPORT_PROJECT}/{project_id}",
        params={"format": "markdown"},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    text = response.text
    assert "## Methodology" in text or "### Methodology" in text
    assert "low_sample" in text
    assert "method-bench" in text
    assert "## Top sessions" in text or "## Top Sessions" in text
    assert "## Waste by rule" in text or "## Waste by Rule" in text
    assert "## Top recommendations" in text or "## Recommendations" in text
    assert "## Benchmarks" in text
    assert "## Unattributed" in text
