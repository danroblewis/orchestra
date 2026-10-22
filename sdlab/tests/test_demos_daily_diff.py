"""Demo 2, daily model diff (docs/demos/daily-diff.md): the found-vs-found diff on small models, and, when the cache
and the stored day 1 exist, the demo's answers against the true change."""

import numpy as np
import pytest

from sdlab.demos import daily_diff as M


def _day(n=60):
    t = list(range(n))
    q = 50 + 20 * np.sin(np.arange(n) / 5.0)
    return {"t": t, "levels": {"q": list(q), "r": list(0.3 * q + 5)}, "inputs": {}}


P = lambda s, k: {"form": "proportional", "stock": s, "k": k}          # noqa: E731


def test_same_changed_added_removed_redrawn():
    a = [{"from": "q", "to": "r", "rate": P("q", 0.6)}, {"from": "r", "to": None, "rate": P("r", 0.4)},
         {"from": None, "to": "q", "rate": {"form": "constant", "value": 10.0}}]
    b = [{"from": "q", "to": "r", "rate": P("q", 0.8)},                                       # a number changed
         {"from": "r", "to": None, "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": "r", "k": 0.4}]}},  # redrawn
         {"from": None, "to": "r", "rate": P("q", 0.1)}]                                        # added; q's inflow removed
    r = M.diff_models(a, b, ["q", "r"], [_day()])
    kind = {e["ends"]: e["kind"] for e in r["edges"]}
    assert kind == {"q → r": "changed", "r → outside": "redrawn", "outside → r": "added", "outside → q": "removed"}
    ch = next(e for e in r["edges"] if e["ends"] == "q → r")
    assert ch["rel"] == pytest.approx(0.25, rel=1e-6) and ch["numbers"][0]["b"] == 0.8


def test_split_flow_is_the_same_edge():
    a = [{"from": "q", "to": None, "rate": P("q", 0.5)}]
    b = [{"from": "q", "to": None, "rate": P("q", 0.2)}, {"from": "q", "to": None, "rate": P("q", 0.3)}]
    r = M.diff_models(a, b, ["q", "r"], [_day()])
    assert [e["kind"] for e in r["edges"]] == ["redrawn"]


def test_tolerance_and_quiet_day_structure():
    a = [{"from": "q", "to": "r", "rate": P("q", 0.6)}, {"from": None, "to": "r", "rate": P("q", 0.01)}]
    b = [{"from": "q", "to": "r", "rate": P("q", 0.606)}]                                     # +1%: inside 2%
    quiet = M.diff_models(a, b, ["q", "r"], [_day()])
    assert {e["ends"]: e["kind"] for e in quiet["edges"]} == {"q → r": "same", "outside → r": "removed"}
    again = M.diff_models(a, b, ["q", "r"], [_day()], baseline=quiet)                          # the same removal: not a change
    assert {e["ends"]: e["kind"] for e in again["edges"]}["outside → r"] == "redrawn"
    tight = M.diff_models(a, b, ["q", "r"], [_day()], tol={"q → r": 0.005})
    assert {e["ends"]: e["kind"] for e in tight["edges"]}["q → r"] == "changed"


def test_hidden_stocks_matched_by_what_they_touch():
    a = [{"from": None, "to": "h1", "rate": {"form": "constant", "value": 1.0}},
         {"from": None, "to": "q", "rate": {"form": "expr", "expr": "2 + 0.5 * h1"}}]
    b = [{"from": None, "to": "zz", "rate": {"form": "constant", "value": 1.0}},
         {"from": None, "to": "q", "rate": {"form": "expr", "expr": "2 + 0.5 * zz"}}]
    assert M.match_hidden(a, b, ["q", "r"]) == {"zz": "h1"}
    r = M.diff_models(a, b, ["q", "r"], [_day()])
    assert all(e["kind"] == "same" for e in r["edges"])


