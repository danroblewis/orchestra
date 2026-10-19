"""The ladder (sdlab/ladder): its cases are sane, its scoring passes the truth and fails wrong models,
its data is deterministic, its store re-runs exactly what is stale, and its CLI and read endpoints
work end to end."""

import copy
import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from sdlab.discovery import strategies as strategies_pkg
from sdlab.ladder import api, catalog, checks, cli, data, noise, runner, score, store
from sdlab.ladder import cases as casemod
from sdlab.skill import truth_by_time


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


def scored(case_id, flows_of, variant="counts-short"):
    c = casemod.load(case_id)
    model = casemod.truth_model(c, variant)
    d = data.load(c, variant)
    flows = flows_of(model, d)
    return score.equations(c, casemod.variant(c, variant)["noise"], model, flows, d)


def perfect(model, d):
    return truth_by_time(model, d["t"])[0]


def flow(model, fid):
    return next(f for f in model["flows"] if f["id"] == fid)


# ---- the cases ----

def test_there_is_a_ladder():
    ids = casemod.case_ids()
    assert len(ids) >= 20 and len(set(ids)) == len(ids)
    levels = [casemod.load(i)["level"] for i in ids]
    assert levels == sorted(levels), "listed simplest first (by level, then id), whatever order the files were written in"
    for i in ids:
        c = casemod.load(i)
        assert c["title"] and c["tests"] and c["tags"], i
        names = [v["name"] for v in c["variants"]]
        # none and counts, and the noises laid on the recorded levels (noise.py) for a case that asks for them
        assert names and len(set(names)) == len(names) and {v["noise"] for v in c["variants"]} <= {"none", "counts", *noise.KINDS}, i
        assert all(bool(v.get("observe")) == (v["noise"] in noise.KINDS) for v in c["variants"]), i


TESTS = [i for i in casemod.case_ids() if not casemod.is_realistic(i)]     # realistic cases: test_ladder_realistic.py


@pytest.mark.parametrize("case_id", TESTS)
def test_every_case_is_sane(case_id):
    assert checks.problems(casemod.load(case_id)) == []


@pytest.mark.parametrize("case_id", TESTS)
@pytest.mark.parametrize("variant", ["none-short", "counts-long"])
def test_the_true_model_passes_its_own_equation_scoring(case_id, variant):
    if variant not in {v["name"] for v in casemod.load(case_id)["variants"]}:
        pytest.skip(f"{case_id} has no {variant} variant")          # the noisy cases (noise.py) run counts and their noises
    s = scored(case_id, perfect, variant)
    assert s["status"] == "pass", [p for p in s["parts"] if not p["ok"]] + s["spurious"]
    assert s["recall"] == 1 and s["precision"] == 1


def test_data_is_deterministic_and_cached(cache):
    c = casemod.load("021-daily-inflow")
    a = data.load(c, "counts-short")
    files = list((cache / "data").glob("*.json"))
    assert len(files) == 1 and c["hash"] in files[0].name
    shutil.rmtree(cache / "data")
    b = data.load(c, "counts-short")
    assert a == b
    fresh = data.load(c, "counts-short", fresh=True)
    assert fresh["levels"] != a["levels"], "the fresh run has other random draws"
    assert data.load(c, "none-short", fresh=True)["levels"] == data.load(c, "none-short")["levels"], "without noise it is the same run"


# ---- scoring ----

def test_a_wrong_rate_fails():
    def wrong(model, d):
        flows = copy.deepcopy(model["flows"])
        flow({"flows": flows}, "ab")["rate"]["k"] = 0.8
        return flows
    s = scored("003-chain-2", wrong, "none-short")
    assert s["status"] == "fail"
    bad = [p for p in s["parts"] if not p["ok"]]
    assert [p["key"] for p in bad] == ["A -> B [A]"] and bad[0]["kind"] == "move"
    assert s["recall"] == 1


