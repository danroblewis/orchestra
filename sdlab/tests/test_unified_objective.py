"""The unified objective (sdlab/discovery/strategies/unified/) on small cases whose outcome is known
(docs/research/unified-design.md, 7.2): the leakage guard, the engine replica, the alpha = 0 corner
(D equals fisher.TruthParams.nll up to the bin constant), and three orderings the objective must get
right: the truth beats the truth without a flow, the truth beats the truth with a spurious link, and
on a noise-free run the truth beats a model with an extra (unneeded) inflow piece."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

pytest.importorskip("jax")

from sdlab.discovery.strategies.unified import objective as ob  # noqa: E402
from sdlab.discovery.strategies.unified.engine import make_step  # noqa: E402
from sdlab.discovery.strategies.unified.frontend import build, check_view, grid_of  # noqa: E402
from sdlab.discovery.strategies.unified.kalman import bin_constant  # noqa: E402
from sdlab.ladder import cases, data  # noqa: E402
from sdlab.ladder.objective_test import view_of  # noqa: E402
from sdlab.skill import truth_by_time  # noqa: E402

CORNER = {"ln_phi": 0.0, "logit_beta": -12.0, "ln_tau": -40.0, "ln_alpha": -40.0, "ln_rho2": -40.0}


def _cell(cid: str, v: str):
    c = cases.load(cid)
    tm = cases.truth_model(c, v)
    d = data.load(c, v)
    view = view_of(tm, d)
    g = grid_of(view)
    flows, _ = truth_by_time(tm, [int(x) for x in g.times])
    return tm, d, view, g, flows


def test_leakage_guard():
    tm, d, view, g, flows = _cell("003-chain-2", "counts-short")
    check_view(view)
    with pytest.raises(AssertionError):
        check_view({**view, "all_levels": d["all_levels"]})
    with pytest.raises(AssertionError):
        grid_of({**view, "counters": {}})


@pytest.mark.parametrize("cid", ["003-chain-2", "016-coflow", "024-floor-binds", "017-linear-effect", "023-injection"])
def test_engine_replica(cid):
    """Stepped noise-free from the first report, the compiled truth reproduces the engine's run."""
    tm, d, view, g, flows = _cell(cid, "none-short")
    st = build(view, flows, grid=g)
    import jax.numpy as jnp
    step = make_step(st)
    th = jnp.concatenate([jnp.asarray(st.theta0()), jnp.zeros(1)])
    x = jnp.asarray(g.y[0])
    inj = {(t, s): a for t, s, a in g.injections}
    worst = 0.0
    for k in range(1, len(g.times)):
        for j, s in enumerate(st.ids):
            if (int(g.times[k]), s) in inj:
                x = x.at[j].set(max(0.0, float(x[j]) + inj[(int(g.times[k]), s)]))
        x, _ = step(th, x, jnp.asarray(st.tidx[k]), jnp.zeros(0))
        x = jnp.asarray(np.round(np.asarray(x), 4))          # the engine's levels are written to 4 decimals
        worst = max(worst, float(np.max(np.abs(np.asarray(x) - g.y[k]) / (np.abs(g.y[k]) + 1))))
    assert worst < 1e-3, worst


@pytest.mark.parametrize("cid", ["003-chain-2", "007-link", "016-coflow"])
def test_alpha_zero_corner(cid):
    """alpha = rho2 = tau = 0, phi = 1, every stock reported: D is the one-step LNA likelihood
    (fisher.TruthParams.nll, a density, plus its 1/2 ln 2 pi per report) up to the bin constant."""
    from sdlab.ladder.fisher import TruthParams
    tm, d, view, g, flows = _cell(cid, "counts-short")
    m = ob.prepare(view, flows, grid=g)
    D = m.D(m.theta0, m.eta_vector(CORNER))
    tp = TruthParams(tm, d, "counts")
    ref = tp.nll(tp.theta0) + 0.5 * g.n_reports * math.log(2 * math.pi)
    assert abs((D + bin_constant(g)) - ref) / g.n_reports < 2e-3


def _fit_J(view, g, flows) -> float:
    m = ob.prepare(view, flows, grid=g)
    return ob.fit(m, [m.theta0])["J"]


def test_truth_beats_a_missing_flow():
    tm, d, view, g, flows = _cell("003-chain-2", "counts-short")
    without = [f for f in flows if f["id"] != "b_out"]
    assert _fit_J(view, g, without) - _fit_J(view, g, flows) > 10       # ~86 nats: tau absorbs much of the missing drain (risk R2)


def test_truth_beats_a_spurious_link():
    tm, d, view, g, flows = _cell("003-chain-2", "counts-short")
    link = {"id": "spur", "from": None, "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.01}}
    assert _fit_J(view, g, flows + [link]) - _fit_J(view, g, flows) > 0.5


def test_truth_beats_an_unneeded_piece():
    """Noise-free: a cut in the outside inflow that the data does not need costs its price."""
    tm, d, view, g, flows = _cell("003-chain-2", "none-short")
    pieced = copy.deepcopy(flows)
    f = next(x for x in pieced if x["id"] == "in")
    f.pop("byTime", None)
    f["inflow"] = [{"from": 1, "to": 150, "value": 20.0}, {"from": 151, "to": 300, "value": 20.0001}]
    assert _fit_J(view, g, pieced) - _fit_J(view, g, flows) > 0.5


def test_labels_of_a_cell():
    """The harness's labels (objective_test._label): the first that applies, the worst per cell."""
    from sdlab.ladder.objective_test import _label, signature
    T = {"J": 100.0, "D": 90.0, "P_num": 5.0, "P_struct": 5.0, "converged": True, "restarts_agree": True,
         "complexity": {"cuts": 0, "flows": 3, "numbers": 3}, "eta_read": {"phi": 1.0, "tau": {"A": 0.0}}}

    def g(delta, **kw):
        fit = {"J": 100 + delta, "complexity": {"cuts": 2, "flows": 3, "numbers": 5}, "eta_read": {"phi": 1.0, "tau": {"A": 0.0}}}
        return {"fit": fit, "delta": delta, "delta_parts": {"D": delta - 1, "P_num": 0.5, "P_struct": 0.5},
                "delta_bic": delta, "source": "store", "right": False, **kw}

    cell = {"Tstar": T, "analysis": "achievable", "sanity": {"ok": True},
            "groups": {"a": g(5.0), "b": g(0.2), "c": g(-3.0), "d": g(-3.0, refit_status="pass"), "e": g(-9.0, right=True)}}
    _label(cell, 0.5)
    lab = {k: v["label"] for k, v in cell["groups"].items()}
    assert lab == {"a": "OK", "b": "TIE-unexplained", "c": "E", "d": "X", "e": "right"}
    assert cell["label"] == "E" and cell["groups"]["c"]["mechanism"] == ["extra pieces"]
    cell["analysis"] = "data-limited"
    _label(cell, 0.5)
    assert cell["groups"]["c"]["label"] == "L"
    f1 = [{"from": None, "to": "A", "rate": {"form": "constant", "value": 3}}, {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.1}}]
    f2 = [{"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.2}}, {"from": None, "to": "A", "rate": {"form": "constant", "value": 5}}]
    assert signature(f1) == signature(f2)
