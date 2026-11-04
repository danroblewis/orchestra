"""What each discovery run and inference round cost, kept: ``<state>/model/runs.jsonl``.

One line per run (``kind`` ``discovery``) and per inference round that ran (``inference``; a round
that only reused its cache is no round), appended when it ends, so the Dynamics page can say what
rediscovering costs and how healthy the job is (``runhealth.py``). The log keeps the last ``KEEP``
lines: once it holds ``SLACK`` more, it is cut back to them, the newest kept. A run going now is
in ``run.now.json`` beside it (its phase and when it began), removed when it ends; one whose
process is gone is not going.

A record: ``id``, ``kind``, ``trigger`` (``schedule``, ``button``, ``cli``, ``config change``),
``started``, ``ended``, ``duration_s``, ``phases`` (seconds each, exclusive: ``reads`` of the
stores, ``inference`` (its survey and probes), the strategy's ``fit``, ``saving``), ``outcome``
(``saved vN``, ``unchanged``, ``no model``, ``failed: <why>``, ``timed out``), ``partial`` (why,
when a source was missing or read in part), ``strategy`` (configured, asked, ran), ``window_s``
and ``step_s``, ``cost`` per source, and the model's ``result`` (stocks, flows, left out, mean stock trust, fitted flows and their mean
R², ``result_of``).

**The cost is derived from the request log** (``sources/reqlog.py``): every request a run makes is
tagged with its id (an inference round inside a discovery with ``<id>~infer-<source>``), and the
run's cost per source is the lines so tagged: ``requests`` sent (``inference`` of them by the
round), ``whole`` and ``incremental`` reads (a range read over less than half the run's window is
the read cache asking only for what is new; one over the window, a refill), ``series``, ``points``
and ``bytes`` in the answers, ``wait_ms`` (milliseconds waiting on the store), ``refused`` (never
sent: the budget, the daily cap, the deadline; or a 429), ``errors``, and the store's count
``today`` against its cap ``per_day`` after the run (``limits.RateLimit.peek``)."""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path

KEEP = 2000
SLACK = KEEP // 10
PHASES = ("reads", "inference", "fit", "saving")
TRIGGERS = ("schedule", "button", "cli", "config change")
READS = ("/api/v1/query_range", "/api/v1/query")
RANGE = re.compile(r"\[(\d+(?:\.\d+)?)s\]\s*$")
_LOCK = threading.Lock()


def new_id(at: float | None = None) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(time.time() if at is None else at)) + "-" + secrets.token_hex(3)


