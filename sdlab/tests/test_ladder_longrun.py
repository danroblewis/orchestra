"""Long-horizon evaluation (sdlab/ladder/longrun.py, jump.py): the jump-ahead equals stepping where
the model is linear, true equilibria match the analytic ones, the far future read off a settled run
equals stepping all the way, and a found model that runs away is flagged."""

from __future__ import annotations

import numpy as np
import pytest

from sdlab.discovery.simulate import Model
from sdlab.ladder import cases, data, longrun
from sdlab.ladder.jump import Affine, Jump, is_affine, power
from sdlab.skill import truth_by_time


def _truth(cid: str, variant: str = "none-short"):
    c = cases.load(cid)
    tm = cases.truth_model(c, variant)
    d = data.load(c, variant)
    return tm, d


def _step(flows, ids, x0, t1, t_end, injections=None):
    """Plain stepping, one step at a time (the reference)."""
    m = Model(flows, ids)
    times = np.arange(t1, t_end + 1, dtype=float)[:, None]
    return m.run(np.asarray(x0, float)[:, None], times, injections)[:, 0]


@pytest.mark.parametrize("cid", ["003-chain-2", "004-chain-3", "012-rework", "021-daily-inflow", "019-announced-era", "023-injection"])
def test_jump_equals_stepping_on_linear_cases(cid):
    tm, d = _truth(cid)
    ids = list(d["all_levels"])
    n = int(d["t"][-1])
    T_end = 6000
    flows, _, n0 = longrun.truth_flows(tm, n, T_end)
    assert is_affine(flows)
    x0 = np.array([d["all_levels"][s][0] for s in ids], float)
    j = Jump(Affine(flows, ids), x0, 2, n0, longrun.period(tm) or 1, d.get("injections"))
    for T in (40, 299, n0 + 7, 1000, 6000):
        want = _step(flows, ids, x0, 2, T, d.get("injections"))
        assert np.allclose(j.at(T), want, rtol=1e-9, atol=1e-7), (T, j.at(T), want)


def test_power_is_repeated_application():
    rng = np.random.default_rng(0)
    M, b = rng.normal(size=(3, 3)) * 0.3, rng.normal(size=3)
    x = rng.normal(size=3)
    y = x.copy()
    for _ in range(37):
        y = M @ y + b
    Mk, bk = power(M, b, 37)
    assert np.allclose(Mk @ x + bk, y)


def test_true_equilibria_match_the_analytic_ones():
    # 002: outside -> A at c, A -> outside at k A: A* = c / k
    tm, d = _truth("002-inflow-outflow")
    c = next(f["rate"]["value"] for f in tm["flows"] if not f.get("from"))
    k = next(f["rate"]["k"] for f in tm["flows"] if f.get("from"))
    s = longrun.Setup(tm, d)
    assert s.traj.how == "settled"
    assert s.dyn["fixed_point"][0] == pytest.approx(c / k, rel=1e-9)
    assert s.traj.at([100_000])[0, 0] == pytest.approx(c / k, rel=1e-9)
    assert s.dyn["tau"] == pytest.approx(-1 / np.log(1 - k), rel=1e-9)
    # 003: A* = in / k_ab, B* = k_ab A* / k_b
    tm, d = _truth("003-chain-2")
    by = {f["id"]: f["rate"] for f in tm["flows"]}
    a = by["in"]["value"] / by["ab"]["k"]
    b = by["ab"]["k"] * a / by["b_out"]["k"]
    s = longrun.Setup(tm, d)
    assert np.allclose(s.dyn["fixed_point"], [a, b], rtol=1e-9)
    assert np.allclose(s.traj.at([10_000, 100_000])[:, 1], [a, b], rtol=1e-9)


@pytest.mark.parametrize("cid", ["021-daily-inflow", "017-linear-effect", "025-runs-empty"])
def test_far_future_read_off_equals_stepping(cid):
    """Settled (periodic) runs answer any step in constant time; it must equal stepping there,
    affine or not (effects, a floor that binds)."""
    tm, d = _truth(cid)
    s = longrun.Setup(tm, d, t_end=8000)
    assert s.traj.how == "settled" and s.traj.t_sim < 8000
    want = _step(s.flows, s.ids, s.x0, s.t1, 8000, d.get("injections"))
    assert np.allclose(s.traj.at([8000])[:, 0], want, rtol=1e-8, atol=1e-8)


