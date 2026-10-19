"""Parametric ladder cases (sdlab/ladder/draws.py): numbers drawn from ranges, one scored case per
draw, reproducible, checked (and drawn again when a draw is not bounded and moving), reported per
draw and over the draws, and frozen into ordinary cases."""

import json
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from sdlab.ladder import api, checks, cli, draws, runner, store
from sdlab.ladder import cases as casemod
from sdlab.ladder.caseformat import CaseError


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


CHAIN = """\
title: Chain of two, random
level: 2
tags: [chain, parametric]
tests: a chain of two with random numbers
seed: 9
draws: 3          # three draws
stocks: {A: draw(0, 100, int), B: 0}
flows:
  outside -> A: draw(5, 40)        # not draw(1, 2): a comment
  A -> B: draw(0.05, 0.6, log) * A
  B -> outside: 0.2 * B
"""

# the loop's gain (births) can exceed B's drain: those draws grow without bound and are drawn again
RUNAWAY = """\
title: A loop that can run away
level: 6
tags: [loop, parametric]
tests: draws that are not bounded are drawn again
seed: 5
draws: 4
stocks: {A: 0, B: 0}
flows:
  outside -> A: 10
  A -> B: 0.5 * A
  B -> outside: 0.2 * B
  outside -> A as births: draw(0.05, 0.4) * B
"""


@pytest.fixture
def folder(tmp_path, monkeypatch):
    f = tmp_path / "cases"
    f.mkdir()
    (f / "003-chain-2.json").write_text(json.dumps(casemod.spec("003-chain-2")))
    (f / "900-random-chain.yaml").write_text(CHAIN)
    monkeypatch.setattr(casemod, "CASES", f)
    return f


# ---- the format ----

def test_sites_values_and_resolve():
    ss = draws.sites(CHAIN, "x")
    assert [s.label for s in ss] == ["stocks: A", "flows: outside -> A", "flows: A -> B"], "the draw in a comment is left alone"
    assert (ss[0].integer, ss[2].log) == (True, True)
    assert draws.count(CHAIN) == 3
    a, b = draws.values(ss, 9, 1), draws.values(ss, 9, 1)
    assert a == b and a != draws.values(ss, 9, 2) and a != draws.values(ss, 9, 1, attempt=1)
    for s, v in zip(ss, a):
        assert s.lo <= v <= s.hi
    assert a[0] == int(a[0]) and len(f"{a[1]:g}".replace(".", "").lstrip("0")) <= 3, "whole numbers, or three significant figures"
    text = draws.resolve(CHAIN, ss, a)
    assert "draws:" not in text and "draw(0, 100" not in text and "draw(1, 2)" in text
    lines = {d["label"]: d["line"] for d in draws.describe(CHAIN, ss, a)}
    assert lines["flows: A -> B"] == f"A -> B: {draws.fmt(a[2])} * A"


def test_the_mapping_form_and_two_draws_in_one_rate():
    text = "draws: 2\nstocks: {P: 0}\nflows:\n  outside -> P: (draw(100, 300) - P) / draw(2, 8)\n  P -> outside: {draw: [0.1, 0.2]}\n"
    ss = draws.sites(text)
    assert [s.label for s in ss] == ["flows: outside -> P [1]", "flows: outside -> P [2]", "flows: P -> outside"]
    assert (ss[2].lo, ss[2].hi) == (0.1, 0.2)


def test_without_a_draws_line_there_are_eight():
    assert draws.count(CHAIN.replace("draws: 3          # three draws\n", "")) == draws.DEFAULT_DRAWS == 8


@pytest.mark.parametrize("text, words", [
    ("stocks: {A: 0}\nflows:\n  outside -> A: draw(5)\n", "draw takes (lo, hi"),
    ("stocks: {A: 0}\nflows:\n  outside -> A: draw(40, 5)\n", "0 <= lo < hi"),
    ("stocks: {A: 0}\nflows:\n  outside -> A: draw(0, 5, log)\n", "lo > 0"),
    ("stocks: {A: 0}\nflows:\n  outside -> A: draw(1, 5, cubic)\n", "log and int"),
    ("draws: 3\nstocks: {A: 0}\nflows:\n  outside -> A: 5\n", "has none"),
    ("draws: 0\nstocks: {A: 0}\nflows:\n  outside -> A: draw(1, 5)\n", ">= 1"),
])
def test_mistakes_are_reported(text, words):
    with pytest.raises(CaseError, match=words.replace("(", r"\(")):
        draws.count(text, "x.yaml")


# ---- draws as cases ----

def test_a_parametric_case_is_listed_as_its_draws(folder):
    ids = casemod.case_ids()
    assert ids == ["003-chain-2", "900-random-chain#1", "900-random-chain#2", "900-random-chain#3"]
    assert casemod.known("900-random-chain#3") and not casemod.known("900-random-chain#4") and not casemod.known("900-random-chain")
    with pytest.raises(KeyError):
        casemod.load("900-random-chain")
    c = casemod.load("900-random-chain#2")
    d = c["draw"]
    assert c["id"] == "900-random-chain#2" and d["base"] == "900-random-chain" and (d["i"], d["of"], d["attempt"]) == (2, 3, 0)
    assert [x["label"] for x in d["values"]] == ["stocks: A", "flows: outside -> A", "flows: A -> B"]
    assert c["model"]["flows"][0]["rate"] == {"form": "constant", "value": d["values"][1]["value"]}
    assert c["model"]["stocks"][0]["initial"] == d["values"][0]["value"]
    assert len({casemod.load(i)["hash"] for i in ids}) == 4, "every draw is its own case, with its own hash"


