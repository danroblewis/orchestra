"""End to end: `orchestra run` launches machines that know nothing of Orchestra's library, one in
plain Python (the standard library only; importing orchestra would fail) and one in shell with
curl. Each announces itself, publishes and reads its event back over HTTP, and the events are on
the bus with the envelope and the machine's source, and on the Machines page."""

import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time

import pytest
from fastapi.testclient import TestClient

from orchestra import endpoint
from orchestra.config import init_project
from orchestra.events import Events
from orchestra.web.app import create_app
from orchestra.web.auth import bearer

BAKER = textwrap.dedent('''\
    import sys
    sys.modules["orchestra"] = None              # no library: an import of it fails
    import json, os, time, urllib.request

    URL, TOKEN = os.environ["ORCHESTRA_EVENTS_ENDPOINT"], os.environ["ORCHESTRA_EVENTS_TOKEN"]

    def call(method, path, body=None):
        req = urllib.request.Request(URL + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())

    call("POST", "/events", {"type": "orchestra.machine.started", "source": "baker/1",
                             "data": {"mode": "continuous", "kind": "program", "listens_for": ["oven.heated"],
                                      "log": os.environ["ORCHESTRA_MACHINE_LOG"]}})
    sent = call("POST", "/events", {"type": "bread.baked", "source": "baker/1", "subject": "loaf-1", "data": {"loaves": 3}})
    heard = call("GET", "/events?after=0&types=oven.heated&wait=20")
    got = call("GET", "/events?after=0&types=bread.baked")
    assert [e["id"] for e in got["events"]] == [sent["id"]]
    call("POST", "/events", {"type": "bread.checked", "source": "baker/1", "causationid": sent["id"],
                             "data": {"read_back": got["events"][0]["id"], "heard": [e["source"] for e in heard["events"]]}})
    print("baker: done", flush=True)
    time.sleep(3600)
''')

OVEN = textwrap.dedent('''\
    #!/bin/sh
    set -e
    post() {
      curl -sf -X POST "$ORCHESTRA_EVENTS_ENDPOINT/events" \\
        -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN" -H "Content-Type: application/json" -d "$1"
    }
    post '{"type": "orchestra.machine.started", "source": "oven", "data": {"mode": "continuous", "kind": "service"}}'
    post '{"type": "oven.heated", "source": "oven", "id": "oven-heated-1", "data": {"celsius": 220}}'
    post '{"type": "oven.heated", "source": "oven", "id": "oven-heated-1", "data": {"celsius": 220}}'
    curl -sf "$ORCHESTRA_EVENTS_ENDPOINT/events?after=0&types=oven.heated" \\
      -H "Authorization: Bearer $ORCHESTRA_EVENTS_TOKEN"
    echo
    exec sleep 3600
''')


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ORCHESTRA_EVENTS_URL", raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    p = init_project(r)
    (r / "baker.py").write_text(BAKER)
    (r / "oven.sh").write_text(OVEN)
    (r / "oven.sh").chmod(0o755)
    (r / "orchestra.toml").write_text(f'[discovery]\nevery = "1h"\n\n[[machines]]\nname = "baker"\n'
                                      f'command = "{sys.executable} -I baker.py"\n\n'
                                      '[[machines]]\nname = "oven"\ncommand = "./oven.sh"\n')
    return p


def until(cond, timeout=40.0, why=""):
    end = time.time() + timeout
    while time.time() < end:
        if (got := cond()):
            return got
        time.sleep(0.2)
    raise AssertionError(f"condition not met in time: {why() if callable(why) else why}")


@pytest.mark.skipif(not shutil.which("curl"), reason="the shell machine needs curl")
def test_machines_publish_and_read_events_over_http_without_the_library(project, tmp_path):
    out = tmp_path / "host.out"
    host = subprocess.Popen([sys.executable, "-m", "orchestra", "--repo", str(project.repo_root), "run"],
                            stdout=out.open("w"), stderr=subprocess.STDOUT, env={**os.environ})
    bus = Events.for_project(project)
    logs = project.logs_dir / "machines"

    def told():
        return f"{out.read_text()}\n--- baker.log\n{(logs / 'baker.log').read_text() if (logs / 'baker.log').exists() else ''}"
    try:
        checked = until(lambda: [e for e in bus.read(0, 10_000)[0] if e["type"] == "bread.checked"], why=told)
        rec = until(lambda: endpoint.recorded(project), why=told)
        assert rec["pid"] == host.pid and rec["url"].startswith("http://127.0.0.1:")
        cli = subprocess.run([sys.executable, "-m", "orchestra", "--repo", str(project.repo_root), "events", "endpoint", "--env"],
                             capture_output=True, text=True, check=True).stdout    # for a machine the host did not launch
        assert cli == f"export ORCHESTRA_EVENTS_ENDPOINT={rec['url']}\nexport ORCHESTRA_EVENTS_TOKEN={endpoint.token(project)}\n"
        evs, _ = bus.read(0, 10_000)
        (baked,) = [e for e in evs if e["type"] == "bread.baked"]
        assert baked["specversion"] == "1.0" and baked["source"] == "baker/1" and baked["subject"] == "loaf-1"
        assert baked["data"] == {"loaves": 3} and baked["time"] and len(baked["id"]) == 32
        assert checked[0]["data"]["read_back"] == baked["id"] and checked[0]["causationid"] == baked["id"]
        assert checked[0]["data"]["heard"] == ["oven"]           # the long poll heard the shell machine
        heated = [e for e in evs if e["type"] == "oven.heated"]
        assert [e["id"] for e in heated] == ["oven-heated-1"]   # posted twice, written once
        assert heated[0]["source"] == "oven" and heated[0]["data"] == {"celsius": 220}
        assert '"oven-heated-1"' in (logs / "oven.log").read_text()  # what curl read back

        web = TestClient(create_app(project), headers=bearer(project))
        view = until(lambda: (v := web.get("/api/machines").json()).get("ok")
                     and {"baker", "oven"} <= {m["id"] for m in v["machines"]} and v,
                     why="the Machines page did not show the machines")
        ms = {m["id"]: m for m in view["machines"]}
        baker = ms["baker"]
        assert baker["mode"] == "continuous" and baker["kind"] == "program"
        assert baker["subscribes"] == ["oven.heated"]
        assert {"bread.baked", "bread.checked"} <= {p["type"] for p in baker["publishes"]}
        assert [(i["id"], i["active"]) for i in baker["instances"]] == [("1", True)]
        assert ms["oven"]["kind"] == "service" and ms["oven"]["publishes"][0]["count"] == 1
        log = web.get("/api/machines/baker/log", params={"instance": "1"}).json()   # the log it announced
        assert log["ok"] and "baker: done" in log["lines"]
        web.close()
    finally:
        host.send_signal(signal.SIGTERM)
        host.wait(timeout=60)
    assert endpoint.recorded(project) is None
    gone = subprocess.run([sys.executable, "-m", "orchestra", "--repo", str(project.repo_root), "events", "endpoint"],
                          check=False, capture_output=True, text=True)
    assert gone.returncode == 1 and "no events endpoint" in gone.stderr
    assert "events endpoint: http://127.0.0.1:" in out.read_text()
