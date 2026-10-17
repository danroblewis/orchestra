"""The measured valley: rain, soil, three reservoirs and a water tower, simulated hour by hour with
rivers between the dams that nothing measures (see sdlab/examples/reservoirs/README.md)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

RES = EXAMPLES / "reservoirs"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "reservoirs-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("reservoirs_sim", RES / "machines" / "sim.py")
sys.path.insert(0, str(RES / "machines"))   # history.py imports sim by its file name
history_mod = load("reservoirs_history", RES / "machines" / "history.py")
sys.path.remove(str(RES / "machines"))


@pytest.fixture(scope="module")
def res():
    return sim.cached()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def model() -> dict:
    return json.loads((EXAMPLES / "reservoirs.json").read_text())


def program(name: str, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RES / "machines" / f"{name}.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=120, cwd=RES / "machines")


def test_the_model_is_the_measured_stocks_only():
    m = model()
    assert validate(m) == []
    assert [s["id"] for s in m["stocks"]] == sim.MEASURED_STOCKS
    assert {s["unit"] for s in m["stocks"]} == {"ML"}, "one unit: water moves one for one"
    assert {s.get("group") for s in m["stocks"]} == {None}
    assert not any(s.get("final") for s in m["stocks"])
    assert m["flows"] == [] and m["machines"] == []
    assert m["history"] == {"program": "reservoirs/history", "args": []}
    assert m["sensors"] == [{"program": "reservoirs/live", "args": []}]
    assert (m["time_unit"], m["horizon"]) == ("hour", 336)
    xs = {s["id"]: s["x"] for s in m["stocks"]}
    ys = {s["id"]: s["y"] for s in m["stocks"]}
    assert ys["rain"] < ys["soil"] and xs["soil"] < xs["upper"] < xs["middle"] < xs["lower"] < xs["tower"]


def test_the_description_reveals_no_structure():
    text = json.dumps(model()).lower()
    words = ("river", "runoff", "run off", "spill", "pump", "release", "evapor", "field capacity", "upstream",
             "downstream", "flows into", "feeds", "drains", "gate", "cascade", "delay", "travel", "hours to", "target")
    assert [w for w in words if w in text] == [], "the model must not give the structure away"


def test_the_history_prints_only_what_is_measured(res):
    stdin = json.dumps({"stocks": [{"id": s} for s in [*sim.MEASURED_STOCKS[:4], "river_ml"]],
                        "flows": [{"id": f} for f in ["runoff", "pumping", "bogus"]]})
    p = program("history", stdin)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(list(r["levels"]) == sim.MEASURED_STOCKS[:4] for r in rows)
    assert all(set(r["flows"]) == {"runoff", "pumping"} for r in rows)
    assert [r["flows"]["runoff"] for r in rows] == res.counters["runoff"]
    assert [r["levels"]["upper"] for r in rows] == res.levels["upper"]
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]
    # the example model itself has no flows: levels only, every measured stock, never a river
    rows = list(history_mod.lines(res, *history_mod.wanted(json.dumps(model()))))
    assert all("flows" not in r and list(r["levels"]) == sim.MEASURED_STOCKS for r in rows)


def test_import_gives_the_simulated_telemetry(client, res):
    snap = client.post("/api/models/reservoirs/live/import").json()
    s = snap["series"]
    assert s["t"] == list(range(1, sim.STEPS + 1))
    assert set(s["levels"]) == set(sim.MEASURED_STOCKS)
    for sid in sim.MEASURED_STOCKS:
        assert s["levels"][sid] == res.levels[sid], sid
    assert s["rates"] == {}
    assert [(e["start"], e["label"]) for e in snap["eras"]] == [(e["t"], e["label"]) for e in res.eras]


def test_the_fixture_is_the_imported_run(res):
    assert FIXTURE.stat().st_size < 5_000_000
    run = json.loads(FIXTURE.read_text())
    assert run["t"] == list(range(1, sim.STEPS + 1))
    assert run["levels"] == {sid: res.levels[sid] for sid in sim.MEASURED_STOCKS}
    assert run["rates"] == {}
    assert run["counters"] == res.counters and set(run["counters"]) == set(sim.COUNTERS)
    assert [(e["start"], e["label"]) for e in run["eras"]] == [(e["t"], e["label"]) for e in res.eras]


def test_every_megalitre_is_accounted_for(res):
    """Water balance inside the simulator: every stock, measured or not, changes by exactly what
    its true flows moved, and nothing is created or lost except at the valley's edges."""
    T, F = res.true, res.flows
    start = {s: T[s][0] - sum(F[f][0] * ((b == s) - (a == s)) for f, (a, b) in sim.FLOWS.items()) for s in sim.STOCKS}
    for s in sim.STOCKS:
        prev = start[s]
        for i in range(sim.STEPS):
            d = sum(F[f][i] * ((b == s) - (a == s)) for f, (a, b) in sim.FLOWS.items())
            assert abs(T[s][i] - prev - d) < 1e-6, (s, i)
            assert T[s][i] > -1e-9, (s, i)
            prev = T[s][i]
    inflow = sum(F["rainfall"])
    outflow = sum(sum(F[f]) for f, (a, b) in sim.FLOWS.items() if b is None)
    held = sum(T[s][-1] - start[s] for s in sim.STOCKS)
    assert abs(inflow - outflow - held) < 1e-6
    for s in sim.MEASURED_STOCKS:                                        # the telemetry reads 0.1 ML
        assert all(abs(a - b) <= 0.05 + 1e-9 for a, b in zip(res.levels[s], T[s]))


