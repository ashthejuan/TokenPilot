"""Insight → benchmark bridge (Task 5.1).

The bridge takes the config observed in an insight's session, adds exactly one
alternative for the recommendation's variable, and links the benchmark back to
the insight. A persisted comparison flips the insight to `tested`.
"""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from tokenpilot.benchmarks.runner import BenchmarkStore
from tokenpilot.config import Settings
from tokenpilot.db.connection import connect
from tokenpilot.detectors.base import EvidenceRef, Finding, Scope
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.schemas.benchmarks import (
    AlternativeSpec,
    RunConfig,
    merge_variant_config,
)
from tokenpilot.timeutil import utc_now_z

AUTH_TOKEN = "test-local-token"
AUTH = {"Authorization": f"Bearer {AUTH_TOKEN}"}
EVENTS = "/api/v1/usage/events"
INSIGHTS = "/api/v1/insights"
BENCHMARKS = "/api/v1/benchmarks"

BUGGY = "def add(a, b):\n    return a - b\n"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "calc.py").write_text(BUGGY)
    tests = path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    _git(path, "init", "--initial-branch=main")
    _git(path, "add", "-A")
    _git(
        path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t.t",
        "commit",
        "-m",
        "init",
    )
    return path


def _register_project(client: TestClient, repo: Path) -> dict[str, Any]:
    response = client.post(
        "/api/v1/projects",
        json={"name": "calc", "repository_path": str(repo)},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _post_event(
    client: TestClient, *, model_id: str = "fake-large", session: str = "s1"
) -> str:
    response = client.post(
        EVENTS,
        json=[
            {
                "provider": "fake",
                "model_id": model_id,
                "started_at": "2026-10-30T10:00:00Z",
                "usage_source": "provider",
                "status": "success",
                "input_tokens": 1000,
                "output_tokens": 100,
                "external_session_id": session,
            }
        ],
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["results"][0]["id"])


def _seed_insight(
    settings: Settings,
    *,
    project_id: str,
    event_id: str | None = None,
    session_id: str | None = None,
    variable: str,
    extra_recommendation: dict[str, Any] | None = None,
) -> str:
    now = utc_now_z()
    conn = connect(settings.db_path)
    try:
        repository = InsightRepository(conn)
        evidence = (
            [EvidenceRef(kind="usage_event", id=event_id)] if event_id is not None else []
        )
        finding = Finding(
            rule_id="retry_amplification",
            rule_version=1,
            anchor=f"session:{session_id or 'none'}",
            severity="medium",
            confidence=0.8,
            title="Retries amplify spend",
            summary="The same request was retried three times.",
            scope=Scope(project_id=project_id, session_id=session_id),
            evidence=evidence,
            measurements={"retries": 2},
            estimated_impact=None,
            impact_currency=None,
        )
        assert repository.upsert(finding, now) == "created"
        row = conn.execute(
            "SELECT id FROM insights WHERE dedupe_key = ?", (finding.dedupe_key,)
        ).fetchone()
        insight_id = str(row["id"])
        recommendation = {
            "action": "Reduce retries for the same request.",
            "variable_to_change": variable,
            "expected_direction": "lower_cost",
            "validation_procedure": "Run the benchmark and compare cost.",
            **(extra_recommendation or {}),
        }
        repository.apply_investigation(
            insight_id,
            root_cause_hypothesis="Rate limits cause repeated full-context retries.",
            recommendation=recommendation,
            investigator_model="test-model",
            now=now,
        )
        conn.commit()
        return insight_id
    finally:
        conn.close()


def _session_id(settings: Settings, external_session_id: str = "s1") -> str:
    conn = connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT id FROM sessions WHERE external_session_id = ?",
            (external_session_id,),
        ).fetchone()
        return str(row["id"])
    finally:
        conn.close()


def _task_spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": "fix-add",
        "description": "Fix add() so the suite passes.",
        "task_prompt": "Fix add() in calc.py so it returns a + b. Do not change tests.",
        "initial_ref": "main",
        "acceptance": {
            "command": ["python", "-m", "pytest", "-q"],
            "required_pass": ["tests/test_calc.py::test_add"],
            "min_success_rate": 1.0,
        },
        "timeout_s": 60,
        "repeat_count": 1,
        "baseline": {
            "model_id": "fake-large",
            "context_strategy": "full_repo",
            "max_steps": 8,
            "retry_policy": {"max_retries": 0},
        },
        "alternatives": [
            {
                "name": "targeted-context",
                "changes": {"context_strategy": "targeted"},
                "context_files": ["calc.py"],
            }
        ],
    }
    spec.update(overrides)
    return spec


