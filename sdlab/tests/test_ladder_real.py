"""Real-data cases (sdlab/ladder/real): every case file compiles and its published model runs as written;
the loaders read only the cache (a missing download is a skip with the fetch command, never a crash,
and nothing is fetched while loading or planning); the BLS snapshot adds up; the twin is the engine's
run of the published model; the scoring is right on tiny fixtures; and real cases never count in the
Tests totals (they have their own summary)."""

import json
import shutil

import numpy as np
import pytest

from sdlab.ladder import api, catalog, runner, store
from sdlab.ladder import cases as casemod
from sdlab.ladder.real import case as realcase
from sdlab.ladder.real import data as realdata
from sdlab.ladder.real import fit, loaders, models, sources
from sdlab.ladder.real import score as realscore

REAL = casemod.CASES / "real"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    monkeypatch.setenv("SDLAB_REAL_CACHE", str(tmp_path / "real"))         # empty: nothing downloaded

    def no_network(*a, **k):
        raise AssertionError("a real case tried to download while loading")
    monkeypatch.setattr(sources, "_get", no_network)
    return tmp_path


def real_ids():
    return [i for i in casemod.case_ids() if casemod.is_real(i)]


# ---- the case files ----

def test_every_real_case_compiles_with_its_two_variants():
    ids = real_ids()
    assert len(ids) >= 40 and "real-bls-labour-flows" in ids and "real-bsflu-1978" in ids
    assert {casemod.load(i)["real"]["source"] for i in ids} == {"bls", "gauseR", "pomp", "owid"}
    for i in ids:
        c = casemod.load(i)
        assert "real" in c["tags"] and [v["name"] for v in c["variants"]] == ["real", "twin"], i
        assert 5 <= c["real"]["train"] <= c["real"]["points"] - 2, i
        assert not casemod.is_realistic(i)


@pytest.mark.parametrize("case_id", ["real-bls-labour-flows", "real-bsflu-1978", "real-gause-a3-mixture", "real-adoption-radio", "real-gause-f32-immigration"])
def test_the_twin_is_the_engine_s_run_of_the_published_model(case_id):
    c = casemod.load(case_id)
    n = c["real"]["points"]
    mine = fit.run(c["model"], n)
    tw = realdata.load(c, "twin", full=True)
    assert tw["t"] == list(range(n)) and len(realdata.load(c, "twin")["t"]) == c["real"]["train"]
    for s, v in mine.items():                                  # every stock, hidden ones too (the engine records 4 decimals)
        assert np.allclose(tw["all_levels"][s], v, rtol=1e-6, atol=1e-3), s
    assert realdata.load(c, "twin", full=True) == tw, "deterministic (and cached)"


def test_the_twin_keeps_a_total_the_data_keep():
    c = casemod.load("real-adoption-radio")
    tw = realdata.load(c, "twin", full=True)
    assert all(abs(a + b - 100) < 1e-6 for a, b in zip(tw["levels"]["A"], tw["levels"]["N"]))


def test_a_case_file_writes_its_model_exactly():
    m = models.bass(5.0, 0.01234567, 0.4, 87.5)
    got = realcase.compile_text("title: t\nlevel: 30\ntags: [real]\ntests: x\nreal: {source: owid, select: {}, points: 9, train: 6, sha256: x, twin: {}}\n"
                                + models.text(m), "t")
    a, b = fit.run(m, 30), fit.run(got["model"], 30)
    assert all(np.allclose(a[s], b[s], rtol=1e-12) for s in a)
    assert models.fmt(4.9999e-06) == "0.0000049999" and models.fmt(119081) == "119081"


# ---- loaders: the cache only ----

def test_a_missing_download_is_a_skip_with_the_fetch_command_not_a_crash():
    c = casemod.load("real-gause-a3-mixture")
    why = realdata.available(c, "real")
    assert why and "fetch gauseR" in why and "--with rdata" in why
    with pytest.raises(sources.Missing):
        realdata.load(c, "real")
    assert realdata.available(c, "twin") is None                  # the twin needs no download
    items = runner.plan(["real-gause-a3-mixture"], [{"name": "matrix", "hash": "m1"}])
    assert [i["variant"] for i in items] == ["twin"], "the real variant is not run, the twin is"
    notes = realdata.missing_notes(["real-gause-a3-mixture", "real-bls-labour-flows", "003-chain-2"])
    assert len(notes) == 1 and notes[0].startswith("real-gause-a3-mixture real")


