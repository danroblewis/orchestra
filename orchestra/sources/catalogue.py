"""One catalogue over the project's own store and its remote sources: what discovery reads.

``read(start, end, step)`` returns every own series as it is, and every remote definition read for
exactly that window, on that grid and never finer than the series' own resolution (``fetch.py``),
named ``<prefix>:<name>``, with each series' declared kind (``sd.series.Declared``) and its
provenance (source, final query, origin, resolution), and each source's status. A source that
fails (refused in ``orchestra.toml``, unreachable, unauthorized, a query it rejects, a script that
fails with nothing cached, past its deadline) is **missing**: the reading says so and why, and the
caller (``sd.rediscover``) discovers from what arrived but saves no version, so an outage neither
churns versions nor deletes stocks. Every range is re-runnable: nothing assumes the last reading
was recent, and the stretches of the window in which a source returned nothing are recorded as
its gaps (a laptop that slept, a server that was down).

A definition of **counted traffic** (``traffic.py``) is read like any other; the reading records,
per result series, the direction, channel and machine it counts for (``Reading.traffic``, and in
its provenance). ``counted`` reads only those definitions, for the Machines page."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from ..metrics import MetricsStore
from ..sd.series import Declared, series_key
from . import PastDeadline, SourceError
from .fetch import grid_step
from .fetch import read as read_definition
from .infer import Inference, definitions
from .own import OWN, OwnSource
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


def summary(d: Definition) -> bool:
    """Whether a definition reads a statistic summarised across reporters (an average, a maximum,
    an upper bound of a quantile), not a quantity: discovery never takes one for a stock."""
    return d.view in SUMMARIES or (d.view == "rollup" and d.name.endswith(("_avg", "_max", "_min")))


def provenance(spec: SourceSpec, d: Definition, traffic: dict | None = None) -> dict:
    return {"source": spec.name, "query": d.query, "kind": d.kind, "origin": list(d.origin), "resolution_s": d.resolution_s,
            "unit": d.unit, "view": d.view, "family": d.family, "flags": list(d.flags), **({"traffic": traffic} if traffic else {}),
            **({"stock": dict(d.stock)} if d.stock else {})}


class Catalogue:
    def __init__(self, project, metrics: MetricsStore | None, specs: Specs | None = None):
        self.project = project
        self.specs = specs if specs is not None else for_project(project)
        self.own = OwnSource(metrics, project.key) if metrics is not None else None
        self.remotes = {s.name: PrometheusSource(s) for s in self.specs.sources}
        self.errors: dict[str, str] = {}            # source -> why the last read of a model's series from it failed (reader)

    def spec(self, name: str) -> SourceSpec:
        return next(s for s in self.specs.sources if s.name == name)

    def inference(self, name: str, start: float, end: float, *, refresh: bool = False, until: float | None = None) -> Inference:
        return definitions(self.remotes[name], self.spec(name), self.specs.declared, Path(self.project.repo_root),
                           Path(self.project.state_dir), start, end, refresh=refresh, until=until)

    def _remote(self, spec: SourceSpec, start: float, end: float, step: float, own_names: set[str], out: Reading) -> None:
        src = self.remotes[spec.name]
        began, before = time.monotonic(), (src.requests, src.points)
        until = began + spec.deadline                   # for the inference and the reads, all told
        st: dict = {"where": spec.where(), "auth": src.auth.describe(), "prefix": spec.prefix}
        out.status[spec.name] = st
        try:
            inf = self.inference(spec.name, start, end, until=until)
        except Exception as e:  # noqa: BLE001 - one source's failure never ends the discovery of the others
            st.update(ok=False, error=f"inference failed: {why(e)}")
            out.missing[spec.name] = st["error"]
            return
        st.update(inferred_at=inf.at, definitions=len(inf.kept), left_out=len(inf.left_out), script=inf.script,
                  inference_error=inf.error)
        results, errors = self._read_all(spec, inf.kept, start, end, step, until)
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
                                          resolution_s=d.resolution_s, summary=summary(d))
                out.provenance[key] = provenance(spec, d, counted)
                if counted:
                    out.traffic[key] = counted
                times += [t for t, _ in pts]
                n += 1
        q = min((grid_step(step, d.resolution_s) for d in inf.kept), default=step)
        st.update(series=n, requests=src.requests - before[0], points=src.points - before[1],
                  seconds=round(time.monotonic() - began, 2), gaps=gaps(times, start, end - spec.settle, q) if n else [],
                  refused_series=refused[:20])
        if errors:
            st.update(ok=False, error="; ".join(errors))
            out.missing[spec.name] = st["error"]
        elif inf.kept and not n:                    # the store answered with nothing: not a source to discover without
            st.update(ok=False, error="returned no series in the window", gaps=[[round(start, 3), round(end - spec.settle, 3)]])
            out.missing[spec.name] = st["error"]
        else:
            st["ok"] = True

    def _read_all(self, spec: SourceSpec, defs: list[Definition], start: float, end: float, step: float,
                  until: float | None = None) -> tuple[dict[str, list], list[str]]:
        """Every definition read from its source at once, by ``until`` (the source's deadline from
        now when not given), all of them ending ``settle`` before ``end``: the results by
        definition id, and what went wrong (the reads not done in time, then the reads that
        failed). A read still running at the deadline is left to stop at its next request."""
        src, failed, results, late = self.remotes[spec.name], [], {}, 0
        until = time.monotonic() + spec.deadline if until is None else until
        end = end - spec.settle
        pool = ThreadPoolExecutor(spec.concurrency)
        futs = {pool.submit(read_definition, src, d, spec.prefix, spec.machine, start, end, step, spec.producers, until): d
                for d in defs}
        done, pending = wait(futs, timeout=max(0.0, until - time.monotonic()))
        pool.shutdown(wait=False, cancel_futures=True)
        late += len(pending)
        for f in done:
            d = futs[f]
            try:
                results[d.id] = f.result()
            except PastDeadline:
                late += 1
            except Exception as e:  # noqa: BLE001 - that source is missing, with why
                failed.append(f"{d.name}: {why(e)}")
        errors = [f"{late} of {len(defs)} reads were not done within the deadline of {spec.deadline:g} s"] if late else []
        if failed:
            errors.append(f"{len(failed)} read{'s' if len(failed) != 1 else ''} failed; the first: {failed[0]}")
        return results, errors

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
            results, errors = self._read_all(spec, defs, start, end, step, until) if defs else ({}, [])
            if errors:
                failed[spec.name] = "; ".join(errors)
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
