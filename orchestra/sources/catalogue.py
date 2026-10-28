"""One catalogue over the project's own store and its remote sources: what discovery reads.

``read(start, end, step)`` returns every own series as it is, and every remote definition read for
exactly that window, on that grid and never finer than the series' own resolution (``fetch.py``),
named ``<prefix>:<name>``, with each series' declared kind (``sd.series.Declared``) and its
provenance (source, final query, origin, resolution), and each source's status. A source that
fails (refused in ``orchestra.toml``, unreachable, unauthorized, a query it rejects, a script that
fails with nothing cached, past its deadline) is **missing**: the reading says so and why, and the
caller (``sd.rediscover``) discovers from what arrived but saves no version, so an outage neither
churns versions nor deletes stocks. A source most of whose reads arrived is **partial**, not
missing: when at most ``PARTIAL`` of its definitions could not be read (a refusal that outlasted
the retries, the round's deadline or budget), the rest are used, the failed ones are named in its
status (``failed``), and discovery goes on. Credentials refused, or more failing, is missing.

A source's reads in one discovery are one round: at most ``max_requests`` requests (retries
included) by ``deadline``, at the source's request ``rate`` shared with every other process of the
project (``limits.py``), the generated views read together (``fetch.read_many``).

A catalogue made with ``infer=False``, or made inside ``reading_only()`` on the same thread (the web
server's "rediscover" button runs so), reads the cached definitions and never starts an inference
round: only the host and the CLI (``orchestra sd discover``, ``orchestra sources infer``) infer
(``cache.py``). Every range is re-runnable: nothing assumes the last reading
was recent, and the stretches of the window in which a source returned nothing are recorded as
its gaps (a laptop that slept, a server that was down).

A definition of **counted traffic** (``traffic.py``) is read like any other; the reading records,
per result series, the direction, channel and machine it counts for (``Reading.traffic``, and in
its provenance). ``counted`` reads only those definitions, for the Machines page."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ..metrics import MetricsStore
from ..sd.series import Declared, series_key
from . import SourceError
from .cache import definitions
from .fetch import grid_step, read_many
from .fetch import read as read_definition
from .infer import Inference
from .limits import Budget, RateLimit
from .own import OWN, OwnSource
from .plan import read_resolution
from .prometheus import PrometheusSource
from .spec import SourceSpec, Specs, for_project
from .transform import TransformError
from .views import Definition


@dataclass
class Reading:
    dump: list = field(default_factory=list)                       # (name, labels, points), own and remote
    kinds: dict[str, Declared] = field(default_factory=dict)       # series key -> declared kind
    provenance: dict[str, dict] = field(default_factory=dict)      # series key -> source, query, origin, ...
    status: dict[str, dict] = field(default_factory=dict)          # source name -> what happened
    missing: dict[str, str] = field(default_factory=dict)          # source name -> why it is missing
    traffic: dict[str, dict] = field(default_factory=dict)         # series key -> direction, channel, machine (counted traffic)


def gaps(times: list[float], start: float, end: float, step: float) -> list[list[float]]:
    """The stretches of [start, end] longer than two steps with no point at all."""
    out, last = [], start
    for t in sorted(set(times)) + [end]:
        if t - last > 2 * step:
            out.append([round(last, 3), round(t, 3)])
        last = max(last, t)
    return out


def why(e: Exception) -> str:
    """What failed, for a source's status: a source's or a script's own message as it is; anything
    else (a server answering in a shape nobody expected) with its type, so it is recognisable."""
    return str(e) if isinstance(e, (SourceError, TransformError)) else f"{type(e).__name__}: {e}"


SUMMARIES = {"avg_by", "upper_by", "max_by", "min_by"}       # views that summarise many reporters' values
PARTIAL = 0.1               # of a source's definitions, at most, that may fail for the source to be partial, not missing


def summary(d: Definition) -> bool:
    """Whether a definition reads a statistic summarised across reporters (an average, a maximum,
    an upper bound of a quantile), not a quantity: discovery never takes one for a stock."""
    return d.view in SUMMARIES or (d.view == "rollup" and d.name.endswith(("_avg", "_max", "_min")))


def provenance(spec: SourceSpec, d: Definition, traffic: dict | None = None, resolution_s: float | None = None) -> dict:
    return {"source": spec.name, "query": d.query, "kind": d.kind, "origin": list(d.origin),
            "resolution_s": d.resolution_s if resolution_s is None else resolution_s,
            "unit": d.unit, **({"unit_label": d.unit_label} if d.unit_label else {}), "view": d.view, "family": d.family, "flags": list(d.flags), **({"traffic": traffic} if traffic else {}),
            **({"stock": dict(d.stock)} if d.stock else {})}


def _failures(failed: dict[str, str], names: dict[str, str], total: int, deadline: float) -> str:
    """What went wrong with a source's reads: those not done in time, then those that failed."""
    late = [i for i, w in failed.items() if w.startswith("late: ")]
    other = [i for i in failed if i not in late]
    out = [f"{len(late)} of {total} reads were not done within the deadline of {deadline:g} s"] if late else []
    if other:
        first = other[0]
        out.append(f"{len(other)} read{'s' if len(other) != 1 else ''} failed; the first: {names.get(first, first)}: {failed[first]}")
    return "; ".join(out)


