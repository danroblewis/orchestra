"""The facts the comparison derives from the metrics store on every read, never stored (§5): a
chosen option's **recording** and its points, and the means a **target** is judged on. Each read
runs under a time limit, on one small process-wide pool (``POOL``): past the limit the fact is
left out and named in ``missing``, and when every worker is still busy with an earlier read (a
hung store) the fact is missing at once, never queued, so a slow store neither holds up a page
nor grows the threads.

A target (§2) is judged on the **mean** over its last ``over_s``: a stock's or effect's level, or a
flow's count over the window (the rate per ``over_s``: "land five a day" is ``above 5`` over a
day). It is met, missed or unknown; a target backed only by simulated parts is never met."""

from __future__ import annotations

import itertools
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

LIMIT_S = 2.0
RECORDING_SPAN_S = 7 * 86400.0
SPARK = 60
POOL = 4

_pool = ThreadPoolExecutor(max_workers=POOL, thread_name_prefix="intended-fact")
_free = threading.BoundedSemaphore(POOL)


def _within(fn, limit: float):
    """``(fn(), True)`` if it answered within ``limit``; ``(None, False)`` if it failed, ran past
    the limit, or no worker was free."""
    if limit <= 0 or not _free.acquire(blocking=False):
        return None, False

    def run():
        try:
            return fn()
        finally:
            _free.release()
    try:
        fut = _pool.submit(run)
    except RuntimeError:                    # the interpreter is shutting down
        _free.release()
        return None, False
    try:
        return fut.result(timeout=limit), True
    except Exception:  # noqa: BLE001 - a failed or late read is a missing fact
        return None, False


class Facts:
    def __init__(self, metrics, limit_s: float = LIMIT_S, now: float | None = None, project: str | None = None):
        """``project``: the project's key, so a store several projects share is read for this one's
        points only (None for a store with no project)."""
        self.metrics = metrics
        self.project = project
        self.deadline = time.monotonic() + limit_s
        self.now = now or time.time()
        self.missing: list[str] = []

    def _read(self, what: str, fn):
        if self.metrics is None:
            self._miss(what)
            return None
        left = self.deadline - time.monotonic()
        v, ok = _within(fn, left) if left > 0 else (None, False)
        if not ok:
            self._miss(what)
        return v

    def _miss(self, what: str) -> None:
        if what not in self.missing:
            self.missing.append(what)

    def recording(self, instrument: str) -> dict | None:
        """What an instrument has written: its busiest series' points (the last ``SPARK``)."""
        def read():
            best: list = []
            match = {"instrument": instrument, **({"project": self.project} if self.project else {})}
            for name, labels in self.metrics.series("", match):
                pts = self.metrics.raw(name, labels, start=self.now - RECORDING_SPAN_S, end=self.now)
                if len(pts) > len(best):
                    best = pts
            return best
        pts = self._read(f"recording {instrument}", read)
        if pts is None:
            return None
        gaps = [b[0] - a[0] for a, b in itertools.pairwise(pts)]
        return {"instrument": instrument, "since": pts[0][0] if pts else None, "points": len(pts),
                "every_s": round(statistics.median(gaps), 1) if gaps else None, "last": pts[-1][1] if pts else None,
                "points_series": [[t, v] for t, v in pts[-SPARK:]]}

    def mean_level(self, ref, over_s: float, what: str) -> float | None:
        pts = self._read(what, lambda: self.metrics.raw(ref.name, ref.labels, start=self.now - over_s, end=self.now))
        if not pts:
            return None
        return sum(v for _, v in pts) / len(pts)

    def count(self, refs: list, over_s: float, what: str) -> float | None:
        """A flow's count over the window: the rises of its counters (a drop is a reset)."""
        def read():
            total, seen = 0.0, False
            for r in refs:
                pts = self.metrics.raw(r.name, r.labels, start=self.now - over_s, end=self.now)
                seen = seen or bool(pts)
                total += sum((b if b < a else b - a) for (_, a), (_, b) in itertools.pairwise(pts))
            return total if seen else None
        return self._read(what, read)


def judged(t: dict, mean: float | None, simulated: bool) -> dict:
    """A target's verdict from its mean: met, missed or unknown."""
    if mean is None:
        return {**t, "mean": None, "met": "unknown"}
    lo_ok = {"below": mean < t["value"], "above": mean > t["value"], "within": t["value"] <= mean <= t.get("hi", t["value"])}
    ok = lo_ok[t["op"]]
    if ok and simulated:
        return {**t, "mean": round(mean, 6), "met": "unknown", "why": "backed only by simulated parts"}
    return {**t, "mean": round(mean, 6), "met": "met" if ok else "missed"}