def test_the_valley_behaves_as_documented(res):
    T, F = res.true, res.flows
    a, b = sim.MAINTENANCE
    assert sum(F["middle_release"][a:b]) == 0 and sum(F["middle_release"][a - 24:a]) > 24
    assert sum(F["rainfall"][sim.DRY[0]:sim.DRY[1]]) == 0 and sum(F["runoff"][sim.DRY[1] - 72:sim.DRY[1]]) == 0
    assert max(F["rainfall"]) == max(F["rainfall"][sim.BIG_STORM[0]:sim.BIG_STORM[0] + sim.BIG_STORM[1]])
    assert sum(F["upper_spill"]) > 0 and sum(F["middle_spill"]) > 0
    assert all(abs(x - y) < 1e-9 for x, y in zip(F["soak"][1:], F["rainfall"]))   # the gauge empties into the soil an hour later
    k = sim.P["pump_time_h"]                                             # pumping closes the tower's gap
    assert all(abs(F["pumping"][i] - max(0.0, (sim.TOWER["target_ml"] - T["tower"][i - 1]) / k)) < 1e-9 for i in range(1, sim.STEPS))
    pipe = sim.P["reach_ml_pipe_h"]                                      # what leaves the middle dam arrives 6 h later
    sent = [x + y for x, y in zip(F["middle_release"], F["middle_spill"])]
    assert all(abs(F["river_ml_arrive"][i] - sent[i - pipe]) < 1e-9 for i in range(pipe, sim.STEPS))
    g = sim.ground_truth(res)
    for h in g["sd_structure"]["hidden"]:                                # Little's law: the rivers hold rate x delay
        assert abs(h["holds"] - h["flow_in_per_h"] * h["delay"]) < 0.1 * h["holds"], h["from"]
    assert all(min(T[s]) > 0 for s in ("soil", "upper", "middle", "lower", "tower"))


def test_truth_json_is_current(res):
    path = RES / "truth.json"
    assert path.stat().st_size < 1_000_000
    truth = json.loads(path.read_text())
    assert truth == json.loads(json.dumps(sim.ground_truth(res)))
    assert set(truth["sd_structure"]) >= {"moves", "outside", "links", "hidden", "echoes"}


def test_same_seed_same_valley(res):
    again = sim.run()
    assert again.levels == res.levels and again.flows == res.flows
    assert sim.run(7).levels != res.levels
    p = program("history")
    assert p.returncode == 0, p.stderr
    assert [json.loads(line) for line in p.stdout.splitlines()] == list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))
    assert program("history", "", "7").stdout != p.stdout


