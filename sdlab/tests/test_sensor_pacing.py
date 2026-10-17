"""A live run of a measured system steps only when the system has a new sample to read."""

import json

from sdlab.runner import LiveRun


def test_a_run_steps_only_when_the_sensor_reports_a_new_sample(tmp_path):
    ex = tmp_path / "examples"
    (ex / "probe" / "machines").mkdir(parents=True)
    clock = tmp_path / "clock"
    clock.write_text("100")
    (ex / "probe" / "machines" / "gauge.py").write_text(
        "import json, sys\n"
        f"t = float(open({str(clock)!r}).read())\n"
        "print(json.dumps({'time': t, 'levels': {'queue': t / 10}}))\n")
    model = {"id": "m", "name": "m", "stocks": [{"id": "queue", "name": "Queue"}], "flows": [], "machines": [],
             "sensors": [{"program": "probe/gauge"}]}
    (tmp_path / "m.json").write_text(json.dumps(model))
    run = LiveRun("m", tmp_path / "m.json", tmp_path / "run", ex)
    assert run.tick(force=False) is True and run.t == 1
    assert run.tick(force=False) is False and run.t == 1          # the same sample again: no step
    assert run.tick() is True and run.t == 2                       # the Step button steps anyway
    clock.write_text("400")
    assert run.tick(force=False) is True and run.t == 3
    assert run.series["levels"]["queue"][-1] == 40
    run.programs.close()


def test_a_run_waits_when_no_sensor_can_read(tmp_path):
    """A recording that ended (or a source that is down) must not fill the run with repeated levels."""
    ex = tmp_path / "examples"
    (ex / "probe" / "machines").mkdir(parents=True)
    (ex / "probe" / "machines" / "gauge.py").write_text(
        "import json, sys\n"
        "t = json.load(sys.stdin)['t']\n"
        "if t > 3:\n"
        "    sys.exit('the recording ends at step 3')\n"
        "print(json.dumps({'levels': {'queue': t * 10}}))\n")
    model = {"id": "m", "name": "m", "stocks": [{"id": "queue", "name": "Queue"}], "flows": [], "machines": [],
             "sensors": [{"program": "probe/gauge"}]}
    (tmp_path / "m.json").write_text(json.dumps(model))
    run = LiveRun("m", tmp_path / "m.json", tmp_path / "run", ex)
    assert [run.tick(force=False) for _ in range(5)] == [True, True, True, False, False]
    assert run.t == 3 and run.series["levels"]["queue"] == [10, 20, 30]
    assert any("recording ends" in e["error"] for e in run.errors)
    run.programs.close()


def test_a_run_stops_when_its_source_keeps_failing(tmp_path):
    """Three failed reads in a row and the run stops itself, saying why; nothing is recorded."""
    import time
    ex = tmp_path / "examples"
    (ex / "probe" / "machines").mkdir(parents=True)
    (ex / "probe" / "machines" / "gauge.py").write_text(
        "import json, sys\n"
        "t = json.load(sys.stdin)['t']\n"
        "if t > 2:\n"
        "    sys.exit('the recording ends at step 2')\n"
        "print(json.dumps({'levels': {'queue': t}}))\n")
    model = {"id": "m", "name": "m", "stocks": [{"id": "queue", "name": "Queue"}], "flows": [], "machines": [],
             "sensors": [{"program": "probe/gauge"}]}
    (tmp_path / "m.json").write_text(json.dumps(model))
    run = LiveRun("m", tmp_path / "m.json", tmp_path / "run", ex)
    run.start(0.01)
    for _ in range(100):
        if not run.running:
            break
        time.sleep(0.05)
    snap = run.snapshot()
    assert not snap["running"] and snap["t"] == 2
    assert snap["stopped"]["t"] == 2 and "recording ends" in snap["stopped"]["reason"]
    run.start(0.01)                                          # starting again clears it (and stops again)
    run.stop()
    run.programs.close()