_THREAD = threading.local()


@contextmanager
def reading_only():
    """Catalogues made on this thread meanwhile, without ``infer=``, never start an inference round."""
    was = getattr(_THREAD, "reading_only", False)
    _THREAD.reading_only = True
    try:
        yield
    finally:
        _THREAD.reading_only = was


class Catalogue:
    def __init__(self, project, metrics: MetricsStore | None, specs: Specs | None = None, *, infer: bool | None = None):
        self.project = project
        self.infer = (not getattr(_THREAD, "reading_only", False)) if infer is None else infer
        self.specs = specs if specs is not None else for_project(project)
        self.own = OwnSource(metrics, project.key) if metrics is not None else None
        rate = lambda s: RateLimit(s.rate, s.burst, Path(project.state_dir) / "sources" / f"{s.name}.rate")
        self.remotes = {s.name: PrometheusSource(s, rate(s)) for s in self.specs.sources}
        self.errors: dict[str, str] = {}            # source -> why the last read of a model's series from it failed (reader)

    def spec(self, name: str) -> SourceSpec:
        return next(s for s in self.specs.sources if s.name == name)

    def inference(self, name: str, start: float, end: float, *, refresh: bool = False, until: float | None = None) -> Inference:
        return definitions(self.remotes[name], self.spec(name), self.specs.declared, Path(self.project.repo_root),
                           Path(self.project.state_dir), start, end, refresh=refresh, until=until, infer_ok=self.infer or refresh)

    def _remote(self, spec: SourceSpec, start: float, end: float, step: float, own_names: set[str], out: Reading) -> None:
        src = self.remotes[spec.name]
        began, before = time.monotonic(), (src.requests, src.points, src.retries)
        st: dict = {"where": spec.where(), "auth": src.auth.describe(), "prefix": spec.prefix}
        out.status[spec.name] = st
        try:
            inf = self.inference(spec.name, start, end)   # a fresh inference (rare: it is cached) has a deadline of its own
        except Exception as e:  # noqa: BLE001 - one source's failure never ends the discovery of the others
            st.update(ok=False, error=f"inference failed: {why(e)}")
            out.missing[spec.name] = st["error"]
            return
        st.update(inferred_at=inf.at, definitions=len(inf.kept), left_out=len(inf.left_out), script=inf.script,
                  inference_error=inf.error)
        results, failed = self._read_all(spec, inf.kept, start, end, step, time.monotonic() + spec.deadline)
        times: list[float] = []
        n = 0
        refused: list[str] = []
        for d in inf.kept:
            for name, labels, pts, counted in results.get(d.id, []):
                key = series_key(name, labels)
                if name in own_names or key in out.provenance:
                    refused.append(key)
                    continue
                out.dump.append((name, labels, pts))
                out.kinds[key] = Declared("counter" if d.kind in ("counter", "rate") else "level",
                                          baseline=d.kind == "counter" and d.view != "increments",
                                          direction=(counted or {}).get("direction"), channel=(counted or {}).get("channel"),
                                          resolution_s=read_resolution(d, step), summary=summary(d))
                out.provenance[key] = provenance(spec, d, counted, read_resolution(d, step))
                if counted:
                    out.traffic[key] = counted
                times += [t for t, _ in pts]
                n += 1
        q = min((grid_step(step, d.resolution_s) for d in inf.kept), default=step)
        st.update(series=n, requests=src.requests - before[0], points=src.points - before[1], retries=src.retries - before[2],
                  seconds=round(time.monotonic() - began, 2), gaps=gaps(times, start, end - spec.settle, q) if n else [],
                  refused_series=refused[:20])
        names = {d.id: d.name for d in inf.kept}
        if failed:
            st["failed"] = [f"{names.get(i, i)}: {w}" for i, w in sorted(failed.items(), key=lambda x: names.get(x[0], x[0]))]
        refused_auth = any("refused the credentials" in w for w in failed.values())
        if failed and (refused_auth or not n or len(failed) > PARTIAL * len(inf.kept)):
            st.update(ok=False, error=_failures(failed, names, len(inf.kept), spec.deadline))
            out.missing[spec.name] = st["error"]
        elif inf.kept and not n:                    # the store answered with nothing: not a source to discover without
            st.update(ok=False, error="returned no series in the window", gaps=[[round(start, 3), round(end - spec.settle, 3)]])
            out.missing[spec.name] = st["error"]
        else:
            st.update(ok=True, partial=bool(failed))
            if failed:
                st["warning"] = "partial: " + _failures(failed, names, len(inf.kept), spec.deadline)

    def _read_all(self, spec: SourceSpec, defs: list[Definition], start: float, end: float, step: float,
                  until: float | None = None) -> tuple[dict[str, list], dict[str, str]]:
        """Every definition read from its source, as one round (``max_requests`` by ``until``, the
        source's deadline from now when not given), all of them ending ``settle`` before ``end``:
        the results by definition id, and why by id for those that could not be read."""
        src = self.remotes[spec.name]
        until = time.monotonic() + spec.deadline if until is None else until
        outer, src.budget = src.budget, Budget(spec.max_requests, until, "this discovery's reads")
        try:
            return read_many(src, defs, spec.prefix, spec.machine, start, end - spec.settle, step, spec.producers, until,
                             spec.concurrency)
        finally:
            src.budget = outer

    def counted(self, start: float, end: float, step: float) -> tuple[list[dict], dict[str, str]]:
        """Every series of counted traffic over [start, end]: its source, name, labels, points,
        direction, channel and machine; and the sources that failed, with why."""
        out, failed = [], {}
        for spec in self.specs.sources:
            until = time.monotonic() + spec.deadline
            try:
                defs = [d for d in self.inference(spec.name, start, end, until=until).kept if d.traffic]
            except Exception as e:  # noqa: BLE001 - that source is missing, with why
                failed[spec.name] = why(e)
                continue
            results, errors = self._read_all(spec, defs, start, end, step, until) if defs else ({}, {})
            if errors:
                failed[spec.name] = _failures(errors, {d.id: d.name for d in defs}, len(defs), spec.deadline)
            for d in defs:
                for name, labels, pts, counted in results.get(d.id, []):
                    out.append({"source": spec.name, "name": name, "labels": labels, "points": pts, "kind": d.kind, **counted})
        return out, failed

    def read(self, start: float, end: float, step: float) -> Reading:
        out = Reading()
        if self.own is not None:
            out.dump = list(self.own.dump())
            out.status[OWN] = {"ok": True, "series": len(out.dump)}
        own_names = {name for name, _, _ in out.dump}
        for name, why in self.specs.refused.items():
            out.status[name] = {"ok": False, "error": f"refused in orchestra.toml: {why}"}
            out.missing[name] = out.status[name]["error"]
        for spec in self.specs.sources:
            self._remote(spec, start, end, step, own_names, out)
        return out

    def reader(self, start: float, end: float, step: float):
        """A reader of the remote series a model is bound to (``SeriesRef`` with a ``source``)
        over one window: ``read(ref)`` gives that series' points, read through the definition of
        that name in the source's current inference. Each definition is read once and shared by
        every stock and flow bound to one of its series; a source that fails is tried once, its
        error kept in ``errors`` (by source name) until a read of it works, and its series read
        as empty. For the web server's levels and history, and ``orchestra sd show``."""
        results: dict[tuple[str, str], dict[str, list]] = {}
        failed: set[str] = set()

        def definition(source: str, name: str) -> dict[str, list]:
            spec = self.spec(source)
            inf = self.inference(source, start, end)
            out: dict[str, list] = {}
            for d in inf.kept:
                if f"{spec.prefix}:{d.name}" == name:
                    for n, labels, pts, _ in read_definition(self.remotes[source], d, spec.prefix, spec.machine, start,
                                                             end - spec.settle, step, spec.producers):
                        out[series_key(n, labels)] = pts
            return out

        def read(ref) -> list[tuple[float, float]]:
            source = ref.source
            if source not in self.remotes or source in failed:
                return []
            if (source, ref.name) not in results:
                try:
                    results[(source, ref.name)] = definition(source, ref.name)
                    self.errors.pop(source, None)
                except Exception as e:  # noqa: BLE001 - the series reads as empty; the page shows why
                    self.errors[source] = why(e)
                    failed.add(source)
                    return []
            return results[(source, ref.name)].get(series_key(ref.name, ref.labels), [])
        return read

    def read_ref(self, ref, start: float, end: float, step: float) -> list[tuple[float, float]]:
        """One remote series' points (``reader``): empty when the source fails (why is in
        ``errors``) or the definition is gone."""
        return self.reader(start, end, step)(ref)
