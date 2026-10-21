"""Flows between the same two stocks are one flow (the user, 2026-10-20; sdlab/ladder/merge.py): a
found model's same-pair flows are merged before scoring, complexity counting and drawing; what rides on
them (co-flows) stays a part and is still scored; a flow that cannot be summed stays apart and says so."""

import numpy as np
import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import complexity, data, merge, score
from sdlab.ladder.caseformat import compile_case
from sdlab.ladder.parts import form_over, linear_system, parts
from sdlab.ladder.substep import per_step
from sdlab.skill import truth_by_time

CHAIN = """title: Chain of two
level: 2
tags: [chain, move]
tests: a move between two stocks, with the chain's inflow and exit
seed: 3
stocks: {A: 0, B: 0}
flows:
  outside -> A: 20
  A -> B: 0.5 * A
  B -> outside: 0.2 * B
"""


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def build(text=CHAIN, cid="900-merge"):
    return casemod._build(cid, compile_case(text, f"{cid}.yaml"))["case"]


def prop(a, b, stock, k, **kw):
    return {"from": a, "to": b, "rate": {"form": "proportional", "stock": stock, "k": k}, **kw}


def const(a, b, v):
    return {"from": a, "to": b, "rate": {"form": "constant", "value": v}}


def perfect(model, d):
    return per_step(truth_by_time(model, d["t"])[0], d, model)[0]


def split(flows):
    """The A -> B flow written as two halves (the lna_pulses mistake on 304)."""
    out = []
    for f in flows:
        if f.get("from") == "A" and f.get("to") == "B":
            k = f["rate"]["k"]
            out += [prop("A", "B", "A", k * 0.498), prop("A", "B", "A", k * 0.502)]
        else:
            out.append(f)
    return out


def scored(case, found, variant="none-short"):
    model = casemod.truth_model(case, variant)
    d = data.load(case, variant)
    return score.equations(case, casemod.variant(case, variant)["noise"], model, found(model, d), d)


# ---- the merge ----

def test_same_reader_terms_are_one_coefficient_and_annotated():
    got = merge.flows([prop("I", "R", "I", 0.249), prop("I", "R", "I", 0.244), prop("Q", None, "Q", 0.06)])
    assert len(got) == 2
    m = got[0]
    assert m["rate"] == {"form": "proportional", "stock": "I", "k": pytest.approx(0.493)}
    assert m["merged"]["note"] == "merged from 2 flows: 0.249*I + 0.244*I"
    assert [f["rate"]["k"] for f in merge.members(got)] == [0.249, 0.244, 0.06]
    assert merge.flows(got) is got                                     # idempotent
    plain = [prop("I", "R", "I", 0.2)]
    assert merge.flows(plain) is plain                                 # nothing to merge: unchanged


def test_constants_add_and_readers_stay_apart():
    got = merge.flows([const(None, "A", 3), const(None, "A", 2), prop(None, "A", "B", 0.1)])
    assert len(got) == 1
    r = got[0]["rate"]
    assert r["form"] == "linear" and r["c"] == 5 and r["terms"] == [{"stock": "B", "k": 0.1}]
    assert "outside -> A: merged from 3 flows: 3 + 2 + 0.1*B" in merge.notes(got)


def test_effects_and_hidden_stocks_stay_apart_and_say_so():
    eff = prop("A", "B", "A", 0.2, effects=[{"stock": "C", "shape": "linear", "normal": 1, "min": 0, "max": 2}])
    via = prop("A", "B", "A", 0.1, via={"delay": 3})
    got = merge.flows([prop("A", "B", "A", 0.1), eff, via, prop("A", "B", "A", 0.1)])
    assert len(got) == 3
    assert got[0]["merged"]["of"] == 2
    assert "effects" in got[1]["apart"] and "hidden stock" in got[2]["apart"]
    assert got[1]["effects"] == eff["effects"]                          # nothing dropped


