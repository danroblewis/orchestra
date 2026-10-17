"""The measured hospital: a seeded stochastic simulation with stocks the model is never told about.

The model has the five stocks a dashboard shows and two counted flows; the simulation behind its
history program also has three hidden stocks (see sdlab/examples/hospital/README.md)."""

import importlib.util
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

HOSPITAL = EXAMPLES / "hospital"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "hospital-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("hospital_sim", HOSPITAL / "machines" / "sim.py")


@pytest.fixture(scope="module")
def res():
    return sim.run()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def model() -> dict:
    return json.loads((EXAMPLES / "hospital.json").read_text())


def history(stdin: str = "", *args: str) -> list[dict]:
    p = subprocess.run([sys.executable, str(HOSPITAL / "machines" / "history.py"), *args], input=stdin,
                       capture_output=True, text=True, timeout=60, cwd=HOSPITAL / "machines")
    assert p.returncode == 0, p.stderr
    return [json.loads(line) for line in p.stdout.splitlines()]


def test_the_model_is_the_measured_part_only():
    m = model()
    assert validate(m) == []
    assert [s["id"] for s in m["stocks"]] == ["waiting", "lwbs", "treatment", "ward", "discharged"]
    assert set(sim.MEASURED_STOCKS) == {s["id"] for s in m["stocks"]}
    assert {s["unit"] for s in m["stocks"]} == {"patients"}
    assert [f["id"] for f in m["flows"]] == sim.MEASURED_FLOWS
    assert all(f["machine"] == "environment" and f["rate"]["form"] == "constant" for f in m["flows"])
    assert m["machines"] == [] and m["history"] == {"program": "hospital/history", "args": []}
    assert (m["time_unit"], m["horizon"], m["dt"]) == ("hour", 168, 0.25)
    text = json.dumps(m).lower()
    assert not any(w in text for w in ("imaging", "radiology", "x-ray", "lab", "blood", "follow", "review")), "the model must not give the hidden stocks away"
    xs = {s["id"]: s["x"] for s in m["stocks"]}
    assert xs["waiting"] < xs["treatment"] < xs["ward"] < xs["discharged"]


def test_the_history_prints_only_what_is_measured(res):
    rows = history(json.dumps({"stocks": [{"id": s} for s in [*sim.MEASURED_STOCKS, "lab", "imaging"]],
                               "flows": [{"id": f} for f in ["arrivals", "admissions", "to_lab"]]}))
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(set(r["levels"]) == set(sim.MEASURED_STOCKS) and set(r["flows"]) == {"arrivals", "admissions"} for r in rows)
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]


def test_import_gives_the_simulated_dashboard(client, res):
    snap = client.post("/api/models/hospital/live/import").json()
    s = snap["series"]
    assert s["t"] == list(range(1, sim.STEPS + 1))
    for sid in sim.MEASURED_STOCKS:
        assert s["levels"][sid] == res.levels[sid], sid
    assert set(s["levels"]) == set(sim.MEASURED_STOCKS)
    for fid in sim.MEASURED_FLOWS:
        assert s["rates"][fid] == res.flows[fid], fid
    assert set(s["rates"]) == set(sim.MEASURED_FLOWS)
    assert [e["start"] for e in snap["eras"]] == [e["t"] for e in res.eras]


def test_the_fixture_is_the_imported_run(res):
    run = json.loads(FIXTURE.read_text())
    assert run["t"] == list(range(1, sim.STEPS + 1))
    assert run["levels"] == {sid: res.levels[sid] for sid in run["levels"]} and set(run["levels"]) == set(sim.MEASURED_STOCKS)
    assert run["rates"] == {fid: res.flows[fid] for fid in sim.MEASURED_FLOWS}
    assert run["moved"][100] == {"arrivals": {"took": {}, "made": {"waiting": res.flows["arrivals"][100]}},
                                 "admissions": {"took": {"treatment": res.flows["admissions"][100]}, "made": {"ward": res.flows["admissions"][100]}}}


def test_every_patient_is_somewhere(res):
    """Conservation in the truth: every patient who ever arrived is in exactly one stock, measured or hidden."""
    arrived = list(itertools.accumulate(res.flows["arrivals"]))
    for i in range(sim.STEPS):
        assert sum(res.levels[s][i] for s in sim.STOCKS) == arrived[i]
    assert arrived[-1] == res.patients
    # and every stock changes by exactly what its true flows moved
    for s in sim.STOCKS:
        prev = 0
        for i in range(sim.STEPS):
            d = sum(res.flows[f][i] * ((to == s) - (fr == s)) for f, (fr, to) in sim.FLOWS.items())
            assert res.levels[s][i] - prev == d, (s, i)
            prev = res.levels[s][i]
    # what the dashboard cannot account for is exactly what the hidden stocks hold
    measured = [sum(res.levels[s][i] for s in sim.MEASURED_STOCKS) for i in range(sim.STEPS)]
    hidden = [sum(res.levels[s][i] for s in sim.HIDDEN_STOCKS) for i in range(sim.STEPS)]
    assert [a - m for a, m in zip(arrived, measured)] == hidden and min(hidden[48:]) > 0


