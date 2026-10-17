"""The bench's instrumentation (tests/bench: candidates.py, seeds.py, compare.py; sdlab/bench_stats.py):
every candidate graded, the judge's rank of the best, failure classes, paired tests, and the leakage
check (discovery sees only what the page gives it)."""

from __future__ import annotations

import builtins
import io
import json
import os
import pathlib
import secrets
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "bench"))
sys.path.insert(0, str(ROOT / "tests"))

import candidates  # noqa: E402
import evaluate  # noqa: E402
import seeds  # noqa: E402
from synth import generate  # noqa: E402

from sdlab.bench_stats import describe, paired  # noqa: E402
from sdlab.discovery import identify  # noqa: E402


def cand(name, judge, s20, s100):
    return {"name": name, "judge": judge, "skill": {"20": s20, "100": s100}}


def test_the_best_candidate_is_the_best_graded_and_its_rank_is_the_judges():
    graded = [cand("a", 0.10, 0.50, 0.40), cand("b", 0.20, 0.95, 0.85), cand("c", 0.30, 0.97, 0.90), cand("d", 0.05, 0.10, 0.10)]
    b = candidates.best_of(graded)
    assert (b["name"], b["rank"], b["of"], b["meets"]) == ("c", 4, 4, True)
    # a candidate graded as well (within half a point) that the judge rates better counts as the best
    graded.append(cand("c2", 0.15, 0.969, 0.899))
    assert candidates.best_of(graded)["name"] == "c2" and candidates.best_of(graded)["rank"] == 3
    # a candidate the judge could not score (no flows) ranks last
    assert candidates.best_of([cand("x", None, 0.99, 0.99), cand("y", 0.1, 0.0, 0.0)])["rank"] == 2


def test_failure_classes():
    ok = {"skill": {"20": 0.95, "100": 0.85}, "error": None}
    assert candidates.classify(ok) is None
    short = {"skill": {"20": 0.5, "100": 0.4}, "error": None}
    assert candidates.classify({**short, "best": {"meets": True}}) == "not chosen"
    assert candidates.classify({**short, "best": {"meets": False}, "truth_better": True}) == "not representable"
    assert candidates.classify({**short, "best": {"meets": False}, "truth_better": False}) == "not supported"
    assert candidates.classify({**short, "error": "boom"}) == "error"
    assert candidates.classify(short) is None                         # candidates not graded


def chain(steps=1500):
    """a -> b -> out, fed from outside, with b's level read by a's outflow: exact answers known."""
    return generate(stocks=[{"id": "a", "initial": 50}, {"id": "b", "initial": 20}],
                    flows=[{"id": "in", "from": None, "to": "a", "rate": {"form": "constant", "value": 8}},
                           {"id": "ab", "from": "a", "to": "b", "rate": {"form": "proportional", "stock": "a", "k": 0.2}},
                           {"id": "out", "from": "b", "to": None, "rate": {"form": "proportional", "stock": "b", "k": 0.1}}], steps=steps)


def test_identify_lists_every_candidate_only_when_asked_and_chooses_the_same():
    d = chain()
    plain = identify(d["stocks"], d["run"], {"eras": None})
    r = identify(d["stocks"], d["run"], {"eras": None, "candidates": True})
    assert "candidates" not in plain
    assert json.dumps(plain["flows"], sort_keys=True) == json.dumps(r["flows"], sort_keys=True) and plain["chosen"] == r["chosen"]
    assert [c["name"] for c in r["candidates"]] == [t["name"] for t in r["tried"]]
    chosen = next(c for c in r["candidates"] if c["name"] == r["chosen"])
    assert chosen["flows"] is r["flows"]


def test_instrumenting_a_run_grades_every_candidate_and_scores_the_truth_with_the_judge():
    d = chain()
    r = identify(d["stocks"], d["run"], {"eras": None, "candidates": True})
    x = candidates.instrument(r, d["model"], d["data"])
    assert len(x["candidates"]) == len(r["tried"]) and x["best"]["of"] == len(r["tried"])
    assert x["best"]["meets"] and x["best"]["rank"] >= 1
    # the true model, run as the judge runs a candidate, scores as the right model found does (the
    # counting noise sets the floor of both); a model with no flows scores far worse
    assert abs(x["truth_judge"] - x["chosen_judge"]) < 0.01 and isinstance(x["truth_better"], bool)
    assert candidates.truth_judge_error({**d["model"], "flows": []}, d["data"]) > 2 * x["truth_judge"]


