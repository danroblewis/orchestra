"""Every numbered ladder case declares its boundary (the user, 2026-10-20; docs/LADDER.md "The boundary"),
and the declaration is the truth's: per measured stock and side, one kind per true outside flow that
reaches it (directly, or through hidden stocks), "measured" for an outside inflow straight into the
stock whose rate, effects and era rates read only measured input series, "estimate" for every other
outside flow; since 2026-10-21 (the user) "input" for a "measured" inflow that is exactly 1 x one input
(no constant, no other term, no effects, no era rates). Parametric templates declare it once for all their draws. Real, realistic (sd-*),
physics and particle cases stay undeclared."""

import os
import re

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder.parts import outside_ends

HOME_CACHE = os.environ.get("SDLAB_LADDER_CACHE")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@pytest.fixture(autouse=True)
def cache(monkeypatch):
    if HOME_CACHE:                                               # the draws' accepted attempts are remembered there
        monkeypatch.setenv("SDLAB_LADDER_CACHE", HOME_CACHE)
    else:
        monkeypatch.delenv("SDLAB_LADDER_CACHE", raising=False)


def names(x, key=None) -> set[str]:
    """The stocks and inputs a rate (or its effects) reads: "stock" fields and an expr's names, not
    its functions."""
    if isinstance(x, dict):
        return set().union(set(), *(names(v, k) for k, v in x.items() if k != "uses"))
    if isinstance(x, list):
        return set().union(set(), *(names(v, key) for v in x))
    if isinstance(x, str) and key == "stock":
        return {x}
    if isinstance(x, str) and key == "expr":
        return {m.group(0) for m in NAME.finditer(x)
                if not x[m.end():].lstrip().startswith("(") and not x[:m.start()][-1:].isdigit()}
    return set()


def exactly_one_input(f: dict, inputs: set) -> bool:
    """A rate that is exactly 1 x one measured input: no constant, no other term, no effects or co-flows."""
    if f.get("effects") or f.get("uses"):
        return False
    r = f.get("rate") or {}
    terms = [{"stock": r.get("stock"), "k": r.get("k")}] if r.get("form") == "proportional" else \
        (r.get("terms") or []) if r.get("form") == "linear" and not r.get("c") else []
    return len(terms) == 1 and terms[0].get("stock") in inputs and float(terms[0].get("k") or 0) == 1.0


def truth_boundary(model: dict) -> dict:
    measured = {s["id"] for s in model["stocks"] if s.get("measured", True)}
    inputs = set(model.get("inputs") or {})
    internal = [f for f in model["flows"] if f.get("from") and f.get("to")]
    era_rates: dict = {}
    for ch in (model.get("schedule") or {}).get("changes") or []:
        for fid, rate in (ch.get("set") or {}).items():
            era_rates.setdefault(fid, []).append(rate)
    out: dict = {}
    for f in model["flows"]:
        if bool(f.get("from")) == bool(f.get("to")):
            continue
        side, end = ("in", f["to"]) if not f.get("from") else ("out", f["from"])
        read = names({k: v for k, v in f.items() if k not in ("id", "name", "from", "to")}) | names(era_rates.get(f["id"], []))
        kind = "measured" if side == "in" and end in measured and read and read <= inputs else "estimate"
        if kind == "measured" and exactly_one_input(f, inputs) and f["id"] not in era_rates:
            kind = "input"                                  # (2026-10-21) the inflow IS the measured series
        for s, sd in outside_ends([f] + internal, measured):
            if sd == side:
                out.setdefault(s, {"in": [], "out": []})[side].append(kind)
    return out


def numbered() -> list[str]:
    return [cid for cid in casemod.case_ids() if cid[0].isdigit()]


def test_every_numbered_case_declares_the_truths_boundary():
    ids = numbered()
    assert len(ids) > 250
    wrong = []
    for cid in ids:
        case = casemod.load(cid)
        assert "boundary" in case, f"{cid}: no boundary declared"
        model = case["model"]
        measured = {s["id"] for s in model["stocks"] if s.get("measured", True)}
        declared = case["boundary"]
        sides = {(s, side) for s, e in declared.items() for side in ("in", "out") if e.get(side)}
        if sides != outside_ends(model["flows"], measured):          # stock and side: what the scorer checks
            wrong.append((cid, "sides", sorted(sides), sorted(outside_ends(model["flows"], measured))))
        want = truth_boundary(model)
        got = {s: {side: list(e.get(side) or []) for side in ("in", "out")} for s, e in declared.items()}
        if {s: {k: sorted(v) for k, v in e.items()} for s, e in got.items()} != \
                {s: {k: sorted(v) for k, v in e.items()} for s, e in want.items()}:
            wrong.append((cid, "kinds", got, want))
    assert not wrong, wrong


def test_the_other_cases_stay_undeclared():
    others = [cid for cid in casemod.case_ids() if not cid[0].isdigit()]
    assert others
    for cid in others:
        case = casemod.load(cid)
        assert "boundary" not in case and casemod.announced(case) == {}, cid