def test_a_changed_download_is_a_skip_too(cache):
    c = casemod.load("real-bsflu-1978")
    folder = cache / "real" / "pomp"
    folder.mkdir(parents=True)
    rows = [{"day": d, "B": b, "C": 0} for d, b in enumerate([1, 6, 26, 73, 222, 293, 258, 236, 191, 124, 69, 26, 11, 4], 1)]
    (folder / "bsflu.json").write_text(json.dumps(rows))           # C all 0: not the data the case was built from
    assert "differ from the case's" in realdata.available(c, "real")


def test_the_cached_tables_are_read_offline(cache):
    folder = cache / "real" / "gauseR"
    folder.mkdir(parents=True)
    rows = [{"Time": t, "Species": sp, "Individuals": v} for sp, vs in (("A", [2, 5, None, 9, 12, 14]), ("B", [1, 2, 3, 4, 5, 6])) for t, v in enumerate(vs)]
    rows.append({"Time": 3.2, "Species": "A", "Individuals": 7})    # a time digitised off the grid: rounded, then averaged
    (folder / "toy.json").write_text(json.dumps(rows))
    s = loaders.series("gauseR", {"table": "toy", "time": "Time", "stocks": {"A": {"value": "Individuals", "where": {"Species": "A"}},
                                                                            "B": {"value": "Individuals", "where": {"Species": "B"}}}})
    assert s["t"] == [0, 1, 2] and s["time"] == [3, 4, 5] and s["levels"]["A"] == [8.0, 12.0, 14.0], "the longest run every stock has"


def test_the_bls_snapshot_adds_up():
    s = loaders.series("bls", {"first": "1990-01", "last": "2025-09"})
    lv, fl = s["levels"], s["flows"]
    rows = {r["month"]: r for r in sources.bls_rows()}
    assert s["time"][0] == "1990-01" and len(s["t"]) == 429
    for i in range(1, len(s["t"])):                                # BLS's flows into a state (and its stayers) add up to its level
        for x in "EUN":
            into = fl[f"outside->{x}"][i] + sum(fl[f"{y}->{x}"][i] for y in "EUN" if y != x) + rows[s["time"][i]][x + x]
            assert abs(into - lv[x][i]) <= 2, (s["time"][i], x)
    assert {s["time"][j["t"]][-2:] for j in s["injections"]} == {"01"}, "population controls: January only"


# ---- scoring on a tiny fixture ----

def tiny():
    """A two-stock chain: A drains into B, B drains out; 12 samples, 8 seen."""
    model = {"stocks": [{"id": "A", "initial": 100.0}, {"id": "B", "initial": 0.0}],
             "flows": [models.flow("ab", "A", "B", models.prop("A", 0.2)), models.flow("b_out", "B", None, models.prop("B", 0.1))], "injections": []}
    run = fit.run(model, 12)
    lv = {k: [float(x) for x in v] for k, v in run.items()}
    full = {"t": list(range(12)), "levels": lv, "all_levels": lv, "eras": [], "injections": [],
            "flows": {"A->B": [None] + [0.2 * lv["A"][i - 1] for i in range(1, 12)], "B->A": [None] + [0.0] * 11}}
    return model, full, realdata.cut(full, 8)


def test_the_published_model_itself_scores_as_the_published_model():
    model, full, d = tiny()
    s = realscore.score({"real": {}}, "real", model, model["flows"], d, full)
    h = s["heldout"]
    assert h["points"] == 4 and h["skill"] == pytest.approx(1.0) and h["published"] == pytest.approx(1.0) and h["beats_published"]
    assert s["status"] == "agrees" and s["recall"] == 1 and s["precision"] == 1
    f = s["flows"]["rows"]["A->B"]
    assert f["matched"] and f["error"] == pytest.approx(0.0, abs=1e-9) and s["flows"]["matched"] == 1


