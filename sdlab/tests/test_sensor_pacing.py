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
