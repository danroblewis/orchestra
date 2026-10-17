"""The measured beer game: four tiers whose books (inventory, cases owed) are measured, with the
trucks, the brewing tanks and the ordering rule hidden (see sdlab/examples/beergame/README.md)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

GAME = EXAMPLES / "beergame"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "beergame-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("beergame_sim", GAME / "machines" / "sim.py")
sys.path.insert(0, str(GAME / "machines"))   # history.py imports sim by its file name:
sys.modules.pop("sim", None)                    # not another example's sim imported before it,
history_mod = load("beergame_history", GAME / "machines" / "history.py")
sys.modules.pop("sim", None)                    # nor this one for the examples after it
sys.path.remove(str(GAME / "machines"))


@pytest.fixture(scope="module")
def res():
    return sim.cached()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def model() -> dict:
    return json.loads((EXAMPLES / "beergame.json").read_text())


def program(name: str, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GAME / "machines" / f"{name}.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=120, cwd=GAME / "machines")


def test_the_model_is_the_measured_stocks_only():
    m = model()
    assert validate(m) == []
    assert {s["id"] for s in m["stocks"]} == set(sim.MEASURED_STOCKS) and len(m["stocks"]) == 8
    units = {s["id"]: s["unit"] for s in m["stocks"]}
    assert all(units[f"inv_{t}"] == "cases" for t in sim.TIERS)
    assert all(units[f"backlog_{t}"] == "cases owed" for t in sim.TIERS), "an order owed is not a case in a warehouse"
    assert all("group" not in s and not s.get("final") for s in m["stocks"])
    assert m["flows"] == [] and m["machines"] == []
    assert m["history"] == {"program": "beergame/history"} and m["sensors"] == [{"program": "beergame/live"}]
    assert (m["time_unit"], m["horizon"], m["dt"]) == ("day", 60, 1)
    xs = {s["id"]: s["x"] for s in m["stocks"]}
    for k in ("inv", "backlog"):                     # beer flows left to right: brewery first
        assert xs[f"{k}_brewery"] < xs[f"{k}_distributor"] < xs[f"{k}_wholesaler"] < xs[f"{k}_retailer"]


def test_the_description_reveals_no_structure():
    text = model()["description"].lower()
    for w in ("truck", "transit", "ship", "lead time", "delay", "anchor", "supply line", "pipe", "brew for", "days", "tank", "mail", "100"):
        assert w not in text, f"the description gives away {w!r}"


def test_the_history_prints_only_what_is_measured(res):
    stdin = json.dumps({"stocks": [{"id": s} for s in ["inv_retailer", "backlog_brewery", "transit_retailer"]],
                        "flows": [{"id": f} for f in ["shipped__wholesaler", "customer_orders", "bogus"]]})
    p = program("history", stdin)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(list(r["levels"]) == ["inv_retailer", "backlog_brewery"] for r in rows)
    assert all(set(r["flows"]) == {"shipped__wholesaler", "customer_orders"} for r in rows)
    assert [r["flows"]["shipped__wholesaler"] for r in rows] == res.counters["shipped__wholesaler"]
    assert [r["levels"]["inv_retailer"] for r in rows] == res.levels["inv_retailer"]
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]
    # the example model itself has no flows: levels only, every measured stock, nothing hidden
    rows = list(history_mod.lines(res, *history_mod.wanted(json.dumps(model()))))
    assert all("flows" not in r and set(r["levels"]) == set(sim.MEASURED_STOCKS) for r in rows)


def test_import_gives_the_simulated_books(client, res):
    snap = client.post("/api/models/beergame/live/import").json()
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


def test_every_case_is_accounted_for(res):
    """Conservation inside the simulator: every stock changes by exactly what came in minus what
    went out, and every case brewed is in a warehouse, a truck or sold."""
    every_case_is_accounted_for(res)


def every_case_is_accounted_for(res):
    C, L = res.counters, res.levels
    n = len(L["inv_retailer"])

    def check(stock, ins, outs):
        prev = res.start[stock]
        for i in range(n):
            assert L[stock][i] - prev == sum(c[i] for c in ins) - sum(c[i] for c in outs), (stock, i)
            assert L[stock][i] >= 0
            prev = L[stock][i]

    for t in sim.TIERS:
        check(f"inv_{t}", [C[f"received__{t}"]], [C[f"shipped__{t}"]])
        check(f"backlog_{t}", [C[f"orders_in__{t}"]], [C[f"shipped__{t}"]])
    for below, up in sim.UPSTREAM.items():
        check(f"transit_{below}", [C[f"shipped__{up}"]], [C[f"received__{below}"]])
        assert C[f"orders_in__{up}"][1:] == C[f"ordered__{below}"][:-1], "orders take a day in the mail"
        d = sim.SHIP_DAYS[up]
        assert C[f"received__{below}"][d:] == C[f"shipped__{up}"][:-d], "a truck takes exactly its days"
    check("brewing", [C["brewed"]], [C["produced"]])
    assert C["produced"][sim.BREW_DAYS:] == C["brewed"][:-sim.BREW_DAYS]
    assert C["orders_in__retailer"] == C["customer_orders"]
    stock_now = lambda i: sum(L[s][i] for s in [f"inv_{t}" for t in sim.TIERS] + ["transit_retailer", "transit_wholesaler", "transit_distributor", "brewing"])  # noqa: E731
    start = sum(res.start[s] for s in res.start if not s.startswith("backlog_") and s != "mail")
    brewed = sold = 0
    for i in range(n):
        brewed, sold = brewed + C["brewed"][i], sold + C["shipped__retailer"][i]
        assert stock_now(i) == start + brewed - sold
    assert all(b <= sim.capacity(i + 1) for i, b in enumerate(C["brewed"]))


def test_the_bullwhip_is_there(res):
    """Orders swing more the further up the chain (the point of the game), after the demand step."""
    import statistics as st
    after = slice(sim.P["step_day"], sim.STEPS)
    sd = [st.pstdev(res.counters[f"ordered__{t}"][after]) for t in sim.TIERS]
    assert st.pstdev(res.counters["customer_orders"][after]) < sd[0] < sd[1] < sd[2] < sd[3]
    for t in sim.TIERS[1:]:                          # every upstream tier runs out of stock at some point
        assert min(res.levels[f"inv_{t}"]) == 0
    assert max(res.levels["backlog_brewery"]) > 250


def test_truth_json_is_current(res):
    path = GAME / "truth.json"
    assert path.stat().st_size < 1_000_000
    truth = json.loads(path.read_text())
    assert truth == json.loads(json.dumps(sim.ground_truth(res)))
    sd = truth["sd_structure"]
    assert set(sd) >= {"moves", "outside", "links", "hidden", "echoes"}
    assert [(h["from"], h["to"], h["shape"], h["delay"]) for h in sd["hidden"]] == [
        ("inv_wholesaler", "inv_retailer", "pipe", 2), ("inv_distributor", "inv_wholesaler", "pipe", 3), ("inv_brewery", "inv_distributor", "pipe", 4)]
    for h in sd["hidden"]:                           # Little's law: what a truck holds is rate x delay
        rate = sum(res.counters[f"received__{h['to'][4:]}"]) / sim.STEPS
        assert abs(h["holds"] - rate * h["delay"]) < 0.05 * h["holds"], h


def test_same_seed_same_game(res):
    again = sim.run()
    assert again.levels == res.levels and again.counters == res.counters
    assert sim.run(7).levels != res.levels
    p = program("history")
    assert p.returncode == 0, p.stderr
    assert [json.loads(line) for line in p.stdout.splitlines()] == list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))
    assert program("history", "", "7").stdout != p.stdout


def test_a_live_run_plays_the_same_days_as_the_history(client, res):
    """Start (or Step) reads the books a day per tick: the run is the history, day by day."""
    assert client.post("/api/models/beergame/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/beergame/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/beergame/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid


def test_the_live_sensor_announces_the_maintenance_and_ends_with_the_recording(res):
    m = model()

    def live(t):
        return program("live", json.dumps({"t": t, "stocks": m["stocks"], "flows": [{"id": "brewed"}]}))

    first = json.loads(live(200).stdout)
    assert first["era"] == sim.CAPACITY[1][2]
    assert first["levels"]["backlog_brewery"] == res.levels["backlog_brewery"][199]
    assert first["flows"] == {"brewed": res.counters["brewed"][199]}
    assert "era" not in json.loads(live(199).stdout)
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


LONG = 3 * sim.STEPS


@pytest.fixture(scope="module")
def long_res():
    return sim.run(steps=LONG)


def test_a_long_run_repeats_the_year(res, long_res):
    every_case_is_accounted_for(long_res)
    assert all(long_res.levels[s][:sim.STEPS] == res.levels[s] for s in long_res.levels), "the first year is the default run"
    assert long_res.eras[:len(res.eras)] == res.eras
    per_year = [[e for e in long_res.eras if y * sim.YEAR < e["t"] <= (y + 1) * sim.YEAR] for y in range(3)]
    assert len(per_year[1]) >= len(per_year[0]) and len(per_year[2]) >= len(per_year[0])
    C, Y = long_res.counters, sim.YEAR

    def mean_orders(a, b):
        return sum(C["customer_orders"][a - 1:b - 1]) / (b - a)

    assert 55 < mean_orders(Y + 10, Y + 100) and mean_orders(Y + 110, Y + 240) < 45       # year 2: 60, then a slump to 40
    assert mean_orders(2 * Y + 10, 2 * Y + 100) < 45 < 55 < mean_orders(2 * Y + 110, 2 * Y + 240)   # year 3: 40, then 60
    assert mean_orders(Y + 240, Y + 254) > 1.3 * mean_orders(Y + 200, Y + 240)               # the promotion comes back
    for y in (1, 2):
        for a, b in ((60, 74), (200, 214)):
            assert max(C["brewed"][y * Y + a - 1:y * Y + b - 1]) <= 40                         # maintenance twice a year
    assert long_res.levels["inv_retailer"][Y:2 * Y] != long_res.levels["inv_retailer"][2 * Y:]   # fresh draws
    assert sim.LONG_STEPS >= 5 * sim.STEPS


def test_long_runs_are_deterministic(long_res):
    again = sim.run(steps=LONG)
    assert again.levels == long_res.levels and again.counters == long_res.counters and again.eras == long_res.eras
    assert sim.run(7, LONG).levels != long_res.levels
    m = sim.measured(steps=LONG)
    rows = history_rows("", str(sim.SEED), str(LONG))
    assert m["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS}
    assert m["eras"][1:] == [{"start": r["t"], "label": r["era"]} for r in rows if "era" in r]
