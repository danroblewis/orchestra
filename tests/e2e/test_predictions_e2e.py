"""Goal G13 end to end: a real ``orchestra run`` judges a machine's prediction of its own change.

The project measures a queue (a ``[[collect]]`` script: jobs arrive at random at the rate in
``rate.txt``, and each waiting job is done at random, at 0.02 a second; a queue that ran like
clockwork would settle at one level, and a level that never moves balances nothing) and runs one scripted machine (``[[machines]]``) that
knows nothing of Orchestra's library: after a few minutes it predicts, over the events endpoint,
that its change will double the arrivals (``orchestra.prediction.made``), doubles them, and
announces the change (``config.changed``, carrying the id its prediction named). A second
prediction about the same change, made with ``orchestra sd predict`` by another machine, says
only that the per-job rate of work is unchanged. The host rediscovers every 20 s; once the horizon
has passed it judges both: the first passes, and the second is a side effect, naming the arrivals
it did not predict.

Slow (about seven minutes), so it runs only when asked: ``ORCHESTRA_E2E=1 uv run python -m pytest
tests/e2e``. Goal G13 asks for this on the dummy agents (``~/orchestra-agents``, ``harness =
"dummy"``); a scripted machine here needs no change on that side."""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from orchestra.config import init_project
from orchestra.events import Events

pytestmark = pytest.mark.skipif(os.environ.get("ORCHESTRA_E2E") != "1", reason="slow end-to-end test: set ORCHESTRA_E2E=1")

WARMUP_S = 240
HORIZON_S = 180

QUEUE = '''#!/usr/bin/env python3
import json, math, pathlib, random, time
here = pathlib.Path(__file__).parent
state = here / "queue.json"
now = time.time()
s = json.loads(state.read_text()) if state.exists() else {"t": now, "arrived": 0, "done": 0}
dt = max(0.0, now - s["t"])

def poisson(mean):
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= random.random()
        if p <= limit:
            return k
        k += 1
q = s["arrived"] - s["done"]
d = sum(random.random() < 1 - math.exp(-0.02 * dt) for _ in range(q))
s["done"] += d
s["arrived"] += poisson(float((here / "rate.txt").read_text()) * dt)
s["t"] = now
state.write_text(json.dumps(s))
print("# TYPE queue_jobs gauge")
print(f"queue_jobs {s['arrived'] - s['done']}")
print(f"queue_jobs_arrived_total {s['arrived']}")
print(f"queue_jobs_done_total {s['done']}")
'''

CHANGER = textwrap.dedent(f'''\
    import sys
    sys.modules["orchestra"] = None              # no library: everything over HTTP
    import json, os, pathlib, time, urllib.request

    URL, TOKEN = os.environ["ORCHESTRA_EVENTS_ENDPOINT"], os.environ["ORCHESTRA_EVENTS_TOKEN"]

    def post(body):
        req = urllib.request.Request(URL + "/events", method="POST", data=json.dumps(body).encode(),
                                     headers={{"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read())

    post({{"type": "orchestra.machine.started", "source": "changer", "data": {{"mode": "ad hoc", "kind": "program"}}}})
    time.sleep({WARMUP_S})
    post({{"type": "orchestra.prediction.made", "source": "changer", "subject": "queue",
           "data": {{"change": "change-1", "expect": [{{"flow": "queue_jobs_arrived_total", "factor": 2}}], "horizon_s": {HORIZON_S}}}}})
    pathlib.Path(sys.argv[1], "rate.txt").write_text("1.0")
    post({{"type": "config.changed", "source": "changer", "id": "change-1", "subject": "queue",
           "data": {{"change": "arrivals 0.5 to 1 a second"}}}})
    print("changer: changed", flush=True)
    time.sleep(3600)
''')


def until(cond, timeout, why):
    end = time.time() + timeout
    while time.time() < end:
        if got := cond():
            return got
        time.sleep(2)
    raise AssertionError(f"not in time: {why()}")


def test_the_host_judges_a_machines_prediction_of_its_change(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    for k in ("ORCHESTRA_EVENTS_URL", "ORCHESTRA_METRICS_URL"):
        monkeypatch.delenv(k, raising=False)
    repo, queue = tmp_path / "repo", tmp_path / "queue"
    repo.mkdir()
    queue.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    project = init_project(repo)
    (queue / "rate.txt").write_text("0.5")
    (queue / "queue.py").write_text(QUEUE)
    (queue / "queue.py").chmod(0o755)
    (repo / "changer.py").write_text(CHANGER)
    (repo / "orchestra.toml").write_text(textwrap.dedent(f'''\
        [discovery]
        strategy = "conservation"
        every = "20s"
        step = "10s"
        window = "30m"

        [[collect]]
        name = "queue"
        command = "{queue / "queue.py"}"
        every = "2s"

        [[machines]]
        name = "changer"
        command = "{sys.executable} -I changer.py {queue}"
        '''), encoding="utf-8")
    orch = [sys.executable, "-m", "orchestra", "--repo", str(repo)]
    out = tmp_path / "host.out"
    host = subprocess.Popen([*orch, "run"], stdout=out.open("w"), stderr=subprocess.STDOUT, env={**os.environ})
    bus = Events.for_project(project)
    try:
        cli = subprocess.run([*orch, "sd", "predict", "--source", "tester", "--change", "change-1",
                              "--expect", "queue_jobs_done_total unchanged", "--horizon", f"{HORIZON_S}s"],
                             capture_output=True, text=True, check=True).stdout
        assert "the change must carry the id change-1" in cli

        def verdicts():
            return {e["data"]["prediction"]: e for e in bus.read(0, 1_000_000)[0] if e["type"] == "orchestra.prediction.judged"}
        got = until(lambda: len(v := verdicts()) == 2 and v, WARMUP_S + HORIZON_S + 300, lambda: out.read_text()[-3000:])
        evs = bus.read(0, 1_000_000)[0]
        [made] = [e for e in evs if e["type"] == "orchestra.prediction.made" and e["source"] == "changer"]
        [change] = [e for e in evs if e["type"] == "config.changed"]
        [started] = [e for e in evs if e["type"] == "orchestra.era.started"]
        assert started["causationid"] == change["id"] == "change-1"
        mine = got[made["id"]]
        assert mine["source"] == "orchestra-host" and mine["subject"] == made["id"] and mine["correlationid"] == "change-1"
        v = mine["data"]
        assert v["verdict"] == "passed", json.dumps(v, indent=1)
        [c] = v["expectations"][0]["params"]
        assert 1.6 < c["ratio"] < 2.5 and c["z"] >= 2
        theirs = next(e for k, e in got.items() if k != made["id"])["data"]
        assert theirs["verdict"] == "side effect", json.dumps(theirs, indent=1)
        assert theirs["expectations"][0]["status"] == "met", "the per-job rate of work did not change"
        assert [u["id"] for u in theirs["unpredicted"]] == ["queue_jobs_arrived_total"], "but it did not predict the arrivals"
        listed = subprocess.run([*orch, "sd", "predictions"], capture_output=True, text=True, check=True).stdout
        assert "era e1" in listed and "    passed" in listed and "    side effect" in listed, listed
    finally:
        host.send_signal(signal.SIGTERM)
        host.wait(timeout=60)
