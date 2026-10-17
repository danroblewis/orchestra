"""The measured library: a year of circulation, simulated per book, with one place books wait that
nothing counts, the interlibrary delivery van (see sdlab/examples/library/README.md)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

LIBRARY = EXAMPLES / "library"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "library-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("library_sim", LIBRARY / "machines" / "sim.py")
_other = sys.modules.get("sim")              # history.py imports sim by its file name: give it this one
sys.modules["sim"] = sim
history_mod = load("library_history", LIBRARY / "machines" / "history.py")
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
    return json.loads((EXAMPLES / "library.json").read_text())


def program(name: str, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(LIBRARY / "machines" / f"{name}.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=120, cwd=LIBRARY / "machines")


def test_the_model_is_the_measured_stocks_only():
    m = model()
    assert validate(m) == []
    assert [s["id"] for s in m["stocks"]] == sim.MEASURED_STOCKS
    assert {s["unit"] for s in m["stocks"]} == {"books"}, "one unit: a reservation is one book requested"
    assert {s.get("group") for s in m["stocks"]} == {"library"}
    assert not any(s.get("final") for s in m["stocks"])
    assert m["flows"] == [] and m["machines"] == []
    assert m["history"] == {"program": "library/history"} and m["sensors"] == [{"program": "library/live"}]
    assert (m["time_unit"], m["horizon"], m["dt"]) == ("day", 365, 1)
    xs = {s["id"]: s["x"] for s in m["stocks"]}
    assert xs["reservations"] < xs["shelves"] < xs["hold_shelf"] < xs["on_loan"] < xs["return_bin"]


def test_the_description_reveals_no_structure():
    text = json.dumps(model()).lower()
    words = ["van", "interlibrary", "other librar", "transit", "deliver", "reshelv", "21", "28", "weeks", "overdue", "pull", "collect"]
    found = [w for w in words if w in text]
    assert found == [], f"the model gives the structure away: {found}"


def test_the_history_prints_only_what_is_measured(res):
    stdin = json.dumps({"stocks": [{"id": s} for s in [*sim.MEASURED_STOCKS, "van"]],
                        "flows": [{"id": f} for f in ["borrow", "ill_request", "ill_arrive", "bogus"]]})
    p = program("history", stdin)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(list(r["levels"]) == sim.MEASURED_STOCKS for r in rows), "nobody counts the van"
    assert all(set(r["flows"]) == {"borrow"} for r in rows), "nor what goes into or out of it"
    assert [r["flows"]["borrow"] for r in rows] == res.flows["borrow"]
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]
    rows = list(history_mod.lines(res, *history_mod.wanted(json.dumps(model()))))
    assert all("flows" not in r and list(r["levels"]) == sim.MEASURED_STOCKS for r in rows)


def test_import_gives_the_simulated_dashboard(client, res):
    snap = client.post("/api/models/library/live/import").json()
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
    assert run["counters"] == res.flows and set(run["counters"]) == set(sim.FLOWS)
    assert run["start"] == {s: res.start[s] for s in sim.MEASURED_STOCKS}
    assert [(e["start"], e["label"]) for e in run["eras"]] == [(e["t"], e["label"]) for e in res.eras]


def test_every_book_is_somewhere(res):
    """Conservation inside the simulator: every stock, the van included, changes by exactly what its
    true flows moved, and what the dashboard cannot account for is what the van holds."""
    every_book_is_somewhere(res)


def every_book_is_somewhere(res):
    F, L = res.flows, res.levels
    n = len(L["shelves"])
    for s in sim.STOCKS:
        prev = res.start[s]
        for i in range(n):
            d = sum(F[f][i] * ((to == s) - (fr == s)) for f, (fr, to) in sim.FLOWS.items())
            assert L[s][i] - prev == d, (s, i)
            assert L[s][i] >= 0
            prev = L[s][i]
    net_in = [sum(F[f][i] * ((fr is None) - (to is None)) for f, (fr, to) in sim.FLOWS.items()) for i in range(n)]
    total = sum(res.start.values())
    for i in range(n):
        total += net_in[i]
        assert sum(L[s][i] for s in sim.MEASURED_STOCKS) + L["van"][i] == total, i
    assert min(L["van"]) == 0 and sum(L["van"]) / n > 50


def test_the_renovation_and_the_longer_loans_show(res):
    F, L = res.flows, res.levels
    a, b = sim.RENOVATION
    for f in ("borrow", "reshelve", "pickup", "pull", "ill_request", "acquire"):
        assert sum(F[f][a:b]) == 0, f
    assert min(F["return"][a:b]) > 100                         # the book drop stays open
    assert L["return_bin"][b - 1] > 4 * L["return_bin"][a - 1]
    assert L["return_bin"][b + 3] < 1.5 * L["return_bin"][a - 1]   # reshelved within days of reopening
    g = sim.ground_truth(res)
    assert g["loans"]["4_weeks"]["realised_mean_days"] > g["loans"]["3_weeks"]["realised_mean_days"] + 3
    e = sim.EXTENDED_FROM                                      # returns per book on loan fall by a fifth, more stays on loan

    def k(a, b):
        return sum(F["return"][a:b]) / sum(L["on_loan"][a - 1:b - 1])

    assert k(e + 40, sim.RENOVATION[0]) < 0.85 * k(e - 40, e)
    assert max(L["on_loan"][e:e + 60]) > max(L["on_loan"][e - 60:e]) + 500


def test_the_hidden_van_behaves_as_documented(res):
    g = sim.ground_truth(res)
    sd = g["sd_structure"]
    (van,) = sd["hidden"]
    assert (van["from"], van["to"], van["shape"]) == ("reservations", "hold_shelf", "pipe")
    assert 4.9 < van["delay"] < 5.6 and all(4 <= d <= 7 for d in res.van_days)
    assert abs(van["holds"] - van["per_day"] * van["delay"]) < 0.1 * van["holds"]           # Little's law
    assert sd["links"][0]["driver"] == "reservations" and sd["links"][0]["into"] == "hold_shelf"
    k = {(m["from"], m["to"]): m for m in sd["moves"]}
    assert abs(k[("return_bin", "shelves")]["k"] - 0.6 * (1 - 3 / 365 - 7 / 365)) < 0.08
    assert abs(k[("shelves", "on_loan")]["k"] - sim.P["borrow_share"]) < 0.006
    assert 1 / 22 < k[("on_loan", "return_bin")]["k"] < 1 / 17
    assert all(sum(res.flows[f]) > 300 for f in sim.FLOWS)          # every flow carries enough to be seen


def test_truth_json_is_current(res):
    path = LIBRARY / "truth.json"
    assert path.stat().st_size < 1_000_000
    assert json.loads(path.read_text()) == json.loads(json.dumps(sim.ground_truth(res)))


def test_same_seed_same_library(res):
    again = sim.run()
    assert again.levels == res.levels and again.flows == res.flows and again.van_days == res.van_days
    assert sim.run(7).levels != res.levels
    p = program("history")
    assert p.returncode == 0, p.stderr
    assert [json.loads(line) for line in p.stdout.splitlines()] == list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))
    assert program("history", "", "7").stdout != p.stdout


def test_a_live_run_plays_the_same_days_as_the_history(client, res):
    """Start (or Step) reads the dashboard a day per tick: the run is the history, day by day."""
    assert client.post("/api/models/library/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/library/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/library/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid


def test_the_live_sensor_announces_changes_and_ends_with_the_recording(res):
    m = model()

    def live(t):
        return program("live", json.dumps({"t": t, "stocks": m["stocks"], "flows": [{"id": "return"}]}))

    t = sim.RENOVATION[0] + 1
    first = json.loads(live(t).stdout)
    assert first["era"] == "Closed for renovation"
    assert first["levels"]["return_bin"] == res.levels["return_bin"][t - 1]
    assert first["flows"] == {"return": res.flows["return"][t - 1]}
    assert "era" not in json.loads(live(t - 1).stdout)
    end = live(sim.STEPS + 1)
    assert end.returncode != 0 and "recording ends" in end.stderr


def history_rows(stdin: str = "", *args: str) -> list[dict]:
    p = program("history", stdin, *args)
    assert p.returncode == 0, p.stderr
    return [json.loads(line) for line in p.stdout.splitlines()]


def test_measured_is_what_the_history_prints(res):
    m = sim.measured()
    rows = history_rows()
    assert m["t"] == [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert m["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS}
    assert m["eras"] == [{"start": 1, "label": "Start"}] + [{"start": r["t"], "label": r["era"]} for r in rows if "era" in r]
    stdin = json.dumps({"stocks": [{"id": s} for s in sim.MEASURED_STOCKS], "flows": [{"id": f} for f in sim.COUNTERS]})
    assert m["counters"] == {f: [r["flows"][f] for r in history_rows(stdin)] for f in sim.COUNTERS}
    assert not {"van", "ill_request", "ill_arrive"} & {*m["levels"], *m["counters"]}


LONG = 3 * sim.STEPS


@pytest.fixture(scope="module")
def long_res():
    return sim.run(steps=LONG)


def test_a_long_run_repeats_the_calendar(res, long_res):
    every_book_is_somewhere(long_res)
    assert all(long_res.levels[s][:sim.STEPS] == res.levels[s] for s in sim.STOCKS), "the first year is the default run"
    assert long_res.eras[:len(res.eras)] == res.eras
    per_year = [[e for e in long_res.eras if y * sim.DAYS < e["t"] <= (y + 1) * sim.DAYS] for y in range(3)]
    assert len(per_year[1]) >= len(per_year[0]) and len(per_year[2]) >= len(per_year[0])
    assert [e["label"] for e in per_year[1]][:2] == ["Loan period back to 3 weeks", "Loan period extended to 4 weeks"]
    F = long_res.flows
    for y in (1, 2):
        a, b = y * sim.DAYS + sim.RENOVATION[0], y * sim.DAYS + sim.RENOVATION[1]
        assert sum(F["borrow"][a:b]) == sum(F["reshelve"][a:b]) == 0 and min(F["return"][a:b]) > 100   # closed every year
        assert sim.loan_days(y * sim.DAYS) == 21 and sim.loan_days(y * sim.DAYS + sim.EXTENDED_FROM) == 28
    assert long_res.levels["shelves"][sim.DAYS:2 * sim.DAYS] != long_res.levels["shelves"][2 * sim.DAYS:]   # fresh draws
    assert len(long_res.loan_lengths["21"]) > 2 * len(res.loan_lengths["21"])
    assert sim.LONG_STEPS >= 5 * sim.STEPS


def test_long_runs_are_deterministic(long_res):
    again = sim.run(steps=LONG)
    assert again.levels == long_res.levels and again.flows == long_res.flows and again.eras == long_res.eras
    assert sim.run(7, LONG).levels != long_res.levels
    m = sim.measured(steps=LONG)
    assert m["levels"] == {s: long_res.levels[s] for s in sim.MEASURED_STOCKS}
    rows = history_rows("", str(sim.SEED), str(LONG))
    assert m["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS}
    assert m["eras"][1:] == [{"start": r["t"], "label": r["era"]} for r in rows if "era" in r]
