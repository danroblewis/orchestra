"""A discovery's input written to a directory and replayed (``sd.snapshot``): the round trip, and a
replay giving the model the live discovery found from the same data, writing nothing."""

from __future__ import annotations

import json
import time

from intended_seed import project_at
from test_intended_simulated import SIM, write_queue

from orchestra.cli import main
from orchestra.metrics import for_project as metrics_for
from orchestra.sd import snapshot
from orchestra.sd.discover import structure
from orchestra.sd.rediscover import rediscover
from orchestra.sd.rediscover import snapshot as take
from orchestra.sd.series import Declared
from orchestra.sd.store import ModelStore
from orchestra.sources.catalogue import Reading


def _same(a, b) -> None:
    """Two models alike in everything discovery decides (persistence and the replay's own note aside)."""
    def strip(m):
        d = m.to_json()
        d["discovery"] = {k: v for k, v in d["discovery"].items() if k != "replayed_from"}
        for s in d["stocks"]:                     # each stock's persistence: from the model store's record of runs
            for k in ("persistence", "persistence_of"):
                (s["evidence"].get("trust") or {}).pop(k, None)
        return d
    assert structure(a) == structure(b)
    assert strip(a) == strip(b)


def test_a_reading_round_trips_through_a_directory(tmp_path):
    r = Reading(dump=[("q_level", {"machine": "m"}, [(1.0, 2.0), (6.0, 3.5)]),
                      ("remote:q_in_total", {"pod": "a"}, [(1.0, 0.0), (6.0, float("nan"))]),
                      ("empty", {}, [])],
                kinds={'remote:q_in_total{pod="a"}': Declared("counter", baseline=True, direction="in", channel="q",
                                                             resolution_s=30.0)},
                provenance={'remote:q_in_total{pod="a"}': {"source": "remote", "query": "q_in_total", "unit": "items"},
                            "orphan": {"source": "own", "view": "pile"}},
                traffic={'remote:q_in_total{pod="a"}': {"direction": "in", "channel": "q", "machine": "m"}},
                status={"own": {"ok": True}, "remote": {"ok": True}}, missing={"gone": "unreachable"})
    snapshot.write(tmp_path / "s", r, start=0.0, end=10.0, step=5.0, strategy="conservation", options={"a": 1}, deadline=7.0)
    back, man = snapshot.read(tmp_path / "s")
    assert back.dump[0] == r.dump[0] and back.dump[2] == r.dump[2]
    assert back.dump[1][2][1][1] != back.dump[1][2][1][1]          # NaN kept
    assert back.kinds == r.kinds and back.provenance == r.provenance and back.traffic == r.traffic
    assert back.status == r.status and back.missing == r.missing
    assert man["window"] == {"start": 0.0, "end": 10.0, "window_s": 10.0} and man["step"] == 5.0
    assert man["method"] == {"strategy": "conservation", "options": {"a": 1}, "deadline": 7.0}
    assert set(man["commit"]) == {"project", "orchestra"} and len(man["series"]) == 3
    # written again: the old series files go
    snapshot.write(tmp_path / "s", Reading(dump=r.dump[:1]), start=0.0, end=10.0, step=5.0, strategy="conservation")
    assert len(list((tmp_path / "s" / "series").glob("*.json"))) == 1


def test_a_replay_reproduces_the_live_discovery_and_writes_nothing(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    now = time.time()
    write_queue(project, {"instrument": "q"}, now)
    r = rediscover(project, metrics_for(project), strategy="conservation", now=now, snapshot=tmp_path / "snap")
    assert r.model.stocks and r.version
    man = json.loads((tmp_path / "snap" / "manifest.json").read_text())
    assert man["project"] == project.key and man["commit"]["project"] is None    # a repository with no commit yet
    store = ModelStore.for_state(project.state_dir)
    before = (store.versions(), metrics_for(project).dump(""))
    m = snapshot.replay(tmp_path / "snap")
    _same(r.model, m)
    assert m.discovery["replayed_from"] == str(tmp_path / "snap")
    assert (store.versions(), metrics_for(project).dump("")) == before
    # taken on its own at the same moment: the same snapshot, the same model
    take(project, metrics_for(project), tmp_path / "again", strategy="conservation", now=now)
    _same(r.model, snapshot.replay(tmp_path / "again"))


def test_a_replay_allows_the_simulated_instruments_the_live_run_did(tmp_path, monkeypatch):
    project = project_at(tmp_path, monkeypatch)
    project.config_file.write_text(project.config_file.read_text() + SIM)
    project.reload_config()
    now = time.time()
    write_queue(project, {"instrument": "features.sim", "simulated": "true"}, now)
    r = rediscover(project, metrics_for(project), strategy="conservation", now=now, snapshot=tmp_path / "snap")
    assert json.loads((tmp_path / "snap" / "manifest.json").read_text())["simulated_instruments"] == ["features.sim"]
    project.config_file.write_text(project.config_file.read_text().replace(SIM, ""))   # the replay never asks the project
    project.reload_config()
    m = snapshot.replay(tmp_path / "snap")
    assert m.stocks and m.stocks[0].evidence["simulated"]
    _same(r.model, m)


def test_orchestra_sd_discover_from_a_snapshot(tmp_path, monkeypatch, capsys):
    project = project_at(tmp_path, monkeypatch)
    now = time.time()
    write_queue(project, {"instrument": "q"}, now)
    r = rediscover(project, metrics_for(project), strategy="conservation", now=now, snapshot=tmp_path / "snap")
    capsys.readouterr()
    assert main(["sd", "discover", "--from", str(tmp_path / "snap"), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert sorted(s["id"] for s in d["stocks"]) == sorted(s.id for s in r.model.stocks)
    assert main(["sd", "discover", "--from", str(tmp_path / "snap")]) == 0
    assert "nothing saved" in capsys.readouterr().out
