"""The inverse run (sd/experiments/inverse.py): given targets over a past window and what must
hold, the smallest set of changes to the model under which a replay meets them; its side effects,
its alternatives, and the fabricate-and-rediscover check of whether the data would tell it apart.

The chain (``experiment_systems.chain``): doubling the arrivals settles the ready stock at 1.5
times its level, and so would doubling the side supply or draining a third slower. Asked for
"ready ×1.5" with nothing held, the solution is ambiguous; holding the side supply's and the
drain's equations, only the arrivals can do it."""

import gzip
import json
import time
from pathlib import Path

import pytest
from experiment_systems import chain, history_of

from orchestra.sd.experiments import inverse as inv
from orchestra.sd.model import Model
from orchestra.sd.strategies import sd_installed

pytestmark = pytest.mark.skipif(not sd_installed(), reason="simulating needs orchestra[sd]")

BAKERY = Path(__file__).parent.parent / "fixtures" / "sd" / "bakery-whatif.json.gz"


def mean(pts):
    return sum(v for _, v in pts) / len(pts)


def solved(model, h, targets, **kw):
    sol = inv.solve(model, h, targets, **kw)
    return sol, inv.report(sol, model, h)


def test_the_single_change_that_made_the_data_is_recovered_as_the_sparsest_with_its_side_effects():
    base = chain()
    h = history_of(base)
    # the window as it would have been with the arrivals doubled: the ready stock ×1.5 or so
    ratio = mean(history_of(chain(arrive=6.0), seed=2)["stocks"]["ready"]) / mean(h["stocks"]["ready"])
    assert 1.4 < ratio < 1.6
    sol, r = solved(base, h, [{"stock": "ready", "scale": round(ratio, 2)}], hold=[{"flow": "side"}, {"flow": "drain"}])
    assert r["reached"] and r["count"] == 1
    [c] = r["changes"]
    assert c["kind"] == "param" and c["flow"] == "arrive" and c["param"] == "c" and 1.8 < c["factor"] < 2.3
    [t] = r["targets"]
    assert t["met"] and abs(t["miss"]) <= inv.TOL and t["base_replay"] == pytest.approx(20.0, abs=0.5)
    side = {(x["part"], x["id"]): x["ratio"] for x in r["side_effects"]}
    assert 1.8 < side[("stock", "queue")] < 2.3, "the queue would have had to double too"
    assert 1.8 < side[("flow", "move")] < 2.3 and 1.3 < side[("flow", "drain")] < 1.7
    assert ("flow", "side") not in side, "the side supply's equation was held, and it does not depend on the levels"
    # the counterfactual data, made and discovered again, shows the same single change
    u = inv.uniqueness(base, inv.apply(base, sol, sol["stages"][-1]["changes"], "inverse"), h, r["changes"], h["start"], h["at"])
    assert u["checked"] and u["consistent"] and u["recovered"] == ["arrive"] and u["missed"] == [] and u["extra"] == []
    assert u["laws"]["move"]["status"] == "unchanged" and u["laws"]["drain"]["status"] == "unchanged"


def test_with_nothing_held_the_other_ways_to_the_target_are_alternatives_and_it_is_ambiguous():
    base = chain()
    h = history_of(base)
    _, r = solved(base, h, [{"stock": "ready", "scale": 1.5}])
    assert r["reached"] and r["count"] == 1
    found = {(r["changes"][0]["flow"], r["changes"][0]["param"])}
    alt = {(a["changes"][0]["flow"], a["changes"][0].get("param")) for a in r["alternatives"] if a["met"]}
    assert len(alt) >= 2 and found | alt >= {("arrive", "c"), ("side", "c"), ("drain", "k")}, r["alternatives"]
    drain = next(a for a in r["alternatives"] + [{"changes": r["changes"]}] if a["changes"][0]["flow"] == "drain")["changes"][0]
    assert 0.6 < drain["factor"] < 0.72, "or drain it a third slower"


def test_an_unmeasured_new_flow_is_flagged_by_the_rediscovery_check():
    base = chain()
    h = history_of(base)
    held = [{"flow": f} for f in ("arrive", "move", "side", "drain")]
    sol, r = solved(base, h, [{"stock": "ready", "scale": 1.5}], hold=held, new_flows=True)
    assert r["reached"] and [c["kind"] for c in r["changes"]] == ["new_flow"] and r["changes"][0]["to"] == "ready"
    u = inv.uniqueness(base, inv.apply(base, sol, sol["stages"][-1]["changes"], "inverse"), h, r["changes"], h["start"], h["at"])
    assert not u["consistent"] and u["unmeasured"] == ["ready_inflow_found"] and u["extra"], \
        "no counter measures the new inflow, so discovery cannot see it: the data would not show this solution"


def test_an_impossible_target_is_unreachable_with_the_best_approach():
    base = chain()
    h = history_of(base)
    _, r = solved(base, h, [{"stock": "ready", "scale": 0.2}], hold=[{"flow": f} for f in ("move", "side", "drain")])
    # the side supply alone keeps ready at 10 or more: half its level, not a fifth
    assert not r["reached"] and r["count"] == 1 and r["changes"][0]["flow"] == "arrive"
    [t] = r["targets"]
    assert not t["met"] and t["solved"] > 2 * t["goal"] and r["changes"][0]["factor"] <= 0.11, "the arrivals cut as far as they go"


def test_holding_a_series_keeps_its_history():
    base = chain()
    h = history_of(base)
    _, r = solved(base, h, [{"stock": "ready", "scale": 1.5}], hold=[{"series": "queue"}])
    assert r["reached"] and all(c["flow"] != "arrive" for c in r["changes"]), "doubling the arrivals would double the queue"
    q = next(t for t in r["targets"] if t["id"] == "queue")
    assert q["kind"] == "hold" and q["met"]


def test_bad_questions_say_what_is_wrong():
    base = chain()
    h = history_of(base, minutes=10)
    for targets, hold, says in (([], None, "at least one"), ([{"stock": "nope", "scale": 2}], None, "no stock 'nope'"),
                                ([{"stock": "ready", "total": 2}], None, "one of scale, level, below, above"),
                                ([{"stock": "ready", "scale": 2}], [{"flow": "nope"}], "no flow 'nope'"),
                                ([{"stock": "ready", "scale": 2}], [{"flow": f} for f in ("arrive", "move", "side", "drain")],
                                 "every flow is held")):
        with pytest.raises(inv.InverseError, match=says):
            inv.solve(base, h, targets, hold=hold)


def test_the_solver_stops_at_its_deadline_with_the_best_so_far():
    with gzip.open(BAKERY, "rt") as fh:
        d = json.load(fh)
    m, h = Model.from_json(d["model"]), d["history"]
    began = time.monotonic()
    _, r = solved(m, h, [{"stock": "bakery_orders_waiting", "scale": 0.5}, {"stock": "bakery_orders_baking", "scale": 3.0}],
                  deadline_s=1.0, step_s=5.0)
    assert r["stopped"] == "deadline" and not r["reached"]
    assert time.monotonic() - began < 3.0, "the deadline, and one replay of the answer"
    # with time, the same model meets a target in one change
    _, r = solved(m, h, [{"stock": "bakery_orders_waiting", "scale": 0.5}], deadline_s=60.0)
    assert r["reached"] and r["count"] == 1 and r["stopped"] is None
