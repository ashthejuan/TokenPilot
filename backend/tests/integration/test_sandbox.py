"""Integration tests for the sandboxed test runner."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tokenpilot.benchmarks.sandbox import run_sandboxed

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")


def _sleep_pids() -> set[str]:
    out = subprocess.run(
        ["ps", "-eo", "pid,args"], capture_output=True, text=True, check=True
    )
    pids = set()
    for line in out.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip() == "sleep 30":
            pids.add(parts[0])
    return pids


def test_sandbox_env_has_no_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "super-secret-key")
    monkeypatch.setenv("TOKENPILOT_LOCAL_TOKEN", "super-secret-token")
    env_bin = shutil.which("env")
    assert env_bin is not None
    result = run_sandboxed([env_bin], cwd=tmp_path, timeout_s=10)
    assert result.exit_code == 0
    assert not result.timed_out
    assert "super-secret-key" not in result.stdout_tail
    assert "super-secret-token" not in result.stdout_tail
    assert "MODEL_API_KEY" not in result.stdout_tail
    assert "LANG=C.UTF-8" in result.stdout_tail
    assert "PYTHONDONTWRITEBYTECODE=1" in result.stdout_tail


def test_sandbox_timeout_kills_process_group(tmp_path: Path) -> None:
    sleep_bin = shutil.which("sleep")
    assert sleep_bin is not None
    before = _sleep_pids()
    started = time.monotonic()
    result = run_sandboxed([sleep_bin, "30"], cwd=tmp_path, timeout_s=1)
    elapsed = time.monotonic() - started
    assert result.timed_out
    assert result.exit_code is None
    assert elapsed < 3
    assert _sleep_pids() - before == set()


def test_sandbox_blocks_network_when_available(tmp_path: Path) -> None:
    if not SANDBOX_EXEC.exists():
        pytest.skip("sandbox-exec not available")
    probe = (
        "import socket, sys; "
        "socket.create_connection(('1.1.1.1', 80), timeout=5); "
        "print('NETWORK-OK')"
    )
    result = run_sandboxed(
        [sys.executable, "-c", probe], cwd=tmp_path, timeout_s=15
    )
    assert result.isolation_level == "sandbox-exec"
    assert result.exit_code != 0
    assert "NETWORK-OK" not in result.stdout_tail


def test_sandbox_success_reports_exit_code(tmp_path: Path) -> None:
    result = run_sandboxed(
        [sys.executable, "-c", "print('hello-sandbox')"],
        cwd=tmp_path, timeout_s=10,
    )
    assert result.exit_code == 0
    assert not result.timed_out
    assert "hello-sandbox" in result.stdout_tail
    assert result.duration_ms >= 0
    assert result.isolation_level in ("sandbox-exec", "env-scrub-only")


def test_sandbox_redacts_secrets_in_output(tmp_path: Path) -> None:
    leaked = "sk-abcdefghijklmnopqrst"
    result = run_sandboxed(
        [sys.executable, "-c", f"print('{leaked}')"],
        cwd=tmp_path, timeout_s=10,
    )
    assert result.exit_code == 0
    assert leaked not in result.stdout_tail
    assert "[REDACTED]" in result.stdout_tail


def test_sandbox_env_scrub_only_when_network_requested(tmp_path: Path) -> None:
    assert "MODEL_API_KEY" not in os.environ
    result = run_sandboxed(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path, timeout_s=10, network=True,
    )
    assert result.exit_code == 0
    assert result.isolation_level == "env-scrub-only"
