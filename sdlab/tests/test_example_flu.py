"""The measured flu season: a seeded chain-binomial epidemic in a town of 50,000 whose five
dashboard counts are the model; how people move between them is the answer key
(see sdlab/examples/flu/README.md)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

FLU = EXAMPLES / "flu"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "flu-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("flu_sim", FLU / "machines" / "sim.py")
_other = sys.modules.get("sim")              # history.py imports sim by its file name: this one, not another example's
sys.modules["sim"] = sim
history_mod = load("flu_history", FLU / "machines" / "history.py")
if _other is not None:
    sys.modules["sim"] = _other
else:
    del sys.modules["sim"]


@pytest.fixture(scope="module")
def res():
    return sim.cached()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def model() -> dict:
    return json.loads((EXAMPLES / "flu.json").read_text())


def program(name: str, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(FLU / "machines" / f"{name}.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=60, cwd=FLU / "machines")


def test_the_model_is_the_measured_stocks_only():
    m = model()
    assert validate(m) == []
    assert {s["id"] for s in m["stocks"]} == set(sim.MEASURED_STOCKS) and len(m["stocks"]) == 5
    assert {s["unit"] for s in m["stocks"]} == {"people"}
    assert {s.get("group") for s in m["stocks"]} == {"town"}, "one group: discovery may relate any two stocks"
    assert not any(s.get("final") for s in m["stocks"])
    assert m["flows"] == [] and m["machines"] == []
    assert m["history"] == {"program": "flu/history"} and m["sensors"] == [{"program": "flu/live"}]
    assert (m["time_unit"], m["horizon"], m["dt"]) == ("day", 60, 1)
    assert sum(s["initial"] for s in m["stocks"]) == sim.N
    xs = {s["id"]: s["x"] for s in m["stocks"]}
    assert xs["susceptible"] < xs["sick"] < xs["hospital"] < xs["recovered"]


def test_the_description_reveals_no_structure():
    text = model()["description"].lower()
    for word in ("wane", "waning", "beta", "contagio", "5 days", "five days", "7 days", "3 days", "admitted", "120", "erlang",
                 "infect", "proportional", "nonlinear", "s x i", "spread"):
        assert word not in text, f"the description gives away {word!r}"


def test_the_history_prints_only_what_is_measured(res):
    stdin = json.dumps({"stocks": [{"id": s} for s in ["sick", "hospital", "severe1", "mild"]],
                        "flows": [{"id": f} for f in ["admissions", "waning", "bogus"]]})
    p = program("history", stdin)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(list(r["levels"]) == ["sick", "hospital"] for r in rows)
    assert all(set(r["flows"]) == {"admissions", "waning"} for r in rows)
    assert [r["flows"]["waning"] for r in rows] == res.counters["waning"]
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]
    # the example model itself has no flows: levels only, every stock
    rows = list(history_mod.lines(res, *history_mod.wanted(json.dumps(model()))))
    assert all("flows" not in r and set(r["levels"]) == set(sim.MEASURED_STOCKS) for r in rows)


def test_import_gives_the_simulated_dashboard(client, res):
    snap = client.post("/api/models/flu/live/import").json()
    s = snap["series"]
    assert s["t"] == list(range(1, sim.STEPS + 1))
    assert set(s["levels"]) == set(sim.MEASURED_STOCKS)
    for sid in sim.MEASURED_STOCKS:
        assert s["levels"][sid] == res.levels[sid], sid
    assert s["rates"] == {}
    assert [e["start"] for e in snap["eras"]] == [e["t"] for e in res.eras]
    assert [e["label"] for e in snap["eras"][1:]] == [e["label"] for e in res.eras[1:]]


def test_the_fixture_is_the_imported_run(res):
    assert FIXTURE.stat().st_size < 5_000_000
    run = json.loads(FIXTURE.read_text())
    assert run["t"] == list(range(1, sim.STEPS + 1))
    assert run["levels"] == {sid: res.levels[sid] for sid in sim.MEASURED_STOCKS}
    assert run["rates"] == {} and run["counters"] == res.counters
    assert run["eras"] == [{"start": 1, "label": "Start"}] + [{"start": e["t"], "label": e["label"]} for e in res.eras[1:]]


def test_everyone_is_somewhere(res):
    """Conservation inside the simulator: the town always holds 50,000, and every count changes by
    exactly what its flows moved."""
    L, C = res.levels, res.counters
    for i in range(sim.STEPS):
        assert sum(L[s][i] for s in sim.MEASURED_STOCKS) == sim.N
        assert L["sick"][i] == sum(L[p][i] for p in sim.SICK_PARTS)
    for s in sim.MEASURED_STOCKS:
        prev = sim.INITIAL[s] if s in sim.INITIAL else sum(sim.INITIAL[p] for p in sim.SICK_PARTS)
        for i in range(sim.STEPS):
            d = sum(C[f][i] * ((to == s) - (fr == s)) for f, (fr, to) in sim.FLOWS.items())
            assert L[s][i] - prev == d, (s, i)
            prev = L[s][i]


def test_the_epidemic_behaves_as_documented(res):
    g = sim.ground_truth(res)
    moves = {(m["from"], m["to"]): m for m in g["sd_structure"]["moves"]}
    assert abs(moves["recovered", "susceptible"]["k_fitted"] - 1 / 120) < 0.001
    assert abs(moves["hospital", "recovered"]["k_fitted"] - 1 / 7) < 0.015
    assert abs(moves["sick", "recovered"]["k_fitted"] - 0.2 * (1 - sim.P["p_severe"])) < 0.02
    by_era = g["sd_structure"]["infection_by_era"]
    for e in by_era[:5]:                                           # k = beta x S / N while there are cases to count
        assert abs(e["k_fitted"] - e["k_per_sick"]) < 0.2 * e["k_per_sick"] + 0.01, e
    assert by_era[1]["k_fitted"] < 0.6 * by_era[0]["k_fitted"]      # holidays cut contacts
    for d, _, _, cap in sim.ERAS:                                 # vaccination at the clinics' capacity
        days = range(d, next((e[0] for e in sim.ERAS if e[0] > d), sim.DAYS + 1))
        got = sum(res.counters["vaccinations"][t - 1] for t in days) / len(days)
        assert abs(got - cap) < 0.08 * cap + 0.01, (d, got)
    assert 25 <= g["peak_sick_day"] <= 75 and max(res.levels["hospital"]) > 60
    assert min(res.levels["susceptible"]) > 5000, "vaccination never runs out of people"
    # admissions follow the infections of ~3 days earlier, not today's
    adm, inf = res.counters["admissions"], res.counters["infections"]

    def corr(lag):
        a, b = adm[lag:], inf[:len(inf) - lag]
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    assert corr(3) > corr(0) and corr(3) > corr(6)


def test_truth_json_is_current(res):
    path = FLU / "truth.json"
    assert path.stat().st_size < 1_000_000
    truth = json.loads(path.read_text())
    assert truth == json.loads(json.dumps(sim.ground_truth(res)))
    assert set(truth["sd_structure"]) >= {"moves", "outside", "links", "hidden", "echoes"}


def test_same_seed_same_season(res):
    again = sim.run()
    assert again.levels == res.levels and again.counters == res.counters
    assert sim.run(7).levels != res.levels
    p = program("history")
    assert p.returncode == 0, p.stderr
    assert [json.loads(line) for line in p.stdout.splitlines()] == list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))
    assert program("history", "", "7").stdout != p.stdout


def test_a_live_run_plays_the_same_days_as_the_history(client, res):
    """Start (or Step) reads the dashboard a day per tick: the run is the history, day by day."""
    assert client.post("/api/models/flu/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/flu/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/flu/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid


def test_the_live_sensor_announces_changes_and_ends_with_the_recording(res):
    m = model()

    def live(t):
        return program("live", json.dumps({"t": t, "stocks": m["stocks"], "flows": [{"id": "infections"}]}))

    first = json.loads(live(41).stdout)
    assert first["era"] == "School holidays: fewer contacts"
    assert first["levels"]["sick"] == res.levels["sick"][40]
    assert first["flows"] == {"infections": res.counters["infections"][40]}
    assert "era" not in json.loads(live(40).stdout)
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


def test_a_long_run_starts_with_the_season_and_keeps_conserving(res):
    n = 3 * sim.STEPS
    long = sim.run(steps=n)
    assert {s: v[:sim.STEPS] for s, v in long.levels.items()} == res.levels
    assert {f: long.counters[f][:sim.STEPS] for f in sim.FLOWS} == res.counters
    assert long.eras[:len(res.eras)] == res.eras
    flows = sim.flows(n)
    assert set(long.counters) == set(flows) and "vaccine_expiry" in flows
    L, C = long.levels, long.counters
    prev = {s: sim.INITIAL[s] if s in sim.INITIAL else sum(sim.INITIAL[p] for p in sim.SICK_PARTS) for s in sim.MEASURED_STOCKS}
    for i in range(n):
        assert sum(L[s][i] for s in sim.MEASURED_STOCKS) == sim.N
        for s in sim.MEASURED_STOCKS:
            assert L[s][i] - prev[s] == sum(C[f][i] * ((to == s) - (fr == s)) for f, (fr, to) in flows.items()), (s, i)
            prev[s] = L[s][i]
    assert C["vaccine_expiry"][sim.YEAR] == L["vaccinated"][sim.YEAR - 1] > 0 and sum(C["vaccine_expiry"]) == C["vaccine_expiry"][sim.YEAR]
    again = sim.measured(steps=n)
    assert again == sim.measured(steps=n) and again["levels"] == {s: L[s] for s in sim.MEASURED_STOCKS}
    assert sim.measured(7, n)["levels"] != again["levels"]
    assert sim.run(steps=1).levels == {s: v[:1] for s, v in res.levels.items()}


def test_every_year_is_a_new_season():
    """Years recur: a new strain, the holidays and the vaccination campaign every year, and the
    epidemic comes back as immunity wanes and the vaccine expires."""
    years = 3
    long = sim.run(steps=years * sim.YEAR)
    per_year = [[e for e in long.eras if y * sim.YEAR < e["t"] <= (y + 1) * sim.YEAR] for y in range(years)]
    assert all(len(es) >= len(per_year[0]) for es in per_year[1:]), [len(es) for es in per_year]
    for y in range(1, years):
        labels = [e["label"] for e in per_year[y]]
        assert labels[0].startswith("New season") and per_year[y][0]["t"] == y * sim.YEAR + 1
        assert any(lab.startswith("Vaccination campaign:") for lab in labels) and "School holidays: fewer contacts" in labels
        sick = long.levels["sick"][y * sim.YEAR:(y + 1) * sim.YEAR]
        assert max(sick) > 500, y
        assert sum(long.counters["vaccinations"][y * sim.YEAR:(y + 1) * sim.YEAR]) > 5000, y
    assert per_year[1] != per_year[2]                          # fresh draws every year