class RunLog:
    """The run records of one model store (``ModelStore.runs()``)."""

    def __init__(self, directory: Path | str):
        self.dir = Path(directory)
        self.path = self.dir / "runs.jsonl"
        self.now_path = self.dir / "run.now.json"

    def append(self, rec: dict) -> None:
        line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"
        try:
            with _LOCK:
                self.dir.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
                with self.path.open("rb") as f:
                    lines = f.readlines()
                if len(lines) > KEEP + SLACK:
                    tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
                    tmp.write_bytes(b"".join(lines[-KEEP:]))
                    tmp.replace(self.path)
        except OSError:
            pass                                  # a record that cannot be written never stops a discovery

    def recent(self, n: int = 200, since: float | None = None) -> list[dict]:
        """The newest ``n`` records (and none that ended before ``since``), oldest first."""
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out = []
        for line in raw[-n:] if n else raw:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and (since is None or (r.get("ended") or 0) >= since):
                out.append(r)
        return out

    def current(self) -> dict | None:
        """The run going now, with its phase; None when none is, or its process is gone."""
        from ..runtime import holds
        try:
            d = json.loads(self.now_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return d if isinstance(d, dict) and holds(d.get("process") or {}) else None

    def _now(self, d: dict | None, run_id: str) -> None:
        try:
            if d is None:
                cur = json.loads(self.now_path.read_text(encoding="utf-8"))
                if cur.get("id") == run_id:
                    self.now_path.unlink(missing_ok=True)
                return
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.now_path.with_name(f"{self.now_path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(d), encoding="utf-8")
            tmp.replace(self.now_path)
        except (OSError, ValueError, AttributeError):
            pass


def read_kind(line: dict, window_s: float | None) -> str | None:
    """``whole`` or ``incremental`` for a range read of a series' points (``None`` for anything
    else: a listing, labels, metadata, an instant): incremental when it reads less than half the
    run's window, the read cache asking only for what is new."""
    if line.get("endpoint") not in READS:
        return None
    w = line.get("window") or []
    if len(w) == 2 and w[0] is not None and w[1] is not None:
        span = w[1] - w[0]
    elif (m := RANGE.search(str(line.get("query") or ""))) is not None:
        span = float(m[1])
    else:
        return None
    return "incremental" if window_s and span < 0.5 * window_s else "whole"


def mine(line: dict, run_id: str) -> bool:
    r = line.get("run")
    return isinstance(r, str) and (r == run_id or r.startswith(run_id + "~"))


def tally(lines: list[dict], window_s: float | None) -> dict:
    """One source's cost from its request log's lines of one run (see the module's docstring)."""
    c = {"requests": 0, "inference": 0, "whole": 0, "incremental": 0, "series": 0, "points": 0, "bytes": 0, "wait_ms": 0.0,
         "refused": 0, "errors": 0}
    has_bytes = False
    for x in lines:
        if x.get("sent") is False:
            c["refused"] += 1
            continue
        c["requests"] += 1
        c["wait_ms"] += float(x.get("ms") or 0)
        c["series"] += int(x.get("series") or 0)
        c["points"] += int(x.get("points") or 0)
        if x.get("bytes") is not None:
            has_bytes = True
            c["bytes"] += int(x["bytes"])
        err = str(x.get("error") or "")
        if err.startswith("HTTP 429"):
            c["refused"] += 1
        elif err:
            c["errors"] += 1
        if x.get("by") == "infer":
            c["inference"] += 1
        elif (k := read_kind(x, window_s)) is not None:
            c[k] += 1
    c["wait_ms"] = round(c["wait_ms"])
    if not has_bytes:
        c["bytes"] = None                          # the transport did not say
    return c


def cost(state_dir: Path | str, specs: list, run_id: str, since: float, window_s: float | None, peek=None) -> dict:
    """Each source's cost of the run ``run_id`` (its lines in the request log since ``since``),
    with the store's count today against its daily cap."""
    from ..sources import reqlog
    out = {}
    for spec in specs:
        lines = [x for x in reqlog.lines_since(state_dir, spec.name, since - 1) if mine(x, run_id)]
        c = tally(lines, window_s)
        try:
            if peek is None:
                from ..sources.limits import for_store
                p = for_store(spec).peek()
            else:
                p = peek(spec)
            c.update(today=p.get("today"), per_day=p.get("per_day"))
        except Exception:  # noqa: BLE001, S110 - a bucket that cannot be read leaves the count out
            pass
        out[spec.name] = c
    return out


def result_of(model) -> dict:
    """The model a run made, in numbers: stocks, flows, series left out, the stocks' mean trust
    score (``sd.stocktrust``), the flows whose current equation is fitted and their mean R²."""
    d = (model.discovery or {}) if model is not None else {}
    stocks = model.stocks if model is not None else []
    flows = model.flows if model is not None else []
    scores = [t["score"] for s in stocks if isinstance(t := (getattr(s, "evidence", None) or {}).get("trust"), dict)
              and isinstance(t.get("score"), (int, float))]
    fitted = [eq for f in flows if (eq := f.current()) is not None and eq.origin == "fitted"]
    r2 = [q for eq in fitted if isinstance(q := (eq.quality or {}).get("r2"), (int, float))]
    return {"stocks": len(stocks), "flows": len(flows), "left_out": len(d.get("left_out") or {}),
            "trust": round(sum(scores) / len(scores), 4) if scores else None, "fitted": len(fitted),
            "r2": round(sum(r2) / len(r2), 4) if r2 else None}


def outcome_of(model, version: int | None) -> str:
    """``saved vN``, ``timed out`` (the strategy stopped at its deadline: conservation's fits are
    kept), ``no model`` or ``unchanged``."""
    d = (model.discovery or {}) if model is not None else {}
    if "deadline" in str(d.get("sdlab") or ""):
        return "timed out"
    if version is not None:
        return f"saved v{version}"
    return "unchanged" if model is not None and model.stocks else "no model"


def partial_of(model) -> str | None:
    """Why the run read less than it asked for: a source missing, or read in part."""
    d = (model.discovery or {}) if model is not None else {}
    if d.get("not_saved"):
        return str(d["not_saved"])
    parts = [f"{k}: {v.get('warning')}" for k, v in (d.get("sources") or {}).items() if isinstance(v, dict) and v.get("partial")]
    return "; ".join(parts) or None


class Run:
    """One run, timed by phase while it goes (``phase``, nested phases timed apart from the one
    around them), recorded when it ends (``finish``)."""

    def __init__(self, log: RunLog, state_dir: Path | str, kind: str, trigger: str, *, specs: list | None = None,
                 run_id: str | None = None, parent: str | None = None, clock=time.monotonic, wall=time.time, live: bool = True):
        self.log, self.state_dir, self.kind, self.trigger = log, Path(state_dir), kind, trigger
        self.specs = specs or []
        self._clock, self._wall = clock, wall
        self.started = wall()
        self.id = run_id or new_id(self.started)
        self.parent = parent
        self.phases: dict[str, float] = {}
        self._stack: list[list] = []              # [name, began] of the phases open now, innermost last
        self._began = clock()
        self.live = live
        self.fields: dict = {}
        self._show(None)

    def _show(self, phase: str | None, what: str | None = None) -> None:
        if not self.live:
            return
        from ..runtime import me
        self.log._now({"id": self.id, "kind": self.kind, "trigger": self.trigger, "started": self.started, "phase": phase,
                       "what": what, "phase_started": self._wall(), "process": me()}, self.id)

    @contextmanager
    def phase(self, name: str, what: str | None = None):
        now = self._clock()
        if self._stack:                          # the phase around this one pauses
            outer = self._stack[-1]
            self.phases[outer[0]] = self.phases.get(outer[0], 0.0) + now - outer[1]
        self._stack.append([name, now])
        self._show(name, what)
        try:
            yield
        finally:
            end = self._clock()
            n, b = self._stack.pop()
            self.phases[n] = self.phases.get(n, 0.0) + end - b
            if self._stack:
                self._stack[-1][1] = end
            self._show(self._stack[-1][0] if self._stack else None)

    def finish(self, outcome: str, *, model=None, window_s: float | None = None, **fields) -> dict:
        ended = self._wall()
        rec = {"id": self.id, "kind": self.kind, "trigger": self.trigger, **({"parent": self.parent} if self.parent else {}),
               "started": round(self.started, 3), "ended": round(ended, 3), "duration_s": round(self._clock() - self._began, 3),
               "phases": {k: round(v, 3) for k, v in self.phases.items()}, "outcome": outcome, **self.fields, **fields,
               **({"window_s": window_s} if window_s is not None else {}),
               "cost": cost(self.state_dir, self.specs, self.id, self.started, window_s)}
        if model is not None:
            rec["result"] = result_of(model)
        self.log.append(rec)
        if self.live:
            self.log._now(None, self.id)
        return rec
