"""Discovery jobs: the page's discovery runs in worker processes, one job per open model.

Discovery takes from well under a second to tens of seconds on a long run, and "keep discovering"
asks often, so it never runs on the server's event loop: each request is a job in a process pool.
A model has one current job; a newer request supersedes it (a job still waiting is cancelled; one
already running finishes in its worker, and its result is dropped). The last finished result is kept
for the model, so a page can show it while a newer job runs.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import threading
import time
from concurrent.futures import CancelledError, Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Any

from .discovery.api import discover


@dataclass
class Job:
    n: int
    model: str
    strategy: str
    steps: int
    started: float = field(default_factory=time.time)
    state: str = "running"                   # running, done, error, superseded, cancelled
    finished: float | None = None
    result: dict | None = None
    error: str | None = None
    future: Future | None = None

    def view(self, with_result: bool = True) -> dict:
        out: dict[str, Any] = {"job": self.n, "state": self.state, "strategy": self.strategy, "steps": self.steps,
                               "started": self.started, "ms": round(1000 * ((self.finished or time.time()) - self.started))}
        if self.error:
            out["error"] = self.error
        if with_result and self.result is not None:
            out["result"] = self.result
        return out


class DiscoveryJobs:
    def __init__(self, workers: int | None = None):
        self.workers = workers or int(os.environ.get("SDLAB_DISCOVERY_WORKERS") or max(1, min(4, (os.cpu_count() or 2) - 1)))
        self.pool: ProcessPoolExecutor | None = None
        self.lock = threading.Lock()
        self.current: dict[str, Job] = {}       # model -> its newest job
        self.last: dict[str, Job] = {}          # model -> its last finished job
        self.count = 0

    def _pool(self) -> ProcessPoolExecutor:
        if self.pool is None:
            # spawn, not fork: the server has threads (live runs), which a forked child would not
            self.pool = ProcessPoolExecutor(max_workers=self.workers, mp_context=multiprocessing.get_context("spawn"))
        return self.pool

    def submit(self, model: str, request: dict) -> Job:
        with self.lock:
            self.count += 1
            job = Job(self.count, model, request.get("strategy") or "matrix", len(request["run"]["t"]))
            old = self.current.get(model)
            if old is not None and old.state == "running":
                old.state, old.finished = "superseded", time.time()
                if old.future is not None:
                    old.future.cancel()
            self.current[model] = job
            try:
                job.future = self._pool().submit(discover, request)
            except BrokenProcessPool:
                self.pool = None
                job.future = self._pool().submit(discover, request)
        job.future.add_done_callback(lambda f: self._finish(job, f))
        return job

    def _finish(self, job: Job, f: Future) -> None:
        with self.lock:
            if job.state != "running":
                return                                   # superseded or cancelled: dropped
            job.finished = time.time()
            try:
                job.result, job.state = f.result(), "done"
                self.last[job.model] = job
            except CancelledError:
                job.state = "cancelled"
            except BrokenProcessPool as e:
                job.state, job.error = "error", f"the discovery worker stopped: {e}"
                self.pool = None
            except Exception as e:  # noqa: BLE001 - any failure of discovery is reported to the page
                job.state, job.error = "error", f"{type(e).__name__}: {e}"

    def status(self, model: str, n: int | None = None) -> dict:
        """The model's job n (default its newest), and its last finished result when that job has
        none (a newer job is running, or it failed)."""
        with self.lock:
            job = self.current.get(model)
            if n is not None and job is not None and job.n != n:
                last = self.last.get(model)
                job = last if last is not None and last.n == n else None
                if job is None:
                    return {"job": n, "state": "superseded"}
            if job is None:
                return {"job": None, "state": "idle"}
            out = job.view()
            last = self.last.get(model)
            if "result" not in out and last is not None:
                out["last"] = last.view()
            return out

    async def wait(self, model: str, n: int | None, timeout: float) -> dict:
        """Wait (without blocking the event loop) until job n finishes, or `timeout` seconds."""
        with self.lock:
            job = self.current.get(model)
        if job is not None and job.state == "running" and job.future is not None and (n is None or job.n == n):
            try:
                await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(job.future)), timeout)
            except (TimeoutError, asyncio.TimeoutError, CancelledError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            for _ in range(100):                         # the done callback runs on the pool's thread
                if job.state != "running" or not job.future.done():
                    break
                await asyncio.sleep(0.01)
        return self.status(model, n)

    def cancel(self, model: str) -> dict:
        with self.lock:
            job = self.current.get(model)
            if job is not None and job.state == "running":
                job.state, job.finished = "cancelled", time.time()
                if job.future is not None:
                    job.future.cancel()
        return self.status(model)

    def forget(self, model: str) -> None:
        self.cancel(model)
        with self.lock:
            self.current.pop(model, None)
            self.last.pop(model, None)

    def close(self) -> None:
        if self.pool is not None:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
