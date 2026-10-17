"""The measured SaaS business: a seeded daily simulation of ads, visitors, 14-day trials, paying
customers and churn, whose five dashboard levels are the model; how they are connected is the
answer key (see sdlab/examples/saas/README.md)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

SAAS = EXAMPLES / "saas"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "saas-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("saas_sim", SAAS / "machines" / "sim.py")
_other = sys.modules.get("sim")              # history.py imports sim by its file name: this one, not another example's
sys.modules["sim"] = sim
history_mod = load("saas_history", SAAS / "machines" / "history.py")
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
    return json.loads((EXAMPLES / "saas.json").read_text())


def program(name: str, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SAAS / "machines" / f"{name}.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=60, cwd=SAAS / "machines")


def test_the_model_is_the_measured_stocks_only(res):
    m = model()
    assert validate(m) == []
    assert [s["id"] for s in m["stocks"]] == sim.MEASURED_STOCKS
    units = {s["id"]: s["unit"] for s in m["stocks"]}
    assert units["ad_budget"] == "dollars" and {units[s] for s in sim.MEASURED_STOCKS[1:]} == {"people"}
    assert {s.get("group") for s in m["stocks"]} == {"saas"}, "one group: discovery may relate any two stocks"
    assert [s["id"] for s in m["stocks"] if s.get("final")] == ["churned"]
    assert m["flows"] == [] and m["machines"] == []
    assert m["history"] == {"program": "saas/history"} and m["sensors"] == [{"program": "saas/live"}]
    assert (m["time_unit"], m["horizon"], m["dt"]) == ("day", 90, 1)
    assert {s["id"]: s["initial"] for s in m["stocks"]} == {s: res.start[s] for s in sim.MEASURED_STOCKS}
    xs = [s["x"] for s in m["stocks"]]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)


def test_the_description_reveals_no_structure():
    text = model()["description"].lower()
    for word in ("14", "fourteen", "90", "viral", "win-back", "win back", "come back", "convert", "per dollar", "a seventh",
                 "proportional", "pipe", "echo", "%"):
        assert word not in text, f"the description gives away {word!r}"


def test_the_history_prints_only_what_is_measured(res):
    stdin = json.dumps({"stocks": [{"id": s} for s in ["trials", "paying", "in_trial_cohort"]],
                        "flows": [{"id": f} for f in ["conversions", "win_backs", "bogus"]]})
    p = program("history", stdin)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(list(r["levels"]) == ["trials", "paying"] for r in rows)
    assert all(set(r["flows"]) == {"conversions", "win_backs"} for r in rows)
    assert [r["flows"]["win_backs"] for r in rows] == res.counters["win_backs"]
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]
    rows = list(history_mod.lines(res, *history_mod.wanted(json.dumps(model()))))
    assert all("flows" not in r and set(r["levels"]) == set(sim.MEASURED_STOCKS) for r in rows)


def test_import_gives_the_simulated_dashboard(client, res):
    snap = client.post("/api/models/saas/live/import").json()
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
    assert run["rates"] == {} and run["counters"] == res.counters and run["start"] == res.start
    assert run["eras"] == [{"start": 1, "label": "Start"}] + [{"start": e["t"], "label": e["label"]} for e in res.eras[1:]]


def test_every_dollar_and_person_is_accounted_for(res):
    """Conservation inside the simulator: every level changes by exactly what its flows moved."""
    L, C = res.levels, res.counters
    for s in sim.MEASURED_STOCKS:
        prev = res.start[s]
        for i in range(sim.STEPS):
            d = sum(C[f][i] * ((to == s) - (fr == s)) for f, (fr, to) in sim.FLOWS.items())
            assert L[s][i] - prev == d, (s, i)
            assert L[s][i] >= 0
            prev = L[s][i]
    assert sum(C["cancellations"]) > 0
    # churned is cumulative: it only grows
    assert all(b >= a for a, b in zip(L["churned"], L["churned"][1:]))


def test_the_business_behaves_as_documented(res):
    C, L = res.counters, res.levels
    # every trial ends exactly 14 days after it started
    for i in range(14, sim.STEPS):
        assert C["conversions"][i] + C["trials_expired"][i] == C["trial_starts"][i - 14]
    # win-backs are 30% of the cancellations exactly 90 days earlier
    later = sum(C["win_backs"][90:])
    assert abs(later - 0.3 * sum(C["cancellations"][:-90])) < 0.06 * later
    assert max(C["win_backs"][289:296]) > 3 * (sum(C["win_backs"][200:280]) / 80)   # the echo of the price-rise cancellations
    g = sim.ground_truth(res)
    sd = g["sd_structure"]
    link = sd["links"][0]
    assert (link["driver"], link["into"]) == ("ad_budget", "visitors") and abs(link["k_fitted"] - link["k"]) < 0.05 * link["k"]
    moves = {(m["from"], m["to"]): m for m in sd["moves"]}
    assert abs(moves["visitors", "trials"]["k_fitted"] - 0.012) < 0.001
    churn = moves["paying", "churned"]
    assert abs(churn["k_fitted"] - 0.005) < 0.0007 and abs(churn["k_fitted_new_price"] - 0.0075) < 0.001
    assert abs(churn["k_fitted_announced"] - 0.035) < 0.005
    assert [e["source"] for e in sd["echoes"]] == ["churned"] and sd["hidden"] == []
    assert max(C["organic_visits"][149:153]) > 2000                                      # the viral spike
    assert min(L["trials"]) > 300 and min(L["paying"]) > 1500


def test_truth_json_is_current(res):
    path = SAAS / "truth.json"
    assert path.stat().st_size < 1_000_000
    truth = json.loads(path.read_text())
    assert truth == json.loads(json.dumps(sim.ground_truth(res)))
    assert set(truth["sd_structure"]) >= {"moves", "outside", "links", "hidden", "echoes"}


def test_same_seed_same_business(res):
    again = sim.run()
    assert again.levels == res.levels and again.counters == res.counters
    assert sim.run(7).levels != res.levels
    p = program("history")
    assert p.returncode == 0, p.stderr
    assert [json.loads(line) for line in p.stdout.splitlines()] == list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))
    assert program("history", "", "7").stdout != p.stdout


def test_a_live_run_plays_the_same_days_as_the_history(client, res):
    """Start (or Step) reads the dashboard a day per tick: the run is the history, day by day."""
    assert client.post("/api/models/saas/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/saas/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/saas/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid


def test_the_live_sensor_announces_changes_and_ends_with_the_recording(res):
    m = model()

    def live(t):
        return program("live", json.dumps({"t": t, "stocks": m["stocks"], "flows": [{"id": "cancellations"}]}))

    first = json.loads(live(200).stdout)
    assert first["era"] == "Price rise announced: +30% in five days"
    assert first["levels"]["paying"] == res.levels["paying"][199]
    assert first["flows"] == {"cancellations": res.counters["cancellations"][199]}
    assert "era" not in json.loads(live(199).stdout)
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


def test_a_long_run_starts_with_the_year_and_keeps_conserving(res):
    n = 3 * sim.STEPS
    long = sim.run(steps=n)
    assert long.start == res.start
    assert {s: v[:sim.STEPS] for s, v in long.levels.items()} == res.levels
    assert {f: v[:sim.STEPS] for f, v in long.counters.items()} == res.counters
    assert long.eras[:len(res.eras)] == res.eras
    L, C = long.levels, long.counters
    for s in sim.MEASURED_STOCKS:
        prev = long.start[s]
        for i in range(n):
            assert L[s][i] - prev == sum(C[f][i] * ((to == s) - (fr == s)) for f, (fr, to) in sim.FLOWS.items()), (s, i)
            assert L[s][i] >= 0
            prev = L[s][i]
    again = sim.measured(steps=n)
    assert again == sim.measured(steps=n) and again["levels"] == L
    assert sim.measured(7, n)["levels"] != L
    assert sim.run(steps=1).levels == {s: v[:1] for s, v in res.levels.items()}


def test_every_year_has_its_campaigns_price_rise_and_viral_spike():
    n = 3 * sim.STEPS
    long = sim.run(steps=n)
    per_year = [[e for e in long.eras if y * sim.DAYS < e["t"] <= (y + 1) * sim.DAYS] for y in range(3)]
    assert all(len(es) >= len(per_year[0]) for es in per_year[1:]), [len(es) for es in per_year]
    churn = long.counters["cancellations"]
    for y in (1, 2):
        es = per_year[y]
        labels = [e["label"] for e in es]
        assert labels[0].startswith("New plans") and es[0]["t"] == y * sim.DAYS + 1
        assert "Price rise announced: +30% in five days" in labels and "New prices apply to every customer" in labels
        rise = next(e["t"] for e in es if e["label"].startswith("Price rise"))
        before = sum(churn[rise - 31:rise - 1]) / 30 / (sum(long.levels["paying"][rise - 32:rise - 2]) / 30)
        during = sum(churn[rise - 1:rise + 4]) / 5 / (sum(long.levels["paying"][rise - 2:rise + 3]) / 5)
        assert during > 3 * before, (y, before, during)                # the announcement still drives churn
        organic = long.counters["organic_visits"][y * sim.DAYS:(y + 1) * sim.DAYS]
        assert max(organic) > 2 * sim.P["organic_per_day"], y         # a viral spike
    assert [e["label"] for e in per_year[1]] != [e["label"] for e in per_year[2]]   # fresh draws every year
