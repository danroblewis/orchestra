"""Strict pass (sdlab/ladder/strict.py): a pass with no extra complexity whose long run and fresh-run
skill@100 are as good as the truth's own structure refitted on the same kind of data achieves."""

import copy

import pytest

from sdlab.ladder import cases as casemod
from sdlab.ladder import complexity, data, longrun, score, strict
from sdlab.skill import truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


_refs: dict = {}


def ref(cid, variant):
    if (cid, variant) not in _refs:
        _refs[(cid, variant)] = strict.reference(cid, variant, seeds=2, edges=2)
    return _refs[(cid, variant)]


def judge(cid, variant, flows):
    """(status, verdict) of a model graded as the ladder grades a found model."""
    c = casemod.load(cid)
    v = casemod.variant(c, variant)
    tm = casemod.truth_model(c, variant)
    d, fr = data.load(c, variant), data.load(c, variant, fresh=True)
    run, fresh = d.get("clean") or d, fr.get("clean") or fr
    if d.get("clean"):
        s = {**score.equations(c, v["noise"], tm, flows, d), "behaviour": score.behaviour(tm, flows, run, fresh)}
    else:
        s = score.score(c, v["noise"], tm, flows, d, fr)
    cx = complexity.of_result({"case": cid, "variant": variant, "status": s["status"], "found": flows})
    lr = longrun.grade(longrun.Setup(tm, run), flows)
    f100 = ((s["behaviour"].get("fresh") or {}).get("100") or {}).get("skill")
    return s["status"], strict.verdict(s["status"], f100, cx, lr, ref(cid, variant))


def truth_flows(cid, variant, change=None):
    c = casemod.load(cid)
    tm = copy.deepcopy(casemod.truth_model(c, variant))
    if change:
        change(tm)
    d = data.load(c, variant)
    return truth_by_time(tm, (d.get("clean") or d)["t"])[0]


@pytest.mark.parametrize("cid, variant", [
    ("003-chain-2", "counts-short"), ("003-chain-2", "none-long"), ("027-stepping-inflow-drain", "counts-long"),
    ("015-hidden-stock", "counts-long"), ("080-noisy-chain-2", "meas-long"),
])
def test_the_truth_strict_passes_its_own_cells(cid, variant):
    status, v = judge(cid, variant, truth_flows(cid, variant))
    assert status == "pass"
    assert v["strict"] is True, v                      # a criterion the refits cannot meet is listed in v["limited"]
    assert ref(cid, variant)["how"] in ("ml", "kalman", "truth (noise-free data)")


def test_a_model_with_an_extra_part_fails_strict():
    def extra(tm):                                       # a tiny move back from B to A: below the scorer's spurious size, so still a pass
        # (not an outside flow: 003 declares its boundary since 2026-10-20, and an outside flow it lacks fails at any size)
        tm["flows"].append({"name": "leak", "id": "leak", "from": "B", "to": "A", "rate": {"form": "proportional", "stock": "B", "k": 1e-5}})
    status, v = judge("003-chain-2", "counts-long", truth_flows("003-chain-2", "counts-long", extra))
    assert status == "pass"
    assert v["strict"] is False and "extra" in v["why"]


def test_a_pass_whose_long_run_drifts_away_fails_strict():
    def off(tm):                                         # B's drain 10% low: within the scorer's tolerance, a pass
        for f in tm["flows"]:
            if f["id"] == "b_out":
                f["rate"]["k"] *= 0.9
    status, v = judge("003-chain-2", "counts-long", truth_flows("003-chain-2", "counts-long", off))
    assert status == "pass"
    assert v["strict"] is False and "longrun" in v["why"]


def test_a_model_that_diverges_fails_strict_without_waiting_for_a_reference():
    runaway = {"hard_fail": True, "flag": "runaway", "err": {"10tau": None}}
    v = strict.verdict("pass", 0.99, {"extra": 0}, runaway, None)
    assert v["strict"] is False and v["why"] == ["longrun"]


def test_not_computed_is_never_a_fail():
    assert strict.verdict("pass", 0.99, {"extra": 0}, None, None)["strict"] is None
    assert strict.verdict("pass", 0.99, {"extra": 0}, {"err": {"10tau": 0.0}, "hard_fail": False}, None)["strict"] is None
    assert strict.cell(strict.verdict("pass", 0.99, {"extra": 0}, None, None)) == {"strict": None, "strict_why": "pending: longrun, reference"}
    assert strict.verdict("fail", None, None, None, None) == {"strict": False, "why": ["not a pass"]}
    assert strict.verdict(None, None, None, None, None)["strict"] is None


def test_a_cell_without_a_refit_has_no_reference():
    r = strict.reference("063-delay3-supply-line", "counts-short", seeds=0, edges=1)
    assert r["limited"] == ["no reference"] and r["fresh_thr"] is None
    v = strict.verdict("pass", 0.99, {"extra": 0}, {"err": {"10tau": 0.0}, "hard_fail": False}, r)
    assert v["strict"] is None and "reference" in v["pending"]
