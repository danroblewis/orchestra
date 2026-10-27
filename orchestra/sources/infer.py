"""One inference round for a remote source: read its schema, generate views, pass them through the
query script, probe each candidate with a read of the window, rank and cap. The result is
cached in ``<state>/sources/<name>.json`` and reused for ``infer_every`` (an hour by default)
while the source's settings and the script are unchanged; when a round fails, the last cached
definitions stand and the failure is recorded beside them."""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import Source, SourceError
from .rank import rank
from .schema import read as read_schema
from .spec import DeclaredSeries, SourceSpec
from .transform import TransformError, apply, script_id
from .views import Definition, one_count_per_thing, views

PROBE_POINTS = 1000          # at most, per series: a probe reads at the series' own resolution, so a change that lasts a few samples is seen


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

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> Inference:
        defs = lambda xs: [Definition(**x) for x in xs]
        return cls(d["source"], d["at"], d["key"], defs(d.get("kept") or []), defs(d.get("left_out") or []),
                   list(d.get("families") or []), d.get("script"), list(d.get("notes") or []), d.get("error"))


def settings_key(spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path) -> str:
    """A hash of everything an inference depends on but the data: the source's settings (not its
    credentials' values, which are never read here), its declared series and the script."""
    s = asdict(spec)
    s.pop("auth", None)
    script = Path(repo_root) / spec.queries_script if spec.queries_script else None
    body = json.dumps([s, [asdict(x) for x in declared], script_id(script) if script and script.is_file() else None], sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _declared(spec: SourceSpec, declared: list[DeclaredSeries]) -> list[Definition]:
    return [Definition(id=f"declared.{i}", source=spec.name, name=x.name, family=f"declared:{x.name}", view="declared",
                       kind=x.kind, query=x.query, unit=x.unit, origin=["declared in orchestra.toml"], pin=True,
                       rename=spec.aliases())
            for i, x in enumerate(declared) if x.source == spec.name]


def probe(source: Source, d: Definition, start: float, end: float) -> dict:
    """A read of the window at the series' resolution (coarser only past PROBE_POINTS): how many
    series a candidate yields, and whether any moves."""
    step = max(d.resolution_s or 60.0, (end - start) / PROBE_POINTS)
    q = d.query
    if d.view in ("starts", "stops"):                   # they move when the count does
        q = f"count by ({', '.join(d.by_real)}) ({d.query})" if d.by_real else f"count({d.query})"
    elif d.view == "increments":
        q = f"sum by ({', '.join(d.by_real)}) ({d.query})" if d.by_real else f"sum({d.query})"
    try:
        got = source.query_range(q, start, end, step)
    except SourceError as e:
        return {"series": 0, "moves": False, "error": str(e)}
    return {"series": len(got), "moves": any(len({v for _, v in pts}) > 1 for _, pts in got)}


def infer(source: Source, spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path,
          start: float, end: float) -> Inference:
    """A fresh round. Raises ``SourceError`` or ``TransformError`` when it cannot finish."""
    inf = Inference(spec.name, time.time(), settings_key(spec, declared, repo_root))
    schema = read_schema(source, spec, start, end)
    inf.notes = list(schema.notes)
    inf.families = [{"name": f.name, "kind": f.kind, "metrics": list(f.metrics), "stats": f.stats, "series": f.series,
                     "resolution_s": f.resolution_s, "rollup": f.rollup,
                     "labels": {c: asdict(i) for c, i in f.labels.items()}} for f in schema.families]
    cands = one_count_per_thing([d for fam in schema.families for d in views(fam, spec)], schema.families)
    for i, d in enumerate(cands):
        d.id = f"c{i}"
    if spec.queries_script:
        cands, dropped, inf.script = apply(spec, repo_root, cands)
        inf.left_out += dropped
    with ThreadPoolExecutor(spec.concurrency) as pool:
        probes = dict(zip([d.id for d in cands], pool.map(lambda d: probe(source, d, start, end), cands), strict=True))
    kept, left = rank(cands, spec, probes)
    inf.kept = _declared(spec, declared) + kept
    inf.left_out += left
    return inf


def cached(state_dir: Path, name: str) -> Inference | None:
    p = Path(state_dir) / "sources" / f"{name}.json"
    try:
        return Inference.from_json(json.loads(p.read_text()))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(state_dir: Path, inf: Inference) -> None:
    d = Path(state_dir) / "sources"
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{inf.source}.json.tmp"
    tmp.write_text(json.dumps(inf.to_json(), indent=1))
    tmp.replace(d / f"{inf.source}.json")


def definitions(source: Source, spec: SourceSpec, declared: list[DeclaredSeries], repo_root: Path, state_dir: Path,
                start: float, end: float, *, refresh: bool = False) -> Inference:
    """The source's definitions: cached while fresh and inferred under the same settings, else a
    new round; when the round fails, the cached ones inferred under the same settings, with the
    failure noted. Raises when there are none."""
    key = settings_key(spec, declared, repo_root)
    old = cached(state_dir, spec.name)
    if old and not refresh and old.key == key and time.time() - old.at < spec.infer_every:
        return old
    try:
        inf = infer(source, spec, declared, repo_root, start, end)
    except (SourceError, TransformError) as e:
        if old is None or old.key != key:          # older definitions under other settings would not be what was asked for
            raise
        old.error = f"inference failed ({e}); using the definitions inferred at {time.strftime('%Y-%m-%d %H:%M', time.localtime(old.at))}"
        return old
    save(state_dir, inf)
    return inf
