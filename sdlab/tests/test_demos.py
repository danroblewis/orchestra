"""The demos (docs/DEMOS.md): they read a stored found model and the case's true model, change only in-memory copies,
and their answers are checked against the truth they are built on."""

import pytest

from sdlab.demos import demos as D
from sdlab.demos import engine as E


def test_numbers_round_trip():
    flows = [{"from": "q", "to": None, "rate": {"form": "proportional", "stock": "q", "k": 0.6}},
             {"from": None, "to": "d", "rate": {"form": "expr", "expr": "1 * (d < min(16, ceil(cpu / 192.5)))"}},
             {"from": None, "to": "m", "rate": {"form": "linear", "c": 2.0, "terms": [{"stock": "a", "k": 0.5}]}}]
    nums = {n["key"]: n for n in E.numbers(flows)}
    assert nums["0/k"]["value"] == 0.6 and nums["2/c"]["value"] == 2.0 and nums["2/terms/0"]["label"] == "× a"
    div = next(n for n in nums.values() if n["value"] == 192.5)
    assert div["label"] == "cpu / 192.5"
    got = E.set_number(flows, div["key"], 150.0)
    assert "150.0" in got[1]["rate"]["expr"] and "192.5" in flows[1]["rate"]["expr"]          # a copy: the input is untouched


def test_true_rate_scaling():
    assert E.scale_true_rate({"form": "proportional", "stock": "x", "k": 2}, 1.5) == {"form": "proportional", "stock": "x", "k": 3.0}
    lin = E.scale_true_rate({"form": "linear", "terms": [{"stock": "a", "k": 1}, {"stock": "b", "k": 2}]}, 2.0, "b")
    assert [t["k"] for t in lin["terms"]] == [1, 4.0]


def _have_310():
    try:
        D._base("memory-oom")
        return True
    except Exception:                                                  # noqa: BLE001  (no stored passing result here)
        return False


@pytest.mark.skipif(not _have_310(), reason="no stored passing result for the 310 scenario in this store")
def test_residual_watch_catches_each_change_on_the_right_flow():
    for change in ("faster-retries", "slower-starts", "more-errors"):
        r = D.residual("memory-oom", change)
        a = r["first_alarm"]
        assert a and 0 <= a["after"] <= 5 and not r["false_alarms"], (change, a, r["false_alarms"])
        assert r["change"]["ends"] in r["suspects"], (change, r["suspects"])


@pytest.mark.skipif(not _have_310(), reason="no stored passing result for the 310 scenario in this store")
def test_whatif_matches_the_true_model_on_a_proportional_flow():
    key = next(n["key"] for n in E.numbers(D._base("memory-oom")["result"]["found"]) if n["ends"] == "retries → queue")
    w = D.whatif("memory-oom", key, 0.9, steps=400)
    assert w["truth_change"]["flow"] == "retried"
    q = w["stocks"]["queue"]
    assert abs(q["found_edited"][-1] - q["truth_edited"][-1]) / q["truth_edited"][-1] < 0.01
