"""Experiment "held-out judge" (docs/DISCOVERY-EXPERIMENTS.md): choosing among candidate models on
data they were not fitted on (blocked cross-validation, sdlab/discovery/holdout.py).

What the mechanism does, in isolation:
  - a candidate whose outside-inflow pieces compensate for a misread flow (births read as a move
    adults -> children, paid back by a large changing inflow into adults) fits its own data best,
    and the in-sample judge (the main line, `matrix`) picks it; fitted on the other blocks, its
    pieces do not carry over, and held out it is the worst candidate, so it is not picked;
  - but the same is true of any candidate whose outside inflow really changes: held out, its pieces
    are a stale guess, so the held-out judge prefers constant inflows even when they are wrong.
    That is what sinks it on the bench, which feeds every model the truth's outside inflows.
"""

from __future__ import annotations

from synth import generate, skill

from sdlab.discovery.holdout import blocks, fill_gaps
from sdlab.discovery.identify import identify as in_sample
from sdlab.discovery.strategies.held_out import identify as held_out

TRAP = "changing inflows, receivers trusted always"
VARIANTS = [
    {"name": TRAP, "slack": 1e9},                       # the pre-fix rule: receivers trusted whatever it costs
    {"name": "changing inflows, trust rows", "trust_receivers": False},
    {"name": "constant inflows", "changes": False},
]


def population(steps: int, seed: int) -> dict:
    stocks = [{"id": "children", "initial": 3000}, {"id": "adults", "initial": 10000}]
    flows = [
        {"id": "births", "from": None, "to": "children", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "adults", "k": 0.022}]}},
        {"id": "grow", "from": "children", "to": "adults", "rate": {"form": "proportional", "stock": "children", "k": 0.056}},
        {"id": "die", "from": "adults", "to": None, "rate": {"form": "proportional", "stock": "adults", "k": 0.02}},
        {"id": "arrive", "from": None, "to": "adults", "rate": {"form": "constant", "value": 80}},
    ]
    ch = [{"t": 1, "set": {"arrive": {"form": "constant", "value": 80}}}, {"t": 150, "set": {"arrive": {"form": "constant", "value": 160}}}]
    return generate(stocks, flows, steps, schedule={"every": 300, "changes": ch}, seed=seed)


def inflow_mean(r: dict, stock: str) -> float:
    f = next(f for f in r["flows"] if f.get("inflow") and f.get("to") == stock)
    w = [g["to"] - g["from"] + 1 for g in f["inflow"]]
    return sum(g["value"] * k for g, k in zip(f["inflow"], w)) / sum(w)


def test_held_out_judge_rejects_a_candidate_whose_pieces_compensate_for_a_misread_flow():
    d = population(600, 3)
    base = in_sample(d["stocks"], d["run"], {"variants": VARIANTS})
    r = held_out(d["stocks"], d["run"], {"variants": VARIANTS})
    # in sample, the trap fits best: births read as a move adults -> children, and adults' outside
    # inflow raised to ~234 a step (truth: 80, then 160) to pay for it
    assert base["chosen"] == TRAP
    assert any(f.get("from") == "adults" and f.get("to") == "children" for f in base["flows"])
    assert inflow_mean(base, "adults") > 200
    # held out, the trap is the worst candidate, and the one chosen reads births as following adults
    errors = {x["name"]: x["error"] for x in r["tried"]}
    assert max(errors, key=errors.get) == TRAP
    assert r["chosen"] != TRAP
    births = [f for f in r["flows"] if f.get("to") == "children" and f.get("driver") == "adults"]
    assert births and abs(births[0]["rate"]["terms"][0]["k"] - 0.022) < 0.004
    assert not any(f.get("from") == "adults" and f.get("to") == "children" for f in r["flows"])
    # graded: in-sample pick 65.6% skill@20, held-out pick 73.7%
    assert skill(r, d) > skill(base, d)


def tickets(steps: int, seed: int) -> dict:
    stocks = [{"id": "customers", "initial": 4600}, {"id": "tickets", "initial": 60}]
    flows = [
        {"id": "signups", "from": None, "to": "customers", "rate": {"form": "constant", "value": 25}},
        {"id": "leave", "from": "customers", "to": None, "rate": {"form": "proportional", "stock": "customers", "k": 0.005}},
        {"id": "opened", "from": None, "to": "tickets", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "customers", "k": 0.012}]}},
        {"id": "bugs", "from": None, "to": "tickets", "rate": {"form": "constant", "value": 0}},
        {"id": "close", "from": "tickets", "to": None, "rate": {"form": "proportional", "stock": "tickets", "k": 0.5}},
    ]
    ch = [{"t": 1, "set": {"signups": {"form": "constant", "value": 25}, "bugs": {"form": "constant", "value": 0}}},
          {"t": 40, "set": {"bugs": {"form": "constant", "value": 45}}}, {"t": 44, "set": {"bugs": {"form": "constant", "value": 0}}},
          {"t": 75, "set": {"signups": {"form": "constant", "value": 45}}},
          {"t": 130, "set": {"signups": {"form": "constant", "value": 15}}},
          {"t": 150, "set": {"bugs": {"form": "constant", "value": 90}}}, {"t": 153, "set": {"bugs": {"form": "constant", "value": 0}}},
          {"t": 220, "set": {"signups": {"form": "constant", "value": 30}}},
          {"t": 250, "set": {"bugs": {"form": "constant", "value": 60}}}, {"t": 256, "set": {"bugs": {"form": "constant", "value": 0}}}]
    return generate(stocks, flows, steps, schedule={"every": 365, "changes": ch}, seed=seed)


def test_held_out_judge_prefers_constant_inflows_when_the_real_inflow_changes():
    # signups really change (and bug spikes hit the tickets): held out, a changing inflow's last
    # piece is a stale guess, so constant inflows look better there, though fed the true signups
    # (as the bench does) the changing-inflow model behaves far better
    d = tickets(730, 1)
    base = in_sample(d["stocks"], d["run"])
    r = held_out(d["stocks"], d["run"])
    assert "changing inflows" in base["chosen"]
    assert "constant inflows" in r["chosen"]
    assert skill(base, d) > 0.6 and skill(r, d) < 0


def test_blocks_and_gaps():
    assert blocks(10, 3) == [(0, 3), (3, 6), (6, 10)]
    f = {"from": None, "to": "a", "inflow": [{"from": 1, "to": 3, "value": 2.0}, {"from": 7, "to": 9, "value": 4.0}]}
    last = fill_gaps([f])[0]["inflow"]
    assert [(g["from"], g["to"], g["value"]) for g in last] == [(-1e18, 6, 2.0), (7, 1e18, 4.0)]
    mean = fill_gaps([f], "mean")[0]["inflow"]
    assert [(g["from"], g["to"], g["value"]) for g in mean] == [(-1e18, 3, 2.0), (4, 6, 3.0), (7, 1e18, 4.0)]
