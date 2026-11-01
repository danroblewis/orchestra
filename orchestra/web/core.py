"""Core: Orchestra's fundamental services, for the Core page.

The Core page must keep working when the rest of Orchestra does not: when the system dynamics
model is broken or every other machine is down. So this module
imports only the event bus, the metrics store and the runtime record; each component is probed in
its own single worker (``Lane``) with a time limit, at most one probe in flight per component, so a
failure or a hang shows on that component's card instead of taking the page, or the other
components' probes, down.

Components:
- **bootstrap host**: the ``orchestra run`` process (Orchestra's own machine) and this web process;
- **event bus**: reads the stream's end and latest events; ``write_probe`` appends an
  ``orchestra.core.bus_probe`` event and reads it back by offset;
- **metrics store**: writes the probe's own measurements as ``orchestra_core_*`` series and reads
  them back until they are visible, so every probe proves the write and the read path.

Logs: the bootstrap host's log file, a core log kept in this process (component state changes,
errors, probe writes), the event stream's tail, and the logs of the processes the host launches
(`orchestra/launcher.py`, read by `process_logs`: by name, bounded, within the state directory or
the repository, under the same time limit)."""

from __future__ import annotations

import collections
import json
import os
import platform
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import datetime
from pathlib import Path

import psutil

from .. import __version__, runtime
from ..config import Project
from ..events import Events, event_time
from ..metrics import MetricsStore, Point
from ..metrics import for_project as metrics_for
from . import process_logs

INTERVAL = 5.0          # seconds between probes, however many browsers poll
TIMEOUT = 4.0           # seconds a component may take before it is reported as timed out
CORE = "orchestra_core"
STARTED = time.time()


def redact(url: str | None) -> str:
    """A URL without its password, for display."""
    if not url or "://" not in url:
        return url or "file"
    p = urllib.parse.urlsplit(url)
    netloc = p.hostname or ""
    if p.port:
        netloc += f":{p.port}"
    if p.username:
        netloc = f"{p.username}:•••@{netloc}"
    return urllib.parse.urlunsplit((p.scheme, netloc, p.path, p.query, ""))


def rate_over(window: float, sampled: int, events: int) -> str:
    """What the bus card's rate is over, as observed: ten minutes, or the shorter span the sample
    covers (a young bus, or a busy one whose last ``sampled`` events took less)."""
    if window >= 600:
        return "over the last 10 min"
    span = f"{round(window / 60)} min" if window >= 90 else f"{round(window)} s"
    why = "the whole bus" if sampled >= events else f"its last {sampled} events"
    return f"over the last {span} ({why})"


def _ts(ev: dict) -> float | None:
    return event_time(ev)


def _proc(pid) -> dict:
    try:
        p = psutil.Process(int(pid))
        if p.status() == psutil.STATUS_ZOMBIE:
            return {"pid": pid, "alive": False}
        return {"pid": pid, "alive": True, "since": p.create_time(), "rss": p.memory_info().rss,
                "cpu": p.cpu_percent(interval=None), "threads": p.num_threads()}
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return {"pid": pid, "alive": False}


def _tail(path: Path, lines: int) -> list[str]:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200 * lines))
            return f.read().decode("utf-8", "replace").splitlines()[-lines:]
    except OSError:                                       # missing or unreadable: no lines, never an error
        return []


class Lane:
    """One component's probe: a worker of its own, and at most one call in flight. While a call is
    still running (a hung store), the next asks get its last result marked as still waiting rather
    than queueing another call behind it, so a hang holds one thread, never the others' workers."""

    def __init__(self, name: str):
        self.name = name
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"core-{name}")
        self._lock = threading.Lock()
        self._fut = None
        self._since: float | None = None
        self.last: dict | None = None

    def start(self, fn, *args):
        """Submit ``fn``, or return None when the previous call has not returned yet."""
        with self._lock:
            if self._fut is not None and not self._fut.done():
                return None
            self._since = time.time()
            self._fut = self._pool.submit(fn, *args)
            self._fut.add_done_callback(self._keep)
            return self._fut

    def _keep(self, fut) -> None:
        if not fut.cancelled() and fut.exception() is None and isinstance(fut.result(), dict):
            self.last = fut.result()

    def waiting(self) -> dict:
        since = datetime.fromtimestamp(self._since or time.time()).strftime("%H:%M:%S")
        return {**(self.last or {}), "ok": False, "waiting_since": self._since,
                "error": f"still waiting since {since}: the probe started then has not returned"}

    def wait(self, fut, timeout: float):
        """The call's result within ``timeout`` (raises ``FutureTimeout`` or the call's error), or
        the still-waiting answer when ``fut`` is None."""
        if fut is None:
            return self.waiting()
        return fut.result(timeout=max(0.0, timeout))

    def run(self, fn, *args, timeout: float):
        return self.wait(self.start(fn, *args), timeout)


