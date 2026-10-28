"""Generated definitions read together: each family's aggregation once, at the finest grouping any
of its views needs, and every view derived from it (``regroup.py``); the reads of all families
batched into few requests (``batch.py``).

A definition's **form** says what is read for it: an inner expression, an aggregation and a step.
The views of one inner expression at one step share a read per base aggregation (sum, count, max,
min), grouped by the union of their groupings. A definition with no form (a declared or
script-written query, a turnover read from raw samples) is read on its own (``fetch.py``).

- **Probes** (inference): each view at the series' resolution (``probe_form``). A counter's probe
  is the sum of its values (a native histogram's count), a turnover's the count of its series.
- **Reads** (discovery, ``read_form``): a level on discovery's grid, never finer than the series'
  resolution; a counter as ``sum by (G) (increase(x[S]))`` on a grid of S, discovery's step or the
  smallest multiple of it holding two of the counter's samples, accumulated from 0 here.
  ``increase`` rather than ``rate``: it is the events of each step, which is what discovery
  balances, and the store handles resets and the windows tile the timeline, so the total over the
  window is the counter's whole increase (VictoriaMetrics' ``increase`` is exact; Prometheus'
  extrapolates within each step). A native histogram is read by ``histogram_count(increase(…))``,
  a delta gauge by ``sum_over_time(x[S])``."""

from __future__ import annotations

import math

from . import Source
from .batch import OVER_LIMIT, Part, run
from .readcache import ReadCache
from .regroup import BASES, derive, expr, fine_by
from .views import Definition

PROBE_POINTS = 1000          # at most, per series: a probe reads at the series' own resolution, so a change that lasts a few samples is seen


def grid_step(step: float, resolution_s: float | None) -> float:
    """Discovery's step, or the smallest multiple of it no finer than the series' resolution."""
    if not resolution_s or resolution_s <= step:
        return step
    return step * math.ceil(resolution_s / step - 1e-9)


def _counter_inner(d: Definition, sel: str) -> str:
    return f"histogram_count({sel})" if d.counter_form == "native" else sel


def probe_form(d: Definition, start: float, end: float) -> tuple[str, str, float] | None:
    """(inner, aggregation, step) of a definition's probe; None when it is probed on its own."""
    step = max(d.resolution_s or 60.0, (end - start) / PROBE_POINTS)
    if d.view in ("starts", "stops") and not d.inner and d.query:
        return d.query, "count", step
    if d.agg == "increase" and d.inner:
        return _counter_inner(d, d.inner), "sum", step
    if d.inner and d.agg in BASES:
        return d.inner, d.agg, step
    return None


def counter_step(step: float, resolution_s: float | None) -> float:
    """S: discovery's step, or the smallest multiple of it that holds two of the counter's samples."""
    return grid_step(step, 2 * (resolution_s or 0.0) or None)


def read_resolution(d: Definition, step: float) -> float | None:
    """How often a definition's read has a point: a counter read server-side, every S (its grid);
    anything else, its own reporting interval."""
    return counter_step(step, d.resolution_s) if d.agg == "increase" and d.inner else d.resolution_s


def read_form(d: Definition, step: float) -> tuple[str, str, float] | None:
    """(inner, aggregation, step) of a definition's read; None when it is read on its own."""
    if d.agg == "increase" and d.inner:
        s = counter_step(step, d.resolution_s)
        w = f"[{int(s)}s]"
        inner = {"native": f"histogram_count(increase({d.inner}{w}))", "delta": f"sum_over_time({d.inner}{w})"}.get(
            d.counter_form, f"increase({d.inner}{w})")
        return inner, "sum", s
    if d.inner and d.agg in BASES:
        return d.inner, d.agg, grid_step(step, d.resolution_s)
    return None


def kept_run(source: Source, ps: list[Part], start: float, end: float, step: float, until: float | None, concurrency: int,
          cache: ReadCache | None, resettle: float) -> tuple[dict, dict]:
    """``run`` over [start, end], or, with a cache, only over what it does not keep of each part
    (``readcache.plan``: parts that need the same stretch are read together), spliced in."""
    if cache is None:
        return run(source, ps, start, end, step, until, concurrency)
    key = lambda p: f"q|{step:g}|{p.expr}"
    spans: dict[tuple[float, float], list[Part]] = {}
    failed: dict = {}
    for p in ps:
        if why := cache.refusal(key(p)):          # refused for its size lately: not asked again yet
            failed[p.key] = why
        elif (sp := cache.plan(key(p), start, end, step, resettle)) is not None:
            spans.setdefault(sp, []).append(p)
    for (a, b), pp in spans.items():
        g, f = run(source, pp, a, b, step, until, concurrency)
        failed.update(f)
        for p in pp:
            if p.key in g:
                cache.put(key(p), g[p.key], a, b, whole=a <= start + 1e-6)
            elif f.get(p.key, "").startswith(OVER_LIMIT):
                cache.refuse(key(p), f[p.key])
    return {p.key: cache.get(key(p), start, end) for p in ps if p.key not in failed}, failed


def shared(source: Source, defs: list[Definition], forms: dict[str, tuple[str, str, float]], starts: dict[float, float], end: float,
           until: float | None = None, concurrency: int = 4, cache: ReadCache | None = None,
           resettle: float = 0.0) -> tuple[dict[str, list], dict[str, str]]:
    """Every definition of ``forms`` (id -> inner, aggregation, step) read from ``starts[step]`` to
    ``end``: its rows by id, and why for those that could not be read. With a ``cache``, only what
    it does not keep is asked for (``readcache.py``)."""
    by_id = {d.id: d for d in defs}
    groups: dict[tuple[str, float], list[Definition]] = {}
    for i, (inner, _, step) in forms.items():
        groups.setdefault((inner, step), []).append(by_id[i])
    parts: dict[float, list[Part]] = {}
    for (inner, step), ds in groups.items():
        bases = sorted({b for d in ds for b in BASES[forms[d.id][1]]})
        by = fine_by([d.by_real + d.agg_labels if forms[d.id][1] == "distinct" else d.by_real for d in ds])
        n = max(d.touched or d.est_series or 1 for d in ds)
        parts.setdefault(step, []) .extend(Part((inner, step, b), expr(b, by, inner), n) for b in bases)
    got: dict = {}
    failed: dict = {}
    for step, ps in parts.items():
        g, f = kept_run(source, ps, starts[step], end, step, until, concurrency, cache, resettle)
        got.update(g)
        failed.update(f)
    out: dict[str, list] = {}
    errors: dict[str, str] = {}
    for i, (inner, agg, step) in forms.items():
        need = BASES[agg]
        if bad := next((failed[(inner, step, b)] for b in need if (inner, step, b) in failed), None):
            errors[i] = bad
            continue
        d = by_id[i]
        out[i] = derive({b: got.get((inner, step, b), []) for b in need}, agg, d.by_real, d.agg_labels)
    return out, errors
