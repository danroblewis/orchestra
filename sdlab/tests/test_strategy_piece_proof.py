"""Experiment "piece-proof judge" (docs/DISCOVERY-EXPERIMENTS.md, docs/research/inflow-conditioned-judge.md):
judges a candidate's own outside-inflow pieces cannot fool (sdlab/discovery/judges.py).

What the mechanisms do, in isolation, on the smallest models where the right answer is known:
  - a misread flow paid back by inflow pieces (births read as a move adults -> children, adults' outside
    inflow raised to ~234 a step to pay for it; truth 80 then 160): with its own pieces it fits the
    data better than the true structure does, so the main line's judge ("own") picks it; fed the same
    outside inflow as everyone ("common": the per-step median of the candidates' inflows) it fails,
    and the true structure is picked;
  - an outside inflow that really changes (signups stepping up and down, bug spikes): the common
    judge still picks a changing-inflow candidate (the held-out judge's failure does not recur);
  - an effect imitated by pieces (a -> b at k x a x table(c); the main line's candidates read it as
    constant rates plus 30-40 pieces): when the true structure is the only candidate without those
    pieces, the common inflow carries them too and double-counts it ("common" fails); refitting a
    coarse inflow per judged window with the dynamics frozen ("window") picks the true structure.
  No single judge passes all three; on the bench (main-line candidates) every one loses to "own".
"""

from __future__ import annotations

import numpy as np
from synth import generate, skill

from sdlab.discovery.judges import exo_error, net_inflow, refit_inflow, score
from sdlab.discovery.matrix import identify_one
from sdlab.discovery.simulate import behaviour_error
from sdlab.discovery.strategies.piece_proof import identify as piece_proof

VARIANTS = [
    {"name": "receivers trusted always", "slack": 1e9},
    {"name": "trust rows", "trust_receivers": False},
    {"name": "constant inflows", "changes": False},
]
STEEP = [[0, 0.1], [20, 0.12], [40, 0.25], [55, 0.55], [70, 0.85], [80, 0.97], [90, 1], [100, 1]]


def population(steps: int = 600, seed: int = 3) -> dict:
    stocks = [{"id": "children", "initial": 3000}, {"id": "adults", "initial": 10000}]
    flows = [
        {"id": "births", "from": None, "to": "children", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "adults", "k": 0.022}]}},
        {"id": "grow", "from": "children", "to": "adults", "rate": {"form": "proportional", "stock": "children", "k": 0.056}},
        {"id": "die", "from": "adults", "to": None, "rate": {"form": "proportional", "stock": "adults", "k": 0.02}},
        {"id": "arrive", "from": None, "to": "adults", "rate": {"form": "constant", "value": 80}},
    ]
    ch = [{"t": 1, "set": {"arrive": {"form": "constant", "value": 80}}}, {"t": 150, "set": {"arrive": {"form": "constant", "value": 160}}}]
    return generate(stocks, flows, steps, schedule={"every": 300, "changes": ch}, seed=seed)


def tickets(steps: int = 730, seed: int = 1) -> dict:
    stocks = [{"id": "customers", "initial": 4600}, {"id": "tickets", "initial": 60}]
    flows = [
        {"id": "signups", "from": None, "to": "customers", "rate": {"form": "constant", "value": 25}},
        {"id": "leave", "from": "customers", "to": None, "rate": {"form": "proportional", "stock": "customers", "k": 0.005}},
        {"id": "opened", "from": None, "to": "tickets", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "customers", "k": 0.012}]}},
        {"id": "bugs", "from": None, "to": "tickets", "rate": {"form": "constant", "value": 0}},
        {"id": "close", "from": "tickets", "to": None, "rate": {"form": "proportional", "stock": "tickets", "k": 0.5}},
    ]
    c = lambda v: {"form": "constant", "value": v}  # noqa: E731
    ch = [{"t": 1, "set": {"signups": c(25), "bugs": c(0)}}, {"t": 40, "set": {"bugs": c(45)}}, {"t": 44, "set": {"bugs": c(0)}},
          {"t": 75, "set": {"signups": c(45)}}, {"t": 130, "set": {"signups": c(15)}}, {"t": 150, "set": {"bugs": c(90)}},
          {"t": 153, "set": {"bugs": c(0)}}, {"t": 220, "set": {"signups": c(30)}}, {"t": 250, "set": {"bugs": c(60)}},
          {"t": 256, "set": {"bugs": c(0)}}]
    return generate(stocks, flows, steps, schedule={"every": 365, "changes": ch}, seed=seed)


def sawmill(steps: int = 2000, seed: int = 1) -> dict:
    """Logs move to planks at 0.25 x logs x table(sharpness); sharpness is restocked by a supply that
    changes every 50 steps, logs arrive at a rate that changes out of step with it."""
    stocks = [{"id": "logs", "initial": 100}, {"id": "planks", "initial": 40}, {"id": "sharp", "initial": 80, "unit": "points"}]
    flows = [
        {"id": "arrive", "from": None, "to": "logs", "rate": {"form": "constant", "value": 10}},
        {"id": "move", "from": "logs", "to": "planks", "rate": {"form": "proportional", "stock": "logs", "k": 0.25},
         "effects": [{"stock": "sharp", "shape": "table", "points": STEEP}]},
        {"id": "leave", "from": "planks", "to": None, "rate": {"form": "proportional", "stock": "planks", "k": 0.2}},
        {"id": "supply", "from": None, "to": "sharp", "rate": {"form": "constant", "value": 5.5}},
        {"id": "decay", "from": "sharp", "to": None, "rate": {"form": "proportional", "stock": "sharp", "k": 0.06}},
    ]
    changes = [{"t": 1 + 50 * i, "set": {"supply": {"form": "constant", "value": v}}} for i, v in enumerate((5.5, 1.5, 3.5, 2.5))]
    changes += [{"t": t, "set": {"arrive": {"form": "constant", "value": 10 * m}}} for t, m in ((1, 1), (76, 1.4), (126, 0.7))]
    return generate(stocks, flows, steps, schedule={"every": 200, "changes": changes}, seed=seed)


