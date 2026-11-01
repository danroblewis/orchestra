"""An instrument's views of its series (orchestra/collect/views.py), carried into discovery: a pile's
level and its moves are one construction (orchestra/sd/construction.py), so the pile is a stock
by construction with no fitted balance, and its moves are flows whose rates are still fitted."""

import random
import subprocess

import pytest

from orchestra import runtime
from orchestra.collect.runner import Collecting
from orchestra.collect.spec import Collector, from_toml
from orchestra.collect.views import declared, parse, provenance
from orchestra.config import ConfigError, init_project
from orchestra.metrics import Point, for_project
from orchestra.sd.construction import PLACES, constructed, sign_of
from orchestra.sd.discover import discover
from orchestra.sd.series import series_key
from orchestra.sources.catalogue import Catalogue

T0, MINUTES, STEP = 1_700_000_000.0, 90, 30.0
VIEWS = {"workflow_pile_items": {"view": "count", "place": "pile", "where": {"kind": "step"}},
         "workflow_item_moves_total": {"view": "moves", "starts": "to", "stops": "from"},
         "workflow_pile_oldest_seconds": {"view": "age"}}
INSTRUMENT = "workflows.piles"
PILES = ("write.waiting", "write.held", "review.waiting")
ROUTE = [("<start>", "write.waiting", 0.08), ("write.waiting", "write.held", 0.04), ("write.held", "review.waiting", 0.03),
         ("review.waiting", "<end>", 0.05)]


def piles(seed: int = 3, instrument: str = INSTRUMENT) -> list:
    """One workflow's step piles and its moves, as one fold makes them: each second an item may
    move along its route, a pile's level and the move counted at once."""
    rng = random.Random(seed)
    level = dict.fromkeys(PILES, 0)
    moved = {(a, b): 0 for a, b, _ in ROUTE}
    pts: dict[tuple, list] = {}
    base = {"instrument": instrument, "workflow": "w"}
    for i in range(MINUTES * 60):
        t = T0 + i
        for a, b, rate in ROUTE:
            if (a == "<start>" or level[a]) and rng.random() < rate * (1 + (level[a] if a != "<start>" else 0)) / 4:
                if a != "<start>":
                    level[a] -= 1
                if b != "<end>":
                    level[b] += 1
                moved[(a, b)] += 1
        if i % 15 == 0:                            # the instrument prints every 15 s
            for p in PILES:
                pts.setdefault(("workflow_pile_items", (("pile", p), ("kind", "step"))), []).append((t, float(level[p])))
            for (a, b), n in moved.items():
                pts.setdefault(("workflow_item_moves_total", (("from", a), ("to", b))), []).append((t, float(n)))
            pts.setdefault(("workflow_pile_oldest_seconds", (("pile", "write.waiting"),)), []).append((t, float(i % 300)))
    return [(name, {**base, **dict(labels)}, ps) for (name, labels), ps in pts.items()]


def by_pile(m):
    return {s.series.labels.get("pile"): s for s in m.stocks if s.series is not None and s.series.name == "workflow_pile_items"}


def test_a_collector_with_views_makes_its_piles_stocks_by_construction():
    assert "pile" not in PLACES                 # the place label is the instrument's own, honoured as declared
    dump = piles()
    prov = provenance(dump, {INSTRUMENT: parse(VIEWS)}, series_key)
    m = discover(dump, start=T0, end=T0 + MINUTES * 60, step=STEP, provenance=prov)
    found = by_pile(m)
    assert set(found) == set(PILES), m.discovery["left_out"]
    for st in found.values():
        ev = st.evidence
        assert ev["by_construction"] is True and ev["balance_r2"] is None and ev["exact_steps"] is None
        assert ev["trust"]["kind"] == "by_construction" and "identification" not in ev
    assert set(m.discovery["by_construction"]) == {s.id for s in found.values()}
    held = found["write.held"].evidence["balance"]
    assert {(b["series"].split("from=")[1].split(",")[0], b["sign"]) for b in held} == {('"write.waiting"', 1), ('"write.held"', -1)}
    # the moves are the flows between the piles, marked by construction, their rates fitted
    moves = {(f.counter.labels["from"], f.counter.labels["to"]): f for f in m.flows if f.counter and f.counter.name == "workflow_item_moves_total"}
    assert set(moves) == {(a, b) for a, b, _ in ROUTE}
    ids = {p: s.id for p, s in found.items()}
    for (a, b), f in moves.items():
        assert f.src == ids.get(a) and f.dst == ids.get(b)
        assert f.evidence["by_construction"] is True
        eq = f.current()
        assert eq.origin == "fitted" and eq.method == "poisson-mle" and eq.params
    assert "an age" in m.discovery["left_out"][series_key("workflow_pile_oldest_seconds", dump[-1][1])]