def test_pieces_are_laid_over_the_union_of_spans_and_sum_exactly():
    pieces = {"from": None, "to": "A", "rate": {"form": "constant", "value": 5},
              "inflow": [{"from": 2, "to": 10, "value": 5}, {"from": 11, "to": 40, "value": 8}]}
    link = prop(None, "A", "B", 0.3)
    got = merge.flows([pieces, link])
    assert len(got) == 1 and len(got[0]["byTime"]) == 2
    assert got[0]["byTime"][1]["rate"] == {"form": "linear", "c": 8, "terms": [{"stock": "B", "k": 0.3}]}
    for a, b in ((2, 10), (5, 30), (11, 40)):
        c1, k1 = form_over(pieces, a, b)
        c2, k2 = form_over(got[0], a, b)
        assert c2 == pytest.approx(c1) and k2 == {"B": pytest.approx(0.3)}
    # complexity: an inflow in 2 pieces and a link cost what the two flows did, less one flow
    assert complexity.count([pieces, link], {"A", "B"}) == {"flows": 1, "terms": 2, "pieces": 1, "other": 0, "total": 4}


def test_a_co_flow_rides_on_the_merged_flow_and_is_still_scored():
    found = [prop("A", "B", "A", 0.25), prop("A", "B", "A", 0.25, uses=[{"stock": "C", "per": 0.1}])]
    got = merge.flows(found)
    assert len(got) == 1 and got[0]["uses"] == [{"stock": "C", "per": 0.1}]
    assert "(uses 0.1 C)" in got[0]["merged"]["note"]
    p, _ = parts(got, {"A", "B", "C"}, (1, 10))
    assert p[("flow", "A", "B", "A")] == pytest.approx(0.5) and p[("uses", "A", "B", "C")] == pytest.approx(0.1)
    # the linear system runs the originals: the co-flow reads only the flow that carried it
    B, _ = linear_system(got, ["A", "B", "C"], (1, 10))
    B0, _ = linear_system(found, ["A", "B", "C"], (1, 10))
    assert np.allclose(B, B0) and B[2, 0] == pytest.approx(-0.025)


def test_complexity_counts_a_split_flow_once():
    m = {"A", "B"}
    one = complexity.count([prop("A", "B", "A", 0.5)], m)
    two = complexity.count([prop("A", "B", "A", 0.25), prop("A", "B", "A", 0.25)], m)
    assert one == two == {"flows": 1, "terms": 1, "pieces": 0, "other": 0, "total": 2}


# ---- the scorer ----

def test_a_split_flow_scores_as_the_flow_with_a_note():
    case = build()
    whole, halves = scored(case, perfect), scored(case, lambda m, d: split(perfect(m, d)))
    assert whole["status"] == halves["status"] == "pass"
    assert [(r["key"], r["ok"]) for r in whole["parts"]] == [(r["key"], r["ok"]) for r in halves["parts"]]
    assert any("A -> B: merged from 2 flows" in n for n in halves["notes"])


def test_a_co_flow_on_a_duplicate_is_spurious():
    case = build()

    def found(m, d):
        fl = split(perfect(m, d))
        i = next(i for i, f in enumerate(fl) if f.get("from") == "A" and f.get("to") == "B")
        fl[i + 1] = {**fl[i + 1], "uses": [{"stock": "B", "per": 0.3}]}
        return fl

    s = scored(case, found)
    assert s["status"] == "fail"
    assert [x["key"] for x in s["spurious"]] == ["uses B on A -> B"]


def test_score_hash_covers_the_merge():
    import inspect
    assert "merge.py" in inspect.getsource(score.score_hash)


def test_merged_flows_are_what_the_page_draws():
    from sdlab.ladder import api
    row = {"found": [prop("I", "R", "I", 0.2), prop("I", "R", "I", 0.3)]}
    assert len(api._merged(row)["found_merged"]) == 1
    assert "found_merged" not in api._merged({"found": [prop("I", "R", "I", 0.2)]})
