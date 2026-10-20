"""The objective test's labelling fixes (docs/research/unified-objective-test.md, "Harness fixes"):
write-back of a schedule slot shared by several segments, hidden-name-free signatures, rightness from
the truth's structure and from the refit, F and L order, beats_scaled -> F, the measurement-error
plausibility check on the combined variance, and X out of the A-bic comparison."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from sdlab.discovery.strategies.unified.frontend import build, write_back
from sdlab.ladder.objective_labels import label, merge_groups, plausible
from sdlab.ladder.objective_test import signature


def _view(n=10):
    return {"stocks": [{"id": "A"}], "t": list(range(n)), "levels": {"A": [10.0 + i for i in range(n)]}}


def test_write_back_fills_every_tied_segment():
    """byTime segments 1 and 3 share a value, so one slot; both get its fitted number, and segment 3's
    other reader is kept (it was dropped when only the first tied segment was written)."""
    flows = [{"from": None, "to": "A", "byTime": [
        {"from": 0, "rate": {"form": "linear", "c": 5.0, "terms": [{"stock": "A", "k": 0.1}]}},
        {"from": 3, "rate": {"form": "constant", "value": 7.0}},
        {"from": 6, "rate": {"form": "linear", "c": 5.0, "terms": [{"stock": "A", "k": 0.2}]}}]}]
    st = build(_view(), flows)
    th = st.theta0().copy()
    tied = [i for i, sl in enumerate(st.slots) if sl.kind == "coef" and sl.path[2] is None and sl.value == 5.0]
    assert len(tied) == 1 and len(st.slots[tied[0]].more) == 1
    th[tied[0]] = 6.5
    out = write_back(st, th)[0]["byTime"]
    assert out[0]["rate"]["c"] == 6.5 and out[2]["rate"]["c"] == 6.5
    assert out[1]["rate"] == {"form": "constant", "value": 7.0}
    assert [t["k"] for t in out[2]["rate"]["terms"]] == [0.2]


def test_signature_ignores_hidden_names():
    def model(h):
        return [{"from": None, "to": h, "rate": {"form": "constant", "value": 3}},
                {"from": h, "to": "A", "rate": {"form": "proportional", "stock": h, "k": 0.1}},
                {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.2}}]
    assert signature(model("H"), {"A"}) == signature(model("pipe"), {"A"})
    assert signature(model("H")) != signature(model("pipe"))            # without `known`: names count
    plain = [{"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.2}}]
    assert signature(plain, {"A"}) == signature(plain)                 # no hidden stock: unchanged
    other = [{"from": None, "to": "B", "rate": {"form": "constant", "value": 3}}]
    assert signature(other, {"A", "B"}) != signature([{"from": None, "to": "A", "rate": {"form": "constant", "value": 3}}], {"A", "B"})


def _T():
    return {"J": 100.0, "D": 90.0, "P_num": 5.0, "P_struct": 5.0, "converged": True, "restarts_agree": True,
            "complexity": {"cuts": 0, "flows": 3, "numbers": 3}, "eta_read": {"phi": 1.0, "tau": {"A": 0.0}}}


def _g(delta, **kw):
    fit = {"J": 100 + delta, "complexity": {"cuts": 2, "flows": 3, "numbers": 5}, "eta_read": {"phi": 1.0, "tau": {"A": 0.0}}}
    return {"fit": fit, "delta": delta, "delta_parts": {"D": delta - 1, "P_num": 0.5, "P_struct": 0.5},
            "delta_bic": delta, "source": "store", "statuses": ["fail"], **kw}


def _cell(groups, analysis="achievable", checks=None):
    ch = checks or {"refit_no_worse": True, "beats_scaled": True, "eta_plausible": True, "innovations": True}
    return {"Tstar": _T(), "analysis": analysis, "sanity": {"ok": all(ch.values()), "checks": ch}, "groups": groups}


def test_rightness_from_truth_structure_and_refit():
    cell = _cell({"stored_right_refit_fails": _g(-3.0, statuses=["pass", "pass"], refit_status="fail"),
                  "stored_right_refit_unscored": _g(-3.0, statuses=["pass"], refit_status="unscored"),
                  "truth_renamed": _g(-3.0, statuses=["fail"], refit_status="fail", truth_structure=True)})
    label(cell, 0.5)
    lab = {k: v["label"] for k, v in cell["groups"].items()}
    assert lab == {"stored_right_refit_fails": "E", "stored_right_refit_unscored": "right", "truth_renamed": "right"}


def test_limited_before_fitbad_and_scaled_gives_F():
    groups = {"w": _g(-3.0)}
    cell = _cell(groups, analysis="data-limited")
    cell["Tstar"]["restarts_agree"] = False
    label(cell, 0.5)
    assert cell["groups"]["w"]["label"] == "L"
    cell = _cell({"w": _g(-3.0)}, checks={"refit_no_worse": True, "beats_scaled": False, "eta_plausible": True, "innovations": True})
    label(cell, 0.5)
    assert cell["groups"]["w"]["label"] == "F" and cell["label"] == "F"
    cell = _cell({"w": _g(-3.0)}, checks={"refit_no_worse": False, "beats_scaled": True, "eta_plausible": True, "innovations": True})
    label(cell, 0.5)
    assert cell["groups"]["w"]["label"] == "F"


def test_X_is_not_a_bic_failure():
    cell = _cell({"x": _g(-3.0, refit_status="pass"), "ok": _g(4.0)})
    label(cell, 0.5)
    assert cell["groups"]["x"]["label"] == "X" and cell["label_bic"] == "OK" and cell["label"] == "OK"


def test_meas_plausibility_uses_the_combined_error():
    """meas rel 0.05, abs 1 at level ~100: the error variance is 1 + 25 = 26. A fit that puts it all in
    alpha (alpha 26, rho2 0) is plausible; one at a tenth of it is not."""
    y = np.full((20, 1), 100.0)
    grid = SimpleNamespace(ids=["A"], q=np.array([1e-4]), scale=np.array([100.0]), y=y)
    v = {"noise": "meas", "observe": {"kind": "meas", "rel": 0.05, "abs": 1.0}}
    eta = {"phi": 1.0, "tau": {"A": 0.0}, "alpha": {"A": 26.0}, "rho2": {"A": 0.0}}
    assert plausible(eta, v, grid)[0]
    assert not plausible({**eta, "alpha": {"A": 2.6}}, v, grid)[0]
    assert plausible({**eta, "alpha": {"A": 1.0}, "rho2": {"A": 0.0025}}, v, grid)[0]
    zero = {"noise": "meas", "observe": {"kind": "meas", "rel": 0.0, "abs": 0.0}}
    assert not plausible(eta, zero, grid)[0] and plausible({**eta, "alpha": {"A": 0.0}}, zero, grid)[0]


def test_merge_groups_keeps_the_best_fit_and_pools_members():
    a = {**_g(2.0), "strategies": ["s1"], "statuses": ["fail"]}
    b = {**_g(-1.0), "strategies": ["s2"], "statuses": ["pass"]}
    alt = {**_g(0.0), "source": "alternative", "strategies": [], "statuses": ["fail"]}
    out = merge_groups({"a": a, "b": b, "alt0-x": alt}, lambda sig, g: "same" if sig in ("a", "b") else sig)
    assert set(out) == {"same", "alt0-x"}
    assert out["same"]["delta"] == -1.0 and out["same"]["strategies"] == ["s1", "s2"] and out["same"]["statuses"] == ["fail", "pass"]


def test_outcome():
    from sdlab.ladder.objective_labels import outcome
    cell = _cell({"x": _g(-3.0, refit_status="pass"), "ok": _g(4.0)})
    label(cell, 0.5)
    cell["done"] = True
    assert outcome(cell) == "truth best"
    cell["groups"]["w"] = _g(-1.0)
    label(cell, 0.5)
    assert outcome(cell) == "equivalent winner"           # the X group is the J-best
    cell["groups"]["w"] = _g(-5.0)
    label(cell, 0.5)
    assert outcome(cell) == "wrong winner"
