"""`sdlab-ladder worker`: a pool worker (docs/pool.md, "Workers"). A supervisor with N slots pulls items from
the server, runs each in its slot's own checkout at the item's commit and posts the result; it never writes
a database.

    sdlab-ladder worker --server http://10.198.1.131:8020 --slots N --home DIR [--max-mem-gb G]
                        [--heavy-slots 2] [--yield-load L] [--nice 19] [--name NAME] [--machine NAME]

- **Code.** Every commit comes from the server as a git bundle into DIR/repo.git; each slot is a checkout
  sharing its objects (DIR/slot-<n>), moved to the item's commit, with its own venv (`uv sync` when the
  lock changes). The supervisor itself runs from DIR/self, at the main line's HEAD: started from any
  checkout it moves there first, and when its own code (sdlab/ladder/pool, uv.lock, pyproject.toml)
  changes on the main line it stops claiming, lets its items finish, and restarts itself from the new
  commit (--no-self-update: run from this checkout, as the tests do).
- **Memory.** It claims only what fits: the memory it can still promise is the lesser of its budget
  (--max-mem-gb, default 85% of the machine) less what its items hold or are expected to reach, and the
  OS's available memory less the growth still expected and a reserve. Heavy items need a free heavy slot.
  Each item has a hard limit (slot.py) and its peak RSS is posted with the result. A slot's item process is
  recycled after --recycle-items items, when it holds more than --recycle-gb after an item, and after
  --child-idle-minutes without one (slot.py), so long-lived processes do not keep growing.
- **Load.** With --yield-load L it takes fewer slots while the 1-minute load is above L (the Mac: its
  agents stay usable); running items finish.
- **Heartbeats** every 30 s renew its leases; a lease the server calls lost or cancelled is stopped.
- **Outbox.** Every result is written to DIR/outbox before it is posted, and resent until the server has
  answered it.
- **Shutdown.** SIGTERM or SIGINT: stop claiming and let running items finish (up to --grace seconds);
  then, or on a second signal, stop them and release their leases.
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import math
import os
import signal
import sys
import threading
import time
from pathlib import Path

from . import auth, host
from .client import Client, Down
from .outbox import Outbox
from .planner import SHARED
from .repo import PROJECT, CodeError, Repo
from . import slot as slot_mod
from .slot import Slot

log = logging.getLogger("sdlab.pool.worker")

SELF_ENV = "SDLAB_POOL_WORKER_SELF"              # set when the supervisor runs from DIR/self: the commit it runs
POOL_DIR = f"{PROJECT}/sdlab/ladder/pool"
OWN = (POOL_DIR, f"{PROJECT}/uv.lock", f"{PROJECT}/pyproject.toml")     # the supervisor's own code: a change restarts it
BUDGET_SHARE = 0.85


class Worker:
    def __init__(self, a, argv: list[str]):
        self.argv = argv
        self.server = a.server
        self.home = Path(a.home).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        tok = auth.token(create=False)
        if not tok:
            raise SystemExit(f"no pool token at {auth.path()} (copy the server's ~/.sdlab/pool.token here, mode 0600)")
        self.client = Client(a.server, tok)
        from .. import machines
        self.machine = a.machine or machines.here()
        self.name = a.name or f"{self.machine}-pool"
        self.slots_n = max(1, min(a.slots, 64))
        self.heavy_slots = max(0, a.heavy_slots)
        self.nice = a.nice
        self.yield_load = a.yield_load
        self.min_slots = max(0, a.min_slots)
        self.grace = a.grace
        self.hb_every = a.heartbeat
        self.poll = a.poll
        self.update_every = a.update_every
        self.recycle_items = max(1, a.recycle_items)
        self.recycle_mb = a.recycle_gb * 1024 if a.recycle_gb else None     # None: slot.recycle_mb's default
        self.child_idle = max(1.0, a.child_idle_minutes * 60.0)
        self.self_update = not a.no_self_update
        self.self_commit = os.environ.get(SELF_ENV) or None
        self.total_mb = host.mem_total_mb()
        self.budget_mb = min(self.total_mb, a.max_mem_gb * 1024 if a.max_mem_gb else BUDGET_SHARE * self.total_mb)
        self.reserve_mb = a.reserve_gb * 1024 if a.reserve_gb is not None else max(2048.0, 0.05 * self.total_mb)
        cache = Path(a.cache).expanduser() if a.cache else Path.home() / ".cache" / "sdlab" / "ladder"
        self.shared_cache = cache if cache.is_dir() else self.home / "cache" / "shared"
        self.repo = Repo(self.home, self.client)
        self.outbox = Outbox(self.home / "outbox", self.client)
        self.sampler = host.Sampler()
        self.slots: list[Slot] = []
        self.stopping = 0.0                            # when the first stop signal came (0: running)
        self.stop_now = False
        self.update_to: str | None = None
        self.checked_heads: set[str] = set()
        self.wake = threading.Event()                  # cuts the main loop's waits short (a signal)
        self.ended = threading.Event()                 # set once the worker stops: the background threads end

    # ---- what the slots use ----

    def child_env(self, cache: Path) -> dict:
        cache.mkdir(parents=True, exist_ok=True)
        for part in SHARED:                            # the cache's parts named by hash: shared by the slots (and, by
            target = self.shared_cache / part          # default, with this machine's ladder cache)
            target.mkdir(parents=True, exist_ok=True)
            link = cache / part
            if not link.exists() and not link.is_symlink():
                link.symlink_to(target, target_is_directory=True)
        from .child import THREAD_ENV
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", SELF_ENV, "SDLAB_POOL_TOKEN_FILE")}
        env.update(THREAD_ENV)
        env.update(SDLAB_LADDER_CACHE=str(cache), SDLAB_MACHINE=self.machine, PYTHONUNBUFFERED="1")
        return env

    def deliver(self, body: dict) -> None:
        f = self.outbox.put(body)
        self.outbox.send(f)

    def release(self, leases: list[str]) -> None:
        if not leases:
            return
        try:
            code, ans = self.client.call("POST", "/api/pool/release", {"worker": self.name, "machine": self.machine, "leases": leases})
            log.info("released %d leases: %s", len(leases), ans)
        except Down as e:
            log.warning("could not release %d leases (%s): they expire on the server", len(leases), e)

    # ---- memory and load ----

    def promise_mb(self) -> float:
        """The memory this worker can still promise to new items (MB)."""
        held = growth = 0.0
        for s in self.slots:
            now = s.rss()
            r = s.run
            exp = r.expected if r else 0.0
            held += max(exp, now)
            growth += max(0.0, exp - now)
        by_budget = self.budget_mb - held
        by_os = host.mem_available_mb() - growth - self.reserve_mb
        return max(0.0, min(by_budget, by_os))

    def effective_slots(self, load: float | None = None) -> int:
        n = self.slots_n
        if self.yield_load is not None:
            over = (host.load1() if load is None else load) - self.yield_load
            if over > 0:
                n = max(self.min_slots, n - math.ceil(over))
        return n

    def busy(self) -> list[Slot]:
        return [s for s in self.slots if s.busy]

    # ---- talking to the server ----

    def heartbeat(self) -> None:
        busy = self.busy()
        held = {s.run.item["lease_id"]: s for s in busy if s.run}
        body = {"worker": self.name, "machine": self.machine, "slots": self.slots_n, "busy": len(busy), "cpus": os.cpu_count(),
                "load": round(host.load1(), 2), "mem_total_mb": round(self.total_mb), "mem_free_mb": round(host.mem_available_mb()),
                "budget_mb": round(self.budget_mb),
                "heavy_slots": self.heavy_slots, "leases": list(held), "version": (self.self_commit or "local")[:12], "nice": self.nice}
        code, ans = self.client.call("POST", "/api/pool/heartbeat", body)
        if code != 200:
            log.error("heartbeat refused (%s): %s", code, ans)
            return
        for why, key in (("lost", "lost"), ("cancel", "cancel")):
            for lease in ans.get(key) or []:
                s = held.get(lease)
                if s is not None:
                    log.info("lease of item %s %s: stopping it", s.run.item["item_id"] if s.run else "?", why)
                    s.abort(why)

    def _heartbeats(self) -> None:
        while not self.ended.is_set():
            try:
                self.heartbeat()
            except Down as e:
                log.warning("heartbeat: the server is down (%s)", e)
            except Exception:                              # noqa: BLE001
                log.exception("heartbeat failed")
            self.ended.wait(self.hb_every)

    def _outbox(self) -> None:
        while not self.ended.wait(15):
            try:
                if self.outbox.pending():
                    self.outbox.flush()
            except Exception:                              # noqa: BLE001
                log.exception("outbox flush failed")

    def claim(self) -> int:
        idle = [s for s in self.slots if not s.busy]
        busy = len(self.slots) - len(idle)
        want = min(len(idle), self.effective_slots() - busy)
        if want <= 0:
            return 0
        heavy_free = self.heavy_slots - sum(1 for s in self.busy() if s.run and s.run.item.get("heavy"))
        free = self.promise_mb()
        commits = sorted({s.commit for s in self.slots if s.commit})
        code, ans = self.client.call("POST", "/api/pool/claim", {"worker": self.name, "machine": self.machine, "slots": want,
                                                               "free_mb": round(free), "heavy_free": max(0, heavy_free), "commits": commits})
        if code != 200:
            log.error("claim refused (%s): %s", code, ans)
            return 0
        items = ans.get("items") or []
        for it in items:
            pick = next((s for s in idle if s.commit == it["commit"]), None) or next((s for s in idle if s.commit is None), None) or idle[0]
            idle.remove(pick)
            pick.give(it, free)
        return len(items)

    # ---- self-update ----

    def own_changed(self, head: str) -> bool:
        if not self.self_commit:
            return False
        self.repo.ensure(head)
        return any(self.repo.tree(head, p) != self.repo.tree(self.self_commit, p) for p in OWN)

    def check_update(self) -> None:
        code, ans = self.client.call("GET", "/api/pool/code/head")
        head = ans.get("commit") if code == 200 else None
        if not head or head == self.self_commit or head in self.checked_heads:
            return
        self.checked_heads.add(head)
        if self.own_changed(head):
            log.info("the worker's code changed at %s: finishing %d items, then restarting from it", head[:12], len(self.busy()))
            self.update_to = head

    def exec_self(self, sha: str) -> None:
        """Run the supervisor from DIR/self at the commit (this process is replaced)."""
        dest = self.home / "self"
        self.repo.ensure(sha)
        self.repo.checkout(dest, sha)
        py = self.repo.python(dest)
        for s in self.slots:
            s.close()
        self.outbox.flush()
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        env[SELF_ENV] = sha
        os.chdir(dest / PROJECT)
        log.info("restarting from %s at %s", dest, sha[:12])
        logging.shutdown()
        os.execve(str(py), [str(py), "-m", "sdlab.ladder", "worker", *self.argv], env)

    def bootstrap(self) -> None:
        """Started outside DIR/self: move there, at the main line's HEAD (when that commit has the worker)."""
        while not self.stop_now:
            try:
                code, ans = self.client.call("GET", "/api/pool/code/head")
                if code != 200:
                    raise SystemExit(f"the server refused /api/pool/code/head ({code}): {ans}")
                head = ans["commit"]
                self.repo.ensure(head)
                if self.repo.tree(head, f"{POOL_DIR}/worker.py") is None:
                    log.warning("the main line (%s) has no worker yet: running from this checkout", head[:12])
                    return
                self.exec_self(head)
            except Down as e:
                log.warning("bootstrap: the server is down (%s); trying again in 30 s", e)
                time.sleep(30)

    # ---- the loop ----

    def _signal(self, signum, _frame) -> None:
        if self.stopping:
            log.info("second signal: stopping running items and releasing their leases")
            self.stop_now = True
        else:
            log.info("signal %s: no new items; finishing %d running (up to %g s)", signum, len(self.busy()), self.grace)
            self.stopping = time.time()
        self.wake.set()

    def run(self) -> int:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, self._signal)
        lock = open(self.home / "worker.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(f"another worker runs in {self.home}") from None
        lock.write(str(os.getpid()))
        lock.flush()
        if self.self_update and not self.self_commit:
            self.bootstrap()
        log.info("worker %s (%s): %d slots, %d heavy, budget %.0f of %.0f MB, reserve %.0f MB, item processes recycled after %d items,"
                 " over %.0f MB or idle %.0f s, nice %s, yield above load %s, code %s, home %s",
                 self.name, self.machine, self.slots_n, self.heavy_slots, self.budget_mb, self.total_mb, self.reserve_mb, self.recycle_items,
                 slot_mod.recycle_mb(self.budget_mb, self.slots_n, self.recycle_mb), self.child_idle, self.nice,
                 self.yield_load, (self.self_commit or "this checkout")[:12], self.home)
        self.sampler.start()
        self.slots = [Slot(n, self) for n in range(1, self.slots_n + 1)]
        threading.Thread(target=self._heartbeats, daemon=True, name="pool-heartbeat").start()
        threading.Thread(target=self._outbox, daemon=True, name="pool-outbox").start()
        try:
            self.outbox.flush()
        except Exception:                                  # noqa: BLE001
            log.exception("outbox flush failed")
        next_update = time.time() + 5
        while not self.stop_now:
            self.wake.clear()
            if self.stopping:
                if not self.busy() or time.time() - self.stopping > self.grace:
                    break
                self.wake.wait(1)
                continue
            if self.update_to:
                if not self.busy():
                    self.exec_self(self.update_to)
                self.wake.wait(1)
                continue
            got = 0
            try:
                if self.self_update and self.self_commit and time.time() >= next_update:
                    next_update = time.time() + self.update_every
                    self.check_update()
                if not self.update_to:
                    got = self.claim()
            except Down as e:
                log.warning("the server is down (%s)", e)
                self.wake.wait(15)
                continue
            except (CodeError, OSError) as e:
                log.error("%s", e)
            except Exception:                              # noqa: BLE001
                log.exception("the loop failed")
            self.wake.wait(0.2 if got else self.poll)
        return self.shutdown()

    def shutdown(self) -> int:
        for s in self.busy():
            s.abort("shutdown")
        deadline = time.time() + 20
        while self.busy() and time.time() < deadline:
            time.sleep(0.2)
        for s in self.slots:
            s.close()
        self.stop_now = True
        self.ended.set()
        try:
            left = self.outbox.flush()
            self.heartbeat()
        except Down:
            left = len(self.outbox.pending())
        except Exception:                                  # noqa: BLE001
            left = len(self.outbox.pending())
        self.sampler.stop()
        log.info("stopped; %d results wait in the outbox", left)
        return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sdlab-ladder worker", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="http://127.0.0.1:8020")
    ap.add_argument("--slots", type=int, required=True, help="items run at once (one core each)")
    ap.add_argument("--home", default=str(Path.home() / ".sdlab" / "pool" / "worker"), help="its checkouts, caches, outbox, logs")
    ap.add_argument("--max-mem-gb", type=float, help=f"memory its items may hold (default {BUDGET_SHARE * 100:.0f}%% of the machine)")
    ap.add_argument("--reserve-gb", type=float, help="available memory never promised (default max(2 GB, 5%% of the machine))")
    ap.add_argument("--heavy-slots", type=int, default=2, help="heavy items at once")
    ap.add_argument("--yield-load", type=float, help="take fewer slots while the 1-minute load is above this")
    ap.add_argument("--min-slots", type=int, default=0, help="slots kept however high the load")
    ap.add_argument("--nice", type=int, default=19)
    ap.add_argument("--name", help="the worker's name (default <machine>-pool)")
    ap.add_argument("--machine", help="the machine's name (default sdlab.ladder.machines.here())")
    ap.add_argument("--cache", help="the ladder cache whose hash-named parts (data, draws, ...) the slots share (default ~/.cache/sdlab/ladder)")
    ap.add_argument("--grace", type=float, default=600, help="seconds running items may take to finish after SIGTERM")
    ap.add_argument("--heartbeat", type=float, default=30)
    ap.add_argument("--poll", type=float, default=3, help="seconds between claims when idle")
    ap.add_argument("--update-every", type=float, default=120, help="seconds between checks for a new worker")
    ap.add_argument("--recycle-items", type=int, default=slot_mod.RECYCLE_ITEMS, help="restart a slot's item process after this many items")
    ap.add_argument("--recycle-gb", type=float, help="restart it when it holds more than this after an item (default max(%.1f GB, %g x the slot's"
                    " share of the budget))" % (slot_mod.RECYCLE_MIN_MB / 1024, slot_mod.RECYCLE_SHARE))
    ap.add_argument("--child-idle-minutes", type=float, default=slot_mod.CHILD_IDLE / 60, help="stop an item process idle this long")
    ap.add_argument("--no-self-update", action="store_true", help="run from this checkout, never DIR/self")
    return ap


def main(argv: list[str]) -> int:
    a = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    return Worker(a, argv).run()