def test_a_collector_without_views_is_unchanged():
    dump = piles()
    m = discover(dump, start=T0, end=T0 + MINUTES * 60, step=STEP)
    assert not m.discovery["by_construction"]
    assert not any(s.evidence.get("by_construction") for s in m.stocks)
    assert not any(f.evidence.get("by_construction") for f in m.flows)
    for st in by_pile(m).values():              # found by the search, fitted, judged as evidence
        assert st.evidence["balance_r2"] is not None


def test_only_a_piles_own_moves_are_its_construction():
    dump = piles()
    prov = provenance(dump, {INSTRUMENT: parse(VIEWS)}, series_key)

    class S:
        def __init__(self, name, labels):
            self.name, self.labels, self.key = name, labels, series_key(name, labels)

    level = S("workflow_pile_items", {"instrument": INSTRUMENT, "workflow": "w", "kind": "step", "pile": "write.held"})
    into = S("workflow_item_moves_total", {"instrument": INSTRUMENT, "workflow": "w", "from": "write.waiting", "to": "write.held"})
    other = S("workflow_item_moves_total", {"instrument": INSTRUMENT, "workflow": "w", "from": "<start>", "to": "write.waiting"})
    elsewhere = S("workflow_item_moves_total", {"instrument": INSTRUMENT, "workflow": "v", "from": "write.waiting", "to": "write.held"})
    for s in (into, other, elsewhere):
        prov.setdefault(s.key, {"source": "own", "instrument": INSTRUMENT, "view": "moves", "starts": "to", "stops": "from"})
    assert sign_of(level, into, prov) == 1 and sign_of(level, other, prov) == 0 and sign_of(level, elsewhere, prov) == 0
    assert constructed(level, [(into, 1)], prov) and not constructed(level, [(into, 1), (other, -1)], prov)
    assert not constructed(level, [(into, -1)], prov)


def test_views_parse_from_toml_and_from_a_plugin():
    raw = {"collect": [{"name": "piles", "command": "true", "views": VIEWS}]}
    plug = Collector.collect("piles", "true", owner="workflows", views=VIEWS)
    [mine, theirs], errors = from_toml(raw | {"collect": raw["collect"] + [{"name": "bad", "command": "true",
                                                                            "views": {"x": {"view": "moves", "starts": "to"}}}]},
                                       [plug])
    assert mine.views == theirs.views == parse(VIEWS) and theirs.name == "workflows.piles"
    assert len(errors) == 1 and "bad" not in {c.name for c in (mine, theirs)} and "stops" in errors[0]
    with pytest.raises(ConfigError):
        parse({"x": {"view": "count"}})                          # a count names its place
    with pytest.raises(ConfigError):
        parse({"x": {"view": "count", "place": "pile", "starts": "to"}})
    assert hash(plug)                                            # still hashable, as the runner needs


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "orchestra.toml").write_text('[metrics]\nurl = "file"\n')
    return init_project(r)


def test_the_runtime_record_carries_a_plugins_views_to_discovery(project):
    c = Collecting(project, lambda _: None, plugin_collectors=[Collector.collect("piles", "true", owner="workflows", views=VIEWS)])
    c._read()
    c._urgent = True
    c._record_health(0.0)
    assert runtime.read(project)["instruments"][INSTRUMENT]["views"]["workflow_item_moves_total"] == [VIEWS["workflow_item_moves_total"]]
    assert declared(project) == {INSTRUMENT: parse(VIEWS)}
    store = for_project(project)
    store.write([Point(n, v, t, {"project": project.key, **labels}) for n, labels, ps in piles() for t, v in ps])
    reading = Catalogue(project, store).read(T0, T0 + MINUTES * 60, STEP)
    recs = {k: r for k, r in reading.provenance.items() if r.get("instrument") == INSTRUMENT}
    assert {r["view"] for r in recs.values()} == {"count", "moves", "age"}
    m = discover(reading.dump, start=T0, end=T0 + MINUTES * 60, step=STEP, provenance=reading.provenance)
    assert set(by_pile(m)) == set(PILES) and all(s.evidence["by_construction"] for s in by_pile(m).values())
