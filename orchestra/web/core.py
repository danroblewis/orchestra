"""The core services the dashboard shows: the event bus and the metrics store.

Each probe exercises the real backend rather than reporting configuration:
- the bus probe reads the stream's end and its latest events (read latency, event rate, the last
  write's age); ``write_probe`` appends a ``bus_probe`` event and reads it back by offset;
- the metrics probe writes the probe's own measurements into the store as ``orchestra_core_*``
  series and reads them back, so every poll proves the write path and the read path, and the
  dashboard's sparklines are drawn from what the store returned.

Probes run at most every ``INTERVAL`` seconds however many browsers poll."""

from __future__ import annotations

import os
import threading
import time
import urllib.parse
from datetime import datetime

from ..config import Project
from ..events import Events
from ..metrics import MetricsStore, Point
from ..metrics import for_project as metrics_for

INTERVAL = 5.0
CORE = "orchestra_core"


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


def _ts(ev: dict) -> float | None:
    try:
        return datetime.fromisoformat(ev["ts"]).timestamp()
    except (KeyError, ValueError):
        return None


class CoreProbe:
    def __init__(self, project: Project, events: Events):
        self.project = project
        self.events = events
        self.metrics: MetricsStore = metrics_for(project)
        self._lock = threading.Lock()
        self._last: dict | None = None
        self._at = 0.0

    def _labels(self, **kw) -> dict[str, str]:
        return {"project": self.project.key, **kw}

    def _bus(self) -> dict:
        bus = self.events.bus
        url = os.environ.get("ORCHESTRA_EVENTS_URL") or self.project.config.events_url or "file"
        out = {"backend": bus.name, "url": redact(url if bus.name != "file" else str(self.project.events_file)),
               "stream": getattr(bus, "_key", None) or getattr(bus, "_queue", None) or getattr(bus, "_topic", None)
               or "events.jsonl", "ok": True}
        try:
            t0 = time.perf_counter()
            end = bus.end()
            recent, _ = bus.read(max(0, end - 200), limit=200)
            out["read_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            out["events"] = end
            stamps = [t for t in (_ts(e) for e in recent) if t]
            now = time.time()
            out["per_min_10m"] = round(sum(1 for t in stamps if t >= now - 600) / 10, 2)
            out["last_event"] = ({"type": recent[-1].get("type"), "age_s": round(now - stamps[-1], 1)} if recent and stamps else None)
            types: dict[str, int] = {}
            for e in recent[-50:]:
                types[e.get("type", "?")] = types.get(e.get("type", "?"), 0) + 1
            out["recent_types"] = sorted(types.items(), key=lambda x: -x[1])[:6]
        except Exception as e:  # noqa: BLE001 - shown on the dashboard
            out.update(ok=False, error=f"{type(e).__name__}: {e}")
        return out

    def _metrics(self, bus: dict) -> dict:
        m = self.metrics
        url = os.environ.get("ORCHESTRA_METRICS_URL") or self.project.config.metrics_url or "file"
        out = {"backend": m.name, "url": redact(url if m.name != "file" else str(self.project.state_dir / "metrics.jsonl")), "ok": True}
        now = time.time()
        try:
            pts = [Point(f"{CORE}_bus_read_ms", bus.get("read_ms", 0.0), now, self._labels()),
                   Point(f"{CORE}_bus_events", float(bus.get("events", 0)), now, self._labels())]
            t0 = time.perf_counter()
            m.write(pts)
            out["write_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            # read it back until it is visible (VictoriaMetrics indexes new points within about a
            # second); how long that took is itself a measure of the store
            t0 = time.perf_counter()
            back, reads = None, 0
            while time.perf_counter() - t0 < 3.0:
                t_read = time.perf_counter()
                back = m.latest(f"{CORE}_bus_events", self._labels())
                reads += 1
                if back and abs(back[0] - now) < 0.01:
                    break
                time.sleep(0.05)
            out["read_ms"] = round((time.perf_counter() - t_read) * 1000, 1)
            out["visible_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            out["round_trip_ok"] = bool(back and abs(back[0] - now) < 0.01)
            m.write([Point(f"{CORE}_metrics_write_ms", out["write_ms"], now, self._labels()),
                     Point(f"{CORE}_metrics_read_ms", out["read_ms"], now, self._labels()),
                     Point(f"{CORE}_metrics_visible_ms", out["visible_ms"], now, self._labels())])
            series = m.series()
            mine = [s for s in series if s[1].get("project") == self.project.key]
            out["series"] = len(mine)
            out["series_kinds"] = sorted({n for n, _ in mine})
            spark = {}
            for key, name in (("bus_read_ms", f"{CORE}_bus_read_ms"), ("bus_events", f"{CORE}_bus_events"),
                              ("metrics_write_ms", f"{CORE}_metrics_write_ms"), ("metrics_read_ms", f"{CORE}_metrics_read_ms"),
                              ("metrics_visible_ms", f"{CORE}_metrics_visible_ms")):
                spark[key] = [[round(t), v] for t, v in m.raw(name, self._labels(), now - 900, now + 1)]
            out["spark"] = spark
        except Exception as e:  # noqa: BLE001 - shown on the dashboard
            out.update(ok=False, error=f"{type(e).__name__}: {e}")
        return out

    def status(self) -> dict:
        with self._lock:
            if self._last is None or time.time() - self._at >= INTERVAL:
                bus = self._bus()
                self._last = {"bus": bus, "metrics": self._metrics(bus), "probed_at": time.time()}
                self._at = time.time()
            return self._last

    def write_probe(self) -> dict:
        """Append a probe event to the real stream and read it back by its offset."""
        bus = self.events.bus
        t0 = time.perf_counter()
        before = bus.end()
        ev = self.events.emit("bus_probe", note="dashboard test write")
        t1 = time.perf_counter()
        got, end = bus.read(before, limit=end_guard(bus, before))
        t2 = time.perf_counter()
        found = next((e for e in got if e.get("type") == "bus_probe" and e.get("ts") == ev["ts"]), None)
        return {"ok": found is not None, "offset": before, "end": end, "append_ms": round((t1 - t0) * 1000, 1),
                "read_back_ms": round((t2 - t1) * 1000, 1), "backend": bus.name}


def end_guard(bus, before: int) -> int:
    """How many events to read back after a probe write: everything since ``before``, bounded."""
    return max(1, min(1000, bus.end() - before))
