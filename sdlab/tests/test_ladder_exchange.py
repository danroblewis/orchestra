"""Two machines (machines.py, exchange.py): --exclude-cases splits the ladder, export/import moves
results between stores (new ids, no duplicates, idempotent), and `latest` is the newest `at` per cell."""

import gzip
import json
import sqlite3

import pytest

from sdlab.ladder import cli, exchange, machines, runner, store, summary_build
from sdlab.ladder import cases as casemod

SPLIT = "tag:realistic,tag:physics,tag:particles,tag:heavy,tag:real,tag:canonical"


@pytest.fixture(autouse=True)
def node2_split(monkeypatch):
    """The split machines.yaml had until 2026-10-20 (the CPU pool replaced it; the file names no machine now):
    the `machine:` syntax and owner() still work for any split a machines.yaml declares."""
    monkeypatch.setattr(machines, "config", lambda: {"node2": {"ssh": "ubuntu@node2", "cases": SPLIT}})


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Switch between node2's store and mac's: use("node2") / use("mac")."""
    def use(name):
        monkeypatch.setenv("SDLAB_MACHINE", name)
        monkeypatch.setenv("SDLAB_LADDER_CACHE", str(tmp_path / name))
    return use


def row(case="001-x", variant="none", strategy="s", at="2026-10-19T10:00:00.000Z", status="pass", **kw):
    return {"case": case, "variant": variant, "strategy": strategy, "case_hash": "ch", "strategy_hash": "sh", "score_hash": "kh",
            "at": at, "status": status, "seconds": 1.5, "scores": {"recall": 1.0}, "found": [{"id": "f"}], "code_commit": "abc",
            "score_seconds": 0.2, "wall_seconds": 2.0, "wait_seconds": 0.1, "run_id": 7, **kw}


# ---- the split ----

def test_exclude_cases_splits_the_ladder_and_keeps_heavy_out_by_default():
    everything = set(casemod.case_ids())
    default = set(runner.select_cases(None))
    node2 = set(runner.select_cases(SPLIT))
    mac = set(runner.select_cases(None, SPLIT))
    assert node2 and mac and not node2 & mac
    assert mac | node2 == default | node2
    heavy = {i for i in everything if "heavy" in casemod.load(i)["tags"]}
    assert heavy <= node2 and not heavy & mac
    assert not heavy & set(runner.select_cases(None, "tag:realistic"))       # excluding something else still leaves heavy out
    assert runner.select_cases("machine:node2") == runner.select_cases(SPLIT) == runner.select_cases(machines.cases_of("node2"))
    assert runner.select_cases("all", "machine:node2") == sorted(mac, key=runner.select_cases(None).index)
    some = runner.select_cases(None)[:5]
    assert runner.select_cases(",".join(some), some[0]) == some[1:]


def test_the_cli_takes_exclude_cases(monkeypatch):
    seen = {}
    monkeypatch.setattr(runner, "plan", lambda cids, *a, **k: seen.setdefault("cids", cids) and [])
    cli.main(["sync", "--strategies", "all", "--exclude-cases", "machine:node2"])
    assert seen["cids"] == runner.select_cases(None, SPLIT)


def test_owner_of_a_case(monkeypatch):
    monkeypatch.setenv("SDLAB_MACHINE", "mac")
    assert machines.owner(["realistic"]) == "node2" and machines.owner(["loop"]) is None
    monkeypatch.setenv("SDLAB_MACHINE", "node2")
    assert machines.owner(["realistic"]) is None


# ---- export / import ----

def test_round_trip_is_idempotent_and_keeps_every_column(two, tmp_path):
    two("node2")
    ids = [store.record(row(at=f"2026-10-19T10:0{i}:00.000Z", case=f"00{i}-x", code_dirty="p1" if i == 1 else None)) for i in range(3)]
    (store.path().parent / "code").mkdir(parents=True, exist_ok=True)
    (store.path().parent / "code" / "p1.patch").write_text("diff --git a/x b/x\n")
    got = exchange.export(out=tmp_path / "a.jsonl.gz")
    assert got["count"] == 3 and got["since_id"] == 0 and got["upto_id"] == ids[-1] and got["patches"] == 1
    assert exchange.export(out=tmp_path / "b.jsonl.gz")["count"] == 0          # since the last export
    assert exchange.export(since_id=ids[0], out=tmp_path / "c.jsonl.gz")["count"] == 2

    two("mac")
    store.record(row(case="009-local"))
    r = exchange.import_file(tmp_path / "a.jsonl.gz")
    assert (r["machine"], r["added"], r["skipped"], r["latest"]) == ("node2", 3, 0, 3)
    again = exchange.import_file(tmp_path / "a.jsonl.gz")
    assert (again["added"], again["skipped"]) == (0, 3)
    assert exchange.import_file(tmp_path / "c.jsonl.gz")["added"] == 0
    rows = {x["case"]: x for x in store.latest(found=True)}
    assert len(rows) == 4 and rows["009-local"]["machine"] == "mac"
    one = rows["001-x"]
    assert one["machine"] == "node2" and one["id"] != ids[1] and one["code_dirty"] == "p1" and one["found"] == [{"id": "f"}]
    assert one["scores"] == {"recall": 1.0} and (one["seconds"], one["score_seconds"], one["wall_seconds"], one["wait_seconds"]) == (1.5, 0.2, 2.0, 0.1)
    assert "run_id" not in one                                               # the remote run means nothing here
    assert (store.path().parent / "code" / "p1.patch").read_text() == "diff --git a/x b/x\n"
    assert exchange.high_water("node2") == ids[-1] and exchange.high_water("other") == 0
    rm = exchange.remotes()
    assert rm[0]["name"] == "node2" and rm[0]["results"] == 3 and rm[0]["header"]["machine"] == "node2"
    # mac's own export never sends back what it imported
    assert exchange.export(out=tmp_path / "m.jsonl.gz")["count"] == 1


def test_import_refuses_a_cut_file(two, tmp_path):
    two("node2")
    store.record(row())
    p = exchange.export(out=tmp_path / "a.jsonl.gz")["path"]
    lines = gzip.open(p, "rt").read().splitlines()
    with gzip.open(tmp_path / "cut.jsonl.gz", "wt") as f:
        f.write("\n".join(lines[:-1]) + "\n")
    two("mac")
    with pytest.raises(ValueError):
        exchange.import_file(tmp_path / "cut.jsonl.gz")
    assert store.latest() == []


def test_latest_is_the_newest_at_per_cell(two, tmp_path):
    two("node2")
    store.record(row(at="2026-10-19T09:00:00.000Z", status="fail"))
    store.record(row(at="2026-10-19T12:00:00.000Z", status="pass"))
    exchange.export(out=tmp_path / "a.jsonl.gz")
    two("mac")
    store.record(row(at="2026-10-19T10:00:00.000Z", status="error"))
    assert [r["status"] for r in summary_build.latest_rows().values()] == ["error"]
    exchange.import_file(tmp_path / "a.jsonl.gz")
    hist = store.history("001-x", "none", "s")
    assert [(h["status"], h["latest"]) for h in hist] == [("pass", True), ("fail", False), ("error", False)]
    assert [r["status"] for r in store.latest()] == ["pass"]
    assert [r["status"] for r in summary_build.latest_rows().values()] == ["pass"]    # the incremental read agrees
    with sqlite3.connect(store.path()) as con:
        assert con.execute("SELECT COUNT(*) FROM results WHERE latest = 1").fetchone()[0] == 1


def test_an_older_import_never_displaces_a_newer_local_row(two, tmp_path):
    two("node2")
    store.record(row(at="2026-10-19T09:00:00.000Z", status="fail"))
    exchange.export(out=tmp_path / "a.jsonl.gz")
    two("mac")
    store.record(row(at="2026-10-19T10:00:00.000Z", status="pass"))
    assert summary_build.latest_rows()[("001-x", "none", "s")]["status"] == "pass"
    assert exchange.import_file(tmp_path / "a.jsonl.gz")["latest"] == 0
    assert [r["status"] for r in store.latest()] == ["pass"]
    assert summary_build.latest_rows()[("001-x", "none", "s")]["status"] == "pass"


def test_rows_from_before_machines_read_as_here(two):
    two("mac")
    store.record(row())
    with sqlite3.connect(store.path()) as con:
        con.execute("UPDATE results SET machine = NULL")
    assert store.latest()[0]["machine"] == "mac"


def test_cli_export_and_import(two, tmp_path, capsys):
    two("node2")
    store.record(row())
    assert cli.main(["export", "--out", str(tmp_path / "x.jsonl.gz")]) == 0
    path = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(gzip.open(path, "rt").readline())["machine"] == "node2"
    two("mac")
    assert cli.main(["import", path]) == 0 and "1 added" in capsys.readouterr().out
    assert cli.main(["import", "--high-water", "node2"]) == 0 and capsys.readouterr().out.strip() == "1"


# ---- backups ----

def test_a_backup_restores_to_the_same_rows_and_rotation_keeps_the_schedule(two, tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from sdlab.ladder import backup
    two("mac")
    for i in range(5):
        store.record(row(case=f"00{i}-x"))
    got = backup.snapshot(tmp_path / "bk")
    assert got["rows"]["results"] == 5 and got["bytes"] > 0
    out = backup.restore(got["file"], tmp_path / "back.sqlite")
    assert out["checked"] and out["rows"] == got["rows"]
    with sqlite3.connect(tmp_path / "back.sqlite") as con:
        assert con.execute("SELECT COUNT(*) FROM results").fetchone()[0] == 5
    with pytest.raises(SystemExit):
        backup.restore(got["file"], store.path())                            # never over the live store by accident
    # rotation: hourly for a day, daily for 14 days, weekly for 8 weeks
    now = datetime(2026, 10, 19, 12, 0, 0)
    d = tmp_path / "rot"
    d.mkdir()
    for h in range(0, 24 * 70, 6):
        (d / f"results-{(now - timedelta(hours=h)).strftime('%Y%m%d-%H%M%S')}.sqlite.zst").write_bytes(b"x")
    backup.rotate(d, now)
    left = [backup._when(p) for p in backup.snapshots(d)]
    assert sum(now - w <= timedelta(hours=24) for w in left) == 5
    days = [w for w in left if timedelta(hours=24) < now - w <= timedelta(days=14)]
    assert len(days) == len({w.date() for w in days}) == 14
    assert all(now - w <= timedelta(weeks=8) for w in left)
