"""Demo 13, agent work as stocks (sdlab/demos/agent_work.py): the true model's own readings are its numbers, the
reading of a found model reports what is missing plainly, and the routes answer from the cached found models
(skipped when the cache is absent: `uv run python -m sdlab.demos.agent_work precompute`)."""

import pytest

from sdlab.demos import agent_work as A


def test_true_model_read_back():
    r = A.readings(A.truth_model()["flows"])
    assert r["per_agent"] == pytest.approx(0.5) and r["agent_scales"]
    assert r["rework_share"] == pytest.approx(0.2)
    assert r["merge_cap"] == pytest.approx(2.2) and r["merge_cap_16"] == pytest.approx(2.2)
    assert r["agent_note"].startswith("found") and r["merge_note"].startswith("found")


def test_missing_parts_are_reported():
    flows = [{"from": "in_progress", "to": "in_review", "rate": {"form": "proportional", "stock": "in_progress", "k": 0.4}},
             {"from": "in_review", "to": "merging", "rate": {"form": "proportional", "stock": "in_review", "k": 0.3}},
             {"from": "merging", "to": "done", "rate": {"form": "expr", "expr": "min(0.5 * merging, 0.275 * agents)"}}]
    r = A.readings(flows)
    assert r["per_agent"] is None and r["agent_note"].startswith("missed")
    assert r["rework_share"] is None and r["rework_note"].startswith("missed")
    assert r["merge_cap"] == pytest.approx(2.2) and r["merge_cap_16"] == pytest.approx(4.4)
    assert "cannot tell" in r["merge_note"]


def _true_summary(add: int, extra: float = 0.0) -> dict:
    H = 14 * A.DAY
    tr = A._truth_run(add, extra, H)
    tl = {s: tr["levels"][s][A.STEPS - 1:] for s in A.STOCKS}
    return A._summary(tl, H, A.truth_model()["flows"], {k: v[A.STEPS - 1:] for k, v in tr["inputs"].items()})


def test_truth_bottleneck_moves_from_agents_to_the_merge_gate():
    four, eight, many = _true_summary(-4), _true_summary(0), _true_summary(12)
    assert four["pile"] == "in_progress" and four["growing"]
    assert eight["pile"] == "merging" and many["pile"] == "merging" and not eight["growing"]
    assert many["done_per_day"] == pytest.approx(eight["done_per_day"], rel=0.02)        # more agents buy nothing past the gate
    busy = _true_summary(12, 0.6)                                                         # a busier month: the gate is the limit
    assert busy["pile"] == "merging" and busy["growing"] and busy["done_per_day"] == pytest.approx(2.2 * 24, rel=0.02)


needs_cache = pytest.mark.skipif(not A.available(), reason="no cached found model (run precompute)")


@needs_cache
def test_routes_answer_from_the_cache():
    from fastapi.testclient import TestClient

    from sdlab.server import create_app
    c = TestClient(create_app())
    ov = c.get("/api/demos/agent-work/overview").json()
    assert ov["models"] and ov["true"]["per_agent"] == pytest.approx(0.5)
    s = ov["models"][0]["strategy"]
    sw = c.get(f"/api/demos/agent-work/sweep?strategy={s}").json()
    assert len(sw["rows"]) >= 5 and all(r["truth"]["done_per_day"] > 0 for r in sw["rows"])
    fc = c.get(f"/api/demos/agent-work/forecast?strategy={s}&add=4").json()
    assert fc["agents"] == 12 and len(fc["found"]["done"]) == len(fc["truth"]["done"])
    assert c.get("/api/demos/agent-work/forecast?strategy=nope").status_code == 409
    assert "/static/demos-agent-work.js" in c.get("/api/demos/manifest").json()["scripts"]


def test_model_view_source():
    if not A.available():
        pytest.skip("no cached found model")
    from sdlab.demos import view
    v = view._view("agent-work", (("strategy", A.available()[0]),))
    assert set(v["stocks"]) == set(A.STOCKS) and all(f["true"] for f in v["flows"] if f["status"] != "found only")