def test_the_hidden_stocks_behave_as_documented(res):
    g = sim.ground_truth(res)
    h = g["hidden_stocks"]
    assert abs(h["imaging"]["delay"]["realised_mean"] - 2.0) < 0.05 and all(1.75 <= d <= 2.25 for d in res.delays["imaging"])
    assert abs(h["lab"]["delay"]["realised_mean"] - 4.0) < 0.4
    assert abs(h["followup"]["delay"]["realised_mean"] - 120) < 6
    assert abs(h["lab"]["branch_shares"]["ward"] - 0.35) < 0.04
    for k in sim.HIDDEN_STOCKS:                                  # Little's law holds in the truth
        f = g["flows"][h[k]["out_flow"]]["per_step_mean"]
        assert abs(h[k]["mean_level"] - f * h[k]["delay"]["mean"]) < 0.15 * h[k]["mean_level"], k
    assert all(sum(res.flows[f]) > 200 for f in sim.FLOWS)          # every flow carries enough to be seen


def test_truth_json_is_current(res):
    path = HOSPITAL / "truth.json"
    assert path.stat().st_size < 5_000_000
    assert json.loads(path.read_text()) == json.loads(json.dumps(sim.ground_truth(res)))


def test_same_seed_same_hospital(res):
    again = sim.run()
    assert again.levels == res.levels and again.flows == res.flows and again.delays == res.delays
    assert sim.run(7).levels != res.levels
    assert history() == history()
    assert history("", "7") != history()


def test_a_live_run_plays_the_same_hours_as_the_history(client, res):
    """Start (or Step) reads the dashboard an hour per tick: the run is the history, hour by hour."""
    assert client.post("/api/models/hospital/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/hospital/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/hospital/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid
    assert L["rates"]["arrivals"] == res.flows["arrivals"][:3]


def test_the_live_sensor_announces_staffing_changes_and_ends_with_the_recording():
    def live(t):
        return subprocess.run([sys.executable, str(HOSPITAL / "machines" / "live.py")], input=json.dumps({"t": t, **json.loads(json.dumps({"stocks": model()["stocks"], "flows": model()["flows"]}))}),
                              capture_output=True, text=True, timeout=60, cwd=HOSPITAL / "machines")
    assert "era" in json.loads(live(361).stdout)
    assert "era" not in json.loads(live(360).stdout)
    end = live(sim.STEPS + 1)
    assert end.returncode != 0 and "recording ends" in end.stderr


def test_measured_is_what_the_history_prints():
    m, rows = sim.measured(), history()
    assert m["t"] == [r["t"] for r in rows]
    assert m["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS}
    assert m["counters"] == {f: [r["flows"][f] for r in rows] for f in sim.MEASURED_FLOWS}
    assert m["eras"][0]["start"] == 1 and m["eras"][1:] == [{"start": r["t"], "label": r["era"]} for r in rows if "era" in r]


@pytest.fixture(scope="module")
def long():
    return sim.run(steps=3 * sim.STEPS)


def test_a_long_run_starts_with_the_default_run_and_keeps_every_patient(long, res):
    n = 3 * sim.STEPS
    assert all(len(long.levels[s]) == n for s in sim.STOCKS) and all(len(long.flows[f]) == n for f in sim.FLOWS)
    for s in sim.STOCKS:
        assert long.levels[s][:sim.STEPS] == res.levels[s], s
    arrived = list(itertools.accumulate(long.flows["arrivals"]))
    assert all(sum(long.levels[s][i] for s in sim.STOCKS) == arrived[i] for i in range(n))
    for s in sim.STOCKS:
        prev = 0
        for i in range(n):
            assert long.levels[s][i] - prev == sum(long.flows[f][i] * ((to == s) - (fr == s)) for f, (fr, to) in sim.FLOWS.items()), (s, i)
            prev = long.levels[s][i]
    assert all(sum(long.flows[f][2 * sim.STEPS:]) > 100 for f in sim.FLOWS)     # every flow still carries patients


def test_a_long_run_keeps_its_eras_and_surges_coming(long):
    first = [e for e in long.eras if 1 < e["t"] <= sim.STEPS]
    for k in (1, 2):
        eras = [e for e in long.eras if k * sim.STEPS < e["t"] <= (k + 1) * sim.STEPS]
        assert len(eras) >= len(first) and {e["label"] for e in eras} == {e["label"] for e in first}, k
        assert len([s for s in long.surges if k * sim.STEPS <= s[0] < (k + 1) * sim.STEPS]) == len(sim.SURGES)
    beds = {b for _, b, _ in long.beds}
    assert beds == {b for _, b, _ in sim.BEDS}
    assert long.eras[len(sim.BEDS):] != [{"t": e["t"] + sim.STEPS, "label": e["label"]} for e in long.eras[1:len(sim.BEDS)]], "a repetition moves its events"


def test_a_long_run_is_deterministic(long):
    again = sim.run(steps=3 * sim.STEPS)
    assert again.levels == long.levels and again.flows == long.flows and again.eras == long.eras
    assert sim.measured(steps=3 * sim.STEPS)["levels"] == {s: long.levels[s] for s in sim.MEASURED_STOCKS}
    assert sim.run(7, 3 * sim.STEPS).levels != long.levels
    short = sim.run(steps=100)
    assert short.levels == {s: v[:100] for s, v in long.levels.items()} and [e["t"] for e in short.eras] == [1]