class CoreProbe:
    def __init__(self, project: Project, events: Events):
        self.project = project
        self.events = events
        self.metrics: MetricsStore | None = None
        self._lock = threading.Lock()
        self._last: dict | None = None
        self._at = 0.0
        # one lane per component, so a hung store never starves another component's probe
        self._lanes = {name: Lane(name) for name in ("host", "bus", "metrics", "bus-write", "events-log", "process-log")}
        self.log: collections.deque = collections.deque(maxlen=500)
        self._state: dict[str, bool] = {}
        try:
            self.metrics = metrics_for(project)
        except Exception as e:  # noqa: BLE001 - a bad metrics URL must not stop the page
            self._note("metrics", f"cannot open the metrics store: {type(e).__name__}: {e}", level="error")

    def _note(self, component: str, msg: str, level: str = "info") -> None:
        self.log.append({"t": time.time(), "component": component, "level": level, "msg": msg})

    def _record(self, component: str, out: dict) -> dict:
        ok = bool(out.get("ok"))
        if self._state.get(component) != ok:
            self._note(component, "ok" if ok else f"failing: {out.get('error', '')}", "info" if ok else "error")
            self._state[component] = ok
        return out

    def _labels(self, **kw) -> dict[str, str]:
        return {"project": self.project.key, **kw}

    def _processes(self, record: dict) -> list[dict]:
        """What the host's launcher keeps running (orchestra/launcher.py), as it recorded them."""
        out = []
        for name, r in sorted((record.get("processes") or {}).items()):
            out.append({"name": name, "state": r.get("state"), "owner": r.get("owner"), "restarts": r.get("restarts", 0),
                        "code": r.get("code"), "command": r.get("command") or [],
                        **(_proc(r["pid"]) if r.get("pid") else {"alive": False}), "since": r.get("since"),
                        "log_error": process_logs.hint(name, self.project.logs_dir, self._roots())})
        return out

    def _roots(self) -> list[Path]:
        return [self.project.state_dir, self.project.repo_root]

    def _host(self) -> dict:
        record = runtime.read(self.project)
        launching = runtime.launcher(record)                   # the host that keeps the processes
        rec = launching or next(iter(runtime.hosts(record)), None) or {}
        loop = _proc(rec.get("pid")) if rec.get("pid") else {"alive": False}
        loop["since"] = rec.get("since", loop.get("since"))
        collector = ((record.get("hosts") or {}).get(str(rec.get("pid"))) or {}).get("collector") if loop.get("alive") else None
        log = self.project.logs_dir / "orchestra-host.log"
        last = _tail(log, 1)
        me = _proc(os.getpid())
        commit = None
        try:
            head = Path(__file__).resolve().parents[2] / ".git" / "HEAD"
            ref = head.read_text().strip()
            commit = (head.parent / ref[5:]).read_text().strip()[:10] if ref.startswith("ref: ") else ref[:10]
        except OSError:
            pass
        return {"ok": True, "loop": loop, "web": {**me, "since": STARTED}, "version": __version__, "commit": commit,
                "python": f"{platform.python_implementation()} {sys.version.split()[0]}",
                "project": self.project.key, "repo": str(self.project.repo_root), "state": str(self.project.state_dir),
                "host_log": str(log), "host_log_last": last[0] if last else None,
                "processes": self._processes(record) if launching else [], "collector": collector}

    def _bus(self) -> dict:
        bus = self.events.bus
        url = os.environ.get("ORCHESTRA_EVENTS_URL") or self.project.config.events_url or "file"
        out = {"backend": bus.name, "url": redact(url if bus.name != "file" else str(self.project.events_file)),
               "stream": getattr(bus, "_key", None) or getattr(bus, "_queue", None) or getattr(bus, "_topic", None)
               or "events.jsonl", "ok": True}
        t0 = time.perf_counter()
        end = bus.end()
        recent, _ = bus.read(max(0, end - 200), limit=200)
        out["read_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["events"] = end
        stamps = [t for t in (_ts(e) for e in recent) if t]
        now = time.time()
        # over the last ten minutes, or over what the sample spans when that is shorter (a minute at
        # least): a young bus, or one whose last 200 events took under ten minutes, is not divided by
        # ten, and the card says the window it observed
        recent_stamps = [t for t in stamps if t >= now - 600]
        window = max(60.0, min(600.0, now - min(stamps))) if stamps else 600.0
        out["per_min_10m"] = round(len(recent_stamps) / (window / 60), 2)
        out["rate_window_s"] = round(window)
        out["rate_over"] = rate_over(window, sampled=len(recent), events=end)
        out["last_event"] = ({"type": recent[-1].get("type"), "age_s": round(now - stamps[-1], 1)} if recent and stamps else None)
        types: dict[str, int] = {}
        for e in recent[-50:]:
            types[e.get("type", "?")] = types.get(e.get("type", "?"), 0) + 1
        out["recent_types"] = sorted(types.items(), key=lambda x: -x[1])[:6]
        return out

    def _metrics(self, bus: dict) -> dict:
        m = self.metrics
        if m is None:
            return {"ok": False, "error": "the metrics store could not be opened"}
        url = os.environ.get("ORCHESTRA_METRICS_URL") or self.project.config.metrics_url or "file"
        out = {"backend": m.name, "url": redact(url if m.name != "file" else str(self.project.state_dir / "metrics.jsonl")), "ok": True}
        now = time.time()
        pts = [Point(f"{CORE}_probe", 1.0, now, self._labels())]          # the point read back below
        if bus:
            pts += [Point(f"{CORE}_bus_read_ms", bus.get("read_ms", 0.0), now, self._labels()),
                    Point(f"{CORE}_bus_events", float(bus.get("events", 0)), now, self._labels())]
        t0 = time.perf_counter()
        m.write(pts)
        out["write_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        # read it back until it is visible (VictoriaMetrics indexes new points within about a
        # second); how long that took is itself a measure of the store
        t0 = time.perf_counter()
        back, t_read = None, t0
        while time.perf_counter() - t0 < 3.0:
            t_read = time.perf_counter()
            back = m.latest(f"{CORE}_probe", self._labels())
            if back and abs(back[0] - now) < 0.01:
                break
            time.sleep(0.05)
        out["read_ms"] = round((time.perf_counter() - t_read) * 1000, 1)
        out["visible_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["round_trip_ok"] = bool(back and abs(back[0] - now) < 0.01)
        m.write([Point(f"{CORE}_metrics_write_ms", out["write_ms"], now, self._labels()),
                 Point(f"{CORE}_metrics_read_ms", out["read_ms"], now, self._labels()),
                 Point(f"{CORE}_metrics_visible_ms", out["visible_ms"], now, self._labels())])
        mine = m.series("", {"project": self.project.key})
        out["series"] = len(mine)
        spark = {}
        for key in ("bus_read_ms", "bus_events", "metrics_write_ms", "metrics_read_ms", "metrics_visible_ms"):
            spark[key] = [[round(t), v] for t, v in m.raw(f"{CORE}_{key}", self._labels(), now - 900, now + 1)]
        out["spark"] = spark
        if not out["round_trip_ok"]:
            out.update(ok=False, error="a point written was not readable within 3 s")
        return out

    def _start(self, component: str, fn, *args):
        return self._lanes[component].start(fn, *args)

    def _finish(self, component: str, fut, deadline: float) -> dict:
        lane = self._lanes[component]
        try:
            return self._record(component, lane.wait(fut, deadline - time.monotonic()))
        except FutureTimeout:
            return self._record(component, {"ok": False, "error": f"timed out after {TIMEOUT:g} s"})
        except Exception as e:  # noqa: BLE001 - shown on the page
            return self._record(component, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def _guarded(self, component: str, fn, *args) -> dict:
        deadline = time.monotonic() + TIMEOUT
        return self._finish(component, self._start(component, fn, *args), deadline)

    def status(self) -> dict:
        with self._lock:
            if self._last is None or time.time() - self._at >= INTERVAL:
                # all three at once, each in its own lane, so the slowest bounds the wait; the
                # metrics probe records the previous bus reading rather than waiting for this one
                prev_bus = (self._last or {}).get("bus") or {}
                deadline = time.monotonic() + TIMEOUT
                host = self._start("host", self._host)
                bus = self._start("bus", self._bus)
                met = self._start("metrics", self._metrics, prev_bus if prev_bus.get("ok") else {})
                self._last = {"host": self._finish("host", host, deadline), "bus": self._finish("bus", bus, deadline),
                              "metrics": self._finish("metrics", met, deadline),
                              "probed_at": time.time(), "interval": INTERVAL, "timeout": TIMEOUT}
                self._at = time.time()
            return self._last

    def write_probe(self) -> dict:
        """Append a probe event to the real stream and read it back by its offset."""
        def go():
            bus = self.events.bus
            t0 = time.perf_counter()
            before = bus.end()
            ev = self.events.publish("orchestra.core.bus_probe", {"note": "core page test write"})
            t1 = time.perf_counter()
            got, end = bus.read(before, limit=max(1, min(1000, bus.end() - before)))
            t2 = time.perf_counter()
            found = any(e.get("id") == ev["id"] for e in got)
            return {"ok": found, "offset": before, "end": end, "append_ms": round((t1 - t0) * 1000, 1),
                    "read_back_ms": round((t2 - t1) * 1000, 1), "backend": bus.name}
        out = self._guarded("bus-write", go)
        self._note("bus", f"test write: {'appended at offset ' + str(out.get('offset')) + ' and read back' if out.get('ok') else 'failed: ' + str(out.get('error'))}",
                   "info" if out.get("ok") else "error")
        return out

    def log_sources(self) -> list[dict]:
        out = [{"id": "host", "name": "Orchestra host (bootstrap)"}, {"id": "core", "name": "Core"},
               {"id": "events", "name": "Event stream"}]
        running = set(runtime.read(self.project).get("processes") or {})
        out += [{"id": f"process:{name}", "name": name if name in running else f"{name} (not running now)",
                 "process": name, "running": name in running,
                 "error": process_logs.hint(name, self.project.logs_dir, self._roots())}
                for name in sorted(running | set(process_logs.names(self.project.logs_dir)))]
        return out

    def process_log(self, name: str, lines: int = 200) -> dict:
        """A launched process's log tail (``process_logs.read``), within the time limit."""
        try:
            return self._lanes["process-log"].run(process_logs.read, name, self.project.logs_dir, self._roots(), lines, timeout=TIMEOUT)
        except FutureTimeout:
            return {"name": name, "lines": [], "more": False, "error": None, "note": f"reading the log timed out after {TIMEOUT:g} s"}
        except Exception as e:  # noqa: BLE001 - shown on the page
            return {"name": name, "lines": [], "more": False, "error": None, "note": f"{type(e).__name__}: {e}"}

    def logs(self, source: str, lines: int = 200) -> dict:
        lines = max(10, min(lines, 2000))
        if source == "host":
            path = self.project.logs_dir / "orchestra-host.log"
            text = _tail(path, lines)
            return {"source": source, "lines": text, "note": None if text else f"No host log yet: {path} is written by `orchestra run` from this version on."}
        if source == "core":
            return {"source": source, "lines": [f"{datetime.fromtimestamp(x['t']).strftime('%H:%M:%S')} {x['level']:<5} {x['component']:<8} {x['msg']}"
                                                for x in list(self.log)[-lines:]]}
        if source == "events":
            def go():
                bus = self.events.bus
                end = bus.end()
                evs, _ = bus.read(max(0, end - lines), limit=lines)
                return [json.dumps(e, ensure_ascii=False)[:400] for e in evs]
            try:
                got = self._lanes["events-log"].run(go, timeout=TIMEOUT)
                if isinstance(got, dict):                  # the previous read is still running
                    return {"source": source, "lines": [], "note": f"the event bus did not answer: {got['error']}"}
                return {"source": source, "lines": got}
            except Exception as e:  # noqa: BLE001
                return {"source": source, "lines": [], "note": f"the event bus did not answer: {type(e).__name__}: {e}"}
        if source.startswith("process:"):
            # the path the launcher writes, found by name, not the record's, so the record cannot name any file
            return {"source": source, **self.process_log(source.partition(":")[2], lines)}
        return {"source": source, "lines": [], "note": "unknown log source"}
