"""Inference as a loop (SPEC §4.4, "The inference loop"): the store's own labels rank every
family's groupings (``storewide.py``); each round reads the last discovery's verdicts and spends
what is left of its budget on the best candidates never probed (``explore.py``)."""

from __future__ import annotations

import math
import time
from types import SimpleNamespace

import pytest
from fake_prometheus import FakePrometheus

from orchestra.sources.explore import ident
from orchestra.sources.feedback import verdicts
from orchestra.sources.infer import infer
from orchestra.sources.prometheus import PrometheusSource
from orchestra.sources.spec import load

NOW = math.floor(time.time() / 60) * 60
T0 = NOW - 3600
SVC = [f"svc-{i}" for i in range(5)]
LENS = [f"caller-{i}" for i in range(40)]


def every(fn, step=30):
    return [(float(t), float(fn(t - T0))) for t in range(int(T0), int(NOW) + 1, step)]


def common_store():
    """Six families carrying ``svc`` (five stable values); one of them also ``lens`` (forty)."""
    out = []
    for f in range(6):
        for k, s in enumerate(SVC):
            if f == 0:
                for j, lens in enumerate(LENS):
                    out.append(("fam0_jobs", {"svc": s, "lens": lens}, every(lambda x, k=k, j=j: (k + j) % 5 + (x // 300) % (2 + k))))
            elif f % 2:
                out.append((f"fam{f}_requests_total", {"svc": s}, every(lambda x, k=k, f=f: (1 + k) * f * x // 10)))
            else:
                out.append((f"fam{f}_items", {"svc": s}, every(lambda x, k=k: (x // (120 * (k + 1))) % 7)))
    return out


@pytest.fixture
def store(tmp_path):
    made = []

    def make(data, **kw):
        f = FakePrometheus(data)
        made.append(f)
        specs = load({"sources": [{"name": "lab", "url": f.url, "match": ['{__name__=~"fam.*"}'], "max_series": 2000,
                                   "max_per_family": 40, **kw}]}, tmp_path)
        assert not specs.refused, specs.refused
        src = PrometheusSource(specs.sources[0])
        src._sleep = lambda s: None
        return f, src, specs.sources[0]
    yield make
    for f in made:
        f.close()


def test_the_stores_common_grouping_ranks_above_one_familys_oddity(store, tmp_path):
    _, src, spec = store(common_store())
    inf = infer(src, spec, [], tmp_path, T0, NOW)
    svc, lens = inf.labels["svc"], inf.labels["lens"]
    assert svc["why"] == "groups 6 of 6 families, 5 stable values" and svc["rank"] == 1.0
    assert lens["groups"] == 1 and lens["values"] == 40 and lens["rank"] < 0.05
    every_def = inf.kept + inf.left_out
    for fam in {d.family for d in every_def}:
        by = lambda label, fam=fam: [d for d in every_def if d.family == fam and d.view not in ("distinct",)
                                     and [c for c in d.group_by if d.labels_info.get(c, {}).get("role") == "grouping"] == [label]]
        assert by("svc"), fam
        assert all("common 1.00 [svc: groups 6 of 6 families" in d.why for d in by("svc") if d.why.startswith("moves"))
        if fam == "fam0_jobs":
            assert by("lens")
            assert min(d.score for d in by("svc")) > max(d.score for d in by("lens")), [(d.name, d.score, d.why) for d in by("svc") + by("lens")]


def _one(inf, family, by, view="sum_by"):
    return next(d for d in inf.kept if d.family == family and d.view == view and
                [c for c in d.group_by if d.labels_info.get(c, {}).get("role") == "grouping"] == by)


def _fate(inf, cand):
    return next(r for r in inf.explored if r["candidate"] == cand)


def test_a_candidate_discovery_refuted_is_not_probed_again_until_the_history_grows(store, tmp_path):
    _, src, spec = store(common_store())
    first = infer(src, spec, [], tmp_path, T0, NOW, held_s=3600.0)
    d = _one(first, "fam2_items", ["svc"])
    cand = ident(d)
    assert _fate(first, cand)["fate"] == "probed" and cand in first.probed
    said = {cand: {"fate": "refuted", "why": "discovery left it out: … so an input, not a stock", "series": "x", "at": 100.0}}
    second = infer(src, spec, [], tmp_path, T0, NOW, memory=first, verdicts=said, held_s=3600.0)
    assert _fate(second, cand)["fate"] == "demoted" and "an input, not a stock" in _fate(second, cand)["why"]
    assert second.probed[cand] == first.probed[cand]                 # carried, not probed again
    assert second.round["demoted"] == 1 and second.demoted[cand]["held"] == 3600.0
    again = next(x for x in second.kept + second.left_out if ident(x) == cand)
    assert "demoted -2.00" in again.why
    third = infer(src, spec, [], tmp_path, T0, NOW, memory=second, verdicts={}, held_s=4000.0)    # the demotion stands
    assert _fate(third, cand)["fate"] == "demoted"
    fourth = infer(src, spec, [], tmp_path, T0, NOW, memory=third, verdicts=said, held_s=6000.0)  # the history grew by more than half
    assert _fate(fourth, cand)["fate"] == "probed" and "held history grew from 1.0 h to 1.7 h" in _fate(fourth, cand)["why"]
    assert fourth.probed[cand]["at"] > first.probed[cand]["at"] and cand not in fourth.demoted
    fifth = infer(src, spec, [], tmp_path, T0, NOW, memory=fourth, verdicts=said, held_s=6000.0)   # the same discovery: not again
    assert _fate(fifth, cand)["fate"] == "probed"
    later = {cand: {**said[cand], "at": 200.0}}                                                     # a newer discovery refutes it again
    assert _fate(infer(src, spec, [], tmp_path, T0, NOW, memory=fifth, verdicts=later, held_s=6000.0), cand)["fate"] == "demoted"


def test_a_stock_is_kept_without_a_probe_and_its_finer_splits_are_proposed_first(store, tmp_path):
    _, src, spec = store(common_store())
    first = infer(src, spec, [], tmp_path, T0, NOW)
    d = _one(first, "fam0_jobs", ["svc"])
    said = {ident(d): {"fate": "stock", "why": "discovery made it a stock", "series": "x", "at": 100.0}}
    second = infer(src, spec, [], tmp_path, T0, NOW, memory=first, verdicts=said)
    assert _fate(second, ident(d))["fate"] == "kept" and second.probed[ident(d)] == first.probed[ident(d)]
    assert any(ident(x) == ident(d) for x in second.kept)
    finer = [r for r in second.explored if "a finer split of fam0_jobs by (svc)" in r["why"]]
    assert finer and all(set(r["group_by"]) >= {"svc", "lens"} for r in finer)
    probed = [r for r in second.explored if r["fate"] == "probed"]
    assert probed[: len(finer)] == finer and second.round["proposed"] == len(finer)


def test_verdicts_read_from_a_discovery():
    ref = lambda name, **labels: SimpleNamespace(name=name, labels=labels)
    model = SimpleNamespace(
        stocks=[SimpleNamespace(series=ref("lab:q", svc="a"))],
        flows=[SimpleNamespace(counter=ref("lab:in_total"), measured_by=[], equations=[SimpleNamespace(origin="fitted")])],
        discovery={"sourced": {'lab:q{svc="a"}': {"source": "lab", "candidate": "q|sum_by||svc"},
                               'lab:q{svc="b"}': {"source": "lab", "candidate": "q|sum_by||svc"},
                               "lab:in_total": {"source": "lab", "candidate": "in|increments||"},
                               "lab:x": {"source": "lab", "candidate": "x|sum_by||"},
                               "lab:y": {"source": "lab", "candidate": "y|sum_by||"},
                               "other:x": {"source": "other", "candidate": "x|sum_by||"}},
                   "left_out": {'lab:q{svc="b"}': "no counters balance it (best R² 0.10)", "lab:x": "no counters balance it (best R² 0.2)",
                                "lab:y": "a level that did not change in the window"}})
    got = verdicts(5.0, model, "lab")
    assert {k: v["fate"] for k, v in got.items()} == {"q|sum_by||svc": "stock", "in|increments||": "flow", "x|sum_by||": "refuted"}
    assert got["x|sum_by||"]["at"] == 5.0

