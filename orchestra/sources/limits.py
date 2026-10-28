"""How hard Orchestra may lean on another company's store: a request rate and a budget per round.

- **Rate** (``RateLimit``): a token bucket per source, ``rate`` requests a second with bursts of
  ``burst``, shared by every thread and, through a small file in the state directory, by every
  process of the project (the host and the web server read the same tenant). A 429's
  ``Retry-After`` holds the whole bucket for that long (``hold``), so the other readers wait it out
  too rather than spending the tenant's quota on refusals.
- **Budget** (``Budget``): the most requests one round may make (an inference, or one
  discovery's reads), retries included, and the time it must be done by. Past either, the next
  request raises ``OverBudget`` (a ``PastDeadline``): the round keeps what it read and says what it
  did not.

Neither ever waits past the round's deadline: a wait that would end after it raises at once."""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from pathlib import Path

from . import PastDeadline


class OverBudget(PastDeadline):
    """A round made as many requests as it may (``Budget``)."""


class RateLimit:
    def __init__(self, rate: float, burst: float, path: Path | None = None, *, sleep=time.sleep, clock=time.time):
        self.rate, self.burst = max(0.01, float(rate)), max(1.0, float(burst))
        self.path = Path(path) if path else None
        self._mem = {"tokens": self.burst, "t": clock(), "hold": 0.0}
        self._lock = threading.Lock()
        self._sleep, self._clock = sleep, clock
        self.waited = 0.0                        # seconds this process waited for the bucket

    def _state(self, fh) -> dict:
        try:
            fh.seek(0)
            d = json.loads(fh.read() or "{}")
            return {"tokens": float(d["tokens"]), "t": float(d["t"]), "hold": float(d.get("hold", 0.0))}
        except (ValueError, KeyError, TypeError):
            return {"tokens": self.burst, "t": self._clock(), "hold": 0.0}

    def _save(self, fh, st: dict) -> None:
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(st))
        fh.flush()

    def _with_state(self, fn):
        """``fn(state) -> result`` under the bucket's locks; the state is written back."""
        with self._lock:
            if self.path is None:
                return fn(self._mem)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            with os.fdopen(fd, "r+") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    st = self._state(fh)
                    out = fn(st)
                    self._save(fh, st)
                    return out
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _try(self, st: dict) -> float:
        """Take a token: 0 when taken, else how long to wait for one."""
        now = self._clock()
        st["tokens"] = min(self.burst, st["tokens"] + max(0.0, now - st["t"]) * self.rate)
        st["t"] = now
        if now < st["hold"]:
            return st["hold"] - now
        if st["tokens"] >= 1.0 - 1e-6:
            st["tokens"] = max(0.0, st["tokens"] - 1.0)
            return 0.0
        return max(0.001, (1.0 - st["tokens"]) / self.rate)

    def take(self, until: float | None = None, where: str = "") -> None:
        """Wait for a token; ``PastDeadline`` when the wait would end after ``until``
        (``time.monotonic()``)."""
        while True:
            wait = self._with_state(self._try)
            if wait <= 0:
                return
            if until is not None and time.monotonic() + wait > until:
                raise PastDeadline(f"{where}: past the deadline (waiting {wait:.1f} s for the source's request rate)")
            self.waited += wait
            self._sleep(min(wait, 5.0))

    def hold(self, seconds: float) -> None:
        """No request from any reader for ``seconds``: the server asked for that (Retry-After)."""
        def fn(st):
            st["hold"] = max(st["hold"], self._clock() + seconds)
        self._with_state(fn)


class Budget:
    def __init__(self, requests: int | None = None, until: float | None = None, what: str = "this round"):
        self.requests, self.until, self.what = requests, until, what
        self.used = 0
        self.retries = 0
        self._lock = threading.Lock()

    def spend(self, where: str = "") -> None:
        with self._lock:
            if self.requests is not None and self.used >= self.requests:
                raise OverBudget(f"{where}: {self.what} made its {self.requests} requests (its budget); the rest is not read")
            if self.until is not None and time.monotonic() > self.until:
                raise OverBudget(f"{where}: past the deadline of {self.what}")
            self.used += 1

    def left(self) -> float | None:
        return None if self.until is None else self.until - time.monotonic()