def test_nothing_found_is_persistence_and_agrees_with_nothing():
    model, full, d = tiny()
    s = realscore.score({"real": {}}, "real", model, [], d, full)
    assert s["heldout"]["skill"] == pytest.approx(0.0) and not s["heldout"]["beats_published"]
    assert s["status"] == "differs" and s["recall"] == 0 and s["flows"]["matched"] == 0 and not s["flows"]["rows"]["A->B"]["found"]


def test_a_wrong_rate_is_found_but_not_matched_and_an_extra_part_costs_precision():
    model, full, d = tiny()
    wrong = [models.flow("ab", "A", "B", models.prop("A", 0.1)), models.flow("b_out", "B", None, models.prop("B", 0.1)),
             models.flow("x", None, "A", models.const(5.0))]
    s = realscore.score({"real": {}}, "real", model, wrong, d, full)
    assert s["recall"] == 1 and s["precision"] == pytest.approx(2 / 3) and s["status"] == "differs"
    row = s["flows"]["rows"]["A->B"]
    assert row["found"] and not row["matched"] and row["error"] > 0.25
    assert s["heldout"]["skill"] < 1


def test_hidden_ends_are_kept_as_hidden_parts():
    c = casemod.load("real-bsflu-1978")
    ks = realscore.keys(c["model"]["flows"], {"B", "C"}, (1, 9))
    assert ("flow", "hidden", "B", "hidden") in ks and ("flow", "B", "C", "B") in ks and ("effect", "hidden", "hidden", "hidden") in ks


# ---- kept out of the Tests totals ----

def test_real_cases_are_kept_out_of_the_tests_totals(tmp_path, monkeypatch):
    folder = tmp_path / "cases"
    (folder / "real").mkdir(parents=True)
    for i in ("002-inflow-outflow", "003-chain-2"):
        (folder / f"{i}.json").write_text(json.dumps(casemod.spec(i)))
    shutil.copy(REAL / "real-bls-labour-flows.yaml", folder / "real" / "real-bls-labour-flows.yaml")
    monkeypatch.setattr(casemod, "CASES", folder)
    assert casemod.is_real("real-bls-labour-flows") and runner.select_cases("tag:real") == ["real-bls-labour-flows"]
    items = runner.plan(casemod.case_ids(), [{"name": "matrix", "hash": "m1"}])
    assert len(items) == 2 * 4 + 2
    for it in items:
        if it["case"].startswith("real-"):
            row = runner.run_item(it)                              # the real scorer, end to end, on matrix
            assert row["status"] in (("agrees", "differs") if it["variant"] == "real" else ("pass", "equivalent", "fail")), row.get("error")
        else:
            row = {**{k: it[k] for k in ("case", "variant", "strategy", "case_hash", "strategy_hash", "score_hash")}, "status": "pass",
                   "seconds": 1.0, "scores": {"recall": 1}, "found": []}
        store.record(row)
    sm = api._summary(["matrix"], catalog.listing())
    t, r = sm["totals"]["matrix"], sm["real"]["matrix"]
    assert t["total"] == 8 and t["pass"] == 8, "the tests' pass rate leaves the real runs out"
    assert r["real"]["run"] == 1 and r["twin"]["run"] == 1 and r["real"]["flows_of"] == 6
    cell = next(c for c in sm["cells"] if c["case"] == "real-bls-labour-flows" and c["variant"] == "real")
    assert cell["heldout"] is not None and cell["agree_recall"] is not None and cell["flows_of"] == 6
    assert next(c for c in sm["cases"] if c["id"] == "real-bls-labour-flows")["real"]["source"] == "bls"
    b = api.board("matrix", "counts-long")
    assert {(x["case"], x["variant"]) for x in b["results"] if x["case"].startswith("real-")} == {("real-bls-labour-flows", "real"), ("real-bls-labour-flows", "twin")}
    assert api.best_strategy() == "matrix"
