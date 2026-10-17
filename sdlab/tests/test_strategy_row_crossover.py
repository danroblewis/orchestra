"""row_crossover: a model assembled row by row from the candidates (docs/research/row-crossover.md).

The smallest model where whole candidates fail: two independent subsystems in one model.
- An inbox whose intake changes every 30 steps, drained at 0.1: it needs changing inflows (with a
  constant inflow its row loses the drain).
- A bakery line: orders baked onto a shelf, each loaf using flour that is restocked slowly, so baking
  stalls when flour runs short. Its rows with changing inflows run away on the data (pieces and flour
  links trade off), so the in-data judge prefers the constant-inflow candidate for the whole model.

The main line (`matrix`) picks the constant-inflow candidate as a whole and so loses the inbox's
drain (skill@20 about -370%). row_crossover starts from that pick and takes the inbox's row from a
changing-inflow candidate: skill@20 above every whole candidate's.
"""

from __future__ import annotations

import pytest
from synth import generate, skill

from sdlab.discovery.crossover import Pool
from sdlab.discovery.identify import VARIANTS, identify as matrix
from sdlab.discovery.matrix import identify_one
from sdlab.discovery.strategies.row_crossover import identify as row_crossover


def P(stock, k):
    return {"form": "proportional", "stock": stock, "k": k}


def C(v):
    return {"form": "constant", "value": v}


INTAKE = [40, 90, 30, 70, 50, 100, 20, 80]
SCHEDULE = {"every": 30 * len(INTAKE), "changes": [{"t": 1 + 30 * i, "set": {"intake": C(v)}} for i, v in enumerate(INTAKE)]}
INBOX = ([{"id": "inbox", "initial": 40}],
         [{"id": "intake", "from": None, "to": "inbox", "rate": C(40)}, {"id": "done", "from": "inbox", "to": None, "rate": P("inbox", 0.1)}])
BAKERY = ([{"id": "orders", "initial": 80}, {"id": "shelf", "initial": 100}, {"id": "flour", "initial": 400, "unit": "kg"}],
          [{"id": "order", "from": None, "to": "orders", "rate": C(40)},
           {"id": "bake", "from": "orders", "to": "shelf", "rate": P("orders", 0.5), "uses": [{"stock": "flour", "per": 0.5}]},
           {"id": "pickup", "from": "shelf", "to": None, "rate": P("shelf", 0.25)},
           {"id": "restock", "from": None, "to": "flour", "rate": {"form": "gap", "stock": "flour", "goal": 600, "time": 80}}])


def model(*parts, seed=1):
    return generate(stocks=[s for p in parts for s in p[0]], flows=[f for p in parts for f in p[1]], steps=600, schedule=SCHEDULE, seed=seed)


def drain(result, stock):
    return sum(f["rate"]["k"] for f in result["flows"] if f["from"] == stock and f["rate"]["form"] == "proportional")


@pytest.mark.parametrize("seed", [1, 3])
def test_rows_from_two_candidates_beat_every_whole_candidate(seed):
    d = model(INBOX, BAKERY, seed=seed)
    whole = {v["name"]: skill(identify_one(d["stocks"], d["run"], dict(v)), d) for v in VARIANTS if not v.get("split_eras")}
    base = matrix(d["stocks"], d["run"], {})
    r = row_crossover(d["stocks"], d["run"], {})
    # the main line takes the constant-inflow candidate whole: the inbox loses its drain
    assert "constant inflows" in base["chosen"]
    assert drain(base, "inbox") < 0.02
    assert skill(base, d) < 0
    # the crossover keeps that pick for the bakery line and takes the inbox's row from a
    # changing-inflow candidate
    assert [s["stock"] for s in r["swaps"]] == ["inbox"]
    assert "changing inflows" in r["swaps"][0]["to"]
    assert 0.08 < drain(r, "inbox") < 0.16
    assert skill(r, d) > max(whole.values()) + 0.02
    assert skill(r, d) > 0.85


def test_no_swap_when_one_candidate_is_right_everywhere():
    d = model(INBOX)
    base = matrix(d["stocks"], d["run"], {})
    r = row_crossover(d["stocks"], d["run"], {})
    assert r["swaps"] == []
    assert r["chosen"] == base["chosen"]
    assert r["flows"] == base["flows"]


def test_assembling_a_candidates_own_rows_gives_that_candidate():
    d = model(INBOX, BAKERY)
    cands = [{"variant": v, "result": identify_one(d["stocks"], d["run"], {**v, "keep_rows": True})} for v in VARIANTS if not v.get("split_eras")]
    pool = Pool(cands, d["stocks"], {})
    for i, c in enumerate(cands):
        assert pool.assemble(pool.start(i))["flows"] == c["result"]["flows"]