def as_pieces(U: np.ndarray, ids: list[str], t: list) -> list[dict]:
    """Per-stock outside inflows (as judges.net_inflow gives them) as found inflow flows."""
    out = []
    for i, s in enumerate(ids):
        if not U[i, 1:].any():
            continue
        segs: list[dict] = []
        for k in range(1, len(t)):
            v = float(U[i, k])
            if segs and segs[-1]["value"] == v:
                segs[-1]["to"] = t[k]
            else:
                segs.append({"from": t[k], "to": t[k], "value": v})
        out.append({"from": None, "to": s, "ratio": 1, "rate": {"form": "constant", "value": float(U[i, 1:].mean())}, "inflow": segs})
    return out


def true_structure(d: dict, fed: list[str]) -> list[dict]:
    """The truth's internal flows, with an outside inflow into `fed` measured from the data (pieces of
    at least 5 steps on what those flows leave unexplained): the right candidate, as a better
    generator would offer it, with nothing taken from the truth's schedule."""
    ids = [s["id"] for s in d["stocks"]]
    dyn = [{k: v for k, v in f.items() if k != "id"} for f in d["model"]["flows"] if f.get("from") or f["rate"]["form"] != "constant"]
    U = refit_inflow(dyn, ids, d["run"]["t"], d["run"]["levels"], [ids.index(s) for s in fed], min_len=5)
    return dyn + as_pieces(U, ids, d["run"]["t"])


def candidates(d: dict, fed: list[str]) -> list[list[dict]]:
    return [identify_one(d["stocks"], d["run"], {"eras": d["eras"], **v})["flows"] for v in VARIANTS] + [true_structure(d, fed)]


def pick(cands, d, judge) -> int:
    return int(np.argmin(score(cands, d["stocks"], d["run"], judge)))


RIGHT = len(VARIANTS)


def test_the_pieces_are_run_as_the_simulator_runs_them():
    d = tickets()
    ids = [s["id"] for s in d["stocks"]]
    flows = identify_one(d["stocks"], d["run"], {})["flows"]
    t, lv = d["run"]["t"], d["run"]["levels"]
    assert abs(exo_error(flows, ids, t, lv, net_inflow(flows, ids, t), 20) - behaviour_error(flows, ids, t, lv, horizon=20)) < 1e-9


def test_a_misread_flow_paid_back_by_pieces_is_caught_by_the_common_inflow():
    d = population()
    cands = candidates(d, ["adults"])
    # the trap: births read as a move adults -> children, adults' inflow raised to pay for it
    assert any(f.get("from") == "adults" and f.get("to") == "children" for f in cands[0])
    assert skill({"flows": cands[RIGHT]}, d) > skill({"flows": cands[0]}, d) + 0.2
    assert pick(cands, d, "own") == 0                       # its own pieces carry it: 0.0135 vs the truth's 0.0154
    assert pick(cands, d, "common") == RIGHT                # fed what the others are fed: 0.26 vs 0.018
    assert pick(cands, d, "mean") != RIGHT                  # at their mean, constant inflows look best


def test_an_inflow_that_really_changes_is_still_chosen():
    d = tickets()
    cands = candidates(d, ["customers", "tickets"])
    assert pick(cands, d, "own") == RIGHT
    assert pick(cands, d, "common") == RIGHT
    # but the common inflow is only as good as the candidates it is taken from: among the main line's
    # candidates alone (no true structure), the median of three inflows is nobody's, and the common
    # judge picks "trust rows" (graded -7.6) where the main line's judge keeps "receivers" (0.68).
    # This is what the bench shows (docs/research/inflow-conditioned-judge.md).
    own = piece_proof(d["stocks"], d["run"], {"variants": VARIANTS, "judge": "own"})
    common = piece_proof(d["stocks"], d["run"], {"variants": VARIANTS, "judge": "common"})
    assert "constant" not in own["chosen"] and "constant" not in common["chosen"]
    assert skill(own, d) > 0.6 and skill(common, d) < 0


def test_an_effect_imitated_by_pieces_needs_the_window_judge():
    d = sawmill()
    cands = candidates(d, ["logs", "sharp"])
    assert any(len(f.get("inflow") or []) > 20 and f.get("from") == "planks" for f in cands[0])   # pieces imitate the effect
    assert skill({"flows": cands[RIGHT]}, d) > 0.95 and max(skill({"flows": c}, d) for c in cands[:RIGHT]) < 0
    assert pick(cands, d, "common") != RIGHT                # the common inflow carries the imitation too
    assert pick(cands, d, "window") == RIGHT                # dynamics given a coarse inflow: 0.18 vs 2.5 and more
