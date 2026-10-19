"""The summary built incrementally (sdlab/ladder/summary_build.py) is the summary built from scratch:
after results arrive, a strategy changes or a case changes, the kept cells and totals give exactly
the value (and the same JSON) a build with nothing kept gives. And the small responses made from it
(leaderboard.py, compact.py) agree with the full summary."""

import json

import pytest
from fastapi.testclient import TestClient

from sdlab.ladder import api, compact, leaderboard, store, summary_build
from sdlab.ladder import cases as casemod

CASES = ("001-inflow-only", "002-inflow-outflow", "003-chain-2", "010-loop-branch")


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    f = tmp_path / "cases"
    f.mkdir()
    for cid in CASES:
        (f / f"{cid}.json").write_text(json.dumps(casemod.spec(cid)))
    monkeypatch.setattr(casemod, "CASES", f)
    summary_build._stores.clear()
    return tmp_path


LISTING = [{"name": "matrix", "hash": "m1", "available": True}, {"name": "lna", "hash": "l1", "available": True},
           {"name": "gone", "hash": "g1", "available": False, "reason": "not importable"}]


def _record(cid, variant, strategy, status, seconds=1.0, recall=1.0, skill=0.9, found=None):
    c = casemod.load(cid)
    beh = {w: {str(h): {"skill": skill - 0.1 * i, "ci": [skill - 0.2, skill]} for i, h in enumerate((20, 100))} for w in ("in_sample", "fresh")}
    store.record({"case": cid, "variant": variant, "strategy": strategy, "case_hash": c["hash"], "strategy_hash": "m1" if strategy == "matrix" else "l1",
                  "score_hash": "x", "status": status, "seconds": seconds,
                  "scores": {"recall": recall, "precision": 0.5, "right": 1, "of": 2, "spurious": [], "behaviour": beh},
                  "found": found if found is not None else c["model"]["flows"]})


def _fresh(names=None, listing=LISTING):
    summary_build._stores.clear()
    return summary_build.build(names, listing)


def test_incremental_build_equals_a_full_build():
    _record("001-inflow-only", "none-short", "matrix", "pass")
    _record("002-inflow-outflow", "counts-long", "lna", "fail", recall=0.5, skill=-3.0)
    first = summary_build.build(None, LISTING)
    assert json.dumps(first) == json.dumps(_fresh())
    _record("003-chain-2", "none-long", "matrix", "equivalent", seconds=2.5)
    _record("001-inflow-only", "none-short", "matrix", "fail", skill=0.1)                 # a newer result for the same cell
    _record("010-loop-branch", "counts-short", "lna", "timeout")
    again = summary_build.build(None, LISTING)
    assert again != first
    assert json.dumps(again) == json.dumps(_fresh())
    one = next(c for c in again["cells"] if (c["case"], c["variant"], c["strategy"]) == ("001-inflow-only", "none-short", "matrix"))
    assert one["status"] == "fail"
    assert again["totals"]["matrix"]["equivalent"] == 1 and again["totals"]["lna"]["timeout"] == 1


def test_a_changed_strategy_hash_or_filter_is_rebuilt_exactly():
    _record("001-inflow-only", "none-short", "matrix", "pass")
    summary_build.build(None, LISTING)
    moved = [dict(LISTING[0], hash="m2"), *LISTING[1:]]
    got = summary_build.build(None, moved)
    assert next(c for c in got["cells"] if c["strategy"] == "matrix" and c["status"])["stale"] == "strategy changed"
    assert json.dumps(got) == json.dumps(_fresh(None, moved))
    only = summary_build.build(["lna"], LISTING)
    assert {c["strategy"] for c in only["cells"]} == {"lna"}
    assert json.dumps(summary_build.build(None, LISTING)) == json.dumps(_fresh())     # the filtered build kept the others


def test_a_replaced_store_is_read_again(cache, monkeypatch):
    _record("001-inflow-only", "none-short", "matrix", "pass")
    summary_build.build(None, LISTING)
    store.path().unlink()
    for p in store.path().parent.glob("results.sqlite-*"):
        p.unlink()
    _record("002-inflow-outflow", "none-short", "lna", "fail")
    got = summary_build.build(None, LISTING)
    assert [(c["case"], c["strategy"]) for c in got["cells"] if c["status"]] == [("002-inflow-outflow", "lna")]


