"""Single-threaded benchmark run queue, started in the app lifespan.

One background thread pulls run ids off a `queue.Queue` and executes them with
its own SQLite connection, so long runs never block API requests. On startup
the worker fails runs a previous process left behind (PRD §14 Reliability).

Cancel sets a per-run flag that the runner checks between agent steps and
that the sandbox wait polls: cancelling a run inside the acceptance command
SIGKILLs the sandbox process group at once and the run is marked `cancelled`.
"""

import logging
import queue
import threading
from pathlib import Path

import httpx

from tokenpilot.benchmarks.runner import INTERRUPTED_BY_RESTART, BenchmarkStore, execute_run
from tokenpilot.db.connection import connect
from tokenpilot.security import redact_text
from tokenpilot.timeutil import utc_now_z

logger = logging.getLogger("tokenpilot.benchmarks")


class BenchmarkWorker:
    def __init__(
        self,
        db_path: Path,
        *,
        gateway_url: str,
        local_token: str,
        data_dir: Path,
        transport: httpx.AsyncBaseTransport | None = None,
        keep_worktrees: bool = False,
    ) -> None:
        self._db_path = Path(db_path)
        self._gateway_url = gateway_url
        self._local_token = local_token
        self._data_dir = Path(data_dir)
        self._transport = transport
        self._keep_worktrees = keep_worktrees
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._cancel_flags: dict[str, threading.Event] = {}
        self._flags_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False

    def cancel_event(self, run_id: str) -> threading.Event:
        """The run's cancel flag, creating it on first use."""
        with self._flags_lock:
            flag = self._cancel_flags.get(run_id)
            if flag is None:
                flag = threading.Event()
                self._cancel_flags[run_id] = flag
            return flag

    def enqueue(self, run_id: str) -> None:
        self.cancel_event(run_id)
        self._queue.put(run_id)

    def cancel(self, run_id: str) -> None:
        """Flag a queued or running run for cancellation."""
        self.cancel_event(run_id).set()

    def start(self) -> None:
        """Recover interrupted runs, then serve the queue on a daemon thread."""
        conn = connect(self._db_path)
        try:
            recovered = BenchmarkStore(conn).recover_interrupted()
            conn.commit()
        finally:
            conn.close()
        if recovered:
            logger.info("benchmark worker recovered %d interrupted runs", recovered)
        self._thread = threading.Thread(
            target=self._serve, name="benchmark-worker", daemon=True
        )
        self._started = True
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Drain nothing: finish nothing new, join the thread. Idempotent."""
        if not self._started:
            return
        self._started = False
        self._queue.put(None)
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

    @property
    def running(self) -> bool:
        return self._started

    def _serve(self) -> None:
        while True:
            run_id = self._queue.get()
            if run_id is None:
                return
            try:
                self._execute_one(run_id)
            except Exception as exc:  # a run must never kill the worker thread
                logger.error(
                    "benchmark run %s failed outside the executor: %s",
                    run_id,
                    redact_text(f"{type(exc).__name__}: {exc}"),
                )
            finally:
                with self._flags_lock:
                    self._cancel_flags.pop(run_id, None)

    def _execute_one(self, run_id: str) -> None:
        conn = connect(self._db_path)
        try:
            store = BenchmarkStore(conn)
            run = store.get_run(run_id)
            if run is None or run.run_status != "queued":
                return
            if self.cancel_event(run_id).is_set():
                store.update_run(
                    run_id,
                    run_status="completed",
                    outcome="cancelled",
                    error="cancelled",
                    completed_at=utc_now_z(),
                    eligible=0,
                )
                conn.commit()
                return
            execute_run(
                conn,
                run_id,
                gateway_url=self._gateway_url,
                local_token=self._local_token,
                data_dir=self._data_dir,
                transport=self._transport,
                cancel=self.cancel_event(run_id),
                keep_worktrees=self._keep_worktrees,
            )
        finally:
            conn.close()


def recover_interrupted_runs(db_path: Path) -> int:
    """Mark runs a dead process left behind as failed/inconclusive (lifespan hook)."""
    conn = connect(db_path)
    try:
        recovered = BenchmarkStore(conn).recover_interrupted()
        conn.commit()
        return recovered
    finally:
        conn.close()


__all__ = ["INTERRUPTED_BY_RESTART", "BenchmarkWorker", "recover_interrupted_runs"]
