"""No secret may leak anywhere across the full offline demo loop (PRD §13).

Unlike ``test_no_secrets_in_ledger`` (gateway-scoped), these drive seed →
analyze → investigate → benchmark → compare → report with a known upstream key
and local token, then grep every place the app persists or emits data: the
SQLite file (and WAL/SHM), the patch files, captured logs, every API response
body, and the Markdown report.

``test_no_secret_leaks`` is the primary check: it runs the real
``demo/scripts/run_demo.sh --offline`` process tree (fake upstream, API, seed,
analyze, web) as subprocesses under the secret env vars, then keeps driving the
live demo API over HTTP. ``test_no_secret_leaks_in_process`` is a fast companion
using an in-process transport.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import signal
import socket
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from tests.fakes.fake_upstream import (
    DEFAULT_OK_USAGE,
    FULL_REPO_USAGE,
    _chat_response,
    _investigation_response,
    _is_tool_agent_request,
    _looks_full_repo,
    _parse_payload,
    canned_investigation_for_request,
    demo_agent_response,
)
from tokenpilot.config import Settings
from tokenpilot.main import create_app

API_KEY = "sk-test-SECRET123456789"
LOCAL_TOKEN = "tp-local-SECRET"
SECRETS = (API_KEY, LOCAL_TOKEN)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAT = "/gateway/v1/chat/completions"
PAD = (
    "Repository files (full_repo context):\n"
    + ("=== invoicing/discounts.py ===\n" + ("# pad line for repeated context\n" * 80))
    + ("=== invoicing/totals.py ===\n" + ("# more fixture context\n" * 80))
)


class DemoUpstream:
    """Offline demo upstream as an in-process transport; records auth it saw."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.fail_next = 0
        self.authorizations: list[str | None] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.authorizations.append(request.headers.get("authorization"))
        source_id = f"chatcmpl-demo-{next(self._ids):05d}"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": []})
        raw = request.content
        canned = canned_investigation_for_request(raw)
        if canned is not None:
            return _investigation_response(
                "fake-large", source_id, canned, dict(DEFAULT_OK_USAGE)
            )
        payload = _parse_payload(raw)
        if payload is not None and _is_tool_agent_request(payload):
            return httpx.Response(
                200, json=demo_agent_response(payload, source_id, scenario="success")
            )
        if self.fail_next > 0:
            self.fail_next -= 1
            return httpx.Response(
                429, json={"error": {"code": "rate_limited", "message": "slow down"}}
            )
        usage = (
            dict(FULL_REPO_USAGE)
            if payload is not None and _looks_full_repo(payload)
            else dict(DEFAULT_OK_USAGE)
        )
        return _chat_response("fake-large", source_id, usage)


