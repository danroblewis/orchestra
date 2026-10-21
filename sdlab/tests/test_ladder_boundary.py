"""The declared boundary (the user, 2026-10-20): a case may declare, per measured stock, its outside
inflows and outflows (kind "measured" or "estimate"); it is announced to discovery and an outside flow
the boundary does not have is an "invented boundary" part that fails the result. A case with no
boundary is loaded, hashed, announced and scored exactly as before."""

import os

import pytest

from sdlab.discovery import strategies as strategies_pkg
from sdlab.ladder import cases as casemod
from sdlab.ladder import data, runner, score
from sdlab.ladder.caseformat import CaseError, boundary_problems, boundary_spec, compile_case
from sdlab.ladder.parts import outside_end, outside_ends
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
HOME_CACHE = os.environ.get("SDLAB_LADDER_CACHE")
DECLARED = CHAIN + "boundary:\n  A: {in: estimate}\n  B: {out: [estimate]}\n"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))


def build(text, cid="900-boundary"):
    return casemod._build(cid, compile_case(text, f"{cid}.yaml"))["case"]


def perfect(model, d):
    return per_step(truth_by_time(model, d["t"])[0], d, model)[0]


def scored(case, flows_of, variant="none-short"):
    model = casemod.truth_model(case, variant)
    d = data.load(case, variant)
    return score.equations(case, casemod.variant(case, variant)["noise"], model, flows_of(model, d), d)


def prop(a, b, stock, k):
    return {"from": a, "to": b, "rate": {"form": "proportional", "stock": stock, "k": k}}


# ---- the case field ----

def test_boundary_spec_forms_and_mistakes():
    assert boundary_spec({"A": {"in": "measured", "out": ["estimate", "estimate"]}, "B": {}}) == \
        {"A": {"in": ["measured"], "out": ["estimate", "estimate"]}}
    assert boundary_spec({}) == {} and boundary_spec("none") == {} and boundary_spec(None) == {}
    for bad in (["A"], {"A": {"in": "guess"}}, {"A": {"side": "estimate"}}, {"A": "in"}):
        with pytest.raises(CaseError):
            boundary_spec(bad)


def test_a_yaml_case_compiles_its_boundary_and_absent_means_undeclared():
    assert compile_case(DECLARED)["boundary"] == {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}}
    assert "boundary" not in compile_case(CHAIN)
    assert compile_case(CHAIN + "boundary: {}\n")["boundary"] == {}


def test_the_boundary_must_match_the_true_model():
    with pytest.raises(CaseError, match="outside outflow from B, not declared"):
        build(CHAIN + "boundary:\n  A: {in: estimate}\n")
    with pytest.raises(CaseError, match="does not have"):
        build(DECLARED.replace("{in: estimate}", "{in: estimate, out: estimate}"))
    with pytest.raises(CaseError, match="needs a measured input"):
        build(DECLARED.replace("{in: estimate}", "{in: measured}"))
    hidden = CHAIN.replace("{A: 0, B: 0}", "{A: 0, B: 0, H: 0 hidden}").replace("B -> outside", "B -> H: 0.1 * B\n  H -> outside")
    with pytest.raises(CaseError, match="H is not a measured stock"):
        build(hidden + "boundary:\n  A: {in: estimate}\n  B: {out: estimate}\n  H: {out: estimate}\n")
    build(hidden + "boundary:\n  A: {in: estimate}\n  B: {out: estimate}\n")      # B -> H -> outside: an outflow from B


def test_outside_ends_go_through_unmeasured_stocks_and_skip_smoothings():
    flows = [{"from": None, "to": "H"}, {"from": "H", "to": "B"}, {"from": "A", "to": "G"}, {"from": "G", "to": None},
             {"from": None, "to": "S"}, {"from": "S", "to": None}, {"from": "B", "to": None}]
    assert outside_ends(flows, {"A", "B"}) == {("B", "in"), ("A", "out"), ("B", "out")}
    assert outside_end(("flow", None, "B", "A")) == ("B", "in") and outside_end(("flow", "A", "B", "A")) is None
    assert outside_end(("hidden", None, "B")) == ("B", "in") and outside_end(("uses", "A", None, "B")) == ("A", "out")


