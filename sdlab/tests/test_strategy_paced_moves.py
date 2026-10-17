"""Mechanism test for the paced_moves strategy (docs/research/paced-moves.md).

A move whose rate reads a third stock (tier2 -> resolved at 0.5 x agents) is -0.5 in tier2's entry for
agents and +0.5 in resolved's. The main line reads the pair as "tier2 drains faster when agents is
high" plus a link agents -> resolved; the strategy reads one move paced by agents. And an inflow that
is a gap on another stock (on_order's reorders, max(0, 110 - 0.2 x shelf)) is read by the main line
as "on_order drains faster when shelf is high" beside a constant inflow; the strategy reads one
inflow that falls as shelf rises and stops when shelf is above 550.
"""

from __future__ import annotations

import pytest
from synth import generate, skill

from sdlab.discovery.strategies import load

# agents turn over fast (10 hired a step, half leave each step: about 20, 10 to 30 from step to
# step); tickets arrive at 8 a step, with an unannounced burst of 18 a step for 20 steps of every 100:
# tier2 piles up in the burst, then is worked down to empty, where the move is cut to what tier2 holds
HIRE = {"every": 100, "changes": [{"t": 1, "set": {"arrive": {"form": "constant", "value": 7}}},
                                  {"t": 91, "set": {"arrive": {"form": "constant", "value": 18}}}]}
AGENTS = [{"id": "hire", "from": None, "to": "agents", "rate": {"form": "constant", "value": 10}},
          {"id": "quit", "from": "agents", "to": None, "rate": {"form": "proportional", "stock": "agents", "k": 0.5}}]
STOCKS = [{"id": "tier2", "initial": 20}, {"id": "agents", "initial": 20, "unit": "agents"}, {"id": "resolved", "initial": 50}]
ARRIVE = {"id": "arrive", "from": None, "to": "tier2", "rate": {"form": "constant", "value": 7}}
CLOSE = {"id": "close", "from": "resolved", "to": None, "rate": {"form": "proportional", "stock": "resolved", "k": 0.2}}


def paced(by: str, k: float) -> dict:
    return {"form": "linear", "c": 0, "terms": [{"stock": by, "k": k}]}


def run(d):
    opts = {"eras": None}
    return load("matrix")(d["stocks"], d["run"], opts), load("paced_moves")(d["stocks"], d["run"], opts)


def term(f, stock):
    return next((t["k"] for t in f["rate"].get("terms") or [] if t["stock"] == stock), None)


@pytest.fixture(scope="module")
def tiers():
    d = generate(STOCKS, [ARRIVE, *AGENTS, {"id": "solve", "from": "tier2", "to": "resolved", "rate": paced("agents", 0.5)}, CLOSE], 1000, schedule=HIRE)
    return d, *run(d)


def test_matrix_reads_a_paced_move_as_an_outflow_and_a_link(tiers):
    d, base, _ = tiers
    out = [f for f in base["flows"] if f["from"] == "tier2" and f["to"] is None and f.get("driver") == "agents"]
    link = [f for f in base["flows"] if f["from"] is None and f["to"] == "resolved" and f.get("driver") == "agents"]
    assert out and link
    # both halves biased far below 0.5 by the steps where tier2 ran low and the move was cut (0.24 and
    # 0.31 on this run; a drain of tier2, 0.10, imitates the cut); 0.20-0.31 on seeds 1-8
    assert out[0]["rate"]["terms"][0]["k"] < 0.35 and link[0]["rate"]["terms"][0]["k"] < 0.35
    assert not any(f["from"] == "tier2" and f["to"] == "resolved" and term(f, "agents") for f in base["flows"])


def test_paced_moves_reads_one_move_paced_by_agents(tiers):
    d, base, r = tiers
    moves = [f for f in r["flows"] if f["from"] == "tier2" and f["to"] == "resolved" and term(f, "agents")]
    assert len(moves) == 1 and not moves[0].get("driver")
    # refitted on the steps where tier2 held enough: 0.465 on this run (0.37-0.53 on seeds 1-8)
    assert abs(term(moves[0], "agents") - 0.5) < 0.05
    assert not any(f.get("driver") == "agents" and f["to"] in ("resolved", None) and f["from"] in ("tier2", None) for f in r["flows"])
    # the move stops when tier2 is empty, so resolved does not keep filling: closer to the truth
    # (0.51 -> 0.94 on this run; on seeds 1-8 the mean goes 0.65 -> 0.84, 5 up, 2 down, 1 not matched)
    assert skill(r, d, 20) >= skill(base, d, 20) + 0.1


def test_gap_on_another_stock_is_one_inflow():
    sell = {"every": 90, "changes": [{"t": 1, "set": {"sell": {"form": "constant", "value": 20}}},
                                     {"t": 30, "set": {"sell": {"form": "constant", "value": 0}}},
                                     {"t": 60, "set": {"sell": {"form": "constant", "value": 30}}}]}
    d = generate([{"id": "on_order", "initial": 100}, {"id": "shelf", "initial": 500}],
                 [{"id": "reorder", "from": None, "to": "on_order", "rate": {"form": "gap", "stock": "shelf", "goal": 550, "time": 5}},
                  {"id": "receive", "from": "on_order", "to": "shelf", "rate": {"form": "proportional", "stock": "on_order", "k": 0.25}},
                  {"id": "sell", "from": "shelf", "to": None, "rate": {"form": "constant", "value": 20}}], 1000, schedule=sell)
    base, r = run(d)
    # matrix: an outflow of on_order paced by shelf (-0.21) beside a constant inflow; it runs away
    assert any(f["from"] == "on_order" and f["to"] is None and f.get("driver") == "shelf" for f in base["flows"])
    assert skill(base, d, 20) < 0
    gap = [f for f in r["flows"] if f["from"] is None and f["to"] == "on_order" and term(f, "shelf")]
    assert len(gap) == 1 and abs(term(gap[0], "shelf") + 0.2) < 0.03
    assert not any(f["from"] == "on_order" and f["to"] is None and f.get("driver") == "shelf" for f in r["flows"])
    assert skill(r, d, 20) > 0.9 and skill(r, d, 100) > 0.9


def test_a_paced_outflow_beside_an_unrelated_link_is_not_merged():
    d = generate(STOCKS, [ARRIVE, *AGENTS, CLOSE, {"id": "lose", "from": "tier2", "to": None, "rate": paced("agents", 0.5)},
                          {"id": "make", "from": None, "to": "resolved", "rate": paced("agents", 0.25)}], 1000, schedule=HIRE)
    base, r = run(d)
    assert not any(f["from"] == "tier2" and f["to"] == "resolved" and term(f, "agents") for f in r["flows"])
    assert r["flows"] == base["flows"]