def test_a_missing_flow_and_a_spurious_flow_fail():
    def missing(model, d):
        return [f for f in model["flows"] if f["id"] != "b_out"]
    s = scored("003-chain-2", missing, "none-short")
    assert s["status"] == "fail" and s["recall"] == pytest.approx(2 / 3)

    def extra(model, d):
        return model["flows"] + [{"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.2}}]
    s = scored("003-chain-2", extra, "none-short")
    assert s["status"] == "fail" and [p["kind"] for p in s["spurious"]] == ["outside outflow"] and s["precision"] < 1


def test_a_link_found_as_a_move_is_equivalent_not_pass():
    """007: B's inflow follows A's level (a link) and A drains 0.2 to outside. A move A -> B at 0.1
    and a drain of 0.1 make the same system: equivalent."""
    def as_move(model, d):
        return [flow(model, "in"), flow(model, "b_out"),
                {"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.1}},
                {"from": "A", "to": None, "rate": {"form": "proportional", "stock": "A", "k": 0.1}}]
    s = scored("007-link", as_move, "none-short")
    assert s["status"] == "equivalent" and not s["pass"] and s["equivalent"]


def test_births_and_deaths_seen_as_their_difference_are_equivalent():
    def net(model, d):
        return [flow(model, "immigration"), {"from": "P", "to": None, "rate": {"form": "proportional", "stock": "P", "k": 0.02}}]
    assert scored("009-births-and-deaths", net, "none-long")["status"] == "equivalent"


def test_eras_must_be_right_in_every_era():
    def one_rate(model, d):
        flows = copy.deepcopy(model["flows"])
        flow({"flows": flows}, "ab")["rate"]["k"] = 0.375          # the mean of 0.5 and 0.25
        return flows
    s = scored("019-announced-era", one_rate, "none-short")
    assert s["status"] == "fail" and s["windows"] > 1


def test_a_hidden_stock_is_scored_by_its_delay():
    def via(delay):
        def found(model, d):
            return [flow(model, "in"), flow(model, "b_out"),
                    {"from": "A", "to": "B", "rate": {"form": "proportional", "stock": "A", "k": 0.2}, "via": {"delay": delay, "shape": "exp"}}]
        return found
    assert scored("015-hidden-stock", via(10), "none-short")["status"] == "pass"
    s = scored("015-hidden-stock", via(4), "none-short")
    assert s["status"] == "fail" and [p["kind"] for p in s["parts"] if not p["ok"]] == ["hidden"]


def test_an_effect_is_needed_for_an_effect_case():
    def no_effect(model, d):
        flows = copy.deepcopy(model["flows"])
        flow({"flows": flows}, "ab").pop("effects")
        return truth_by_time({**model, "flows": flows}, d["t"])[0]
    s = scored("017-linear-effect", no_effect, "none-short")
    assert s["status"] == "fail"
    assert {p["kind"] for p in s["parts"] if not p["ok"]} >= {"effect"}


def test_noise_gets_the_oracle_s_slack_and_no_noise_does_not():
    """With counting noise a number may be off by 3 standard errors of the truth's own structure
    fitted on the run; without noise, 2% is all."""
    def off(frac):
        def found(model, d):
            flows = copy.deepcopy(model["flows"])
            flow({"flows": flows}, "a_out")["rate"]["k"] = 0.1 * (1 + frac)
            return flows
        return found
    assert scored("002-inflow-outflow", off(0.05), "none-short")["status"] == "fail"
    s = scored("002-inflow-outflow", off(0.05), "counts-short")
    assert s["status"] == "pass", s["parts"]
    assert all(p["se"] and p["se"] > 0 for p in s["parts"])


def test_behaviour_has_bootstrap_intervals():
    c = casemod.load("003-chain-2")
    model = casemod.truth_model(c, "counts-short")
    d = data.load(c, "counts-short")
    flows = copy.deepcopy(model["flows"])
    flow({"flows": flows}, "ab")["rate"]["k"] = 0.4
    b = score.behaviour(model, flows, d, data.load(c, "counts-short", fresh=True))
    for where in ("in_sample", "fresh"):
        for h in ("20", "100"):
            x = b[where][h]
            assert x["ci"][0] <= x["skill"] <= x["ci"][1] and x["ci"][0] < x["ci"][1]


# ---- the store and staleness ----

@pytest.fixture
def two_cases(tmp_path, monkeypatch):
    folder = tmp_path / "cases"
    folder.mkdir()
    for i in ("002-inflow-outflow", "003-chain-2"):
        (folder / f"{i}.json").write_text(json.dumps(casemod.spec(i)))     # a JSON case still loads
    monkeypatch.setattr(casemod, "CASES", folder)
    return folder


def fake_row(item, status="pass"):
    return {**{k: item[k] for k in ("case", "variant", "strategy", "case_hash", "strategy_hash", "score_hash")}, "status": status,
            "seconds": 0.1, "scores": {"recall": 1}, "found": []}


def test_sync_reruns_exactly_the_stale_pairs(two_cases, monkeypatch):
    strategies = [{"name": "matrix", "hash": "m1"}, {"name": "other", "hash": "o1"}]
    first = runner.plan(casemod.case_ids(), strategies)
    assert len(first) == 2 * 4 * 2 and {i["reason"] for i in first} == {"new"}
    for it in first:
        store.record(fake_row(it))
    assert runner.plan(casemod.case_ids(), strategies) == []

    # a case changes: its 8 pairs (4 variants x 2 strategies) run again, nothing else
    p = two_cases / "003-chain-2.json"
    spec = json.loads(p.read_text())
    spec["model"]["flows"][1]["rate"]["k"] = 0.4
    p.write_text(json.dumps(spec))
    again = runner.plan(casemod.case_ids(), strategies)
    assert {(i["case"], i["reason"]) for i in again} == {("003-chain-2", "case changed")} and len(again) == 8
    for it in again:
        store.record(fake_row(it))

    # a strategy changes: its pairs only; a new strategy: all of its pairs
    strategies = [{"name": "matrix", "hash": "m2"}, {"name": "other", "hash": "o1"}, {"name": "new", "hash": "n1"}]
    again = runner.plan(casemod.case_ids(), strategies)
    assert {(i["strategy"], i["reason"]) for i in again} == {("matrix", "strategy changed"), ("new", "new")} and len(again) == 16
    for it in again:
        store.record(fake_row(it))

    # the scorer changes: everything is re-scored (discovery is not run again)
    monkeypatch.setattr(score, "score_hash", lambda: "another")
    again = runner.plan(casemod.case_ids(), strategies)
    assert len(again) == 2 * 4 * 3 and {i["mode"] for i in again} == {"rescore"}

    # history is kept; one latest per key
    rows = store.history("003-chain-2", "none-short", "matrix")
    assert len(rows) == 3 and [r["latest"] for r in rows] == [True, False, False]
    assert len(store.latest(strategy="matrix")) == 8


def test_a_strategy_that_raises_or_hangs_is_recorded(monkeypatch, two_cases):
    item = runner.plan(["003-chain-2"], [{"name": "matrix", "hash": "m1"}], ["none-short"])[0]

    def boom(*a):
        raise ValueError("no luck")
    monkeypatch.setattr(runner, "discover", boom)
    row = runner.run_item(item)
    assert row["status"] == "error" and "no luck" in row["error"]

    def slow(*a):
        time.sleep(5)
    monkeypatch.setattr(runner, "discover", slow)
    began = time.time()
    row = runner.run_item(item, timeout=0.3)
    assert row["status"] == "timeout" and time.time() - began < 3


def test_a_strategy_needing_a_missing_package_is_skipped(tmp_path, monkeypatch):
    extra = tmp_path / "more"
    extra.mkdir()
    (extra / "needs_pkg.py").write_text("import not_a_real_package_xyz  # noqa\n\ndef identify(stocks, run, opts):\n    return {'flows': []}\n")
    monkeypatch.setattr(strategies_pkg, "__path__", [*strategies_pkg.__path__, str(extra)])
    listing = {s["name"]: s for s in catalog.listing()}
    assert listing["matrix"]["available"]
    assert not listing["needs_pkg"]["available"] and "not_a_real_package_xyz" in listing["needs_pkg"]["reason"]
    avail, skipped = runner.select_strategies("all")
    assert "needs_pkg" in [s["name"] for s in skipped] and "needs_pkg" not in [s["name"] for s in avail]


def test_strategy_hash_follows_discovery_but_not_other_strategies():
    h = catalog.strategy_hash("matrix")
    assert h == catalog.strategy_hash("matrix") and len(h) == 16
    files = {p.name for p in catalog._shared_files()}
    assert "identify.py" in files and "matrix.py" in files and "simulate.py" in files   # discovery/matrix.py is shared code
    assert all(p.parent != catalog.STRATEGIES or p.name == "__init__.py" for p in catalog._shared_files())


# ---- the CLI and the read endpoints, end to end ----

def test_the_cli_runs_a_subset_end_to_end(capsys):
    assert cli.main(["run", "--strategies", "matrix", "--cases", "001,003", "--variants", "none-short", "--jobs", "1", "--quiet"]) == 0
    rows = store.latest()
    assert {(r["case"], r["variant"], r["strategy"]) for r in rows} == {("001-inflow-only", "none-short", "matrix"), ("003-chain-2", "none-short", "matrix")}
    assert all(r["status"] == "pass" for r in rows), rows
    assert cli.main(["sync", "--strategies", "matrix", "--cases", "001,003", "--variants", "none-short", "--quiet"]) == 0
    assert "Nothing to run" in capsys.readouterr().out
    assert cli.main(["status", "--strategies", "matrix"]) == 0
    out = capsys.readouterr().out
    assert "003-chain-2" in out and "P..." in out
    assert cli.main(["show", "003", "--strategy", "matrix"]) == 0
    out = capsys.readouterr().out
    assert "True equations" in out and "A -> B = 0.5 * A" in out and "PASS" in out
    p = store.progress()
    assert p["run"]["total"] == 2 and p["run"]["done"] == 2 and p["run"]["finished"]


def test_the_cli_runs_in_a_process_pool():
    assert cli.main(["sync", "--strategies", "matrix", "--cases", "002", "--variants", "short", "--jobs", "2", "--quiet"]) == 0
    rows = store.latest(case="002-inflow-outflow")
    assert {r["variant"] for r in rows} == {"none-short", "counts-short"} and all(r["status"] in api.STATUSES for r in rows)
    assert all(r["seconds"] is not None for r in rows)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path / "home"))
    from sdlab.server import create_app
    with TestClient(create_app()) as c:
        yield c


def test_the_read_endpoints(client):
    cs = client.get("/api/ladder/cases").json()
    assert [c["id"] for c in cs] == casemod.case_ids()
    one = client.get("/api/ladder/cases/003-chain-2").json()
    assert one["model"]["flows"][1]["id"] == "ab" and one["variants"][0]["name"] == "none-short"
    assert "matrix" in [s["name"] for s in client.get("/api/ladder/strategies").json()]
    assert client.get("/api/ladder/results").json() == []
    assert client.get("/api/ladder/progress").json() == {"run": None, "items": []}
    assert client.get("/api/ladder/results/003-chain-2/none-short/matrix").status_code == 404

    cli.main(["run", "--strategies", "matrix", "--cases", "003", "--variants", "none-short", "--jobs", "1", "--quiet"])
    rs = client.get("/api/ladder/results", params={"strategy": "matrix"}).json()
    assert len(rs) == 1 and rs[0]["status"] == "pass" and "found" not in rs[0]
    r = client.get("/api/ladder/results/003-chain-2/none-short/matrix").json()
    assert r["found"] and r["scores"]["parts"]
    assert len(client.get("/api/ladder/results/003-chain-2/none-short/matrix/history").json()) == 1
    assert client.get("/api/ladder/progress").json()["run"]["done"] == 1
    s = client.get("/api/ladder/summary", params={"strategies": "matrix"}).json()
    cell = next(c for c in s["cells"] if c["case"] == "003-chain-2" and c["variant"] == "none-short")
    assert cell["status"] == "pass" and cell["skill20_ci"] and cell["stale"] is None
    assert s["totals"]["matrix"]["pass"] == 1 and s["by_tag"]["chain"]["matrix"]["total"] >= 4


@pytest.mark.parametrize("url", ["/api/ladder/cases/..%2F..%2Fetc", "/api/ladder/cases/nope", "/api/ladder/results/003-chain-2/none-short/nope",
                                 "/api/ladder/results/003-chain-2/bogus/matrix", "/api/ladder/results/nope/none-short/matrix/history",
                                 "/api/ladder/results?case=nope", "/api/ladder/results?variant=bogus", "/api/ladder/results?strategy=os",
                                 "/api/ladder/summary?strategies=matrix,nope"])
def test_the_read_endpoints_refuse_unknown_names(client, url):
    assert client.get(url).status_code == 404


def test_the_page_s_endpoints(client):
    page = client.get("/ladder")
    assert page.status_code == 200 and "ladder.js?v=" in page.text and "diagram.js?v=" in page.text
    assert client.get("/ladder/leaderboard").status_code == 200
    d = client.get("/api/ladder/cases/015-hidden-stock/data/none-short").json()
    assert d["measured"] == ["A", "B"] and set(d["all_levels"]) == {"A", "H", "B"} and "H" not in d["levels"]
    assert len(d["t"]) == len(d["levels"]["A"]) == 300
    fresh = client.get("/api/ladder/cases/021-daily-inflow/data/counts-short", params={"fresh": True}).json()
    assert fresh["fresh"] and fresh["levels"] != client.get("/api/ladder/cases/021-daily-inflow/data/counts-short").json()["levels"]
    assert client.get("/api/ladder/strategies/matrix/timeline").json() == []

    for _ in range(2):
        cli.main(["run", "--strategies", "matrix", "--cases", "003", "--variants", "none-short", "--jobs", "1", "--quiet"])
    h = client.get("/api/ladder/results/003-chain-2/none-short/matrix/history").json()
    one = client.get(f"/api/ladder/result/{h[-1]['id']}").json()
    assert one["id"] == h[-1]["id"] and one["found"] and not one["latest"]
    light = client.get("/api/ladder/progress", params={"recent": 0}).json()
    assert light["items"] == [] and light["counts"] == {"pass": 1} and light["queued"] == 0 and light["run"]["done"] == 1
    assert len(client.get("/api/ladder/progress", params={"recent": 5}).json()["items"]) == 1
    tl = client.get("/api/ladder/strategies/matrix/timeline").json()
    assert len(tl) == 1 and tl[0]["ran"] == 2 and tl[0]["totals"]["pass"] == 1 and tl[0]["of"] == sum(len(casemod.load(i)["variants"]) for i in casemod.case_ids())


@pytest.mark.parametrize("url", ["/api/ladder/cases/nope/data/none-short", "/api/ladder/cases/003-chain-2/data/bogus",
                                 "/api/ladder/result/999999", "/api/ladder/strategies/nope/timeline", "/api/ladder/strategies/..%2Fos/timeline"])
def test_the_page_s_endpoints_refuse_unknown_names(client, url):
    assert client.get(url).status_code == 404


def test_a_run_whose_process_died_is_reported_over(monkeypatch):
    items = [{"case": "003-chain-2", "variant": v, "strategy": "matrix"} for v in ("none-short", "none-long")]
    rid = store.start_run("run", items)
    store.mark(rid, items[0], "running")
    p = store.progress()["run"]
    assert p["finished"] is None and p["running"] == 1, "a live run is live"
    monkeypatch.setattr(store, "STALL", -1)
    p = store.progress()
    assert p["run"]["finished"] and p["run"]["aborted"] and p["run"]["running"] == 0 and p["items"][0]["state"] in ("aborted", "queued")
    monkeypatch.setattr(store, "STALL", 10_000)
    for it in items:
        store.mark(rid, it, "done", "pass")
    p = store.progress()["run"]
    assert p["finished"] and not p["aborted"], "everything done: over, though nobody marked it finished"


def test_the_board_has_every_case_with_one_strategy_s_results(client):
    cli.main(["run", "--strategies", "matrix", "--cases", "003,007", "--jobs", "1", "--quiet"])
    b = client.get("/api/ladder/board", params={"strategy": "matrix", "variant": "counts-long"}).json()
    assert b["strategy"] == "matrix" and b["variant"] == "counts-long" and b["best"] == "matrix"
    assert [c["id"] for c in b["cases"]] == casemod.case_ids()
    assert {(r["case"], r["variant"]) for r in b["results"]} == {("003-chain-2", "counts-long"), ("007-link", "counts-long")}
    assert all(r["found"] is not None and r["scores"]["parts"] for r in b["results"])
    every = client.get("/api/ladder/board", params={"strategy": "matrix", "variant": "all"}).json()
    assert every["variant"] is None and len(every["results"]) == 8
    assert client.get("/api/ladder/board").json()["strategy"] == "matrix", "the best strategy by default"
    assert client.get("/api/ladder/board", params={"strategy": "nope"}).status_code == 404
    assert client.get("/api/ladder/board", params={"variant": "bogus"}).status_code == 404
