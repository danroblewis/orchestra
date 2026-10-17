"""latent-eras: an internal rate that switches back and forth unannounced is found as recurring
regimes (a Markov-switching regression on the rows), and the era machinery then fits a number per
regime (docs/research/latent-eras.md).

The smallest model where it matters: a fed at a constant 100, moved to b at a rate that switches
between 0.5 and 0.1 every 12 steps, b drained at 0.2. The main line (`matrix`) can absorb only the
constant part of a switch in inflow pieces, which the grader replaces with the true constant
inflow; it finds one averaged move (0.35) and runs away (skill@20 about -2).
"""

from __future__ import annotations

import pytest
from synth import generate, skill

from sdlab.discovery.identify import identify as matrix
from sdlab.discovery.regimes import find
from sdlab.discovery.strategies import load

latent_eras = load("latent_eras")


def mv(k):
    return {"form": "proportional", "stock": "a", "k": k}


def link(k):
    return {"form": "linear", "c": 0, "terms": [{"stock": "creators", "k": k}]}


def find_flow(r, a, b):
    return next((f for f in r["flows"] if f.get("from") == a and f.get("to") == b and not f.get("driver")), None)


@pytest.fixture(scope="module")
def switching():
    return generate(stocks=[{"id": "a", "initial": 200}, {"id": "b", "initial": 100}],
                    flows=[{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 100}},
                           {"id": "ab", "from": "a", "to": "b", "rate": mv(0.5)},
                           {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}}],
                    steps=2000, schedule={"every": 24, "changes": [{"t": 1, "set": {"ab": mv(0.5)}}, {"t": 13, "set": {"ab": mv(0.1)}}]})


def test_the_main_line_averages_a_switching_move_and_runs_away(switching):
    r = matrix(switching["stocks"], switching["run"])
    assert skill(r, switching) < 0.5


def test_a_switching_move_is_found_as_two_regimes_with_their_switch_times_and_rates(switching):
    base = matrix(switching["stocks"], switching["run"])
    processes = find(switching["stocks"], switching["run"], base["matrix"], {})
    assert len(processes) == 1 and processes[0]["K"] == 2 and sorted(processes[0]["rows"]) == ["a", "b"]

    r = latent_eras(switching["stocks"], switching["run"], {})
    ab = find_flow(r, "a", "b")
    assert ab and ab.get("byTime"), "the move's rate follows the regimes"
    # every switch of the truth (k set to 0.5 at 1 + 24n, to 0.1 at 13 + 24n) found within one step
    true_switches = sorted([t for t in range(25, 2001, 24)] + [t for t in range(13, 2001, 24)])
    seg = ab["byTime"]
    found = [s["from"] for p, s in zip(seg, seg[1:]) if s["rate"]["k"] != p["rate"]["k"]]
    assert len(found) == len(true_switches)
    assert all(min(abs(f - t) for f in found) <= 1 for t in true_switches)
    ks = sorted({s["rate"]["k"] for s in seg})
    assert len(ks) == 2 and abs(ks[0] - 0.1) <= 0.01 and abs(ks[1] - 0.5) <= 0.01
    assert skill(r, switching) > 0.9


def test_a_switching_link_into_a_queue_is_left_to_inflow_pieces_where_they_already_replay_it():
    """The brief's model (creators feed a screening queue at 0.1 or 0.03 per creator, switching every 12
    steps). Within a 12-step spell creators barely move, so the switch is a change in the queue's
    inflow, which the main line replays as pieces (the grader keeps them: the queue is not fed a
    constant) and behaves; the strategy behaves at least as well."""
    d = generate(stocks=[{"id": "creators", "initial": 300}, {"id": "screening", "initial": 100}, {"id": "published", "initial": 0, "final": True}],
                 flows=[{"id": "join", "from": None, "to": "creators", "rate": {"form": "constant", "value": 20}},
                        {"id": "quit", "from": "creators", "to": None, "rate": {"form": "proportional", "stock": "creators", "k": 0.008}},
                        {"id": "post", "from": None, "to": "screening", "rate": link(0.1)},
                        {"id": "screen", "from": "screening", "to": "published", "rate": {"form": "proportional", "stock": "screening", "k": 0.5}}],
                 steps=2000, schedule={"every": 24, "changes": [{"t": 1, "set": {"post": link(0.1)}}, {"t": 13, "set": {"post": link(0.03)}}]})
    base = skill(matrix(d["stocks"], d["run"]), d)
    assert base > 0.9
    assert skill(latent_eras(d["stocks"], d["run"], {}), d) >= base - 0.01


def test_an_outside_inflow_that_changes_alone_gets_no_regime():
    d = generate(stocks=[{"id": "q", "initial": 100}, {"id": "done", "initial": 0, "final": True}],
                 flows=[{"id": "in", "from": None, "to": "q", "rate": {"form": "constant", "value": 200}},
                        {"id": "work", "from": "q", "to": "done", "rate": {"form": "proportional", "stock": "q", "k": 0.5}}],
                 steps=2000, schedule={"every": 300, "changes": [{"t": 1, "set": {"in": {"form": "constant", "value": 200}}},
                                                                {"t": 101, "set": {"in": {"form": "constant", "value": 80}}}]})
    r = latent_eras(d["stocks"], d["run"], {})
    assert r["regimes"] == []


def test_a_model_that_never_changes_gets_no_regime():
    d = generate(stocks=[{"id": "a", "initial": 200}, {"id": "b", "initial": 100}],
                 flows=[{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 100}},
                        {"id": "ab", "from": "a", "to": "b", "rate": mv(0.3)},
                        {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.2}}], steps=2000)
    r = latent_eras(d["stocks"], d["run"], {})
    assert r["regimes"] == []
