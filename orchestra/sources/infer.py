"""One inference round for a remote source: read its schema, generate views, pass them through the
query script, probe each candidate with a read of the window, rank and cap.

The round has a **budget**: at most ``infer_requests`` requests (retries included) and
``infer_deadline`` seconds, the schema's reads included (``limits.Budget``). Its reads are batched
across families (``survey.py``, ``plan.py``), so a tenant of hundreds of metrics costs tens of
requests. What could not be read by then is not guessed at: a family the schema could not read
keeps what the last round found of it (``known``) or is unknown, and a candidate not probed is left
out and says why; such a round is **partial**. More than half the candidates unprobed fails the
round. A candidate the store refuses (over its per-query series limit, or a query it rejects) is
left out and says so, and the round is not partial for it: no later round would read it either.

A rule over a counter (``views.py``: ``left``) is left out before ranking, naming the counter.

When and whether a round runs, and what is kept of it, is ``cache.py``."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from itertools import pairwise
from pathlib import Path

from ..sd.units import from_name
from . import PastDeadline, Source, SourceError
from .limits import Budget
from .plan import probe_form, shared
from .rank import rank
from .regroup import expr
from .schema import read as read_schema
from .spec import DeclaredSeries, SourceSpec
from .survey import known_record
from .transform import apply, script_id
from .views import Definition, one_count_per_thing, views

SHAPE_POINTS = 30            # a probe's series, kept at this many points, to compare counts (duplicates.same_shape)
REFUSED = re.compile(r"over the store's per-query series limit|HTTP 4(?!29|01|03)\d\d")   # the store will not read it: no retry helps
UNPROBED = 0.5               # of the candidates, at most, not probed for the round to stand (partial)
TRANSPORT = ("timeout", "deadline", "concurrency", "infer_every", "rate", "burst", "max_requests", "infer_requests",
             "infer_deadline", "max_points", "settle", "script_timeout", "series_per_query")   # how a source is read, not what it holds


@dataclass
class Inference:
    source: str
    at: float
    key: str                                     # what it was inferred under: settings and script
    kept: list[Definition] = field(default_factory=list)
    left_out: list[Definition] = field(default_factory=list)
    families: list[dict] = field(default_factory=list)
    script: str | None = None
    notes: list[str] = field(default_factory=list)
    error: str | None = None                     # the last round's failure, when these are older definitions
    partial: bool = False                        # some families or candidates were not read by the round's budget: never fresh
    window: list[float] = field(default_factory=list)   # [start, end] it was inferred over
    requests: int = 0                            # the round's requests, retries included
    seconds: float = 0.0                         # its wall time

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> Inference:
        fields = set(Definition.__dataclass_fields__)
        defs = lambda xs: [Definition(**{k: v for k, v in x.items() if k in fields}) for x in xs]
        return cls(d["source"], d["at"], d["key"], defs(d.get("kept") or []), defs(d.get("left_out") or []),
                   list(d.get("families") or []), d.get("script"), list(d.get("notes") or []), d.get("error"),
                   bool(d.get("partial")), list(d.get("window") or []), int(d.get("requests") or 0), float(d.get("seconds") or 0.0))

    def span(self) -> float:
        return self.window[1] - self.window[0] if len(self.window) == 2 else 0.0


def settings_key(spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path) -> str:
    """A hash of everything an inference depends on but the data: the source's settings (not its
    credentials' values, which are never read here, nor how hard it is read: ``TRANSPORT``), its
    declared series and the script."""
    s = asdict(spec)
    s.pop("auth", None)
    for k in TRANSPORT:
        s.pop(k, None)
    script = Path(repo_root) / spec.queries_script if spec.queries_script else None
    body = json.dumps([s, [asdict(x) for x in declared], script_id(script) if script and script.is_file() else None], sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _declared(spec: SourceSpec, declared: list[DeclaredSeries]) -> list[Definition]:
    """The hand-written and preset definitions: a ``select`` is a counter read from raw samples
    (view ``increments``, reset-safe, summed by its ``by`` labels), anything else a query."""
    aliases = spec.aliases()
    return [Definition(id=f"declared.{i}", source=spec.name, name=x.name, family=f"declared:{x.name}",
                       view="increments" if x.by is not None else "declared", kind=x.kind, query=x.query, unit=x.unit or from_name(x.name),
                       group_by=[aliases.get(b, b) for b in x.by or []], by_real=list(x.by or []),
                       origin=[f"declared in the preset {x.preset}" if x.preset else "declared in orchestra.toml"], pin=True,
                       rename=aliases, traffic=dict(x.traffic or {}))
            for i, x in enumerate(declared) if x.source == spec.name]


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 3:
        return 1.0
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 1.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / (va * vb) ** 0.5


def apart(got: list[tuple[dict, list]], start: float, end: float) -> float:
    """How far a grouping's groups move on their own, 0 to 1: one less the least correlation
    between the changes of two of them (of the eight that vary most), over ``SHAPE_POINTS``
    stretches of the window (coarse enough that a sample's noise does not decide it). 0 when fewer
    than two groups move: one that moves beside flat ones says nothing its total does not."""
    diffs = []
    for v in shape(got, start, end):
        d = [0.0 if a is None or b is None else b - a for a, b in pairwise(v)]
        if any(d):
            diffs.append(d)
    diffs = sorted(diffs, key=lambda d: -sum(x * x for x in d))[:8]
    least = min((_corr(a, b) for i, a in enumerate(diffs) for b in diffs[i + 1:]), default=1.0)
    return round(min(1.0, max(0.0, 1.0 - least)), 3)


def shape(got: list[tuple[dict, list]], start: float, end: float) -> list[list[float | None]]:
    """Each series at ``SHAPE_POINTS`` points of the window: its last value at or before each."""
    grid = [start + (end - start) * k / (SHAPE_POINTS - 1) for k in range(SHAPE_POINTS)]
    out = []
    for _, pts in got:
        pts, vals, i, last = sorted(pts), [], 0, None
        for g in grid:
            while i < len(pts) and pts[i][0] <= g + 1e-6:
                last = pts[i][1]
                i += 1
            vals.append(last)
        out.append(vals)
    return out


def summary(got: list[tuple[dict, list]], d: Definition, start: float, end: float) -> dict:
    """What a probe's read says of a candidate: how many series it yields, whether any moves, how
    far its groups move on their own (``apart``), its least value, and, for a count, a counter or
    a sum, its series' shape."""
    out = {"series": len(got), "moves": any(len({v for _, v in pts}) > 1 for _, pts in got),
           "min": min((v for _, pts in got for _, v in pts), default=None), "apart": apart(got, start, end) if len(got) > 1 else 0.0}
    if d.view in ("count", "distinct", "increments", "sum_by", "rollup"):
        out["shape"] = shape(got, start, end)
    return out


def probe(source: Source, d: Definition, start: float, end: float, until: float | None = None) -> dict:
    """One candidate's probe: a read of the window at the series' resolution (coarser only past
    ``plan.PROBE_POINTS``), summarised (``summary``)."""
    return probe_all(source, [d], start, end, until, 1)[d.id]


def probe_all(source: Source, cands: list[Definition], start: float, end: float, until: float | None = None,
              concurrency: int = 4) -> dict[str, dict]:
    """Every candidate's probe; the generated ones read together (``plan.py``), the others (a
    script's query) one by one. A probe that failed says why (``error``), and ``late`` when the
    round's deadline or budget stopped it."""
    forms = {d.id: f for d in cands if (f := probe_form(d, start, end)) is not None}
    rows, errors = shared(source, cands, forms, {step: start for _, _, step in forms.values()}, end, until, concurrency) if forms else ({}, {})
    out: dict[str, dict] = {}
    for d in cands:
        if d.id in forms:
            if d.id in errors:
                out[d.id] = {"series": 0, "moves": False, "error": errors[d.id], "late": errors[d.id].startswith("late: ")}
            else:
                out[d.id] = summary(rows.get(d.id, []), d, start, end)
            continue
        step = max(d.resolution_s or 60.0, (end - start) / 1000)
        q = d.query
        if d.view in ("starts", "stops", "increments"):          # a selector: its count of series, or the sum of its counters
            q = expr("count" if d.view != "increments" else "sum", d.by_real, d.query)
        try:
            out[d.id] = summary(source.query_range(q, start, end, step, until=until), d, start, end)
        except SourceError as e:
            out[d.id] = {"series": 0, "moves": False, "error": str(e), "late": isinstance(e, PastDeadline)}
    return out


def unique_names(defs: list[Definition]) -> None:
    """Two families' definitions never share a name and a grouping (they would be one series to
    discovery): the one whose family is the name keeps it, else the first family by name; the
    others are named after their family as well. Stable: it depends on the definitions only."""
    by: dict[tuple, list[Definition]] = {}
    for d in defs:
        by.setdefault((d.name, tuple(d.group_by)), []).append(d)
    for (name, _), ds in by.items():
        fams = sorted({d.family for d in ds}, key=lambda f: (re.sub(r"[^a-z0-9_]+", "_", f.lower()).strip("_") != name, f))
        for d in ds:
            if d.family != fams[0]:
                d.name = f"{name}__{re.sub(r'[^a-z0-9_]+', '_', d.family.lower()).strip('_')}"
                d.flags.append(f"named after its family too: {fams[0]} gives a series of the same name")


def infer(source: Source, spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path,
          start: float, end: float, until: float | None = None, known: dict[str, dict] | None = None) -> Inference:
    """A fresh round, by ``until`` (``time.monotonic()``; the source's ``infer_deadline`` from now
    by default) and within ``infer_requests``. Raises ``SourceError`` or ``TransformError`` when it
    cannot stand; ``known``: the last round's families by name."""
    began = time.monotonic()
    until = began + spec.infer_deadline if until is None else until
    before, outer = getattr(source, "requests", 0), getattr(source, "budget", None)
    if hasattr(source, "budget"):
        source.budget = Budget(spec.infer_requests, until, "the inference round")
    try:
        inf = _infer(source, spec, declared, repo_root, start, end, until, known)
    finally:
        if hasattr(source, "budget"):
            source.budget = outer
    inf.requests, inf.seconds = getattr(source, "requests", 0) - before, round(time.monotonic() - began, 1)
    return inf


def _infer(source: Source, spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path,
           start: float, end: float, until: float, known: dict[str, dict] | None) -> Inference:
    inf = Inference(spec.name, time.time(), settings_key(spec, declared, repo_root), window=[start, end])
    schema = read_schema(source, spec, start, end, until=until, known=known)
    inf.notes = list(schema.notes)
    inf.partial = any("could not be read this round" in n for n in schema.notes)
    inf.families = [{"name": f.name, "metrics": list(f.metrics), "stats": f.stats, "series": f.series, "unit": f.unit,
                     "rollup": f.rollup, "rollups": sorted(r["metric"] for r in f.rollups.values()), "notes": list(f.notes),
                     **known_record(f)} for f in schema.families]
    cands = one_count_per_thing([d for fam in schema.families for d in views(fam, spec)], schema.families)
    unique_names(cands)
    for i, d in enumerate(cands):
        d.id = f"c{i}"
    inf.left_out += [replace(d, why=d.left) for d in cands if d.left]
    cands = [d for d in cands if not d.left]
    if spec.queries_script:
        cands, dropped, inf.script = apply(spec, repo_root, cands)
        inf.left_out += dropped
    probes = probe_all(source, cands, start, end, until, spec.concurrency)
    big = {i for i, p in probes.items() if REFUSED.search(p.get("error") or "")}
    missed = {i for i, p in probes.items() if p.get("error") and i not in big}
    if missed and len(missed) > UNPROBED * len(probes):
        first = next(probes[i]["error"] for i in missed)
        raise SourceError(f"{len(missed)} of {len(probes)} probes could not be made; the first: {first} "
                          "(narrow match, or raise infer_deadline or infer_requests on the [[sources]] entry)")
    if missed or big:
        why = lambda i: (f"the store refuses its read ({probes[i]['error']}): narrow match, or declare it in [[series]]"
                         if i in big else f"not probed this round ({probes[i]['error']})")
        inf.left_out += [replace(d, why=why(d.id)) for d in cands if d.id in missed | big]
        if missed:
            inf.notes.append(f"{len(missed)} of {len(probes)} candidates were not probed this round and are left out; the first: "
                             f"{probes[next(iter(missed))]['error']}")
        cands, inf.partial = [d for d in cands if d.id not in missed | big], inf.partial or bool(missed)
    for d in cands:
        if d.kind == "rate" and (probes[d.id].get("min") or 0.0) < 0:     # its name says a rate; its data, which went below 0, says not
            d.kind = "level"
            d.flags.append("named a rate, but it went below zero: read as a level")
    kept, left = rank(cands, spec, probes)
    inf.kept = _declared(spec, declared) + kept
    inf.left_out += left
    return inf
