"""Realistic cases (sdlab/ladder/realistic.py): SD Lab's examples on the ladder by reference. Every
example is referenced and compiles to its own truth model; the data are the examples' bench data for
the same seed; the hash is the example's model, not the wrapper's wording; realistic cases are kept
out of the tests' totals and have their own (skill, goals met)."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from sdlab.ladder import api, catalog, data, realistic, runner, store
from sdlab.ladder import cases as casemod

ROOT = Path(__file__).resolve().parents[1]
REAL = casemod.CASES / "realistic"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    monkeypatch.setenv("SDLAB_BENCH_CACHE", str(tmp_path / "bench"))
    return tmp_path / "ladder"


def bench_datasets():
    spec = importlib.util.spec_from_file_location("bench_datasets", ROOT / "tests" / "bench" / "datasets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def examples() -> list[str]:
    return sorted(p.parent.name for p in (ROOT / "sdlab" / "examples").glob("sd-*/truth.model.json"))


def test_every_example_is_a_realistic_case_and_compiles_to_its_truth():
    ids = [i for i in casemod.case_ids() if casemod.is_realistic(i)]
    assert ids == examples() and len(ids) == 33, "the 33 examples of the bench (31, and sd-k8s-platform and sd-k8s-small), each once"
    for i in ids:
        c = casemod.load(i)
        truth = json.loads(realistic.truth_path(i).read_text())
        assert c["example"] == i and "realistic" in c["tags"] and c["title"] and c["tests"]
        assert c["model"]["stocks"] == truth["stocks"] and c["model"]["flows"] == truth["flows"] and c["model"]["seed"] == truth["seed"]
        assert c["model"].get("schedule") == truth.get("schedule") and c["model"].get("injections") == truth.get("injections")
        assert c["model"].get("inputs") == truth.get("inputs") and c["model"].get("dt") == truth.get("dt")
        assert [(v["name"], v["steps"]) for v in c["variants"]] == [("counts-short", truth["steps"]), ("counts-long", truth.get("long_steps", 10 * truth["steps"]))]
        tm = casemod.truth_model(c, "counts-short")
        assert tm["noise"] == truth["noise"] and tm["steps"] == truth["steps"]
    order = [i for i in casemod.case_ids() if not casemod.is_real(i) and (casemod.is_realistic(i) or casemod.load(i)["level"] <= 20)]
    assert order[-len(ids):] == ids, "after the tests of level 20 or below (cases of a higher level, e.g. distilled 21 or physics 21-23, may follow; the real-data cases, level 30, come last)"


@pytest.mark.parametrize("example", ["sd-saas", "sd-population", "sd-print-shop"])
def test_the_data_are_the_bench_s_for_the_same_seed(example):
    ds = bench_datasets()
    c = casemod.load(example)
    sim = ds.load_sim(example)
    for fresh in (False, True):
        mine = data.load(c, "counts-short", fresh=fresh)
        bench = json.loads(ds.dataset(example, seed=sim.SEED + 1 if fresh else None).read_text())
        for k in ("t", "levels", "all_levels", "eras"):
            assert mine[k] == bench[k], (example, fresh, k)
        assert mine.get("injections") == bench.get("injections")


def copy_cases(tmp_path, monkeypatch, real=("sd-population",)):
    folder = tmp_path / "cases"
    (folder / "realistic").mkdir(parents=True)
    for i in ("002-inflow-outflow", "003-chain-2"):
        (folder / f"{i}.json").write_text(json.dumps(casemod.spec(i)))
    for e in real:
        shutil.copy(REAL / f"{e}.yaml", folder / "realistic" / f"{e}.yaml")
    monkeypatch.setattr(casemod, "CASES", folder)
    return folder


def test_the_hash_is_the_example_s_model_not_the_wrapper_s_words(tmp_path, monkeypatch):
    folder = copy_cases(tmp_path, monkeypatch)
    before = casemod.load("sd-population")["hash"]
    p = folder / "realistic" / "sd-population.yaml"
    p.write_text(p.read_text().replace("level: 20", "level: 21").replace('title: "', 'title: "Reworded: ') + "# a comment\n")
    casemod._load.cache_clear()
    after = casemod.load("sd-population")
    assert after["level"] == 21 and after["title"].startswith("Reworded") and after["hash"] == before
    p.write_text(p.read_text() + "lengths: {short: 200, long: 3000}\n")
    casemod._load.cache_clear()
    assert casemod.load("sd-population")["hash"] != before, "other lengths are other runs"


@pytest.mark.parametrize("text, words", [("example: sd-saas\n", "must be 'sd-population'"), ("example: sd-population\nstocks: {A: 0}\n", "unknown key"),
                                         ("example: sd-nope\n", "must be")])
def test_a_wrong_wrapper_is_reported(tmp_path, monkeypatch, text, words):
    folder = copy_cases(tmp_path, monkeypatch)
    (folder / "realistic" / "sd-population.yaml").write_text(text)
    with pytest.raises(casemod.CaseError, match=words):
        casemod.read(folder / "realistic" / "sd-population.yaml")


def test_realistic_items_have_their_own_timeout_and_run_after_the_tests(tmp_path, monkeypatch):
    copy_cases(tmp_path, monkeypatch)
    assert runner.case_timeout("sd-population", 120) == realistic.TIMEOUT
    assert runner.case_timeout("003-chain-2", 120) == 120
    assert runner.select_cases("tag:realistic") == ["sd-population"]


def behaviour(s20, s100):
    b = {"20": {"skill": s20, "ci": None}, "100": {"skill": s100, "ci": None}}
    return {"in_sample": b, "fresh": b}


def test_realistic_cases_are_kept_out_of_the_tests_totals(tmp_path, monkeypatch):
    copy_cases(tmp_path, monkeypatch)
    items = runner.plan(casemod.case_ids(), [{"name": "matrix", "hash": "m1"}])
    assert len(items) == 2 * 4 + 2, "two test cases in four variants, the example at its two lengths"
    skill = {("sd-population", "counts-short"): (0.95, 0.85), ("sd-population", "counts-long"): (0.95, 0.5)}
    for it in items:
        s20, s100 = skill.get((it["case"], it["variant"]), (0.99, 0.99))
        store.record({**{k: it[k] for k in ("case", "variant", "strategy", "case_hash", "strategy_hash", "score_hash")},
                      "status": "fail" if it["case"].startswith("sd-") else "pass", "seconds": 2.0,
                      "scores": {"recall": 0.5, "behaviour": behaviour(s20, s100)}, "found": []})
    sm = api._summary(["matrix"], catalog.listing())
    t, r = sm["totals"]["matrix"], sm["realistic"]["matrix"]
    assert t["total"] == 8 and t["pass"] == 8 and t["fail"] == 0, "the tests' pass rate leaves the realistic runs out"
    assert r["cells"] == 2 and r["run"] == 2 and r["fail"] == 2 and r["goals"] == 1 and r["goals_fresh"] == 1
    assert r["skill20"] == pytest.approx(0.95) and r["skill100"] == pytest.approx(0.675) and r["seconds"] == 4.0
    real_cells = [c for c in sm["cells"] if c["case"] == "sd-population"]
    assert [c["goal"] for c in real_cells] == [True, False] and all("goal" not in c for c in sm["cells"] if c["case"] != "sd-population")
    assert next(c for c in sm["cases"] if c["id"] == "sd-population")["example"] == "sd-population"


def test_the_goal_is_the_bench_s():
    assert realistic.meets_goal("fail", 0.9, 0.8) and not realistic.meets_goal("fail", 0.89, 0.99)
    assert not realistic.meets_goal("timeout", 1.0, 1.0) and not realistic.meets_goal("error", 1.0, 1.0) and not realistic.meets_goal(None, 1.0, 1.0)
    agg = realistic.aggregate([{"status": "timeout", "skill20": None, "skill100": None, "fresh20": None, "fresh100": None, "seconds": None, "goal": False},
                               {"status": "fail", "skill20": -5.0, "skill100": 0.2, "fresh20": -3.0, "fresh100": 0.1, "seconds": 3.0, "goal": False, "recall": 0.4}])
    assert agg["timeout"] == 1 and agg["graded"] == 1 and agg["skill20"] == -1.0, "clipped at -100% as on the bench; a timeout has no skill"