def test_schedule_laid_out_far_ahead_matches_the_truth():
    for cid in ("019-announced-era", "021-daily-inflow", "022-pulse"):
        tm, d = _truth(cid)
        flows, _, _ = longrun.truth_flows(tm, int(d["t"][-1]), 3000)
        ref, _ = truth_by_time(tm, list(range(1, 3001)))
        ts = np.arange(1, 3001, dtype=float)[:, None]
        L = np.full((len(d["all_levels"]), 1), 50.0)
        ids = list(d["all_levels"])
        assert np.allclose(Model(flows, ids).run(L, ts), Model(ref, ids).run(L, ts))


@pytest.mark.parametrize("cid", ["001-inflow-only", "003-chain-2", "019-announced-era", "024-floor-binds"])
def test_the_truth_written_as_found_has_no_long_run_error(cid):
    tm, d = _truth(cid)
    s = longrun.Setup(tm, d)
    found, _ = truth_by_time(tm, d["t"])                  # the truth as a perfect discovery writes it
    g = longrun.grade(s, found)
    assert g["flag"] is None and not g["hard_fail"]
    assert all(v is not None and v < 1e-9 for v in g["err"].values()), g["err"]
    assert g["eq_err"] is not None and g["eq_err"] < 1e-9


def test_a_found_model_that_runs_away_is_flagged():
    tm, d = _truth("002-inflow-outflow")
    s = longrun.Setup(tm, d)
    # an inflow that grows with A faster than A drains: x' = 1.03 x + 20
    found = [{"from": None, "to": "A", "rate": {"form": "linear", "c": 20, "terms": [{"stock": "A", "k": 0.05}]}},
             {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.02}}]
    g = longrun.grade(s, found)
    assert g["flag"] in ("runaway", "unstable") and g["hard_fail"]
    assert g["unstable"] and g["rho_found"] == pytest.approx(1.03, rel=1e-9)
    assert g["eq_err"] is None and g["far"] is None


def test_a_found_model_that_settles_wrong_is_graded_by_its_equilibrium():
    tm, d = _truth("002-inflow-outflow")
    s = longrun.Setup(tm, d)
    k = next(f["rate"]["k"] for f in tm["flows"] if f.get("from"))
    found = [{"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": k * 1.25}}]   # inflow from the truth
    g = longrun.grade(s, found)
    assert g["flag"] is None
    assert g["eq_err"] == pytest.approx(0.2 * (s.dyn["fixed_point"][0]) / max(s.scale[0], s.dyn["fixed_point"][0]), rel=1e-6)
    assert g["tau_err"] > 0.2


def test_a_one_step_piece_at_the_runs_end_does_not_hold_for_ever():
    f = {"from": None, "to": "B", "rate": {"form": "constant", "value": 7.7},
         "inflow": [{"from": 2, "to": 1999, "value": 7.7}, {"from": 2000, "to": 2000, "value": 22.6}]}
    ext = longrun.extend(f, 2000, None, 100_000)
    assert ext["inflow"][-1] == {"from": 2001, "to": 100_000, "value": 7.7}
    assert ext["inflow"][1]["value"] == 22.6                         # the run itself is unchanged
    held = {**f, "inflow": [{"from": 2, "to": 1000, "value": 7.7}, {"from": 1001, "to": 2000, "value": 9.0}]}
    assert longrun.extend(held, 2000, None, 100_000) is held          # a lasting last piece holds as it is


def test_a_mode_too_slow_to_double_within_the_horizon_is_not_unstable():
    tm, d = _truth("002-inflow-outflow")
    s = longrun.Setup(tm, d)
    # A' = A + 1e-7 A: grows by 1% in 100,000 steps
    found = [{"from": None, "to": "A", "rate": {"form": "proportional", "stock": "A", "k": 1e-7}}]
    g = longrun.grade(s, found)
    assert not g["unstable"] and g["rho_found"] > 1
