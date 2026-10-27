"""A real `orchestra run` runs a project's [[collect]] detector and writes what it prints to the
project's store, labelled ``instrument`` with the target's own labels kept. The detector is an
instrument, not a machine: it is on the Instruments page, and not on the Machines page."""

import signal
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from orchestra.config import init_project
from orchestra.events import Events
from orchestra.metrics import for_project
from orchestra.web.app import create_app
from orchestra.web.machines import last_writes, machines_view


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "machines").mkdir()
    # like goes_protons: a detector of something no machine of ours influences, whose text names
    # the satellite it reads in a `machine` label of its own
    (r / "machines" / "goes_protons.sh").write_text('#!/bin/sh\necho "# TYPE goes_proton_flux gauge"\n'
                                                    'echo "goes_proton_flux{channel=\\"10MeV\\",machine=\\"goes18\\"} 0.4"\n'
                                                    'echo "goes_readings_total 7"\n')
    (r / "machines" / "goes_protons.sh").chmod(0o755)
    p = init_project(r)
    (r / "orchestra.toml").write_text('[discovery]\nevery = "1h"\n\n[[collect]]\nname = "goes_protons"\n'
                                      'command = "machines/goes_protons.sh"\nevery = "1s"\n')
    return p


def test_a_detector_is_an_instrument_not_a_machine(project, tmp_path):
    out = (tmp_path / "host.out").open("w")
    host = subprocess.Popen([sys.executable, "-m", "orchestra", "--repo", str(project.repo_root), "run"],
                            stdout=out, stderr=subprocess.STDOUT)
    web = TestClient(create_app(project))
    try:
        store = for_project(project)
        end = time.time() + 30
        while time.time() < end and len(store.raw("goes_readings_total", {"instrument": "goes_protons"})) < 2:
            time.sleep(0.2)
        assert len(store.raw("goes_readings_total", {"instrument": "goes_protons"})) >= 2, (tmp_path / "host.out").read_text()
        [(_, labels)] = store.series("goes_proton_flux")
        assert labels == {"project": project.key, "instrument": "goes_protons", "channel": "10MeV", "machine": "goes18"}
        time.sleep(1.5)
        inst = web.get("/api/instruments").json()
        assert inst["ok"] and inst["host_running"]
        [goes] = [i for i in inst["instruments"] if i["name"] == "goes_protons"]
        assert goes["kind"] == "script" and goes["target"] == "machines/goes_protons.sh" and goes["every_s"] == 1.0
        assert goes["last_write"] > 0 and goes["points"] == 2 and goes["failures"] == 0
    finally:
        host.send_signal(signal.SIGTERM)
        host.wait(timeout=30)
    evs, _ = Events.for_project(project).read(0, limit=10_000)
    assert not any(e.get("source") == "goes_protons" for e in evs)          # nothing announced for it
    dumped = store.dump("", {"project": project.key})
    view = machines_view(evs, written=last_writes(dumped))
    assert {m["id"] for m in view["machines"]} == {"orchestra-host"}        # not the detector, nor the satellite it names

    log = web.get("/api/instruments/goes_protons/log").json()
    assert log["ok"] and any("wrote 2 points" in ln for ln in log["lines"])
    assert "goes_protons" not in {m["id"] for m in web.get("/api/machines").json().get("machines", [])}
    assert "Instruments" in web.get("/instruments").text
    cat = web.get("/api/core/metrics/catalog").json()
    assert {"goes_proton_flux", "goes_readings_total"} <= {m["name"] for m in cat["metrics"]}