def _mean(xs):
    xs = [max(-1, x) for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def test_leaderboard_rows_agree_with_the_full_summary():
    _record("001-inflow-only", "none-short", "matrix", "pass")
    _record("001-inflow-only", "counts-short", "matrix", "fail", recall=0.5, skill=-4.0)
    _record("002-inflow-outflow", "none-long", "matrix", "equivalent", seconds=3.0)
    _record("003-chain-2", "counts-long", "lna", "error", seconds=0.5)
    _record("010-loop-branch", "none-short", "lna", "pass", skill=0.95)
    sm = _fresh()
    ix = leaderboard.index(sm)
    rows = {r["name"]: r for r in leaderboard.rows(sm, ix, set_="tests")}
    assert set(rows) == {"matrix", "lna"}, "a strategy with no run cell has no row"
    for name, r in rows.items():
        t = sm["totals"][name]
        ran = [c for c in sm["cells"] if c["strategy"] == name and c["status"]]
        assert r["of"] == t["total"] and r["runs"] == t["total"] - t["missing"] == len(ran)
        assert (r["p"], r["e"], r["fl"]) == (t["pass"], t["equivalent"], t["fail"])
        assert r["pass"] == pytest.approx(t["pass"] / r["runs"]) and r["cover"] == pytest.approx(r["runs"] / t["total"])
        assert r["seconds"] == pytest.approx(t["seconds"])
        assert r["recall"] == pytest.approx(_mean([c["recall"] for c in ran]))
        assert r["skill20"] == pytest.approx(_mean([c["skill20"] for c in ran]))
        assert r["strict"] != r["strict"] or 0 <= r["strict"] <= 1
    counts = {r["name"]: r for r in leaderboard.rows(sm, ix, variant="counts", set_="tests")}
    assert counts["matrix"]["runs"] == 1 and counts["matrix"]["p"] == 0 and counts["lna"]["o"] == 1
    lv = {r["name"]: r for r in leaderboard.rows(sm, ix, level=casemod.load("002-inflow-outflow")["level"], set_="tests")}
    assert lv["matrix"]["e"] >= 1
    assert leaderboard.rows(sm, ix, kind="draws") == []


def test_javascript_formatting():
    # what the old page printed (node: (x).toFixed(d)), including halves, which round away from zero
    assert [leaderboard.fixed(x, 1) for x in (0.25, 0.35, 2.45, -0.04, -0.0, 1.05, 12.5)] == ["0.3", "0.3", "2.5", "-0.0", "0.0", "1.1", "12.5"]
    assert leaderboard.fixed(0.5, 0) == "1" and leaderboard.fixed(2.5, 0) == "3"
    assert leaderboard.pct(None) == "–" and leaderboard.pct(float("nan")) == "–" and leaderboard.pct(0.12345) == "12.3%"
    # the old page's seeded bootstrap (node: ciText([0.1, 0.5, 0.9, -0.2, 0.3]))
    assert leaderboard.ci_text([0.1, 0.5, 0.9, -0.2, 0.3]) == "[-0.0, 66.0]"
    assert leaderboard.ci_text([0.4]) == "–"


def test_endpoints(monkeypatch):
    from sdlab.server import create_app
    _record("001-inflow-only", "none-short", "matrix", "pass")
    _record("003-chain-2", "counts-long", "lna", "fail")
    monkeypatch.setattr("sdlab.ladder.catalog.listing", lambda: LISTING)
    monkeypatch.setattr("sdlab.ladder.catalog.names", lambda: [s["name"] for s in LISTING])
    api._summaries.clear()
    compact._made.clear()
    with TestClient(create_app()) as cl:
        full = cl.get("/api/ladder/summary").json()
        v = cl.get("/api/ladder/version").json()["version"]
        lb = cl.get("/api/ladder/leaderboard?set=tests").json()
        assert lb["version"] == v and {r["name"] for r in lb["rows"]} == {"matrix", "lna"}
        assert lb["levels"] == sorted({c["level"] for c in full["cases"]})
        m = cl.get("/api/ladder/matrix").json()
        cells = {(m["cases"][r[0]], m["variants"][r[1]], m["strategies"][r[2]]["name"]): dict(zip(m["fields"], r[3:])) for r in m["cells"]}
        assert len(cells) == len(full["cells"]) and m["totals"] == full["totals"] and m["by_tag"] == full["by_tag"]
        for c in full["cells"]:
            got = cells[(c["case"], c["variant"], c["strategy"])]
            assert all(got[k] == c.get(k) for k in compact.FIELDS if k != "error")
        one = cl.get("/api/ladder/matrix?case=003-chain-2").json()
        assert set(one["cases"]) == {"003-chain-2"} and "totals" not in one
        assert cl.get("/api/ladder/matrix?case=nope").status_code == 404
        assert cl.get("/api/ladder/leaderboard?kind=bad").status_code == 422


def test_leaderboard_rows_kept_per_strategy_equal_rows_made_again():
    _record("001-inflow-only", "none-short", "matrix", "pass")
    _record("003-chain-2", "counts-long", "lna", "fail")
    memo = {}
    sm = summary_build.build(None, LISTING)
    first = leaderboard.rows(sm, leaderboard.index(sm), set_="tests", memo=memo)
    _record("002-inflow-outflow", "none-long", "lna", "pass")                    # lna changes, matrix does not
    sm2 = summary_build.build(None, LISTING)
    again = leaderboard.rows(sm2, leaderboard.index(sm2), set_="tests", memo=memo)
    assert again == leaderboard.rows(sm2, leaderboard.index(sm2), set_="tests") and again != first
    assert next(r for r in again if r["name"] == "matrix") is next(r for r in first if r["name"] == "matrix")


def test_a_response_not_made_again_is_a_304(monkeypatch):
    from sdlab.server import create_app
    _record("001-inflow-only", "none-short", "matrix", "pass")
    monkeypatch.setattr("sdlab.ladder.catalog.listing", lambda: LISTING)
    api._summaries.clear()
    compact._made.clear()
    with TestClient(create_app()) as cl:
        r = cl.get("/api/ladder/leaderboard?set=tests")
        tag = r.headers["etag"]
        again = cl.get("/api/ladder/leaderboard?set=tests", headers={"If-None-Match": f"W/{tag}"})
        assert again.status_code == 304 and again.headers["etag"] == tag and not again.content
        assert cl.get("/api/ladder/leaderboard?set=all", headers={"If-None-Match": tag}).status_code == 200
