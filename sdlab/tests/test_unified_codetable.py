"""Code-table versions of the unified objective (sdlab/discovery/strategies/unified/codetable.py):
parsing, v1 as the unchanged default, and what each noise option does to a fit (held eta, phi held,
tau priced, the phi prior, the joint and lean data-set eta)."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

pytest.importorskip("jax")

from sdlab.discovery.strategies.unified import codetable as ct  # noqa: E402
from sdlab.discovery.strategies.unified import objective as ob  # noqa: E402
from sdlab.discovery.strategies.unified.frontend import grid_of  # noqa: E402
from sdlab.ladder import cases, data  # noqa: E402
from sdlab.ladder.objective_test import view_of  # noqa: E402
from sdlab.skill import truth_by_time  # noqa: E402


def _cell(cid: str, v: str):
    c = cases.load(cid)
    tm = cases.truth_model(c, v)
    d = data.load(c, v)
    view = view_of(tm, d)
    g = grid_of(view)
    flows, _ = truth_by_time(tm, [int(x) for x in g.times])
    return view, g, flows


@pytest.fixture(scope="module")
def chain():
    view, g, flows = _cell("003-chain-2", "counts-short")
    return view, g, flows, ob.prepare(view, flows, grid=g)


def test_parse_names_and_conflicts(monkeypatch):
    assert ct.parse(None).is_v1 and ct.parse("v1").name == "v1"
    assert ct.parse("v2-tau-priced").tau_priced
    assert ct.parse("v2-phi-prior").phi_prior == ct.PHI_PRIOR_WIDTH
    assert ct.parse("v2-phi-prior=0.5").phi_prior == 0.5
    t = ct.parse("v2-tau-priced+phi-lean")
    assert (t.held, t.source, t.tau_priced) == ("phi", "lean", True)
    assert t.name == "v2-phi-lean+tau-priced" and ct.parse(t.name) == t     # canonical, round trips
    assert ct.parse("v2-eta-joint").held_index(2) == list(range(9)) and ct.parse("v2-phi-joint").held_index(2) == [0]
    for bad in ("v3", "v2-", "v2-eta-lean+phi-lean", "v2-eta-lean+tau-priced", "v2-phi-lean+phi-prior", "v2-phi-prior=0", "v2-tau"):
        with pytest.raises(ValueError):
            ct.parse(bad)
    monkeypatch.delenv(ct.ENV, raising=False)
    assert ct.active().is_v1
    monkeypatch.setenv(ct.ENV, "v2-tau-priced")
    assert ct.active().name == "v2-tau-priced"


def test_cache_dir_follows_the_table(monkeypatch):
    from sdlab.ladder.objective_test import cache_dir
    monkeypatch.delenv(ct.ENV, raising=False)
    assert cache_dir().name.startswith("v1-")
    monkeypatch.setenv(ct.ENV, "v2-phi-prior")
    assert cache_dir().name.startswith("v2-phi-prior-")


def test_v1_is_the_default_and_unpriced(chain, monkeypatch):
    view, g, flows, m = chain
    monkeypatch.delenv(ct.ENV, raising=False)
    a = ob.fit(m, [m.theta0])
    b = ob.fit(m, [m.theta0], table=ct.Table())
    assert a["J"] == b["J"] and a["eta"] == b["eta"]
    assert "P_eta" not in a
    assert a["J"] == pytest.approx(a["D"] + a["P_num"] + a["P_struct"], abs=0)


def test_held_eta_is_held(chain):
    view, g, flows, m = chain
    free = ob.fit(m, [m.theta0], table=ct.Table())
    held = np.asarray(free["eta"]) + 0.3
    r = ob.fit(m, [m.theta0], held=held, table=ct.parse("v2-eta-lean"))
    assert np.allclose(r["eta"], held)                       # every component held
    assert r["D"] >= free["D"] - 1e-6                        # held away from the optimum: no better
    r0 = ob.fit(m, [m.theta0], fit_theta=False, held=held, table=ct.parse("v2-eta-lean"))
    assert r0["D"] == pytest.approx(m.D(m.theta0, held))     # nothing free: an evaluation
    p = ob.fit(m, [m.theta0], held=held, table=ct.parse("v2-phi-joint"))
    assert p["eta"][0] == held[0] and not np.allclose(p["eta"][1:], held[1:])   # only phi held
    assert p["held"] == [0]


def test_tau_priced_stays_off_on_counted_truth_and_comes_on_for_a_missing_flow(chain):
    view, g, flows, m = chain
    t = ct.parse("v2-tau-priced")
    r = ob.fit(m, [m.theta0], table=t)
    assert r["tau_on"] == [] and r["P_eta"] == 0.0           # counting noise explains the innovations
    assert all(v < 1e-10 * float(np.max(g.scale)) ** 2 for v in r["eta_read"]["tau"].values())
    lean = copy.deepcopy(flows)
    drop = max(range(len(lean)), key=lambda i: lean[i].get("from") is not None and lean[i].get("to") is not None)
    del lean[drop]                                           # the chain's move: the stocks lose their link
    mm = ob.prepare(view, lean, grid=g)
    r2 = ob.fit(mm, [mm.theta0], table=t)
    assert r2["tau_on"], "a missing flow leaves innovations counting noise does not explain"
    assert r2["P_eta"] == pytest.approx(sum(ob.tau_price(mm, i) for i in r2["tau_on"]))
    assert r2["J"] == pytest.approx(r2["D"] + r2["P_num"] + r2["P_struct"] + r2["P_eta"])
    assert ob.tau_price(mm, 2) == pytest.approx(0.5 * math.log(np.isfinite(g.y[1:, 0]).sum()))


def test_phi_prior_is_charged_and_pulls_phi_to_one(chain):
    view, g, flows, m = chain
    free = ob.fit(m, [m.theta0], table=ct.Table())
    w = 0.05
    r = ob.fit(m, [m.theta0], table=ct.parse(f"v2-phi-prior={w}"))
    lp = r["eta"][0]
    assert r["P_eta"] == pytest.approx(0.5 * (lp / w) ** 2)
    assert r["J"] == pytest.approx(r["D"] + r["P_num"] + r["P_struct"] + r["P_eta"])
    assert abs(lp) <= abs(free["eta"][0]) + 1e-9


def test_joint_eta_of_one_candidate_is_its_own(chain):
    view, g, flows, m = chain
    t = ct.parse("v2-eta-joint")
    free = ob.fit(m, [m.theta0], table=ct.Table())
    j = ob.joint_eta([(m, free["theta"], free["eta"]), (m, free["theta"], free["eta"])], t)
    assert j["candidates"] == 2
    assert j["sum_D"] <= 2 * free["D"] + 1e-6               # the shared optimum is its own (at least as good)
    assert j["sum_D"] == pytest.approx(2 * free["D"], abs=0.05)


def test_lean_model_and_its_eta(chain):
    view, g, flows, m = chain
    fl = ob.lean_flows(view)
    assert len(fl) == 2 * len(view["stocks"])
    r = ob.lean_eta(view, g, ct.parse("v2-eta-lean"))
    assert len(r["eta"]) == len(m.eta_vector(ob.ETA_STARTS[0])) and "held" not in r   # lean fits with nothing held (v1 table)


def test_exact_cells_select_only_those():
    from sdlab.ladder.objective_test import cells_for
    got = cells_for(None, None, None, "007@counts-short,048#1@counts-short,141@none-short")
    assert got == [("007-link", "counts-short"), ("048-random-stepping-inflow-drain#1", "counts-short"), ("141-noisy-offset-oscillator", "none-short")]
    with pytest.raises(SystemExit):
        cells_for(None, None, None, "081@counts-medium")


def test_cells_from_a_cache_folder(tmp_path, monkeypatch):
    import json as _json

    from sdlab.ladder.objective_test import cells_of
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path))
    f = tmp_path / "objective_test" / "v1-base"
    f.mkdir(parents=True)
    (f / "a.json").write_text(_json.dumps({"case": "007-link", "variant": "counts-short"}))
    (f / "b.json").write_text("not json")
    assert cells_of("v1-base") == [("007-link", "counts-short")]
    with pytest.raises(SystemExit):
        cells_of("v1-missing")
