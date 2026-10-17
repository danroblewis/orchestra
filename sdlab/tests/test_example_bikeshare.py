"""The measured bike share: 6 stations and a rebalancing van, simulated per ride, with the rides
themselves (bikes out on the street) never measured (see sdlab/examples/bikeshare/README.md)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

BIKESHARE = EXAMPLES / "bikeshare"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "bikeshare-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("bikeshare_sim", BIKESHARE / "machines" / "sim.py")
_other = sys.modules.get("sim")              # history.py imports sim by its file name: give it this one
sys.modules["sim"] = sim
history_mod = load("bikeshare_history", BIKESHARE / "machines" / "history.py")
if _other is None:
    del sys.modules["sim"]
else:
    sys.modules["sim"] = _other


@pytest.fixture(scope="module")
def res():
    return sim.cached()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def model() -> dict:
    return json.loads((EXAMPLES / "bikeshare.json").read_text())


def program(name: str, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BIKESHARE / "machines" / f"{name}.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=120, cwd=BIKESHARE / "machines")


def test_the_model_is_the_measured_stocks_only():
    m = model()
    assert validate(m) == []
    assert [s["id"] for s in m["stocks"]] == sim.MEASURED_STOCKS
    assert {s["unit"] for s in m["stocks"]} == {"bikes"}, "one unit: discovery may move bikes between any two stocks"
    assert {s.get("group") for s in m["stocks"]} == {"city"}
    assert not any(s.get("final") for s in m["stocks"])
    assert m["flows"] == [] and m["machines"] == []
    assert m["history"] == {"program": "bikeshare/history"} and m["sensors"] == [{"program": "bikeshare/live"}]
    assert (m["time_unit"], m["horizon"], m["dt"]) == ("5-minute step", 288, 1)
    xs = {s["id"]: s["x"] for s in m["stocks"]}
    assert xs["riverside"] < xs["old_town"] < xs["central"] < xs["university"] < xs["business_park"]


def test_the_description_reveals_no_structure():
    text = model()["description"].lower()
    names = [v[0].lower() for v in sim.STATIONS.values()]
    words = ["commut", "rush", "ride", "rider", "neighbour", "fullest", "emptiest", "shift", "minutes long", "per pair"]
    found = [w for w in names + words if w in text]
    assert found == [], f"the description gives the structure away: {found}"


def test_the_history_prints_only_what_is_measured(res):
    stdin = json.dumps({"stocks": [{"id": s} for s in [*sim.MEASURED_STOCKS[:3], "riding", "van"]],
                        "flows": [{"id": f} for f in ["loaded__old_town", "rides__riverside__old_town", "bogus"]]})
    p = program("history", stdin)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(list(r["levels"]) == [*sim.MEASURED_STOCKS[:3], "van"] for r in rows)
    assert all(set(r["flows"]) == {"loaded__old_town", "rides__riverside__old_town"} for r in rows)
    assert [r["flows"]["loaded__old_town"] for r in rows] == res.counters["loaded__old_town"]
    assert [r["levels"]["riverside"] for r in rows] == res.levels["riverside"]
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]
    # the example model itself has no flows: levels only, every measured stock
    rows = list(history_mod.lines(res, *history_mod.wanted(json.dumps(model()))))
    assert all("flows" not in r and list(r["levels"]) == sim.MEASURED_STOCKS for r in rows)


def test_import_gives_the_simulated_dashboard(client, res):
    snap = client.post("/api/models/bikeshare/live/import").json()
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


def test_every_bike_is_somewhere(res):
    conserved(res)


def conserved(res, cal=None):
    """Conservation inside the simulator: docked + on the van + being ridden = the fleet, every step,
    and every stock changes by exactly what its true flows moved."""
    C, L = res.counters, res.levels
    n = len(L["van"])
    riding = sim.riding_total(res)
    for i in range(n):
        assert sum(L[s][i] for s in sim.MEASURED_STOCKS) + riding[i] == sim.BIKES, i
    for s in sim.IDS:
        prev = sim.STATIONS[s][2]
        for i in range(n):
            d = C[f"ended__{s}"][i] - C[f"started__{s}"][i] + C[f"unloaded__{s}"][i] - C[f"loaded__{s}"][i]
            assert L[s][i] - prev == d, (s, i)
            assert 0 <= L[s][i] <= sim.docks(s, i, cal), (s, i)
            prev = L[s][i]
        assert C[f"started__{s}"] == [sum(C[f"rides__{s}__{b}"][i] for b in sim.IDS if b != s) for i in range(n)]
    prev = 0
    for i in range(n):
        d = sum(C[f"loaded__{s}"][i] - C[f"unloaded__{s}"][i] for s in sim.IDS)
        assert L["van"][i] - prev == d and 0 <= L["van"][i] <= sim.VAN_RULES["capacity"], i
        prev = L["van"][i]
    for a, b in sim.PAIRS:                                    # each hidden stock: rides started minus rides ended
        key, prev = f"{a}__{b}", 0
        for i in range(n):
            assert res.riding[key][i] - prev == C[f"rides__{key}"][i] - res.ended_pair[key][i], (key, i)
            prev = res.riding[key][i]
    assert sum(map(sum, (C[f"ended__{s}"] for s in sim.IDS))) == sum(map(sum, res.ended_pair.values()))


def test_the_closed_station_is_locked(res):
    a, b, s = sim.CLOSED
    span = range(a * sim.STEPS_PER_DAY, b * sim.STEPS_PER_DAY)
    assert len({res.levels[s][i] for i in span}) == 1
    assert sum(res.counters[f"started__{s}"][i] + res.counters[f"ended__{s}"][i] for i in span) == 0
    assert sum(res.counters[f"diverted__{sim.STATIONS[s][3]}"][i] for i in span) > 20


def test_the_hidden_rides_behave_as_documented(res):
    g = sim.ground_truth(res)
    sd = g["sd_structure"]
    assert sd["outside"] == [] and sd["links"] == [] and sd["echoes"] == []
    assert len(sd["hidden"]) == sum(len(v["midday"]) for v in sim.DEST.values())     # the pairs riders use
    for h in sd["hidden"]:
        assert abs(h["delay_realised_steps"] - h["delay"]) < 0.15, h
        assert 2 <= h["delay"] <= 5 and h["rides"] > 500, h
        assert abs(h["holds"] - h["per_step"] * h["delay"]) < 0.12 * h["holds"], h        # Little's law
    assert 8 < g["riding_total"]["mean"] < 20
    assert {(m["from"], m["to"]) for m in sd["moves"]} >= {("old_town", "van"), ("van", "university")}
    assert all("van" in (m["from"], m["to"]) for m in sd["moves"])
    assert sum(m["total"] for m in sd["moves"] if m["from"] == "van") == g["van"]["bikes_moved"]


def test_truth_json_is_current(res):
    path = BIKESHARE / "truth.json"
    assert path.stat().st_size < 1_000_000
    assert json.loads(path.read_text()) == json.loads(json.dumps(sim.ground_truth(res)))


def test_same_seed_same_city(res):
    again = sim.run()
    assert again.levels == res.levels and again.counters == res.counters and again.riding == res.riding
    assert sim.run(7).levels != res.levels
    p = program("history")
    assert p.returncode == 0, p.stderr
    assert [json.loads(line) for line in p.stdout.splitlines()] == list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))
    assert program("history", "", "7").stdout != p.stdout


def test_a_live_run_plays_the_same_steps_as_the_history(client, res):
    """Start (or Step) reads the dashboard five minutes per tick: the run is the history, step by step."""
    assert client.post("/api/models/bikeshare/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/bikeshare/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/bikeshare/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid


def test_the_live_sensor_announces_changes_and_ends_with_the_recording(res):
    m = model()

    def live(t):
        return program("live", json.dumps({"t": t, "stocks": m["stocks"], "flows": [{"id": "unloaded__university"}]}))

    t = sim.CLOSED[0] * sim.STEPS_PER_DAY + 1
    first = json.loads(live(t).stdout)
    assert first["era"] == "Waterfront closed for a festival"
    assert first["levels"]["waterfront"] == res.levels["waterfront"][t - 1]
    assert first["flows"] == {"unloaded__university": res.counters["unloaded__university"][t - 1]}
    assert "era" not in json.loads(live(t - 1).stdout)
    end = live(sim.STEPS + 1)
    assert end.returncode != 0 and "recording ends" in end.stderr


def test_measured_is_what_the_history_prints(res):
    p = program("history")
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    m = sim.measured()
    assert m["t"] == [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert m["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS} == res.levels
    assert m["eras"][0]["start"] == 1 and m["eras"][1:] == [{"start": r["t"], "label": r["era"]} for r in rows if "era" in r]
    assert m["counters"] == res.counters                     # what the live feed can print as measured flows


@pytest.fixture(scope="module")
def long():
    return sim.run(steps=3 * sim.STEPS)


def test_a_long_run_starts_with_the_default_run_and_keeps_every_bike(long, res):
    n = 3 * sim.STEPS
    assert all(len(v) == n for v in long.levels.values()) and all(len(v) == n for v in long.counters.values())
    assert {s: v[:sim.STEPS] for s, v in long.levels.items()} == res.levels
    conserved(long, sim.calendar(sim.SEED, n))
    assert all(sum(long.counters[f"started__{s}"][2 * sim.STEPS:]) > 1000 for s in sim.IDS)
    assert all(sum(long.counters[f"loaded__{s}"][2 * sim.STEPS:]) + sum(long.counters[f"unloaded__{s}"][2 * sim.STEPS:]) > 0 for s in sim.IDS)


def test_a_long_run_keeps_its_eras_and_events_coming(long):
    first = [e for e in long.eras if e["t"] <= sim.STEPS]
    for k in (1, 2):
        eras = [e for e in long.eras if k * sim.STEPS < e["t"] <= (k + 1) * sim.STEPS]
        assert len(eras) >= len(first), k
        assert eras[0] == {"t": k * sim.STEPS + 1, "label": sim.RESET_LABEL}
        assert [e["label"] for e in eras[1:]] == [e["label"] for e in first[1:]]
    cal = sim.calendar(sim.SEED, 3 * sim.STEPS)
    for k in (1, 2):                                         # each fortnight: one rain day, one closed spell, the docks back and forth
        days = cal[k * sim.DAYS:(k + 1) * sim.DAYS]
        assert sum(d["rain"] < 1 for d in days) == 1 and 1 <= sum(d["closed"] for d in days) <= 2
        assert days[0]["bp_docks"] == 44 and days[-1]["bp_docks"] == 64 and days[0]["shift"] == "day" and days[-1]["shift"] == "day and late"
        closed = [i for i in range(k * sim.STEPS, (k + 1) * sim.STEPS) if cal[i // sim.STEPS_PER_DAY]["closed"]]
        assert len({long.levels[sim.CLOSED[2]][i] for i in closed}) == 1, k      # locked in while closed
    assert [e["t"] - sim.STEPS for e in long.eras if sim.STEPS < e["t"] <= 2 * sim.STEPS][1:] != [e["t"] for e in long.eras[1:5]], "a repetition moves its events"


def test_a_long_run_is_deterministic(long):
    again = sim.run(steps=3 * sim.STEPS)
    assert again.levels == long.levels and again.counters == long.counters and again.eras == long.eras
    assert sim.measured(steps=3 * sim.STEPS)["levels"] == long.levels
    assert sim.run(7, 3 * sim.STEPS).levels != long.levels
    short = sim.run(steps=100)
    assert short.levels == {s: v[:100] for s, v in long.levels.items()} and [e["t"] for e in short.eras] == [1]
