"""One inference round for a remote source: read its schema, generate views, pass them through the
query script, probe each candidate with a read of the window, rank and cap. The result is
cached in ``<state>/sources/<name>.json`` and reused for ``infer_every`` (an hour by default)
while the source's settings and the script are unchanged. When a round fails (the schema, a
probe or the script), or keeps fewer than half the definitions the cached round kept, the cached
definitions stand, the reason is recorded beside them and their time is not renewed, so the next
discovery tries again."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from itertools import pairwise
from pathlib import Path

from . import PastDeadline, Source, SourceError
from .rank import rank
from .schema import read as read_schema
from .spec import DeclaredSeries, SourceSpec
from .transform import TransformError, apply, script_id
from .views import Definition, one_count_per_thing, views

PROBE_POINTS = 1000          # at most, per series: a probe reads at the series' own resolution, so a change that lasts a few samples is seen
SHAPE_POINTS = 30            # a probe's series, kept at this many points, to compare counts (duplicates.same_shape)


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
    partial: bool = False                        # some candidates were not probed by the deadline: never fresh

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> Inference:
        defs = lambda xs: [Definition(**x) for x in xs]
        return cls(d["source"], d["at"], d["key"], defs(d.get("kept") or []), defs(d.get("left_out") or []),
                   list(d.get("families") or []), d.get("script"), list(d.get("notes") or []), d.get("error"),
                   bool(d.get("partial")))


def settings_key(spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path) -> str:
    """A hash of everything an inference depends on but the data: the source's settings (not its
    credentials' values, which are never read here), its declared series and the script."""
    s = asdict(spec)
    s.pop("auth", None)
    script = Path(repo_root) / spec.queries_script if spec.queries_script else None
    body = json.dumps([s, [asdict(x) for x in declared], script_id(script) if script and script.is_file() else None], sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _declared(spec: SourceSpec, declared: list[DeclaredSeries]) -> list[Definition]:
    """The hand-written and preset definitions: a ``select`` is a counter read from raw samples
    (view ``increments``, reset-safe, summed by its ``by`` labels), anything else a query."""
    aliases = spec.aliases()
    return [Definition(id=f"declared.{i}", source=spec.name, name=x.name, family=f"declared:{x.name}",
                       view="increments" if x.by is not None else "declared", kind=x.kind, query=x.query, unit=x.unit,
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


def probe(source: Source, d: Definition, start: float, end: float, until: float | None = None) -> dict:
    """A read of the window at the series' resolution (coarser only past PROBE_POINTS): how many
    series a candidate yields, whether any moves, how far its groups move on their own
    (``apart``), its least value, and, for a count, a counter or a sum, its series' shape."""
    step = max(d.resolution_s or 60.0, (end - start) / PROBE_POINTS)
    q = d.query
    if d.view in ("starts", "stops"):                   # they move when the count does
        q = f"count by ({', '.join(d.by_real)}) ({d.query})" if d.by_real else f"count({d.query})"
    elif d.view == "increments":
        q = f"sum by ({', '.join(d.by_real)}) ({d.query})" if d.by_real else f"sum({d.query})"
    try:
        got = source.query_range(q, start, end, step, until=until)
    except PastDeadline as e:
        return {"series": 0, "moves": False, "error": str(e), "late": True}
    except SourceError as e:
        return {"series": 0, "moves": False, "error": str(e)}
    out = {"series": len(got), "moves": any(len({v for _, v in pts}) > 1 for _, pts in got),
           "min": min((v for _, pts in got for _, v in pts), default=None), "apart": apart(got, start, end) if len(got) > 1 else 0.0}
    if d.view in ("count", "distinct", "increments", "sum_by", "rollup"):
        out["shape"] = shape(got, start, end)
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
          start: float, end: float, until: float | None = None) -> Inference:
    """A fresh round. Raises ``SourceError`` or ``TransformError`` when it cannot finish; a probe
    not made by ``until`` (``time.monotonic()``; by default the source's deadline counted from the
    end of the schema's read, which on a slow store takes a deadline of its own) is left out, and
    the round is partial."""
    inf = Inference(spec.name, time.time(), settings_key(spec, declared, repo_root))
    schema = read_schema(source, spec, start, end)
    until = time.monotonic() + spec.deadline if until is None else until
    inf.notes = list(schema.notes)
    inf.families = [{"name": f.name, "kind": f.kind, "metrics": list(f.metrics), "stats": f.stats, "series": f.series,
                     "resolution_s": f.resolution_s, "rollup": f.rollup, "rollups": sorted(r["metric"] for r in f.rollups.values()),
                     "labels": {c: asdict(i) for c, i in f.labels.items()}, "retyped": f.retyped, "notes": list(f.notes),
                     "where": dict(f.where)} for f in schema.families]
    cands = one_count_per_thing([d for fam in schema.families for d in views(fam, spec)], schema.families)
    unique_names(cands)
    for i, d in enumerate(cands):
        d.id = f"c{i}"
    if spec.queries_script:
        cands, dropped, inf.script = apply(spec, repo_root, cands)
        inf.left_out += dropped
    with ThreadPoolExecutor(spec.concurrency) as pool:
        probes = dict(zip([d.id for d in cands], pool.map(lambda d: probe(source, d, start, end, until), cands), strict=True))
    if failed := [p["error"] for p in probes.values() if p.get("error") and not p.get("late")]:
        raise SourceError(f"{len(failed)} of {len(probes)} probes failed; the first: {failed[0]}")
    late = {i for i, p in probes.items() if p.get("late")}
    if late and len(late) * 2 > len(probes):
        raise SourceError(f"{len(late)} of {len(probes)} probes were not made within the source's deadline of {spec.deadline:g} s: "
                          "narrow match, or raise deadline (or concurrency) on the [[sources]] entry")
    if late:                                            # a slow store: rank what was probed, and say what was not
        inf.left_out += [replace(d, why=f"not probed within the source's deadline of {spec.deadline:g} s") for d in cands if d.id in late]
        inf.notes.append(f"{len(late)} of {len(probes)} candidates were not probed within the deadline and are left out: "
                         "narrow match, or raise deadline (or concurrency)")
        cands, inf.partial = [d for d in cands if d.id not in late], True
    for d in cands:
        if d.kind == "rate" and (probes[d.id].get("min") or 0.0) < 0:     # its name says a rate; its data, which went below 0, says not
            d.kind = "level"
            d.flags.append("named a rate, but it went below zero: read as a level")
    kept, left = rank(cands, spec, probes)
    inf.kept = _declared(spec, declared) + kept
    inf.left_out += left
    return inf


def inferred(inf: Inference) -> int:
    """How many of its kept definitions the round inferred (the declared ones are kept anyway)."""
    return sum(1 for d in inf.kept if not d.id.startswith("declared."))


def cached(state_dir: Path, name: str) -> Inference | None:
    p = Path(state_dir) / "sources" / f"{name}.json"
    try:
        return Inference.from_json(json.loads(p.read_text()))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(state_dir: Path, inf: Inference) -> None:
    """Written whole and then moved into place, from a temporary file of this save's own (the host
    and the web server may both save at once)."""
    d = Path(state_dir) / "sources"
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{inf.source}.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(inf.to_json(), indent=1))
        os.replace(tmp, d / f"{inf.source}.json")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def definitions(source: Source, spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path, state_dir: Path,
                start: float, end: float, *, refresh: bool = False, until: float | None = None) -> Inference:
    """The source's definitions: cached while fresh and inferred under the same settings, else a
    new round; when the round fails, the cached ones inferred under the same settings, with the
    failure noted. Raises when there are none."""
    key = settings_key(spec, declared, repo_root)
    if not spec.infer:                     # only what is declared: nothing to infer, nothing to cache
        return Inference(spec.name, time.time(), key, _declared(spec, declared),
                         notes=["infer = false: only the declared series are read, never the schema"])
    old = cached(state_dir, spec.name)
    if old and not refresh and not old.partial and old.key == key and time.time() - old.at < spec.infer_every:
        return old
    same = old is not None and old.key == key        # older definitions under other settings would not be what was asked for
    when = time.strftime('%Y-%m-%d %H:%M', time.localtime(old.at)) if old else ""
    try:
        inf = infer(source, spec, declared, repo_root, start, end, until)
    except Exception as e:
        if not same:
            raise
        said = str(e) if isinstance(e, (SourceError, TransformError)) else f"{type(e).__name__}: {e}"
        old.error = f"inference failed ({said}); using the definitions inferred at {when}"
        return old
    if same and not refresh and inferred(inf) < inferred(old) / 2:
        # A store that answered but held little in the window (a laptop that slept, a server
        # restarted empty) must not replace what was seen; the next discovery tries again.
        old.error = (f"the last round kept {inferred(inf)} definitions where the one at {when} kept {inferred(old)}; "
                     "using those (`orchestra sources infer` accepts the new round)")
        return old
    save(state_dir, inf)
    return inf