def test_numbered_cases_declare_and_the_others_do_not_and_hashes(monkeypatch):
    """Every numbered ladder case declares its boundary (2026-10-20; tests/test_ladder_case_boundaries.py
    checks it against the truth); the real, realistic, physics and particle cases do not, so nothing is
    announced for them. An undeclared case's hash does not move, a declared one's does."""
    if HOME_CACHE:                                               # the draws' accepted attempts are remembered there
        monkeypatch.setenv("SDLAB_LADDER_CACHE", HOME_CACHE)
    else:
        monkeypatch.delenv("SDLAB_LADDER_CACHE")
    for cid in casemod.case_ids():
        c = casemod.load(cid)
        if cid[0].isdigit():
            assert "boundary" in c and casemod.announced(c)["boundary_declared"] is True, cid
        else:
            assert "boundary" not in c and casemod.announced(c) == {}, cid
    c = build(CHAIN)
    assert c["hash"] == casemod.case_hash({k: v for k, v in c.items() if k != "hash"})
    assert build(DECLARED)["hash"] != c["hash"] != build(DECLARED.replace("[estimate]", "[estimate, estimate]"))["hash"]


def test_the_boundary_is_announced_to_discovery_and_nothing_else(monkeypatch):
    seen = {}

    def fake(stocks, run, opts):
        seen.update(stocks=stocks, run=run, opts=opts)
        return {"flows": []}
    monkeypatch.setattr(strategies_pkg, "load", lambda name: fake)
    for text, want in ((CHAIN, None), (DECLARED, {"A": {"in": ["estimate"], "out": []}, "B": {"in": [], "out": ["estimate"]}})):
        c = build(text)
        model = casemod.truth_model(c, "none-short")
        d = {**data.load(c, "none-short"), **casemod.announced(c)}
        runner.discover("any", model, d)
        if want is None:
            assert set(seen["run"]) == {"t", "levels"}
        else:
            assert set(seen["run"]) == {"t", "levels", "boundary", "boundary_declared"}
            assert seen["run"]["boundary"] == want and seen["run"]["boundary_declared"] is True
        assert set(seen["opts"]) == {"eras"} and [s["id"] for s in seen["stocks"]] == ["A", "B"]


# ---- the scorer ----

def test_declared_outside_flows_score_as_before():
    s = scored(build(DECLARED), perfect)
    assert s["status"] == "pass" and s["boundary_declared"] and s["invented_boundary"] == 0
    u = scored(build(CHAIN), perfect)
    assert u["status"] == "pass" and "boundary_declared" not in u and "invented_boundary" not in u


def test_a_move_written_as_outflow_plus_inflow_is_an_invented_boundary():
    """A -> outside plus outside -> B reading A is the same linear system as the move A -> B:
    undeclared, equivalent (as before); declared, it fails with the invented boundary."""
    def split(model, d):
        t = perfect(model, d)
        move = next(f for f in t if f.get("from") == "A" and f.get("to") == "B")
        k = move["rate"]["k"]
        return [f for f in t if f is not move] + [prop("A", None, "A", k), prop(None, "B", "A", k)]
    assert scored(build(CHAIN), split)["status"] == "equivalent"
    s = scored(build(DECLARED), split)
    assert s["status"] == "fail" and not s["equivalent"] and s["invented_boundary"] == 2
    assert {e["kind"] for e in s["spurious"]} == {"invented boundary"}
    assert "invented boundary: an outside outflow from A, which the case's boundary does not have" in s["notes"]
    assert "invented boundary: an outside inflow to B, which the case's boundary does not have" in s["notes"]


def test_a_tiny_invented_outside_flow_still_fails_but_zero_does_not():
    def tiny(k):
        def found(model, d):
            return perfect(model, d) + [prop("A", None, "A", k)]
        return found
    assert scored(build(CHAIN), tiny(1e-6))["status"] == "pass"            # undeclared: negligible, as before
    assert scored(build(DECLARED), tiny(1e-6))["status"] == "fail"
    assert scored(build(DECLARED), tiny(0.0))["status"] == "pass"


def test_an_outside_flow_through_a_found_unmeasured_stock_is_invented():
    def via_hidden(model, d):
        return perfect(model, d) + [prop("A", "G", "A", 0.05), prop("G", None, "G", 0.5)]
    s = scored(build(DECLARED), via_hidden)
    assert s["status"] == "fail" and any(e["key"] == "A -> (unmeasured) -> outside" for e in s["spurious"])


def test_boundary_problems_reads_the_page_stocks():
    model = compile_case(CHAIN)["model"]
    assert boundary_problems({"A": {"in": ["estimate"]}, "B": {"out": ["estimate"]}}, model) == []
    assert boundary_problems({}, model) == ["boundary: the model has an outside inflow to A, not declared",
                                            "boundary: the model has an outside outflow from B, not declared"]
