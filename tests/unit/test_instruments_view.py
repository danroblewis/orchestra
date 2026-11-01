"""The Instruments page's data (web/instruments.py), and the Machines page leaving instruments out,
including those the host announced as machines before 2026-10-27."""

import subprocess

import pytest

from orchestra import runtime
from orchestra.config import init_project
from orchestra.web.instruments import instruments_view
from orchestra.web.machines import machines_view


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    p = init_project(r)
    (r / "orchestra.toml").write_text('[[collect]]\nname = "tides"\ncommand = "machines/tides.py"\nevery = "6m"\n'
                                      '\n[[scrape]]\nname = "app"\nurl = "http://127.0.0.1:9/metrics"\n'
                                      '\n[[scrape]]\nname = "bad"\nurl = "ftp://x"\n'
                                      '\n[[sources]]\nname = "rig"\ntype = "prometheus"\nurl = "http://127.0.0.1:9090"\nprefix = "rig"\n')
    p.reload_config()
    return p


def test_with_no_host_the_declared_instruments_are_listed_not_running(project):
    runtime.update(project, lambda d: d.__setitem__("instruments", {"tides": {"last_write": 5.0, "points": 3, "failures": 0}}))
    v = instruments_view(project, {"sources": {"rig": {"ok": False, "error": "refused"}}})
    by = {i["name"]: i for i in v["instruments"]}
    assert not v["host_running"] and set(by) == {"tides", "app", "rig"}
    assert (by["tides"]["kind"], by["tides"]["every_s"], by["tides"]["running"], by["tides"]["last_write"]) == ("script", 360.0, False, 5.0)
    assert by["app"]["kind"] == "URL"
    assert by["rig"]["kind"] == "source" and by["rig"]["target"] == "http://127.0.0.1:9090" and by["rig"]["last_error"] == "refused"
    assert any("bad" in e for e in v["errors"])


def test_an_instrument_the_host_once_announced_is_no_machine():
    evs = [{"type": "orchestra.machine.started", "source": "goes_protons", "time": "2026-10-26T00:00:00Z",
            "data": {"mode": "scheduled", "kind": "program", "listens_for": [], "collector": "collect", "command": "x"}},
           {"type": "orchestra.machine.started", "source": "worker/1", "time": "2026-10-26T00:00:00Z", "data": {"listens_for": []}}]
    ids = {m["id"] for m in machines_view(evs)["machines"]}
    assert ids == {"orchestra-host", "worker"}


def test_each_instrument_says_whether_it_is_simulated_or_a_draft(project):
    from orchestra.collect.runner import Collecting
    from orchestra.collect.spec import Collector

    (project.repo_root / "orchestra.toml").write_text(
        '[[collect]]\nname = "ramp"\ncommand = "x"\nsimulated = true\n'
        '\n[[collect]]\nname = "try"\ncommand = "x"\ndraft = true\nexpires = "2026-11-08T00:00:00Z"\n'
        '\n[[collect]]\nname = "plain"\ncommand = "x"\n')
    project.reload_config()
    by = {i["name"]: i for i in instruments_view(project)["instruments"]}
    assert (by["ramp"]["simulated"], by["ramp"]["draft"], by["ramp"]["expires"]) == (True, False, None)
    assert (by["try"]["simulated"], by["try"]["draft"], by["try"]["expires"]) == (False, True, 1794096000.0)
    assert (by["plain"]["simulated"], by["plain"]["draft"], by["plain"]["expires"]) == (False, False, None)
    c = Collecting(project, lambda *_: None, plugin_collectors=[Collector("ramp", "collect", "x", owner="features", simulated=True)])
    c.wanted = {"features.ramp": Collector("features.ramp", "collect", "x", owner="features", simulated=True)}
    assert c.snapshot()["features.ramp"]["simulated"] is True


def test_the_page_lists_every_instrument_an_attachment_may_name(project):
    from orchestra.sd.intended.instruments import Instruments

    runtime.update(project, lambda d: d.__setitem__("instruments", {"features.ramp": {"kind": "collect", "last_write": 5.0}}))
    v = instruments_view(project)
    by = {i["name"]: i for i in v["instruments"]}
    assert set(by) == set(Instruments(project).kinds()) == {"features.ramp", "tides", "app", "rig"}
    assert (by["features.ramp"]["kind"], by["features.ramp"]["running"]) == ("collector", False)
