"""Where a result comes from: the case hash covers the model, not its wording; a result records the
hash of the strategy code its process imported (not the plan's), the git commit, and a patch hash
when that code is not the commit's."""

import json

import pytest

from sdlab.discovery import strategies as strategies_pkg
from sdlab.ladder import cases as casemod
from sdlab.ladder import catalog, provenance, runner, store


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / "ladder"))
    return tmp_path / "ladder"


@pytest.fixture
def folder(tmp_path, monkeypatch):
    f = tmp_path / "cases"
    f.mkdir()
    (f / "003-chain-2.yaml").write_text((casemod.CASES / "003-chain-2.yaml").read_text())
    monkeypatch.setattr(casemod, "CASES", f)
    return f


def test_rewording_a_case_keeps_its_hash(folder):
    p = folder / "003-chain-2.yaml"
    before = casemod.load("003-chain-2")["hash"]
    assert before == casemod.case_hash(casemod.load("003-chain-2"))
    text = p.read_text()
    p.write_text(text.replace("title: Chain of two", "title: Two in a row").replace("tests: ", "tests: (reworded) ")
                 .replace("level: 2", "level: 3").replace("tags: [chain, move]", "tags: [chain]"))
    assert casemod.load("003-chain-2")["hash"] == before, "title, level, tags and tests are not what a run is made from"
    p.write_text(text.replace("A -> B: 0.5 * A", "A -> B: 0.4 * A"))
    assert casemod.load("003-chain-2")["hash"] != before
    p.write_text(text + "tolerance: {rel: 0.2}\n")
    assert casemod.load("003-chain-2")["hash"] != before, "the tolerance changes the scores"


@pytest.fixture
def toy(tmp_path, monkeypatch):
    """A strategy outside the repository (so its code is never a commit's): toy_strategy."""
    extra = tmp_path / "more"
    extra.mkdir()
    f = extra / "toy_strategy.py"
    f.write_text("VERSION = 1\n\ndef identify(stocks, run, opts):\n    return {'flows': []}\n")
    monkeypatch.setattr(strategies_pkg, "__path__", [*strategies_pkg.__path__, str(extra)])
    monkeypatch.setattr(provenance, "_DONE", {})
    yield f
    import sys
    sys.modules.pop("sdlab.discovery.strategies.toy_strategy", None)


def test_a_result_records_the_code_it_ran(folder, toy, cache):
    item = runner.plan(["003-chain-2"], [{"name": "toy_strategy", "hash": catalog.strategy_hash("toy_strategy")}], ["none-short"])[0]
    row = runner.run_item(item)
    assert row["status"] == "fail" and row["strategy_hash"] == item["strategy_hash"]
    assert row["code_commit"] and len(row["code_commit"]) == 40
    assert row["code_dirty"], "a file that is not in the commit makes the code dirty"
    patch = (cache / "code" / f"{row['code_dirty']}.patch").read_text()
    assert "VERSION = 1" in patch and "toy_strategy.py" in patch
    rid = store.record(row)
    got = store.get(rid)
    assert (got["code_commit"], got["code_dirty"]) == (row["code_commit"], row["code_dirty"])

    # the file changes after this process imported it: the next result still carries the hash of the
    # code that ran (so it shows stale), and a run here goes to a fresh process instead
    toy.write_text(toy.read_text().replace("VERSION = 1", "VERSION = 2"))
    planned = runner.plan(["003-chain-2"], [{"name": "toy_strategy", "hash": catalog.strategy_hash("toy_strategy")}], ["none-short"], force=True)[0]
    again = runner.run_item(planned)
    assert planned["strategy_hash"] != item["strategy_hash"] and again["strategy_hash"] == item["strategy_hash"]
    assert provenance.stale_in_memory(["toy_strategy"]) and not provenance.stale_in_memory(["matrix"])


def test_a_committed_strategy_is_clean_unless_edited():
    p = provenance.loaded("matrix")
    assert p["strategy_hash"] and p["code_commit"]
    files = catalog.code_files("matrix")
    import subprocess
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *map(str, files)], capture_output=True, text=True,
                           cwd=catalog.DISCOVERY).stdout.strip()
    assert bool(p["code_dirty"]) == bool(dirty)


def test_an_old_store_gains_the_columns(cache):
    import sqlite3
    cache.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(cache / "results.sqlite")
    con.execute("CREATE TABLE results (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, case_hash TEXT NOT NULL, variant TEXT NOT NULL,"
                " strategy TEXT NOT NULL, strategy_hash TEXT NOT NULL, score_hash TEXT NOT NULL, at TEXT NOT NULL, latest INTEGER NOT NULL DEFAULT 1,"
                " status TEXT NOT NULL, seconds REAL, error TEXT, scores TEXT, found TEXT)")
    con.execute("INSERT INTO results (case_id, case_hash, variant, strategy, strategy_hash, score_hash, at, status) VALUES ('x', 'h', 'v', 's', 'sh', 'sc', 'now', 'pass')")
    con.commit()
    con.close()
    rows = store.latest()
    assert rows[0]["code_commit"] is None and json.dumps(rows)