def test_the_paired_tests_count_changes_and_drop_ties():
    before = [{"example": f"e{i}", "length": "default", "skill": {"20": 0.5, "100": 0.5}} for i in range(12)]
    after = [{**x, "skill": {"20": 0.6 if i < 10 else 0.5, "100": 0.5}} for i, x in enumerate(before)]
    t = paired(before, after)
    assert (t["n"], t["better"], t["worse"], t["same"]) == (12, 10, 0, 2)
    assert abs(t["sign_p"] - 2 / 1024) < 1e-12 and t["wilcoxon_p"] < 0.01
    assert "10 better" in describe(t)
    assert paired(before, after, h=100)["sign_p"] is None              # nothing changed
    mixed = [{**x, "skill": {"20": 0.5 + (0.1 if i % 2 else -0.1), "100": 0.5}} for i, x in enumerate(before)]
    assert paired(before, mixed)["sign_p"] == 1.0
    # clipped at -100% as the headline is, and paired only where both have the run
    worse = [{"example": "e0", "length": "default", "skill": {"20": -50.0, "100": 0.5}}]
    assert paired(before, worse)["mean"] == -1.5 and paired(before, worse)["n"] == 1


def test_the_seed_spread_and_headline():
    x = {"skill": {"20": 0.9, "100": 0.8}, "seeds": [{"skill": {"20": 0.8, "100": 0.8}, "fresh": {"20": 0.85, "100": 0.8}},
                                                    {"skill": {"20": 1.0, "100": 0.8}, "fresh": {"20": 0.95, "100": 0.8}}]}
    assert seeds.values(x, 20) == [0.9, 0.8, 1.0] and seeds.values(x, 20, "fresh") == [0.85, 0.95]
    assert seeds.spread(x, 20) == "90.0% ± 10.0"
    assert "90.0% ± 10.0 over seeds" in seeds.headline([x])[0]


# ---- leakage: discovery sees only the page's inputs ----

def test_the_bench_hands_discovery_only_the_pages_inputs(monkeypatch):
    seen = {}

    def strategy(stocks, run, opts):
        seen.update(stocks=stocks, run=run, opts=opts)
        return {"flows": []}

    monkeypatch.setattr(evaluate, "load", lambda name: strategy)
    evaluate.evaluate_one("sd-eras", "default", "matrix", with_candidates=False)
    model = json.loads((evaluate.EXAMPLES / "sd-eras.json").read_text())
    assert [s["id"] for s in seen["stocks"]] == [s["id"] for s in model["stocks"]]
    assert all(set(s) <= {"id", "name", "unit", "final", "group"} for s in seen["stocks"])
    assert set(seen["run"]) == {"t", "levels"} and list(seen["run"]["levels"]) == [s["id"] for s in model["stocks"]]
    assert set(seen["opts"]) == {"eras"} and all(set(e) == {"start", "label"} for e in seen["opts"]["eras"])


@pytest.mark.parametrize("example", ["sd-eras", "sd-saas"])
def test_discovery_finds_the_same_model_with_truth_unreadable_and_stocks_renamed(example, monkeypatch):
    """Stock ids and names replaced by random strings, and every truth file (and the example's
    folder and the dataset cache) unreadable while discovery runs: the same model, up to renaming."""
    model = json.loads((evaluate.EXAMPLES / f"{example}.json").read_text())
    data = evaluate.load_data(example, "default")
    stocks, run, opts = evaluate.page_inputs(model, data)
    plain = identify(stocks, run, opts)

    new = {s["id"]: f"q{secrets.token_hex(6)}" for s in stocks}
    renamed = [{**s, "id": new[s["id"]], "name": f"n{secrets.token_hex(6)}"} for s in stocks]
    run2 = {"t": run["t"], "levels": {new[k]: v for k, v in run["levels"].items()}}

    blocked = (str(evaluate.EXAMPLES / example), "truth", str(evaluate.datasets.cache_dir()))

    def guard(opener):
        def open_(file, *a, **k):
            if isinstance(file, (str, os.PathLike)) and any(b in os.fspath(file) for b in blocked):
                raise PermissionError(f"discovery read {file}")
            return opener(file, *a, **k)
        return open_

    for mod, name in ((builtins, "open"), (io, "open"), (os, "open")):
        monkeypatch.setattr(mod, name, guard(getattr(mod, name)))
    for name in ("read_text", "read_bytes", "open"):
        orig = getattr(pathlib.Path, name)
        monkeypatch.setattr(pathlib.Path, name, lambda self, *a, _o=orig, **k: (_ for _ in ()).throw(PermissionError(str(self)))
                            if any(b in str(self) for b in blocked) else _o(self, *a, **k))
    with pytest.raises(PermissionError):
        (evaluate.EXAMPLES / example / "truth.model.json").read_text()
    found = identify(renamed, run2, opts)
    monkeypatch.undo()

    back = json.dumps(found["flows"], sort_keys=True)
    for old, n in new.items():
        back = back.replace(n, old)
    assert back == json.dumps(plain["flows"], sort_keys=True)
    assert found["chosen"] == plain["chosen"]
