"""Run test commands with a scrubbed env, rlimits, and (on macOS) sandbox-exec."""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from tokenpilot.security import redact_text

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
TAIL_BYTES = 64 * 1024
FSIZE_LIMIT_BYTES = 50 * 1024 * 1024
NOFILE_LIMIT = 256
POLL_INTERVAL_S = 0.05


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int | None
    timed_out: bool
    stdout_tail: str
    stderr_tail: str
    duration_ms: int
    isolation_level: str
    cancelled: bool = False


def _sandbox_profile(cwd: Path, home: Path) -> str:
    def lit(path: Path) -> str:
        return str(path).replace("\\", "\\\\").replace('"', '\\"')

    return f"""(version 1)
(allow process-exec (subpath "/"))
(allow process-fork)
(allow signal)
(allow file-read* (subpath "/"))
(allow file-write*
  (subpath "{lit(cwd)}")
  (subpath "{lit(home)}")
  (subpath "/tmp")
  (subpath "/private/tmp")
  (subpath "/var/folders")
  (subpath "/dev"))
(allow network-outbound (remote ip "localhost:*"))
(allow system-socket)
(allow mach-lookup)
(allow sysctl-read)
(deny network*)
(deny default)
"""


def _limit_resources(timeout_s: int) -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (timeout_s, timeout_s))
    resource.setrlimit(
        resource.RLIMIT_FSIZE, (FSIZE_LIMIT_BYTES, FSIZE_LIMIT_BYTES)
    )
    resource.setrlimit(resource.RLIMIT_NOFILE, (NOFILE_LIMIT, NOFILE_LIMIT))


def _tail(data: bytes) -> str:
    return redact_text(data[-TAIL_BYTES:].decode("utf-8", errors="replace"))


def _kill_group(pid: int) -> None:
    """SIGKILL the process group; a just-exited group is not an error."""
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


def run_sandboxed(
    cmd: list[str],
    cwd: Path,
    timeout_s: int,
    network: bool = False,
    cancel: threading.Event | None = None,
) -> SandboxResult:
    """Run `cmd` in `cwd` with a scrubbed env and resource limits.

    The child sees exactly `PATH`, `HOME` (a fresh temp dir), `LANG`, and
    `PYTHONDONTWRITEBYTECODE`. On timeout the whole process group is SIGKILLed.

    When `cancel` is set, the wait ends promptly: the group is SIGKILLed and
    the result carries `cancelled=True` (with `timed_out=False` and
    `exit_code=None`). Unset preserves the previous behavior exactly.

    Isolation notes (deliberate relaxations, see Phase 4 notes):
    file writes are allowed under `cwd`, the temp HOME, and the system temp
    dirs (`/tmp`, `/private/tmp`, `/var/folders`) so pytest tmpdirs work;
    localhost TCP outbound is allowed for local tooling. `network=True`
    skips the `sandbox-exec` wrap entirely (`isolation_level="env-scrub-only"`)
    for callers that need real network access.
    """
    home = Path(tempfile.mkdtemp(prefix="tokenpilot-sandbox-home-"))
    env = {
        "PATH": os.pathsep.join(
            [os.path.dirname(sys.executable), "/usr/bin", "/bin"]
        ),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    argv = list(cmd)
    isolation_level = "env-scrub-only"
    if not network and SANDBOX_EXEC.exists():
        profile = home / "sandbox.sb"
        profile.write_text(
            _sandbox_profile(cwd.resolve(), home), encoding="utf-8"
        )
        argv = [str(SANDBOX_EXEC), "-f", str(profile), *cmd]
        isolation_level = "sandbox-exec"
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        preexec_fn=lambda: _limit_resources(timeout_s),
    )
    timed_out = False
    cancelled = False
    try:
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=POLL_INTERVAL_S)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    _kill_group(proc.pid)
                    stdout, stderr = proc.communicate()
                    break
                if time.monotonic() - started >= timeout_s:
                    timed_out = True
                    _kill_group(proc.pid)
                    stdout, stderr = proc.communicate()
                    break
        exit_code: int | None = None if (timed_out or cancelled) else proc.returncode
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        shutil.rmtree(home, ignore_errors=True)
    return SandboxResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
        duration_ms=duration_ms,
        isolation_level=isolation_level,
        cancelled=cancelled,
    )