def test_a_live_run_plays_the_same_hours_as_the_history(client, res):
    """Start (or Step) reads the telemetry an hour per tick: the run is the history, hour by hour."""
    assert client.post("/api/models/reservoirs/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/reservoirs/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/reservoirs/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid


def test_the_live_sensor_announces_eras_and_ends_with_the_recording(res):
    m = model()

    def live(t):
        return program("live", json.dumps({"t": t, "stocks": m["stocks"], "flows": [{"id": "pumping"}]}))

    t = sim.MAINTENANCE[0] + 1
    first = json.loads(live(t).stdout)
    assert first["era"].startswith("Maintenance week")
    assert first["levels"]["middle"] == res.levels["middle"][t - 1]
    assert first["flows"] == {"pumping": res.counters["pumping"][t - 1]}
    assert "era" not in json.loads(live(t - 1).stdout)
    end = live(sim.STEPS + 1)
    assert end.returncode != 0 and "recording ends" in end.stderr


def test_measured_is_what_the_history_prints(res):
    m = sim.measured()
    p = program("history")
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert m["t"] == [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert m["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS}
    assert m["eras"][0]["start"] == 1
    assert [(e["start"], e["label"]) for e in m["eras"][1:]] == [(r["t"], r["era"]) for r in rows if "era" in r]
    assert m["counters"] == res.counters


@pytest.fixture(scope="module")
def long():
    return sim.run(steps=3 * sim.STEPS)


def test_a_long_run_starts_with_the_season_and_keeps_its_water_balance(res, long):
    n = 3 * sim.STEPS
    assert {s: v[:sim.STEPS] for s, v in long.true.items()} == res.true
    assert {f: v[:sim.STEPS] for f, v in long.flows.items()} == res.flows
    assert long.eras[:len(res.eras)] == res.eras
    T, F = long.true, long.flows
    for s in sim.STOCKS:
        prev = T[s][0] - sum(F[f][0] * ((b == s) - (a == s)) for f, (a, b) in sim.FLOWS.items())
        for i in range(n):
            assert abs(T[s][i] - prev - sum(F[f][i] * ((b == s) - (a == s)) for f, (a, b) in sim.FLOWS.items())) < 1e-6, (s, i)
            assert T[s][i] > -1e-9, (s, i)
            prev = T[s][i]
    again = sim.measured(steps=n)
    assert again["levels"] == long.levels and again["counters"] == long.counters
    assert again == sim.measured(steps=n)
    assert sim.measured(7, n)["levels"] != long.levels
    assert sim.run(steps=1).levels == {s: v[:1] for s, v in res.levels.items()}


def test_every_season_has_weather_and_a_maintenance_week(long):
    per = [[e for e in long.eras if k * sim.SEASON < e["t"] <= (k + 1) * sim.SEASON] for k in range(3)]
    assert all(len(es) >= len(per[0]) for es in per[1:]), [len(es) for es in per]
    for k in (1, 2):
        es = per[k]
        assert es[0]["t"] == k * sim.SEASON + 1 and es[0]["label"] == sim.SEASONS[k][0]
        shut = next(e["t"] for e in es if e["label"].startswith("Maintenance week"))
        back = next(e["t"] for e in es if e["label"] == "Middle dam back in service")
        assert back - shut == 7 * 24 and all(long.flows["middle_release"][h] == 0 for h in range(shut - 1, back - 1))
        dry = next(e["t"] for e in es if e["label"] == "Dry spell")
        storm = next(e["t"] for e in es if e["label"] == "Storm")
        rain = long.flows["rainfall"]
        wet = next((e["t"] for e in es if e["label"] == "Rain returns"), storm)
        assert sum(rain[dry - 1:wet - 1]) == 0 and max(rain[storm - 1:storm + 47]) > 50, k
    assert [e["label"] for e in per[1]] != [e["label"] for e in per[2]]