def _create_from_insight(
    client: TestClient, insight_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(
        f"{INSIGHTS}/{insight_id}/benchmark", json=body, headers=AUTH
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_context_strategy_recommendation_creates_one_variable_benchmark(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client, model_id="fake-observed")
    session_id = _session_id(settings)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=session_id,
        variable="context_strategy",
    )

    benchmark = _create_from_insight(
        client,
        insight_id,
        {"task_spec": _task_spec(), "repeat_count": 2},
    )

    assert benchmark["insight_id"] == insight_id
    assert benchmark["baseline"]["model_id"] == "fake-observed"
    assert benchmark["baseline"]["context_strategy"] == "full_repo"
    assert len(benchmark["alternatives"]) == 1
    alternative = benchmark["alternatives"][0]
    assert alternative["changes"] == {"context_strategy": "targeted"}
    assert alternative["context_files"] == ["calc.py"]
    assert benchmark["repeat_count"] == 2

    stored = client.get(f"{BENCHMARKS}/{benchmark['id']}", headers=AUTH)
    assert stored.status_code == 200, stored.text
    assert stored.json()["insight_id"] == insight_id


def test_unsupported_variable_returns_422(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable="prompt_template",
    )

    response = client.post(
        f"{INSIGHTS}/{insight_id}/benchmark",
        json={"task_spec": _task_spec()},
        headers=AUTH,
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "unsupported_variable"
    assert "manually" in error["message"]
    assert client.get(BENCHMARKS, headers=AUTH).json() == []


def test_comparison_marks_insight_tested(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable="context_strategy",
    )
    benchmark = _create_from_insight(
        client, insight_id, {"task_spec": _task_spec()}
    )
    assert client.get(f"{INSIGHTS}/{insight_id}", headers=AUTH).json()["insight"][
        "status"
    ] == "new"

    baseline_config = RunConfig.model_validate(benchmark["baseline"])
    alternative_spec = AlternativeSpec.model_validate(benchmark["alternatives"][0])
    alternative_config = merge_variant_config(baseline_config, alternative_spec)
    conn = connect(settings.db_path)
    try:
        store = BenchmarkStore(conn)
        baseline_run = store.create_run(
            benchmark["id"], "baseline", baseline_config.model_id, benchmark["baseline"], 0
        )
        alternative_run = store.create_run(
            benchmark["id"],
            alternative_spec.name,
            str(alternative_config["model_id"]),
            alternative_config,
            0,
        )
        now = utc_now_z()
        store.update_run(
            baseline_run.id,
            run_status="completed",
            outcome="passed",
            total_cost=0.30,
            completed_at=now,
            eligible=1,
        )
        store.update_run(
            alternative_run.id,
            run_status="completed",
            outcome="passed",
            total_cost=0.12,
            completed_at=now,
            eligible=1,
        )
        conn.commit()
    finally:
        conn.close()

    compared = client.post(
        f"{BENCHMARKS}/{benchmark['id']}/compare",
        json={
            "baseline_variant": "baseline",
            "alternative_variant": alternative_spec.name,
        },
        headers=AUTH,
    )
    assert compared.status_code == 201, compared.text

    detail = client.get(f"{INSIGHTS}/{insight_id}", headers=AUTH)
    assert detail.status_code == 200, detail.text
    assert detail.json()["insight"]["status"] == "tested"


def test_model_id_recommendation_uses_a_different_task_spec_model(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client, model_id="fake-large")
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable="model_id",
    )
    spec = _task_spec(
        alternatives=[
            {
                "name": "cheaper-model",
                "changes": {"model_id": "fake-small"},
                "context_files": [],
            }
        ]
    )

    benchmark = _create_from_insight(
        client, insight_id, {"task_spec": spec}
    )

    assert benchmark["baseline"]["model_id"] == "fake-large"
    assert benchmark["alternatives"][0]["changes"] == {"model_id": "fake-small"}


def test_task_spec_path_loads_yaml(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable="context_strategy",
    )
    spec_path = tmp_path / "benchmark_task.yaml"
    spec_path.write_text(yaml.safe_dump(_task_spec()), encoding="utf-8")

    benchmark = _create_from_insight(
        client, insight_id, {"task_spec_path": str(spec_path)}
    )

    assert benchmark["name"] == "fix-add"
    assert benchmark["task_prompt"].startswith("Fix add()")
    assert benchmark["insight_id"] == insight_id


def test_missing_task_spec_returns_422(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable="context_strategy",
    )

    response = client.post(
        f"{INSIGHTS}/{insight_id}/benchmark", json={}, headers=AUTH
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "task_spec_required"
    assert client.get(BENCHMARKS, headers=AUTH).json() == []


def test_session_context_strategy_is_the_baseline(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    session_id = _session_id(settings)
    conn = connect(settings.db_path)
    try:
        conn.execute(
            "UPDATE sessions SET metadata_json = ? WHERE id = ?",
            (json.dumps({"context_strategy": "targeted"}), session_id),
        )
        conn.commit()
    finally:
        conn.close()
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=session_id,
        variable="context_strategy",
    )

    benchmark = _create_from_insight(
        client, insight_id, {"task_spec": _task_spec()}
    )

    assert benchmark["baseline"]["context_strategy"] == "targeted"
    assert benchmark["alternatives"][0]["changes"] == {
        "context_strategy": "full_repo"
    }


@pytest.mark.parametrize(
    ("variable", "baseline_override", "expected_change"),
    [
        (
            "retry_policy",
            {"retry_policy": {"max_retries": 2}},
            {"retry_policy": {"max_retries": 0}},
        ),
        ("temperature", {"temperature": 0.7}, {"temperature": 0.0}),
    ],
)
def test_retry_and_temperature_recommendations_map_to_alternatives(
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
    variable: str,
    baseline_override: dict[str, Any],
    expected_change: dict[str, Any],
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable=variable,
    )
    baseline = {**_task_spec()["baseline"], **baseline_override}

    benchmark = _create_from_insight(
        client, insight_id, {"task_spec": _task_spec(baseline=baseline)}
    )

    assert benchmark["alternatives"][0]["changes"] == expected_change


def test_task_spec_path_outside_allowed_roots_is_rejected(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable="context_strategy",
    )
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    spec_path = outside / "benchmark_task.yaml"
    spec_path.write_text(yaml.safe_dump(_task_spec()), encoding="utf-8")

    response = client.post(
        f"{INSIGHTS}/{insight_id}/benchmark",
        json={"task_spec_path": str(spec_path)},
        headers=AUTH,
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "task_spec_path_outside_allowed_roots"
    assert client.get(BENCHMARKS, headers=AUTH).json() == []


def test_unsupported_variable_wins_over_missing_task_spec(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable="prompt_template",
    )

    response = client.post(
        f"{INSIGHTS}/{insight_id}/benchmark", json={}, headers=AUTH
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "unsupported_variable"


def test_invalid_task_spec_does_not_echo_file_content(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    event_id = _post_event(client)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        event_id=event_id,
        session_id=_session_id(settings),
        variable="context_strategy",
    )
    spec_path = tmp_path / "invalid_task.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "task_prompt": "fix it",
                "acceptance": "hunter2-not-a-config",
            }
        ),
        encoding="utf-8",
    )

    response = client.post(
        f"{INSIGHTS}/{insight_id}/benchmark",
        json={"task_spec_path": str(spec_path)},
        headers=AUTH,
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_task_spec"
    assert "hunter2" not in response.text


def test_missing_model_returns_422(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        variable="context_strategy",
    )

    response = client.post(
        f"{INSIGHTS}/{insight_id}/benchmark",
        json={"task_spec": _task_spec()},
        headers=AUTH,
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "missing_baseline_model"
    assert client.get(BENCHMARKS, headers=AUTH).json() == []


def test_model_falls_back_to_latest_session_event(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    project = _register_project(client, repo)
    _post_event(client, model_id="fake-observed")
    session_id = _session_id(settings)
    insight_id = _seed_insight(
        settings,
        project_id=project["id"],
        session_id=session_id,
        variable="context_strategy",
    )

    benchmark = _create_from_insight(
        client, insight_id, {"task_spec": _task_spec()}
    )

    assert benchmark["baseline"]["model_id"] == "fake-observed"
