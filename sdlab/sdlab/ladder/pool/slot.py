"""One worker slot: its own checkout ($HOME/slot-<n>, moved to each item's commit), its own ladder cache
($HOME/cache/slot-<n>: an empty store, with the hash-named data parts shared), and one item process at a
time (child.py), kept between items of the same commit and recycled (stopped; the next item starts a new
one) when the commit changes, after a heavy item, after `recycle_items` items, when its resident memory
after an item is over `recycle_mb` (default the larger of RECYCLE_MIN_MB and RECYCLE_SHARE of the slot's
share of the budget), and after `child_idle` seconds without an item. A long-lived item process only
grows (numpy, numba and JAX caches, fragmentation): on node2 on 2026-10-21 23 of them held ~2 GB each
after 5.5 hours, and memory admission ran 1 slot of 23.

While an item runs the slot watches it every half second: over its hard memory limit (the expected peak
x 2, at least 4 GB, at most half the machine or the worker's budget) the process is killed and the item posted as `crashed`
(the server retries it once where there is more memory); past a guard of twice its timeout plus
GUARD_EXTRA seconds (run_item's own timeout covers discovery, not scoring) it is killed and posted as a
timeout; a lease the server says is lost or cancelled is killed and not posted; at shutdown it is killed
and its lease released.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .child import Child, ChildError
from .client import Down
from .repo import PROJECT, CodeError

log = logging.getLogger("sdlab.pool.worker")

RECYCLE_ITEMS = 25           # an item process is recycled after this many items
RECYCLE_MIN_MB = 1536.0      # ... or when it holds more than max(this, RECYCLE_SHARE x the slot's budget share) after an item
RECYCLE_SHARE = 0.25
CHILD_IDLE = 600.0           # ... or after this many seconds without an item
GUARD_FACTOR = 2.0
GUARD_EXTRA = 900.0
MIN_LIMIT_MB = 4096.0
HASHES = ("case_hash", "strategy_hash", "score_hash")


@dataclass
class Running:
    item: dict
    expected: float
    limit: float
    free_at_claim: float
    started: float = field(default_factory=time.time)
    abort: str | None = None         # lost | cancel | shutdown
    peak: float = 0.0


def hard_limit(expected: float, total_mb: float, budget_mb: float | None = None) -> float:
    """Twice the expected peak, at least MIN_LIMIT_MB, at most half the machine and never past the worker's
    budget (the Mac's 96 GB of 256: one item once reached 132 GB under a half-the-machine limit)."""
    top = total_mb / 2.0 if budget_mb is None else min(total_mb / 2.0, budget_mb)
    return min(max(2.0 * expected, MIN_LIMIT_MB), top)


def recycle_mb(budget_mb: float, slots: int, override: float | None = None) -> float:
    """The resident memory past which an item process is recycled after an item: `override` when given, else
    the larger of RECYCLE_MIN_MB and RECYCLE_SHARE of one slot's share of the budget."""
    if override:
        return float(override)
    return max(RECYCLE_MIN_MB, RECYCLE_SHARE * budget_mb / max(1, slots))


class Slot:
    def __init__(self, n: int, worker):
        self.n = n
        self.w = worker
        self.path: Path = worker.home / f"slot-{n}"
        self.cache: Path = worker.home / "cache" / f"slot-{n}"
        self.log_path: Path = worker.home / "logs" / f"slot-{n}.log"
        self.commit: str | None = worker.repo.head(self.path) if (self.path / ".git").exists() else None
        self.child: Child | None = None
        self.run: Running | None = None
        self.q: queue.Queue = queue.Queue()
        self.idle_since = time.time()
        self.thread = threading.Thread(target=self._loop, daemon=True, name=f"pool-slot-{n}")
        self.thread.start()

    @property
    def busy(self) -> bool:
        return self.run is not None

    def give(self, item: dict, free_at_claim: float) -> None:
        exp = float(item.get("expected_peak_mb") or 1000.0)
        self.run = Running(item, exp, hard_limit(exp, self.w.total_mb, self.w.budget_mb), free_at_claim)
        self.q.put(item)

    def abort(self, why: str) -> None:
        r = self.run
        if r is not None:
            r.abort = why

    def close(self) -> None:
        self.q.put(None)
        self._drop_child(stop=True)

    def rss(self) -> float:
        c = self.child
        return self.w.sampler.get(c.pid)[0] if c and c.pid else 0.0

    # ---- running one item ----

    def _loop(self) -> None:
        while True:
            idle = float(getattr(self.w, "child_idle", CHILD_IDLE))
            try:
                it = self.q.get(timeout=max(0.05, min(30.0, idle / 4)))
            except queue.Empty:
                if self.child is not None and self.run is None and time.time() - self.idle_since > idle:
                    self._recycle(f"idle for {time.time() - self.idle_since:.0f} s")
                continue
            if it is None:
                return
            try:
                self._do(it)
            except Exception:                                  # noqa: BLE001  (logged; the lease expires or the post says why)
                log.exception("slot %s: item %s failed in the worker", self.n, it.get("item_id"))
                self._drop_child(stop=False)
            finally:
                self.run = None
                self.idle_since = time.time()

    def _recycle(self, why: str) -> None:
        c = self.child
        if c is None:
            return
        log.info("slot %s: recycling its item process %s after %d items: %s", self.n, c.pid, c.items, why)
        self._drop_child(stop=True)

    def _drop_child(self, stop: bool) -> None:
        c, self.child = self.child, None
        if c is None:
            return
        if stop:
            c.stop()
        else:
            c.kill()
        if c.pid:
            self.w.sampler.forget(c.pid)

    def _prepare(self, commit: str) -> Child:
        if self.commit != commit or not (self.path / ".git").exists():
            self._drop_child(stop=True)
            self.w.repo.ensure(commit)
            self.w.repo.checkout(self.path, commit)
            self.commit = commit
        py = self.w.repo.python(self.path)
        if self.child is None or not self.child.alive():
            self._drop_child(stop=False)
            c = Child(py, self.path / PROJECT, self.w.child_env(self.cache), self.w.nice, self.log_path)
            c.start()
            self.child = c
            self.w.sampler.watch(c.pid)
        return self.child

    def _do(self, it: dict) -> None:
        r = self.run
        assert r is not None
        try:
            child = self._prepare(it["commit"])
        except Down as e:
            log.warning("slot %s: the server is down while fetching %s (%s); releasing item %s", self.n, it["commit"][:12], e, it["item_id"])
            self.w.release([it["lease_id"]])
            return
        except (CodeError, ChildError, OSError) as e:
            log.error("slot %s: cannot run commit %s: %s", self.n, it["commit"][:12], e)
            self._post(it, "crashed", None, None, None, f"the slot could not run commit {it['commit'][:12]}: {e}"[:1500])
            return
        if r.abort:
            if r.abort == "shutdown":
                self.w.release([it["lease_id"]])
            return
        child.send({"item_id": it["item_id"], "case": it["case"], "variant": it["variant"], "strategy": it["strategy"],
                    "mode": it.get("mode") or "run", "prev": it.get("prev"), "timeout": it.get("timeout") or 300,
                    "promised": {k: it[k] for k in HASHES}})
        self.w.sampler.reset_high(child.pid)
        guard = GUARD_FACTOR * float(it.get("timeout") or 300) + GUARD_EXTRA
        hashes = None
        log.info("slot %s: item %s %s %s %s (job %s, %s, expect %.0f MB, limit %.0f MB)", self.n, it["item_id"], it["case"], it["variant"],
                 it["strategy"], it["job_id"], it.get("mode"), r.expected, r.limit)
        while True:
            ev = child.next(0.5)
            now, high = self.w.sampler.get(child.pid)
            r.peak = max(r.peak, high)
            if ev is False or ev is None:
                why = self._watch(r, now, guard)
                if ev is None or why:
                    how = "" if why else child.exit_how()
                    self._drop_child(stop=False)
                    self._ended(it, r, hashes, why, how)
                    return
                continue
            kind = ev.get("event")
            if kind == "error":
                log.error("slot %s: item %s cannot be planned at %s: %s", self.n, it["item_id"], it["commit"][:12], ev.get("error"))
                self._post(it, "result", {}, {"status": "error", "error": ev.get("error")}, None)
                return
            if kind == "start":
                hashes = ev.get("hashes")
                if not ev.get("match"):
                    log.error("slot %s: item %s: this checkout's hashes %s differ from the promised ones; not run", self.n, it["item_id"], hashes)
                continue
            if kind == "done":
                row = ev.get("row")
                if row is None:
                    row = {"status": "error", "error": "not run: the worker's checkout computed other hashes than the promised ones"}
                peak = ev.get("hwm_mb")
                if peak is None:
                    peak = max(r.peak, ev.get("maxrss_mb") or 0.0) if child.fresh else max(r.peak, now)
                child.fresh = False
                self._post(it, "result", ev.get("hashes"), row, peak)
                held = max(now, ev.get("rss_mb") or 0.0)
                top = recycle_mb(self.w.budget_mb, getattr(self.w, "slots_n", 1), getattr(self.w, "recycle_mb", None))
                most = int(getattr(self.w, "recycle_items", RECYCLE_ITEMS))
                if held > top:
                    self._recycle(f"memory: it holds {held:.0f} MB, over {top:.0f} MB")
                elif it.get("heavy"):
                    self._recycle("heavy item")
                elif child.items >= most:
                    self._recycle(f"items: {child.items} run (at most {most})")
                return

    def _watch(self, r: Running, rss: float, guard: float) -> str | None:
        if r.abort:
            return r.abort
        if rss > r.limit:
            return "memory"
        if time.time() - r.started > guard:
            return "guard"
        return None

    def _ended(self, it: dict, r: Running, hashes: dict | None, why: str | None, how: str) -> None:
        if why in ("lost", "cancel"):
            log.info("slot %s: item %s stopped (%s lease)", self.n, it["item_id"], why)
            return
        if why == "shutdown":
            self.w.release([it["lease_id"]])
            return
        took = round(time.time() - r.started, 1)
        if why == "memory":
            err = (f"killed by the worker: its resident memory {r.peak:.0f} MB passed the item's hard limit {r.limit:.0f} MB"
                   f" (expected peak {r.expected:.0f} MB)")
            log.warning("slot %s: item %s: %s", self.n, it["item_id"], err)
            self._post(it, "crashed", hashes, None, r.peak, err)
        elif why == "guard" and hashes:
            row = {"case": it["case"], "variant": it["variant"], "strategy": it["strategy"], **hashes, "status": "timeout",
                   "error": f"stopped by the worker after {took:g} s (its own timeout covers discovery, not scoring)", "wall_seconds": took}
            self._post(it, "result", hashes, row, r.peak)
        else:
            err = f"the item process {how or 'was stopped'} after {took:g} s (resident memory up to {r.peak:.0f} MB)"
            log.warning("slot %s: item %s: %s", self.n, it["item_id"], err)
            self._post(it, "crashed", hashes, None, r.peak, err)

    def _post(self, it: dict, outcome: str, hashes: dict | None, row: dict | None, peak: float | None, error: str | None = None) -> None:
        r = self.run
        body = {"worker": self.w.name, "machine": self.w.machine, "slot": self.n, "item_id": it["item_id"], "lease_id": it["lease_id"],
                "commit": it["commit"], "outcome": outcome, "hashes": hashes or {}, "row": row or {},
                "peak_rss_mb": round(peak, 1) if peak else None, "free_mb": round(r.free_at_claim, 1) if r else None, "error": error}
        self.w.deliver(body)
