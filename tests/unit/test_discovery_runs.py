"""What each discovery run and inference round cost (``sd/runs.py``): phases timed apart, the
store cost derived from the request lines tagged with the run's id, the outcome in its kinds, the
log bounded; the job's health in words (``sd/runhealth.py``); and the API the Dynamics and Core
pages read (``web/runs_view.py``)."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from orchestra.metrics.file import FileMetrics
from orchestra.sd import rediscover as rd
from orchestra.sd import runs
from orchestra.sd.model import Model, Stock
from orchestra.sd.runhealth import health
from orchestra.sd.store import ModelStore
from orchestra.sd.strategies import CONSERVATION
from orchestra.sources import reqlog

NOW = 1_800_000_000.0


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def test_phases_are_timed_apart_a_nested_one_pausing_the_one_around_it(tmp_path):
    c = Clock()
    run = runs.Run(runs.RunLog(tmp_path), tmp_path, "discovery", "schedule", clock=c, wall=c, live=False)
    with run.phase("reads"):
        c.t += 2
        with run.phase("inference"):
            c.t += 5
        c.t += 1
    with run.phase("fit"):
        c.t += 10
    with run.phase("saving"):
        c.t += 0.5
    rec = run.finish("unchanged", window_s=3600.0)
    assert rec["phases"] == {"reads": 3.0, "inference": 5.0, "fit": 10.0, "saving": 0.5}
    assert rec["duration_s"] == 18.5 and rec["kind"] == "discovery" and rec["trigger"] == "schedule"
    assert runs.RunLog(tmp_path).recent() == [rec]


def test_a_live_run_is_shown_with_its_phase_and_gone_when_it_ends(tmp_path):
    log = runs.RunLog(tmp_path)
    run = runs.Run(log, tmp_path, "discovery", "button")
    with run.phase("fit", "conservation"):
        now = log.current()
        assert now["id"] == run.id and now["phase"] == "fit" and now["what"] == "conservation" and now["trigger"] == "button"
    assert log.current()["phase"] is None                # back in no phase
    run.finish("no model")
    assert log.current() is None
    (tmp_path / "run.now.json").write_text(json.dumps({"id": "x", "process": {"pid": 999999, "since": 1}}))
    assert log.current() is None                          # its process is gone: not going


def spec(name):
    return SimpleNamespace(name=name)


def test_the_cost_is_derived_from_the_request_lines_tagged_with_the_run(tmp_path):
    rid = "R1"
    line = lambda **k: reqlog.append(tmp_path, "chrono", k)
    line(endpoint="/api/v1/query_range", window=[0, 3600], series=4, points=240, ms=120.0, by="host", run=rid, bytes=1000)
    line(endpoint="/api/v1/query_range", window=[3300, 3600], series=4, points=20, ms=30.0, by="host", run=rid, bytes=100)
    line(endpoint="/api/v1/query", query="up{job=\"a\"}[3600s]", window=[3600], series=1, points=60, ms=10.0, by="host", run=rid)
    line(endpoint="/api/v1/series", series=7, ms=50.0, by="infer", run=rid + "~infer-chrono")
    line(endpoint="/api/v1/query_range", window=[0, 3600], ms=5.0, by="host", run=rid, error="HTTP 429: asked again")
    line(endpoint="/api/v1/query_range", window=[0, 3600], ms=0.0, by="host", run=rid, sent=False, error="past the deadline")
    line(endpoint="/api/v1/query_range", window=[0, 3600], series=9, points=900, ms=999.0, by="host", run="R2")   # another run's
    line(endpoint="/api/v1/query_range", window=[0, 3600], series=9, points=900, ms=999.0, by="web")             # the page's
    got = runs.cost(tmp_path, [spec("chrono"), spec("quiet")], rid, 0.0, 3600.0, peek=lambda s: {"today": 41, "per_day": 20000})
    c = got["chrono"]
    assert (c["requests"], c["inference"], c["whole"], c["incremental"]) == (5, 1, 3, 1)
    assert (c["series"], c["points"], c["bytes"], c["wait_ms"]) == (16, 320, 1100, 215)
    assert (c["refused"], c["errors"], c["today"], c["per_day"]) == (2, 0, 41, 20000)
    assert got["quiet"]["requests"] == 0 and got["quiet"]["bytes"] is None      # no line: nothing said of bytes


def test_outcomes_in_their_kinds():
    m = Model("system", "The system")
    assert runs.outcome_of(m, None) == "no model"
    m.stocks = [Stock("s", "s", evidence={})]
    m.discovery = {}
    assert runs.outcome_of(m, None) == "unchanged" and runs.outcome_of(m, 7) == "saved v7"
    m.discovery = {"sdlab": "stopped at its deadline of 240 s: conservation's fits are kept"}
    assert runs.outcome_of(m, None) == "timed out"
    m.discovery = {"not_saved": "missing chrono: unreachable"}
    assert runs.partial_of(m) == "missing chrono: unreachable"
    m.discovery = {"sources": {"chrono": {"ok": True, "partial": True, "warning": "partial: 2 of 9 late"}}}
    assert runs.partial_of(m) == "chrono: partial: 2 of 9 late"


def test_the_log_keeps_its_last_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "KEEP", 20)
    monkeypatch.setattr(runs, "SLACK", 2)
    log = runs.RunLog(tmp_path)
    for i in range(23):
        log.append({"i": i, "ended": i})
    got = log.recent(0)
    assert len(got) == 20 and got[0]["i"] == 3 and got[-1]["i"] == 22
    assert [r["i"] for r in log.recent(3)] == [20, 21, 22] and [r["i"] for r in log.recent(0, since=21)] == [21, 22]


def _project(tmp_path):
    return SimpleNamespace(key="p", state_dir=tmp_path, config=SimpleNamespace(
        discovery_strategy=CONSERVATION, discovery_options={}, discovery_window=3600.0, discovery_step=30.0, discovery_every=300.0,
        eras_from=None, prior_for=None))


def test_rediscover_records_each_run_with_its_trigger_window_result_and_failure(tmp_path, monkeypatch):
    project = _project(tmp_path)

    def discovered(*a, **k):
        m = Model("system", "The system")
        m.stocks = [Stock("s", "s", evidence={})]
        m.discovery = {"start": k["start"], "end": k["end"], "step": k["step"], "left_out": {"a": "x", "b": "y"}, "ran": CONSERVATION}
        return m
    monkeypatch.setattr(rd.simulated, "discovered", discovered)
    rd.rediscover(project, FileMetrics(tmp_path / "m.jsonl"), now=NOW, trigger="button")
    rd.rediscover(project, FileMetrics(tmp_path / "m.jsonl"), now=NOW + 300, trigger="schedule")
    monkeypatch.setattr(rd.simulated, "discovered", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        rd.rediscover(project, FileMetrics(tmp_path / "m.jsonl"), now=NOW + 600, trigger="config change")
    first, second, third = ModelStore.for_state(tmp_path).runs().recent()
    assert (first["trigger"], first["outcome"], first["version"]) == ("button", "saved v1", 1)
    assert first["result"] == {"stocks": 1, "flows": 0, "left_out": 2} and (first["window_s"], first["step_s"]) == (3600.0, 30.0)
    assert first["strategy"] == {"configured": CONSERVATION, "asked": CONSERVATION, "ran": CONSERVATION}
    assert set(first["phases"]) == {"reads", "fit", "saving"} and first["cost"] == {}
    assert second["outcome"] == "unchanged" and "version" not in second
    assert third["trigger"] == "config change" and third["outcome"] == "failed: RuntimeError: boom" and "result" not in third
    assert ModelStore.for_state(tmp_path).runs().current() is None


def rec(i, *, outcome="unchanged", trigger="schedule", dur=10.0, partial=None, kind="discovery", every=300.0):
    r = {"kind": kind, "trigger": trigger, "started": NOW - (20 - i) * every, "ended": NOW - (20 - i) * every + dur,
         "duration_s": dur, "outcome": outcome}
    return {**r, **({"partial": partial} if partial else {})}


def test_health_green_when_the_last_scheduled_run_succeeded_within_twice_its_interval():
    rs = [rec(i) for i in range(20)]
    rs[-1]["ended"] = NOW - 100
    h = health(rs, 300.0, NOW)
    assert h["level"] == "green" and h["reasons"][0].startswith("the last scheduled run unchanged 1 m 40 s ago")


def test_health_amber_overdue_slow_partial_or_failed_once():
    rs = [rec(i) for i in range(20)]
    rs[-1]["ended"] = NOW - 700
    h = health(rs, 300.0, NOW)
    assert h["level"] == "amber" and "overdue: the last scheduled run ended 11 m 40 s ago, and the host runs one every 5 m 0 s" in h["reasons"]
    assert health(rs, 300.0, NOW, running={"kind": "discovery"})["level"] == "green"        # one is going now: not overdue
    rs[-1].update(ended=NOW - 10, duration_s=40.0)
    assert health(rs, 300.0, NOW)["reasons"] == ["the last run took 40 s, more than 3× the median of 10 s"]
    rs[-1].update(duration_s=10.0, partial="missing chrono: unreachable")
    assert health(rs, 300.0, NOW)["reasons"] == ["the last run was partial: missing chrono: unreachable"]
    rs[-1].pop("partial")
    rs[-1]["outcome"] = "failed: SourceError: refused"
    assert health(rs, 300.0, NOW) == {"level": "amber", "reasons": ["the last run failed (SourceError: refused)"]}
    only_button = [rec(19, trigger="button")]
    assert "no scheduled run recorded" in health(only_button, 300.0, NOW)["reasons"][0]


def test_health_red_when_the_last_two_failed_or_a_daily_cap_is_spent():
    rs = [rec(i) for i in range(18)] + [rec(18, outcome="failed: A"), rec(19, outcome="failed: B: too slow")]
    rs[-1]["ended"] = NOW - 10
    h = health(rs, 300.0, NOW)
    assert h["level"] == "red" and h["reasons"][0] == "the last two runs failed (B: too slow)"
    ok = [rec(i) for i in range(20)]
    ok[-1]["ended"] = NOW - 10
    h = health(ok, 300.0, NOW, {"chrono": {"today": 20000, "per_day": 20000}, "other": {"today": 5, "per_day": 100}})
    assert h == {"level": "red", "reasons": ["chrono spent its daily cap (20000 of 20000 requests): no reads of it until 00:00 UTC"]}
    assert health([], 300.0, NOW) == {"level": "none", "reasons": ["no discovery run recorded yet"]}
    inference_only = [rec(19, kind="inference")]
    assert health(inference_only, 300.0, NOW)["level"] == "none"


def test_the_api_serves_the_runs_the_run_going_now_and_the_health(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from orchestra import plugins
    from orchestra.config import init_project
    from orchestra.web.app import create_app
    from orchestra.web.auth import bearer
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    project = init_project(r)
    log = ModelStore.for_state(project.state_dir).runs()
    import time
    t = time.time()
    log.append({"id": "a", "kind": "discovery", "trigger": "schedule", "started": t - 70, "ended": t - 60, "duration_s": 10.0,
                "outcome": "saved v3", "cost": {}})
    log.append({"id": "a~infer-x", "kind": "inference", "trigger": "schedule", "started": t - 69, "ended": t - 65, "duration_s": 4.0,
                "outcome": "inferred 3 definitions", "cost": {}, "source": "x", "parent": "a"})
    going = runs.Run(log, project.state_dir, "discovery", "button")
    web = TestClient(create_app(project), headers=bearer(project))
    with going.phase("reads"):
        v = web.get("/api/dynamics/runs").json()
        assert v["ok"] and [x["id"] for x in v["runs"]] == ["a", "a~infer-x"] and v["running"]["phase"] == "reads"
        assert v["running"]["elapsed_s"] >= 0 and "process" not in v["running"] and v["health"]["level"] == "green"
        h = web.get("/api/dynamics/runs/health").json()
        assert h["ok"] and h["last"]["id"] == "a" and h["health"]["level"] == "green" and h["running"]["trigger"] == "button"
    going.finish("no model")
    assert web.get("/api/dynamics/runs", params={"n": 1}).json()["runs"][0]["kind"] == "discovery"
