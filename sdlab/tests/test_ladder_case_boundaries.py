"""Every numbered ladder case declares its boundary (the user, 2026-10-20; docs/LADDER.md "The boundary"),
and the declaration is the truth's: per measured stock and side, one kind per true outside flow that
reaches it (directly, or through hidden stocks), "measured" for an outside inflow straight into the
stock whose rate, effects and era rates read only measured input series, "estimate" for every other
outside flow. Parametric templates declare it once for all their draws. Real, realistic (sd-*),
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