def test_the_kind_rule():
    model = {"stocks": [{"id": "T"}, {"id": "H", "measured": False}], "inputs": {"pump": {}},
             "flows": [{"id": "a", "from": None, "to": "T", "rate": {"form": "proportional", "stock": "pump", "k": 2}},
                       {"id": "b", "from": None, "to": "T", "rate": {"form": "constant", "value": 3}},
                       {"id": "c", "from": None, "to": "H", "rate": {"form": "proportional", "stock": "pump", "k": 1}},
                       {"id": "d", "from": "H", "to": "T", "rate": {"form": "proportional", "stock": "H", "k": 0.5}},
                       {"id": "e", "from": "T", "to": None, "rate": {"form": "proportional", "stock": "pump", "k": 1}},
                       {"id": "f", "from": None, "to": "T", "rate": {"form": "proportional", "stock": "pump", "k": 1},
                        "effects": [{"stock": "T", "shape": "table", "points": [[0, 1], [9, 0]]}]}]}
    assert truth_boundary(model) == {"T": {"in": ["measured", "estimate", "estimate", "estimate"], "out": ["estimate"]}}
    model["flows"][0]["rate"]["k"] = 1                               # exactly 1 x the input: "input"; 0.5 + 1 x pump stays "measured"
    model["flows"].append({"id": "g", "from": None, "to": "T", "rate": {"form": "linear", "c": 0.5, "terms": [{"stock": "pump", "k": 1}]}})
    assert truth_boundary(model) == {"T": {"in": ["input", "estimate", "estimate", "estimate", "measured"], "out": ["estimate"]}}


def test_input_sides_are_the_36_exact_inflows():
    """(2026-10-21) 36 declared inflows are exactly 1 x an input (kind "input"), 6 keep "measured"."""
    kinds = {}
    for cid in numbered():
        for s, e in casemod.load(cid)["boundary"].items():
            for k in e.get("in") or []:
                if k in ("input", "measured"):
                    kinds.setdefault(k, set()).add((cid.split("#")[0], s))
    assert len(kinds["input"]) == 36 and len(kinds["measured"]) == 6, {k: len(v) for k, v in kinds.items()}
    assert ("306-k8s-ready-replicas-cap", "queue") in kinds["input"] and ("062-tank-fed-by-measured-pump", "T") in kinds["measured"]
    assert casemod.announced(casemod.load("303-k8s-daily-traffic"))["boundary"]["queue"] == {"in": ["input"], "out": []}


def test_an_input_kind_must_match_the_truth():
    from sdlab.ladder.caseformat import CaseError, boundary_problems, boundary_spec
    model = {"stocks": [{"id": "T"}], "inputs": {"pump": {}},
             "flows": [{"id": "a", "from": None, "to": "T", "rate": {"form": "proportional", "stock": "pump", "k": 2}}]}
    assert boundary_spec({"T": {"in": "input"}}) == {"T": {"in": ["input"], "out": []}}
    assert any("'input'" in p for p in boundary_problems({"T": {"in": ["input"]}}, model))
    assert not boundary_problems({"T": {"in": ["measured"]}}, model)
    model["flows"][0]["rate"]["k"] = 1
    assert not boundary_problems({"T": {"in": ["input"]}}, model)
    with pytest.raises(CaseError):
        boundary_spec({"T": {"in": "given"}})


# (2026-10-21) the 34 case files that declared "input": their model, variants, tolerance and every
# variant's truth model, as before the change (digests taken from the files at c7f89e7 and after)
# 307 re-pinned 2026-10-21: meas variants added (the user); its none/counts data are unchanged
UNCHANGED = {"115-canonical-enrolment-pipeline": "f9ac6c165d42efd5", "117-canonical-fixed-delay-line": "645d5c295539e283", "142-oscillator-pushed-by-measured-input": "590d0be92c905da8", "170-fast-cells-under-daily-input": "359e46709bcbb2d5", "171-binding-product-fed-by-inputs": "f375711474df08cd", "195-two-way-exchange-between-chambers": "bc74eb5fb7573d77", "201-control-pi-room-heater": "9ae99cddef161b97", "202-control-pid-two-tanks": "b5bc58a9102afbff", "203-control-cruise-on-hills": "09edc26501c25cc5", "207-control-cascade-two-tanks": "d8791676b47dfc69", "209-control-cruise-windup-downhill": "32894fce1fb537cc", "213-control-closed-loop-id-steady": "0aaf57036f1a2aec", "214-control-closed-loop-id-steps": "ce57dc61bce02ff9", "215-control-closed-loop-id-prbs": "9b909a2aa7aa2e23", "216-distilled-exact-integral-fed-by-stepping-input": "d66c834bbc6f10b9", "226-distilled-exchange-shut-in-announced-eras": "736b78cea6299f8b", "300-k8s-requests-in-flight": "b93134e833937fa6", "301-k8s-request-queue": "129b55136c2db3a1", "302-k8s-responses-counter": "9dff0686c0a0ad87", "303-k8s-daily-traffic": "05b5bc53dc1e02d0", "304-k8s-timeouts-and-errors": "72f8ab74e81c5e16", "305-k8s-retries": "b3386259d114d605", "306-k8s-ready-replicas-cap": "68e10c461fe219b1", "307-k8s-cpu-usage": "e216327c3d276b3d", "308-k8s-hpa": "afad58fec8734a45", "309-k8s-pod-startup": "bd4346d715b727ed", "310-k8s-memory-oom": "c2258b483625e37a", "311-k8s-node-pool": "85247673bc6a9891", "312-k8s-cluster-autoscaler": "57113f52ae4dfe30", "313-k8s-two-services": "f8a7fba9f1bbfe84", "314-k8s-chain-of-three": "ef974f3959e7c881", "315-k8s-fan-out": "12c3b5ad29e80d24", "316-k8s-shared-database": "a204b457f10c1b0b", "317-k8s-mesh-of-three": "65a7ac32ae88b61b"}


def test_input_cases_simulate_as_before():
    import hashlib
    import json
    for cid, want in UNCHANGED.items():
        case = casemod.load(cid)
        h = {"model": case["model"], "variants": case["variants"], "tolerance": case["tolerance"],
             "truth": [casemod.truth_model(case, v["name"]) for v in case["variants"]]}
        assert hashlib.sha256(json.dumps(h, sort_keys=True, default=str).encode()).hexdigest()[:16] == want, cid