def test_judge_right_false_missed():
    edges = [{"ends": "q → r", "from": "q", "to": "r", "kind": "changed"}, {"ends": "r → outside", "from": "r", "to": None, "kind": "added"},
             {"ends": "h → outside", "from": "h", "to": None, "kind": "same"}]
    truth = [{"from": "q", "to": "r", "ends": "q → r"}, {"from": "leak", "to": None, "ends": "leak → outside"}]
    v = M.judge(edges, truth, {"h": "leak"})
    assert [x["ends"] for x in v["right"]] == ["q → r"] and [x["ends"] for x in v["false"]] == ["r → outside"]
    assert [x["ends"] for x in v["missed"]] == ["leak → outside"] and edges[2]["verdict"] == "missed"


def test_day2_truth_is_a_copy():
    _, truth = M._case_truth("two-services")
    before = [dict(f) for f in truth["flows"]]
    m = M.day2_truth("two-services", "more-calls")
    assert next(f for f in m["flows"] if f["id"] == "catalog_calls")["rate"]["k"] == 0.45
    assert m["inputs"]["traffic"] == M.DAY2_TRAFFIC
    assert [dict(f) for f in M._case_truth("two-services")[1]["flows"]] == before
    assert len(M.day2_truth("two-services", "frontend-cache")["flows"]) == len(before) + 1
    assert M.true_change("memory-oom", "retries")[0]["after"] == "0.8 × retries"


def _ready(scen):
    try:
        M._base(scen)
    except Exception:                                                  # noqa: BLE001  (no stored day 1 here)
        return False
    return all((M._cached(scen, k) or {}).get("flows") for k in M.SCENARIOS[scen]["changes"])


@pytest.mark.skipif(not _ready("two-services"), reason="no stored day 1 or no cached day 2 (python -m sdlab.demos.daily_diff precompute)")
def test_two_services_against_the_truth():
    q = M.diff("two-services", "quiet")
    assert q["day2"]["status"] == "pass" and not q["verdict"]["false"]          # a quiet day: no edits
    for change in ("more-calls", "slow-catalog", "frontend-cache"):
        r = M.diff("two-services", change)
        v = r["verdict"]
        assert len(v["right"]) == len(r["truth"]) and not v["false"] and not v["missed"], (change, v)
    r = M.diff("two-services", "client-retry")                                  # every true change is found or reported missed
    assert len(r["truth"]) == len({x["true"]["ends"] for x in r["verdict"]["right"]}) + len(r["verdict"]["missed"])


@pytest.mark.skipif(not _ready("memory-oom"), reason="no stored day 1 or no cached day 2 (python -m sdlab.demos.daily_diff precompute memory-oom)")
def test_memory_oom_reports_failed_days():
    for change in M.SCENARIOS["memory-oom"]["changes"]:
        r = M.diff("memory-oom", change)
        assert r["day2"]["status"] and r["source"]["result"]
        if r["day2"]["status"] != "pass":
            assert r["verdict"]["false"] or r["verdict"]["missed"] or not r["truth"]


def test_api():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    got = c.get("/api/demos/daily-diff/changes")
    assert got.status_code == 200 and {s["key"] for s in got.json()["scenarios"]} == set(M.SCENARIOS)
    assert c.get("/api/demos/daily-diff/diff", params={"scenario": "two-services", "change": "nope"}).status_code == 404
    assert "/static/demos-daily-diff.js" in c.get("/api/demos/manifest").json()["scripts"]
    if _ready("two-services"):
        r = c.get("/api/demos/daily-diff/diff", params={"scenario": "two-services", "change": "slow-catalog"})
        assert r.status_code == 200 and r.json()["verdict"]["right"]


def test_model_view_source_each_day():
    from sdlab.demos import view
    for day in ("1", "2"):
        try:
            v = view._view("daily-diff", (("change", "more-calls"), ("day", day), ("scenario", "two-services")))
        except LookupError:
            pytest.skip("no stored day 1 or cached day 2")
        assert v["title"].startswith(f"Day {day}") and v["flows"] and v["diagram"]["flows"]
