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
