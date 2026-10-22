"""A found model's own hidden stock matched to the truth's, and a schedule standing in for hidden state is "fits"
(2026-10-21, the user; sdlab/ladder/hidden_match.py, score._schedule_stand_ins), on kubernetes 310's leak."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from sdlab.ladder import cases as casemod, data, hidden_match, score

CASE = "310-k8s-memory-oom"


@pytest.fixture(scope="module")
def k310():
    c = casemod.load(CASE)
    m = casemod.truth_model(c, "none-short")
    return c, m, data.load(c, "none-short")


def _eq(k310, flows):
    c, m, d = k310
    return score.equations(c, "none", m, flows, d)


def _scaled(m, alpha=3.0, beta=2.0, name="h"):
    """The truth's flows with the leak written as h = alpha + beta x leak (the same model in other units)."""
    f = copy.deepcopy(m["flows"])
    for x in f:
        if x["id"] == "allocated":
            x["rate"]["expr"] = x["rate"]["expr"].replace("leak", f"(({name} - {alpha}) / {beta})")
        if x["id"] == "leaking":
            x["to"], x["rate"]["value"] = name, beta
        if x["id"] == "oom_reset":
            x["from"], x["rate"] = name, {"form": "linear", "c": -alpha, "terms": [{"stock": name, "k": 1.0}]}
    return f


def test_truth_without_its_leak_name_passes(k310):
    _, m, _ = k310
    s = _eq(k310, _scaled(m, 0.0, 1.0, "myleak"))
    assert s["status"] == "pass" and s["of"] == 26
    assert s["hidden_match"]["leak"]["found"] == "myleak"


def test_scale_and_offset_are_free(k310):
    _, m, _ = k310
    s = _eq(k310, _scaled(m))
    assert s["status"] == "pass", [p["key"] for p in s["parts"] if not p["ok"]] + [x["key"] for x in s["spurious"]]
    hm = s["hidden_match"]["leak"]
    assert hm["alpha"] == pytest.approx(3.0, abs=1e-2) and hm["beta"] == pytest.approx(2.0, rel=1e-3)


def test_wrong_reader_of_the_matched_stock_fails(k310):
    _, m, _ = k310
    f = _scaled(m)
    for x in f:
        if x["id"] == "allocated":
            x["rate"]["expr"] = x["rate"]["expr"].replace("((h - 3.0) / 2.0)", "(0.6 * (h - 3.0) / 2.0)")
    s = _eq(k310, f)
    assert s["status"] == "fail" and [p["key"] for p in s["parts"] if not p["ok"]] == ["outside -> mem [as a whole]"]


def test_unlike_hidden_stock_is_not_matched(k310):
    _, m, _ = k310
    f = _scaled(m)
    for x in f:
        if x["id"] == "oom_reset":                            # h saturates at 2: nothing like the leak
            x["rate"], x.pop("effects")
            x["rate"] = {"form": "proportional", "stock": "h", "k": 1.0}
    s = _eq(k310, f)
    assert "hidden_match" not in s and s["of"] == 23 and s["status"] == "fail"


def test_found_stock_named_as_the_truths_is_not_read_on_its_level(k310):
    _, m, d = k310
    f = copy.deepcopy(m["flows"])
    for x in f:
        if x["id"] == "oom_reset":                            # a "leak" that saturates: not the truth's
            x.pop("effects")
    s = _eq(k310, f)
    assert "hidden_match" not in s and s["status"] == "fail"
    assert not next(p for p in s["parts"] if p["key"] == "outside -> mem [as a whole]")["ok"]


def test_schedule_standing_in_for_the_leak_is_fits(k310):
    _, m, d = k310
    t, leak = d["t"], d["all_levels"]["leak"]
    f = [x for x in copy.deepcopy(m["flows"]) if x["id"] not in ("leaking", "oom_reset")]
    for x in f:
        if x["id"] == "allocated":                            # the leak's true level as a schedule, one piece a step
            x["byTime"] = [{"from": t[i + 1], "to": t[i + 1], "rate": {"form": "expr", "expr": x["rate"]["expr"].replace("leak", repr(float(leak[i])))}}
                           for i in range(len(t) - 1)]
            x["rate"] = x["byTime"][0]["rate"]
    s = _eq(k310, f)
    assert s["right"] == s["of"] == 23
    assert s["status"] == "fits" and not s["pass"]
    assert any(n.startswith("fits, not robust: outside -> mem reads hidden leak") for n in s["notes"])


def test_rewrite_linear_rate():
    f = [{"from": None, "to": "h", "rate": {"form": "constant", "value": 4.0}},
         {"from": "h", "to": None, "rate": {"form": "proportional", "stock": "h", "k": 0.5},
          "effects": [{"stock": "h", "shape": "table", "points": [[1, 0], [5, 1]]}]},
         {"from": None, "to": "m", "rate": {"form": "linear", "c": 1.0, "terms": [{"stock": "h", "k": 2.0}, {"stock": "m", "k": -0.1}]}},
         {"from": "m", "to": "h", "rate": {"form": "proportional", "stock": "m", "k": 0.2}}]
    g = hidden_match.rewrite(f, "h", "L", 1.0, 2.0, {"m"})       # h = 1 + 2 L
    assert g[0]["to"] == "L" and g[0]["rate"]["c"] == pytest.approx(2.0)                       # 1 / beta of an outside inflow
    assert g[1]["rate"]["c"] == pytest.approx(0.25) and g[1]["rate"]["terms"] == [{"stock": "L", "k": pytest.approx(0.5)}]
    assert g[1]["effects"][0]["points"] == [[0.0, 0], [2.0, 1]]
    assert g[2]["rate"]["c"] == pytest.approx(3.0) and {x["stock"]: x["k"] for x in g[2]["rate"]["terms"]} == {"m": -0.1, "L": 4.0}
    assert g[3]["to"] == "L" and g[3]["rate"] == f[3]["rate"]                                   # a move keeps its amount


def test_affine_recovers_map():
    y = np.linspace(0, 10, 50) ** 1.5
    a, b, r2 = hidden_match._affine(3 + 2 * y, y)
    assert (a, b, r2) == (pytest.approx(3), pytest.approx(2), pytest.approx(1))
