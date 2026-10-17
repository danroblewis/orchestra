"""Mechanism test for the behaviour-consistency gate (sdlab/discovery/gate.py, strategy `gated`;
docs/research/behaviour-consistency.md).

- A wrong candidate that wins the judge in-sample (a spurious reinforcing loop on the stock, with
  outside-inflow pieces that replay the run) is rejected by the gate, and the right one is chosen;
  the culprit it names is the loop's coefficient.
- A trap of the playbook's kind (a positive own coefficient beside a constant) is rejected, and the
  bounded refit of the culprit recovers the true drain.
- Controls: a growing population passes and keeps its growth; a truth whose linear part is unstable
  but held by floors and caps (sd-manufacturing's structure) passes, and `gated` chooses as `matrix`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from sdlab.discovery.flows import read_flows
from sdlab.discovery.gate import check, choose, jacobian
from sdlab.discovery.identify import judge
from sdlab.discovery.simulate import Model
from sdlab.discovery.strategies import load
from sdlab.discovery.strategies.gated import refit
from synth import generate, skill

EXAMPLES = Path(__file__).resolve().parents[1] / "sdlab" / "examples"
DRAIN = [{"id": "in", "from": None, "to": "x", "rate": {"form": "constant", "value": 10}},
         {"id": "out", "from": "x", "to": None, "rate": {"form": "proportional", "stock": "x", "k": 0.1}}]
SHIFTS = {"every": 0, "changes": [{"t": 150, "set": {"in": {"form": "constant", "value": 20}}},
                                  {"t": 300, "set": {"in": {"form": "constant", "value": 5}}},
                                  {"t": 450, "set": {"in": {"form": "constant", "value": 12}}}]}


def replaying_trap(run: dict, k: float) -> list[dict]:
    """x grows with itself at k; outside inflows, one piece per step, make up the rest of every
    step's change (in-sample they replay the run exactly)."""
    x = np.asarray(run["levels"]["x"], dtype=float)
    t = run["t"]
    res = np.diff(x) - k * x[:-1]
    seg = lambda v: [{"from": t[i + 1], "to": t[i + 1], "value": float(a)} for i, a in enumerate(v)]
    return [{"from": None, "to": "x", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "x", "k": k}]}, "driver": "x"},
            {"from": None, "to": "x", "rate": {"form": "constant", "value": 1}, "inflow": seg(np.maximum(0, res))},
            {"from": "x", "to": None, "rate": {"form": "constant", "value": 1}, "inflow": seg(np.maximum(0, -res))}]


@pytest.fixture(scope="module")
def shifting():
    return generate([{"id": "x", "initial": 100}], DRAIN, steps=600, schedule=SHIFTS)


def test_a_replaying_loop_wins_the_judge_but_not_the_gate(shifting):
    d = shifting
    right = load("matrix")(d["stocks"], d["run"], {})
    trap = replaying_trap(d["run"], 0.02)
    # the in-sample judge prefers the trap (it replays the run), though it behaves far worse
    assert judge(trap, d["stocks"], d["run"]) < 0.5 * judge(right["flows"], d["stocks"], d["run"])
    assert skill({"flows": trap}, d) < -1 < 0 < skill(right, d)
    v = check(trap, d["stocks"], d["run"])
    assert not v["ok"]
    assert {"observed"} <= {r["test"] for r in v["reasons"]}
    assert v["culprit"]["row"] == "x" and v["culprit"]["level"] == "x" and v["culprit"]["k"] == pytest.approx(0.02, abs=1e-4)
    assert check(right["flows"], d["stocks"], d["run"])["ok"]
    ch = choose([("trap", trap), ("right", right["flows"])], d["stocks"], d["run"], judge)
    assert ch["best"] == 1 and ch["passed"] == 1


def test_a_positive_own_coefficient_is_refitted_to_the_true_drain():
    d = generate([{"id": "x", "initial": 100}], DRAIN, steps=1000)
    run, stocks = d["run"], d["stocks"]
    x = np.asarray(run["levels"]["x"], dtype=float)
    prev, T = x[:-1], len(x) - 1
    c = float((np.diff(x) - 0.02 * prev).mean())                      # the trap: +0.02 x plus a constant
    rows = [{"id": "x", "coef": {"x": 0.02}, "inflow": [{"from": run["t"][1], "to": run["t"][-1], "value": c}]}]
    trap = {"flows": read_flows(stocks, rows, prev[None, :]), "matrix": [{**rows[0], "coefL": [{"x": 0.02}], "cuts": [0, T]}]}
    v = check(trap["flows"], stocks, run)
    assert not v["ok"] and v["culprit"]["row"] == "x" and v["culprit"]["level"] == "x"
    r = refit(stocks, run, trap, v["culprit"])
    assert -r["matrix"][0]["coef"]["x"] == pytest.approx(0.1, abs=0.02)
    assert r["matrix"][0]["inflow"][0]["value"] == pytest.approx(10, abs=2)
    assert check(r["flows"], stocks, run)["ok"]


def test_a_growing_population_passes_and_keeps_its_growth():
    flows = [{"id": "births", "from": None, "to": "adults", "rate": {"form": "proportional", "stock": "adults", "k": 0.02}},
             {"id": "deaths", "from": "adults", "to": None, "rate": {"form": "proportional", "stock": "adults", "k": 0.01}}]
    d = generate([{"id": "adults", "initial": 100}], flows, steps=300)
    v = check(flows, d["stocks"], d["run"])
    assert v["ok"] and v["rho"] > 1.005
    r = load("gated")(d["stocks"], d["run"], {})
    assert r["gate"]["passed"] == r["gate"]["candidates"]
    assert check(r["flows"], d["stocks"], d["run"])["rho"] > 1.005
    assert skill(r, d) > 0.95


def test_an_unstable_linear_part_held_by_floors_and_caps_passes():
    truth = json.loads((EXAMPLES / "sd-manufacturing" / "truth.model.json").read_text())
    stocks = [{"id": s["id"], "initial": s["initial"]} for s in truth["stocks"]]          # all measured
    flows = [{k: f[k] for k in ("id", "from", "to", "rate") if k in f} for f in truth["flows"]]
    ids = [s["id"] for s in stocks]
    J = jacobian(Model(flows, ids), np.array([float(s["initial"]) for s in stocks]), 1.0)
    assert max(abs(np.linalg.eigvals(J))) > 1.04                      # the linear part grows
    schedule = {"every": 0, "changes": [{"t": t, "set": {"demand": {"form": "constant", "value": v}}} for t, v in ((200, 30), (400, 12), (600, 25))]}
    d = generate(stocks, flows, steps=1000, schedule=schedule)
    assert check(flows, d["stocks"], d["run"])["ok"]                  # floors and caps hold it
    plain, gated = load("matrix")(d["stocks"], d["run"], {}), load("gated")(d["stocks"], d["run"], {})
    assert gated["chosen"] == plain["chosen"]
    assert skill(gated, d) == pytest.approx(skill(plain, d))