class RecordingClient(TestClient):
    """Keeps the body of every response so the test can grep them all."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.bodies: list[str] = []

    def request(self, *args: Any, **kwargs: Any) -> httpx.Response:  # type: ignore[override]
        response = super().request(*args, **kwargs)
        self.bodies.append(response.text)
        return response


def _wait(predicate: Any, *, timeout: float, what: str) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def _contains_secret(blob: bytes) -> str | None:
    for secret in SECRETS:
        if secret.encode() in blob:
            return secret
    return None


def test_no_secret_leaks_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", API_KEY)
    monkeypatch.setenv("TOKENPILOT_LOCAL_TOKEN", LOCAL_TOKEN)
    monkeypatch.setenv("TOKENPILOT_FAKE_DEMO_MODE", "1")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    settings = Settings(
        _env_file=None,
        db_path=data_dir / "tokenpilot.sqlite3",
        data_dir=data_dir,
        upstream_provider="fake",
    )
    upstream = DemoUpstream()
    app = create_app(settings, upstream_transport=upstream.transport())
    auth = {"Authorization": f"Bearer {LOCAL_TOKEN}"}

    fixture = tmp_path / "fixture-repo"
    subprocess.run(
        ["bash", str(REPO_ROOT / "demo/scripts/init_fixture_repo.sh"), str(fixture)],
        check=True,
        capture_output=True,
    )
    spec = yaml.safe_load((REPO_ROOT / "demo/benchmark_task.offline.yaml").read_text())

    markdown = ""
    with caplog.at_level(logging.DEBUG), RecordingClient(app) as client:
        project = client.post(
            "/api/v1/projects",
            json={
                "name": "invoicing-demo",
                "slug": "invoicing-demo",
                "repository_path": str(fixture),
            },
            headers=auth,
        )
        assert project.status_code == 201, project.text
        project_id = project.json()["id"]

        def chat(**extra: str) -> httpx.Response:
            return client.post(
                CHAT,
                json={
                    "model": "fake-large",
                    "messages": [{"role": "user", "content": f"Debug the bug.\n{PAD}"}],
                },
                headers={
                    **auth,
                    "X-TokenPilot-Project": "invoicing-demo",
                    "X-TokenPilot-Session": "demo-debug-1",
                    **extra,
                },
            )

        assert chat().status_code == 200
        for _ in range(2):
            upstream.fail_next = 1
            first = chat()
            assert first.status_code == 429
            retry = chat(**{"X-TokenPilot-Retry-Of": first.headers["X-TokenPilot-Event-Id"]})
            assert retry.status_code == 200
        assert chat().status_code == 200

        # Wrong-token probes must not echo the presented credential.
        denied = client.get(
            "/api/v1/usage/summary", headers={"Authorization": f"Bearer {LOCAL_TOKEN}-wrong"}
        )
        assert denied.status_code == 401

        analyzed = client.post("/api/v1/insights/analyze", json={}, headers=auth)
        assert analyzed.status_code == 202, analyzed.text

        def job_done(job_id: str) -> dict[str, Any] | None:
            job = client.get(f"/api/v1/jobs/{job_id}", headers=auth).json()
            return job if job["status"] in ("succeeded", "failed") else None

        job = _wait(lambda: job_done(analyzed.json()["job_id"]), timeout=60, what="analyze")
        assert job["status"] == "succeeded", job
        insights = client.get("/api/v1/insights?limit=50", headers=auth).json()["items"]
        assert insights, "demo seed produced no insights"
        insight_id = next(
            (i["id"] for i in insights if i["rule_id"] == "retry_amplification"),
            insights[0]["id"],
        )

        investigated = client.post(
            f"/api/v1/insights/{insight_id}/investigate",
            json={"mode": "metadata_only"},
            headers=auth,
        )
        assert investigated.status_code == 202, investigated.text
        job = _wait(
            lambda: job_done(investigated.json()["job_id"]), timeout=60, what="investigate"
        )
        assert job["status"] == "succeeded", job

        created = client.post(
            f"/api/v1/insights/{insight_id}/benchmark",
            json={"task_spec": spec, "repeat_count": 1},
            headers=auth,
        )
        assert created.status_code == 201, created.text
        benchmark = created.json()
        alt = benchmark["alternatives"][0]["name"]
        started = client.post(
            f"/api/v1/benchmarks/{benchmark['id']}/runs",
            json={"variants": ["baseline", alt], "repeat_count": 1},
            headers=auth,
        )
        assert started.status_code == 202, started.text

        def runs_done() -> list[dict[str, Any]] | None:
            detail = client.get(f"/api/v1/benchmarks/{benchmark['id']}", headers=auth).json()
            runs = detail["runs"]
            done = runs and all(r["run_status"] in ("completed", "failed") for r in runs)
            return runs if done else None

        runs = _wait(runs_done, timeout=240, what="benchmark runs")
        compare = client.post(
            f"/api/v1/benchmarks/{benchmark['id']}/compare",
            json={"baseline_variant": "baseline", "alternative_variant": alt},
            headers=auth,
        )
        assert compare.status_code == 201, compare.text
        for run in runs:
            client.get(f"/api/v1/benchmark-runs/{run['id']}", headers=auth)
            client.get(f"/api/v1/benchmark-runs/{run['id']}/patch", headers=auth)

        for path in (
            "/api/v1/health",
            "/api/v1/usage/summary",
            "/api/v1/usage/events?limit=100",
            "/api/v1/sessions?limit=50",
            "/api/v1/projects",
            "/api/v1/benchmarks",
            f"/api/v1/insights/{insight_id}",
            f"/api/v1/insights/{insight_id}/investigations",
            f"/api/v1/benchmarks/{benchmark['id']}/comparisons",
            f"/api/v1/reports/project/{project_id}?format=json",
            "/api/v1/reports/savings",
        ):
            assert client.get(path, headers=auth).status_code == 200, path
        report = client.get(
            f"/api/v1/reports/project/{project_id}?format=markdown", headers=auth
        )
        assert report.status_code == 200
        markdown = report.text
        bodies = list(client.bodies)

    # The secrets were genuinely in play: the upstream saw the real key.
    assert f"Bearer {API_KEY}" in upstream.authorizations
    # ...and the local bearer token never crossed the proxy to the upstream.
    assert not any(LOCAL_TOKEN in (auth or "") for auth in upstream.authorizations)

    leaks: list[str] = []
    db_files = [p for p in data_dir.glob("tokenpilot.sqlite3*") if p.is_file()]
    assert db_files
    for path in db_files:
        if secret := _contains_secret(path.read_bytes()):
            leaks.append(f"{path.name} contains {secret}")
    patches = sorted((data_dir / "patches").glob("*"))
    assert patches, "benchmark runs wrote no patch files"
    for path in patches:
        if secret := _contains_secret(path.read_bytes()):
            leaks.append(f"patch {path.name} contains {secret}")
    log_blob = "\n".join(
        [caplog.text, *(record.getMessage() for record in caplog.records)]
    ).encode()
    if secret := _contains_secret(log_blob):
        leaks.append(f"logs contain {secret}")
    for index, body in enumerate(bodies):
        if secret := _contains_secret(body.encode()):
            leaks.append(f"api response #{index} contains {secret}")
    if secret := _contains_secret(markdown.encode()):
        leaks.append(f"markdown report contains {secret}")
    assert markdown.strip(), "markdown report was empty"
    assert not leaks, leaks


# --- primary: the real demo script as a process tree ---------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class DemoApi:
    """HTTP client for the live demo API that keeps every response body.

    Each record is ``(label, body, expect_echo)``. ``expect_echo`` marks the only
    responses allowed (and required) to contain the secrets: the deliberate
    echo probes, whose bodies the proxy relays verbatim from the hostile upstream.
    """

    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {LOCAL_TOKEN}"},
            timeout=120.0,
        )
        self.records: list[tuple[str, str, bool]] = []

    def request(
        self, method: str, path: str, *, expect_echo: bool = False, **kwargs: Any
    ) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        label = f"{method} {path} -> {response.status_code}"
        self.records.append((label, response.text, expect_echo))
        return response

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)


def _stop_process_group(proc: subprocess.Popen[bytes]) -> None:
    """Stop the demo script and every child it started, then wait until they are gone."""
    for sig, wait_s in ((signal.SIGTERM, 10.0), (signal.SIGKILL, 10.0)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            try:
                os.killpg(proc.pid, 0)
            except (ProcessLookupError, PermissionError):
                break
            time.sleep(0.1)
        else:
            continue
        break
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        proc.kill()


def test_no_secret_leaks(tmp_path: Path) -> None:
    api_port, web_port, fake_port = _free_port(), _free_port(), _free_port()
    data_dir = tmp_path / "demo-data"
    log_path = tmp_path / "demo.log"
    request_log = tmp_path / "upstream-requests.jsonl"
    request_log.touch()
    # `make demo` opens a browser when not --once; shadow `open` so tests never do.
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "open").write_text("#!/bin/sh\nexit 0\n")
    (stub_bin / "open").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        "MODEL_API_KEY": API_KEY,
        "TOKENPILOT_LOCAL_TOKEN": LOCAL_TOKEN,
        "TOKENPILOT_DEMO_DATA_DIR": str(data_dir),
        "TOKENPILOT_DEMO_API_PORT": str(api_port),
        "TOKENPILOT_DEMO_WEB_PORT": str(web_port),
        "TOKENPILOT_DEMO_FAKE_PORT": str(fake_port),
        # A hostile upstream: it can reflect credentials back in bodies and ids.
        "TOKENPILOT_FAKE_ECHO_SECRETS": f"{API_KEY},{LOCAL_TOKEN}",
        "TOKENPILOT_FAKE_REQUEST_LOG": str(request_log),
    }
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            ["bash", str(REPO_ROOT / "demo/scripts/run_demo.sh"), "--offline"],
            cwd=REPO_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    api: DemoApi | None = None
    markdown = ""
    try:

        def demo_ready() -> bool:
            assert proc.poll() is None, log_path.read_text(errors="replace")[-3000:]
            return "Demo ready (offline)" in log_path.read_text(errors="replace")

        _wait(demo_ready, timeout=180, what="run_demo.sh --offline to be ready")
        api = DemoApi(f"http://127.0.0.1:{api_port}")

        projects = api.get("/api/v1/projects").json()
        project_id = next(p["id"] for p in projects if p["slug"] == "invoicing-demo")

        # Redaction paths: the upstream echoes the key and the local token, once in
        # an error body and once in the response id the ledger stores. The proxy
        # relays these two replies verbatim, so they are the ONLY responses that
        # must contain the secrets (expect_echo=True: asserted dirty below).
        # Every other recorded body, gateway or /api/v1, must be clean.
        for behavior, status in (("echo-id", 200), ("echo-error", 401)):
            reply = api.post(
                CHAT,
                expect_echo=True,
                json={
                    "model": "fake-large",
                    "messages": [{"role": "user", "content": "echo my credentials"}],
                },
                headers={
                    "X-TokenPilot-Project": "invoicing-demo",
                    "X-TokenPilot-Session": f"demo-{behavior}",
                    "X-Fake-Behavior": behavior,
                },
            )
            assert reply.status_code == status, reply.text

        denied = api.get(
            "/api/v1/usage/summary", headers={"Authorization": f"Bearer {LOCAL_TOKEN}-wrong"}
        )
        assert denied.status_code == 401

        analyzed = api.post("/api/v1/insights/analyze", json={})
        assert analyzed.status_code == 202, analyzed.text

        def job_done(job_id: str) -> dict[str, Any] | None:
            job = api.get(f"/api/v1/jobs/{job_id}").json()
            return job if job["status"] in ("succeeded", "failed") else None

        job = _wait(lambda: job_done(analyzed.json()["job_id"]), timeout=60, what="analyze")
        assert job["status"] == "succeeded", job
        insights = api.get("/api/v1/insights?limit=50").json()["items"]
        insight_id = next(
            i["id"] for i in insights if i["rule_id"] == "retry_amplification"
        )

        investigated = api.post(
            f"/api/v1/insights/{insight_id}/investigate", json={"mode": "metadata_only"}
        )
        assert investigated.status_code == 202, investigated.text
        job = _wait(lambda: job_done(investigated.json()["job_id"]), timeout=90, what="investigate")
        assert job["status"] == "succeeded", job

        spec = yaml.safe_load((REPO_ROOT / "demo/benchmark_task.offline.yaml").read_text())
        created = api.post(
            f"/api/v1/insights/{insight_id}/benchmark",
            json={"task_spec": spec, "repeat_count": 1},
        )
        assert created.status_code == 201, created.text
        benchmark = created.json()
        alt = benchmark["alternatives"][0]["name"]
        started = api.post(
            f"/api/v1/benchmarks/{benchmark['id']}/runs",
            json={"variants": ["baseline", alt], "repeat_count": 1},
        )
        assert started.status_code == 202, started.text

        def runs_done() -> list[dict[str, Any]] | None:
            runs = api.get(f"/api/v1/benchmarks/{benchmark['id']}").json()["runs"]
            done = runs and all(r["run_status"] in ("completed", "failed") for r in runs)
            return runs if done else None

        runs = _wait(runs_done, timeout=300, what="benchmark runs")
        compare = api.post(
            f"/api/v1/benchmarks/{benchmark['id']}/compare",
            json={"baseline_variant": "baseline", "alternative_variant": alt},
        )
        assert compare.status_code == 201, compare.text
        for run in runs:
            assert api.get(f"/api/v1/benchmark-runs/{run['id']}").status_code == 200
            api.get(f"/api/v1/benchmark-runs/{run['id']}/patch")

        for path in (
            "/api/v1/health",
            "/api/v1/usage/summary",
            "/api/v1/usage/events?limit=200",
            "/api/v1/sessions?limit=50",
            "/api/v1/benchmarks",
            f"/api/v1/insights/{insight_id}",
            f"/api/v1/insights/{insight_id}/investigations",
            f"/api/v1/benchmarks/{benchmark['id']}/comparisons",
            f"/api/v1/reports/project/{project_id}?format=json",
            "/api/v1/reports/savings",
        ):
            assert api.get(path).status_code == 200, path
        report = api.get(f"/api/v1/reports/project/{project_id}?format=markdown")
        assert report.status_code == 200
        markdown = report.text
    finally:
        _stop_process_group(proc)

    assert api is not None
    logs = log_path.read_text(errors="replace")
    assert "Demo ready (offline)" in logs
    assert "Uvicorn running" in logs or "Application startup complete" in logs

    leaks: list[str] = []
    db_files = [p for p in data_dir.glob("tokenpilot.sqlite3*") if p.is_file()]
    assert db_files
    for path in db_files:
        if secret := _contains_secret(path.read_bytes()):
            leaks.append(f"{path.name} contains {secret}")
    patches = sorted((data_dir / "patches").glob("*"))
    assert patches, "benchmark runs wrote no patch files"
    for path in patches:
        if secret := _contains_secret(path.read_bytes()):
            leaks.append(f"patch {path.name} contains {secret}")
    if secret := _contains_secret(logs.encode()):
        leaks.append(f"demo stdout/stderr logs contain {secret}")
    # Every recorded body is scanned; nothing is dropped from the set.
    assert sum(1 for _, _, echo in api.records if echo) == 2, "expected exactly two echo probes"
    for index, (label, body, expect_echo) in enumerate(api.records):
        found = {secret for secret in SECRETS if secret in body}
        if expect_echo:
            # Allowlisted probe: must carry BOTH echoed secrets, else the redaction
            # exercise did not fire and the test proves nothing.
            if found != set(SECRETS):
                leaks.append(f"echo probe #{index} [{label}] unexpectedly clean/partial: {found}")
        elif found:
            leaks.append(f"response #{index} [{label}] contains {sorted(found)}")
    if secret := _contains_secret(markdown.encode()):
        leaks.append(f"markdown report contains {secret}")
    assert markdown.strip(), "markdown report was empty"
    assert not leaks, leaks

    # The redaction path really ran: the echoed id and the 401 are in the ledger, masked.
    with sqlite3.connect(data_dir / "tokenpilot.sqlite3") as conn:
        echoed = conn.execute(
            "SELECT source_event_id FROM usage_events WHERE source_event_id LIKE 'chatcmpl-echo-%'"
        ).fetchall()
        rejected = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE http_status = 401"
        ).fetchone()
    assert echoed, "echoed-id event missing from the ledger"
    assert all("[REDACTED]" in row[0] for row in echoed), echoed
    assert rejected[0] >= 1, "echoed-error event missing from the ledger"

    # What the upstream received: the real key, never the local token (headers or bodies).
    upstream_lines = [
        json.loads(line) for line in request_log.read_text().splitlines() if line.strip()
    ]
    assert upstream_lines, "fake upstream recorded no requests"
    assert any(
        f"Bearer {API_KEY}" in json.dumps(entry["headers"]) for entry in upstream_lines
    )
    assert LOCAL_TOKEN not in request_log.read_text(), "local token reached the upstream"