def test_draws_are_reproducible_and_more_draws_keep_the_first(folder, cache):
    before = {i: casemod.load(i)["hash"] for i in casemod.case_ids()}
    casemod._load_draw.cache_clear()
    for p in (cache / "draws").glob("*.json"):
        p.unlink()
    assert {i: casemod.load(i)["hash"] for i in casemod.case_ids()} == before
    (folder / "900-random-chain.yaml").write_text(CHAIN.replace("draws: 3", "draws: 5"))
    after = {i: casemod.load(i)["hash"] for i in casemod.case_ids()}
    assert len(after) == 6 and all(after[i] == h for i, h in before.items())


def test_a_draw_that_is_not_bounded_is_drawn_again(folder):
    (folder / "901-runaway.yaml").write_text(RUNAWAY)
    got = [casemod.load(f"901-runaway#{i}") for i in range(1, 5)]
    redrawn = [c for c in got if c["draw"]["rejected"]]
    assert redrawn, "some draws of a gain up to 0.4 against a drain of 0.2 run away"
    for c in got:
        assert c["draw"]["problems"] == [] and checks.problems(c) == []
        births = c["model"]["flows"][3]["rate"]["k"]
        assert births < 0.2
    r = redrawn[0]["draw"]["rejected"][0]
    assert r["attempt"] == 0 and r["problems"] and r["values"]["flows: outside -> A as births"] >= 0.15


def test_every_draw_on_the_ladder_passed_its_checks():
    for cid in casemod.case_ids():
        d = casemod.load(cid).get("draw")
        if d:
            assert d["problems"] == [], cid


# ---- running, reporting, freezing ----

def test_select_by_draw_and_by_case(folder):
    assert runner.select_cases("900#2") == ["900-random-chain#2"]
    assert runner.select_cases("900-random-chain#3") == ["900-random-chain#3"]
    assert runner.select_cases("900") == ["900-random-chain#1", "900-random-chain#2", "900-random-chain#3"]
    assert runner.select_cases("tag:parametric") == runner.select_cases("900")


def test_status_and_summary_aggregate_over_draws(folder, capsys):
    strategies = [{"name": "matrix", "hash": "m1"}]
    items = runner.plan(runner.select_cases("900"), strategies)
    assert len(items) == 3 * 4
    for it in items:
        ok = it["case"].endswith("#1") or it["variant"].startswith("none")
        store.record({**{k: it[k] for k in ("case", "variant", "strategy", "case_hash", "strategy_hash", "score_hash")},
                      "status": "pass" if ok else "fail", "seconds": 0.1, "scores": {"recall": 1}, "found": []})
    sm = api._summary(["matrix"], [{"name": "matrix", "hash": "m1", "available": True}])
    g = sm["parametric"]["900-random-chain"]
    t = g["strategies"]["matrix"]
    assert g["draws"] == ["900-random-chain#1", "900-random-chain#2", "900-random-chain#3"]
    assert (t["pass"], t["fail"], t["total"], t["draws_passing"], t["draws_run"]) == (8, 4, 12, 1, 3) and t["rate"] == pytest.approx(8 / 12)
    one = next(c for c in sm["cases"] if c["id"] == "900-random-chain#2")
    assert one["draw"]["i"] == 2 and one["draw"]["lines"][0].startswith("stocks: {A: ")
    assert "draw" not in next(c for c in sm["cases"] if c["id"] == "003-chain-2")
    assert cli.main(["status", "--strategies", "matrix"]) == 0
    out = capsys.readouterr().out
    assert "Parametric cases" in out and "66.7% 1/3" in out
    assert cli.main(["show", "900#2", "--strategy", "matrix"]) == 0
    out = capsys.readouterr().out
    assert "Draw 2 of 3" in out and "drawn from [5, 40]" in out


def test_freeze_writes_the_draw_as_a_fixed_case(folder, capsys):
    want = casemod.load("900-random-chain#2")
    assert cli.main(["freeze", "900#2"]) == 0
    path = folder / "901-random-chain-draw-2.yaml"
    assert capsys.readouterr().out.strip() == str(path)
    text = path.read_text()
    assert "draw(" not in text.split("# not")[0] and "draws:" not in text and "frozen-draw" in text and "Frozen from 900-random-chain#2" in text
    c = casemod.load("901-random-chain-draw-2")
    assert c["model"] == want["model"] and "draw" not in c and "900-random-chain#2" in c["tests"]
    assert checks.problems(c) == []
    assert cli.main(["freeze", "900", "--slug", "x"]) == 2, "one draw at a time"
    assert cli.main(["freeze", "900#3", "--slug", "my-regression"]) == 0
    assert (folder / "902-my-regression.yaml").exists()


def test_the_endpoints_take_draw_ids(folder, monkeypatch, tmp_path):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path / "home"))
    from sdlab.server import create_app
    with TestClient(create_app()) as client:
        q = urllib.parse.quote("900-random-chain#2", safe="")
        c = client.get(f"/api/ladder/cases/{q}").json()
        assert c["id"] == "900-random-chain#2" and c["draw"]["i"] == 2
        assert client.get(f"/api/ladder/cases/{urllib.parse.quote('900-random-chain#9', safe='')}").status_code == 404
        assert client.get("/api/ladder/cases/900-random-chain").status_code == 404
        d = client.get(f"/api/ladder/cases/{q}/data/none-short").json()
        assert len(d["t"]) == 300
        assert [b["case"] for b in client.get("/api/models").json()["basics"]] == ["003-chain-2"], "draws are not basic models"
