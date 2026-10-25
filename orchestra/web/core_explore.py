"""Core page explorers: the metrics store's catalogue and queries, and the event bus's event types,
volumes and emitters.

Like the rest of Core (web/core.py), this reads only the metrics store and the event bus, never
the model, the ticket store or the machines, and every call runs under Core's time limit, so a
slow or broken backend shows as an error on its panel instead of hanging the page."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from itertools import pairwise

from ..metrics import step_sample

RESIDENT = {"supervisor": "supervisor", "coordinator": "coordinator", "pipeline-manager": "pipeline-manager"}
CACHE_S = 20.0


def _ts(ev: dict) -> float | None:
    try:
        return datetime.fromisoformat(ev["ts"]).timestamp()
    except (KeyError, ValueError, TypeError):
        return None


def emitter(ev: dict) -> str:
    """Which machine an event came from, from what the event itself says. An agent's tool call
    names it (``by``); a session event names its session; everything else the loop emitted, so it
    belongs to the bootstrap host."""
    who = ev.get("by") or ev.get("author")
    if who and who != "orchestra":
        return str(who).replace("_", "-")
    sess = ev.get("session") or ""
    if sess in RESIDENT:
        return RESIDENT[sess]
    for prefix in ("worker", "reviewer"):
        if sess.startswith(prefix + "-") and ev["type"] not in ("session_started", "session_settled"):
            return prefix
    return "orchestra-host"


class Explorer:
    def __init__(self, core):
        self.core = core                    # CoreProbe: project, events, metrics, the guarded pool
        self._cache: dict[str, tuple[float, object]] = {}

    def _cached(self, key: str, fn):
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < CACHE_S:
            return hit[1]
        val = fn()
        self._cache[key] = (time.time(), val)
        return val

    def _guard(self, fn, *args) -> dict:
        try:
            return self.core._pool.submit(fn, *args).result(timeout=self.core_timeout())
        except Exception as e:  # noqa: BLE001 - shown on the panel
            return {"ok": False, "error": f"{type(e).__name__}: {e}" if str(e) else f"timed out after {self.core_timeout():g} s"}

    @staticmethod
    def core_timeout() -> float:
        return 8.0

    # ---- metrics ----
    def _dump(self):
        m = self.core.metrics
        if m is None:
            raise RuntimeError("the metrics store could not be opened")
        return self._cached("dump", lambda: m.dump("orchestra_", {"project": self.core.project.key}))

    def catalog(self) -> dict:
        def go():
            now = time.time()
            dump = self._dump()
            names: dict[str, dict] = {}
            hourly = Counter()
            for name, labels, pts in dump:
                d = names.setdefault(name, {"name": name, "series": 0, "points": 0, "labels": defaultdict(set),
                                            "first": None, "last": None, "last_hour": 0, "last_day": 0})
                d["series"] += 1
                d["points"] += len(pts)
                for k, v in labels.items():
                    d["labels"][k].add(v)
                if pts:
                    d["first"] = pts[0][0] if d["first"] is None else min(d["first"], pts[0][0])
                    d["last"] = pts[-1][0] if d["last"] is None else max(d["last"], pts[-1][0])
                for t, _ in pts:
                    if t >= now - 86400:
                        d["last_day"] += 1
                        hourly[int((t - (now - 86400)) // 3600)] += 1
                        if t >= now - 3600:
                            d["last_hour"] += 1
            rows = [{**d, "labels": {k: {"arity": len(v), "values": sorted(v)[:12]} for k, v in sorted(d["labels"].items())}}
                    for d in sorted(names.values(), key=lambda x: x["name"])]
            return {"ok": True, "backend": self.core.metrics.name, "project": self.core.project.key, "metrics": rows, "series": sum(r["series"] for r in rows),
                    "points": sum(r["points"] for r in rows),
                    "writes_per_hour_24h": [[now - 86400 + h * 3600, hourly.get(h, 0)] for h in range(24)]}
        return self._guard(go)

    def query(self, metric: str, match: str, hours: float, step_s: float, agg: str) -> dict:
        def go():
            want = dict(kv.split("=", 1) for kv in [x.strip() for x in match.split(",")] if "=" in kv)
            now = time.time()
            start = now - hours * 3600 if hours > 0 else None
            sel = [(n, lab, pts) for n, lab, pts in self._dump() if n == metric and all(lab.get(k) == v for k, v in want.items())]
            if not sel:
                return {"ok": True, "lines": [], "note": "no series match"}
            all_t = [t for _, _, pts in sel for t, _ in pts]
            t0 = start if start is not None else min(all_t)
            t0 -= t0 % step_s
            hide = {"project"} if len({lab.get("project") for _, lab, _ in sel}) == 1 else set()
            lines = []
            for _, lab, pts in sel:
                stepped = step_sample(pts, t0, now, step_s)
                if agg == "rate":           # a counter's increase per hour in each step
                    stepped = [(t, max(0.0, v - pv) * 3600 / step_s) for (_, pv), (t, v) in pairwise(stepped)]
                elif agg == "raw":
                    stepped = [(t, v) for t, v in pts if t >= t0]
                if agg == "rate" and not any(v for _, v in stepped):
                    continue                # a counter that did not move in range says nothing here
                key = ",".join(f"{k}={v}" for k, v in sorted(lab.items()) if k not in hide) or metric
                lines.append({"label": key, "points": [[round(t), v] for t, v in stepped]})
            if agg == "sum" and lines:
                acc: dict[float, float] = defaultdict(float)
                for ln in lines:
                    for t, v in ln["points"]:
                        acc[t] += v
                lines = [{"label": f"sum of {len(sel)} series", "points": [[t, acc[t]] for t in sorted(acc)]}]
            moving = len(lines)
            lines = lines[:30]
            return {"ok": True, "lines": lines, "matched": len(sel), "moving": moving, "shown": len(lines)}
        return self._guard(go)

    def promql(self, query: str, hours: float, step_s: float) -> dict:
        def go():
            m = self.core.metrics
            if m is None or m.name != "victoriametrics":
                return {"ok": False, "error": "PromQL needs the VictoriaMetrics backend"}
            now = time.time()
            params = urllib.parse.urlencode({"query": query, "start": now - hours * 3600, "end": now, "step": f"{int(step_s)}s"})
            try:
                with urllib.request.urlopen(f"{m.base}/api/v1/query_range?{params}", timeout=8) as r:
                    d = json.loads(r.read())
            except urllib.error.HTTPError as e:      # VictoriaMetrics explains a bad query in the body
                try:
                    return {"ok": False, "error": json.loads(e.read()).get("error", str(e))}
                except ValueError:
                    return {"ok": False, "error": str(e)}
            if d.get("status") != "success":
                return {"ok": False, "error": d.get("error", "query failed")}
            lines = [{"label": ",".join(f"{k}={v}" for k, v in sorted(res["metric"].items()) if k != "project") or query,
                      "points": [[float(t), float(v)] for t, v in res["values"]]} for res in d["data"]["result"][:30]]
            return {"ok": True, "lines": lines, "matched": len(d["data"]["result"])}
        return self._guard(go)

    # ---- events ----
    def _events(self):
        def read():
            bus = self.core.events.bus
            end = bus.end()
            evs, _ = bus.read(0, limit=min(end, 300_000))
            return evs
        return self._cached("events", read)

    def events(self, hours: float) -> dict:
        def go():
            now = time.time()
            since = now - hours * 3600 if hours > 0 else 0
            types: dict[str, dict] = {}
            by_machine: dict[str, Counter] = defaultdict(Counter)
            evs = self._events()
            stamps = [_ts(e) for e in evs]
            first = min((t for t in stamps if t), default=now)
            t0 = max(since, first) if since else first
            nb = 48
            width = max(60.0, (now - t0) / nb)
            buckets: dict[str, Counter] = defaultdict(Counter)
            for e, t in zip(evs, stamps):
                ty = e.get("type", "?")
                d = types.setdefault(ty, {"type": ty, "total": 0, "in_range": 0, "first": t, "last": t, "machines": Counter()})
                d["total"] += 1
                if t:
                    d["first"] = min(d["first"] or t, t)
                    d["last"] = max(d["last"] or t, t)
                if t and t >= t0:
                    d["in_range"] += 1
                    who = emitter(e)
                    d["machines"][who] += 1
                    by_machine[who][ty] += 1
                    buckets[ty][min(nb - 1, int((t - t0) // width))] += 1
            top = [ty for ty, _ in sorted(((k, v["in_range"]) for k, v in types.items()), key=lambda x: -x[1])[:6] if types[ty]["in_range"]]
            series = [{"label": ty, "points": [[t0 + i * width, buckets[ty].get(i, 0)] for i in range(nb)]} for ty in top]
            rows = [{**d, "machines": d["machines"].most_common(4)} for d in sorted(types.values(), key=lambda x: (-x["in_range"], -x["total"]))]
            machines = [{"machine": m, "events": sum(c.values()), "types": c.most_common(5)} for m, c in sorted(by_machine.items(), key=lambda x: -sum(x[1].values()))]
            return {"ok": True, "backend": self.core.events.bus.name, "total": len(evs), "in_range": sum(d["in_range"] for d in types.values()),
                    "types": rows, "machines": machines, "volume": series, "bucket_s": width, "from": t0}
        return self._guard(go)
