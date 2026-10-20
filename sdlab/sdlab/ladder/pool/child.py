"""A slot's item process: the slot checkout's own python (its venv) running SNIPPET, which imports that
commit's ladder and runs items one at a time, as today's runs do in their worker processes
(`runner.run_item`, one numpy/BLAS/numba thread, XLA_FLAGS for JAX). The snippet uses only what every
commit's runner has (select_strategies, plan, run_item), so a job at an older commit runs that commit's
code, not the supervisor's.

Protocol: one JSON object per line. The supervisor writes items on stdin; the process answers on the
stdout it had at start (anything the code prints goes to stderr, the slot's log):

    {"ready": true, "pid": n}
    {"event": "start", "item_id", "hashes": {case_hash, strategy_hash, score_hash}, "match": bool}
    {"event": "done",  "item_id", "hashes", "row" (None when the hashes differ: not run), "hwm_mb", "maxrss_mb", "rss_mb"}
    {"event": "error", "item_id", "error"}       the item could not be planned at this commit

hashes are this checkout's own plan of the item (`runner.plan(force=True)`); an item whose promised hashes
differ is not run. A re-score is given the stored result's flows (`prev`) in place of the store, which a
worker never has. On Linux the process resets its peak RSS (/proc/self/clear_refs) before each item and
reports VmHWM after it. It exits when stdin closes or when its parent (the supervisor) is gone.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

THREAD_ENV = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1",
              "NUMBA_NUM_THREADS": "1", "XLA_FLAGS": "--xla_cpu_multi_thread_eigen=false intra_op_parallelism_threads=1"}

SNIPPET = r'''
import json, os, sys, threading, time, traceback, resource
proto = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)
sys.stdout = sys.stderr
_ppid = os.getppid()
def _orphan():
    while True:
        time.sleep(2)
        if os.getppid() != _ppid:
            os._exit(3)
threading.Thread(target=_orphan, daemon=True).start()
from sdlab.ladder import runner, store
LINUX = sys.platform.startswith("linux")
def _status(key):
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(key + ":"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        return None
def _reset():
    try:
        with open("/proc/self/clear_refs", "w") as f:
            f.write("5")
        return True
    except OSError:
        return False
def _maxrss():
    m = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return m / 1024.0 if LINUX else m / 1048576.0
def send(**m):
    proto.write(json.dumps(m, default=str) + "\n")
HASHES = ("case_hash", "strategy_hash", "score_hash")
_planned = {}
def hashes(case, variant, strategy):
    key = (case, variant, strategy)
    if key not in _planned:
        avail, skipped = runner.select_strategies(strategy)
        s = next((x for x in avail if x["name"] == strategy), None)
        if s is None:
            why = next((x.get("reason") for x in skipped if x["name"] == strategy), None)
            raise RuntimeError("strategy %s is not available at this commit%s" % (strategy, ": %s" % why if why else ""))
        got = [p for p in runner.plan([case], [s], [variant], force=True) if p["variant"] == variant]
        if not got:
            raise RuntimeError("%s has no variant %s at this commit" % (case, variant))
        _planned[key] = {k: got[0][k] for k in HASHES}
    return _planned[key]
send(ready=True, pid=os.getpid())
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    iid = msg.get("item_id")
    try:
        h = hashes(msg["case"], msg["variant"], msg["strategy"])
    except BaseException as e:
        send(event="error", item_id=iid, error=("%s: %s" % (type(e).__name__, e))[:1500])
        continue
    promised = msg.get("promised") or {}
    match = all(h[k] == promised.get(k) for k in HASHES)
    send(event="start", item_id=iid, hashes=h, match=match)
    if not match:
        send(event="done", item_id=iid, hashes=h, row=None)
        continue
    prev = msg.get("prev")
    mode = msg.get("mode") or "run"
    if mode == "rescore" and not prev:
        mode = "run"                                   # no stored flows to score again: run it (the same hashes)
    item = {"case": msg["case"], "variant": msg["variant"], "strategy": msg["strategy"], **h, "mode": mode}
    latest = store.latest
    if mode == "rescore":
        store.latest = lambda *a, **k: [prev]
    reset = LINUX and _reset()
    try:
        row = runner.run_item(item, float(msg.get("timeout") or 300))
    except BaseException:
        row = {**{k: item[k] for k in ("case", "variant", "strategy", *HASHES)}, "status": "error",
               "error": " ".join(traceback.format_exc().strip().splitlines()[-3:])[:2000]}
    finally:
        store.latest = latest
    send(event="done", item_id=iid, hashes=h, row=row, hwm_mb=_status("VmHWM") if reset else None,
         maxrss_mb=_maxrss(), rss_mb=_status("VmRSS"))
'''


class ChildError(Exception):
    pass


class Child:
    """One item process of a slot (started at the slot's commit; stopped when the slot moves)."""

    def __init__(self, python: Path, cwd: Path, env: dict, nice: int, log: Path):
        self.python, self.cwd, self.env, self.nice, self.log = python, cwd, env, nice, log
        self.proc: subprocess.Popen | None = None
        self.events: queue.Queue = queue.Queue()
        self.pid: int | None = None
        self.items = 0
        self.fresh = True                                       # no item run yet: its ru_maxrss is the item's own

    def start(self, timeout: float = 600) -> None:
        self.log.parent.mkdir(parents=True, exist_ok=True)
        logf = open(self.log, "ab")
        cmd = ([ "nice", "-n", str(self.nice)] if self.nice else []) + [str(self.python), "-u", "-c", SNIPPET]
        self.proc = subprocess.Popen(cmd, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=logf,
                                     start_new_session=True)
        logf.close()
        threading.Thread(target=self._read, daemon=True, name=f"pool-child-{self.proc.pid}").start()
        ev = self.next(timeout)
        if not ev or not ev.get("ready"):
            self.kill()
            raise ChildError(f"the item process did not start: {self.tail()}")
        self.pid = int(ev["pid"])

    def _read(self) -> None:
        assert self.proc and self.proc.stdout
        for raw in self.proc.stdout:
            try:
                self.events.put(json.loads(raw))
            except ValueError:
                pass
        self.events.put(None)                                   # EOF: the process is gone

    def next(self, timeout: float) -> dict | None | bool:
        """The next event; None: the process ended; False: nothing within timeout."""
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return False

    def send(self, msg: dict) -> None:
        assert self.proc and self.proc.stdin
        try:
            self.proc.stdin.write((json.dumps(msg, default=str) + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass                                                # it died: next() says so
        self.items += 1

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def exit_how(self) -> str:
        if self.proc is None:
            return "not started"
        try:
            rc = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return "still running"
        if rc < 0:
            import signal
            name = signal.Signals(-rc).name if -rc in signal.Signals._value2member_map_ else str(-rc)
            return f"killed by {name}" + (" (the OOM killer, or a kill -9)" if -rc == 9 else "")
        return f"exited with code {rc}"

    def kill(self) -> None:
        if self.proc is None:
            return
        try:
            os.killpg(self.proc.pid, 9)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def stop(self) -> None:
        """Close its stdin (it exits after the item it is on), then kill it if it lingers."""
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        deadline = time.time() + 5
        while time.time() < deadline and self.proc.poll() is None:
            time.sleep(0.1)
        if self.proc.poll() is None:
            self.kill()

    def tail(self, n: int = 1200) -> str:
        try:
            return self.log.read_bytes()[-n:].decode(errors="replace").strip()
        except OSError:
            return ""
