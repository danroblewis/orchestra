"""The measured kanban board: a software team's six columns are measured; how cards move, the
rework, and the defects that come back as bugs weeks later are hidden (see
sdlab/examples/kanban/README.md)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

BOARD = EXAMPLES / "kanban"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "kanban-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("kanban_sim", BOARD / "machines" / "sim.py")
sys.path.insert(0, str(BOARD / "machines"))   # history.py imports sim by its file name:
sys.modules.pop("sim", None)                    # not another example's sim imported before it,
history_mod = load("kanban_history", BOARD / "machines" / "history.py")
sys.modules.pop("sim", None)                    # nor this one for the examples after it
sys.path.remove(str(BOARD / "machines"))


@pytest.fixture(scope="module")
def res():
    return sim.cached()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def model() -> dict:
    return json.loads((EXAMPLES / "kanban.json").read_text())


def program(name: str, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(BOARD / "machines" / f"{name}.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=120, cwd=BOARD / "machines")


def test_the_model_is_the_measured_stocks_only():
    m = model()
    assert validate(m) == []
    assert [s["id"] for s in m["stocks"]] == sim.MEASURED_STOCKS
    assert {s["unit"] for s in m["stocks"]} == {"cards"}
    assert [s["id"] for s in m["stocks"] if s.get("final")] == ["done"], "nothing leaves Done"
    assert all("group" not in s for s in m["stocks"])
    assert m["flows"] == [] and m["machines"] == []
    assert m["history"] == {"program": "kanban/history"} and m["sensors"] == [{"program": "kanban/live"}]
    assert (m["time_unit"], m["horizon"], m["dt"]) == ("day", 60, 1)
    xs = {s["id"]: s["x"] for s in m["stocks"]}
    assert xs["backlog"] < xs["dev"] < xs["review"] < xs["testing"] < xs["done"]


def test_the_description_reveals_no_structure():
    text = model()["description"].lower()
    for w in ("defect", "rework", "reject", "triage", "wip", "limit", "week later", "weeks later", "echo", "back to", "hidden", "noticed", "%"):
        assert w not in text, f"the description gives away {w!r}"


def test_the_history_prints_only_what_is_measured(res):
    stdin = json.dumps({"stocks": [{"id": s} for s in ["backlog", "bugs", "defects"]],
                        "flows": [{"id": f} for f in ["rejected", "reported", "bogus"]]})
    p = program("history", stdin)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(list(r["levels"]) == ["backlog", "bugs"] for r in rows)
    assert all(set(r["flows"]) == {"rejected", "reported"} for r in rows)
    assert [r["flows"]["rejected"] for r in rows] == res.counters["rejected"]
    assert [r["levels"]["bugs"] for r in rows] == res.levels["bugs"]
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]
    rows = list(history_mod.lines(res, *history_mod.wanted(json.dumps(model()))))
    assert all("flows" not in r and set(r["levels"]) == set(sim.MEASURED_STOCKS) for r in rows)


def test_import_gives_the_simulated_board(client, res):
    snap = client.post("/api/models/kanban/live/import").json()
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


def test_every_card_is_accounted_for(res):
    """Conservation inside the simulator: every column changes by exactly what its true flows
    moved, every card planned or reported is on the board, and every defect shipped is either
    reported or still unnoticed."""
    every_card_is_accounted_for(res)


def every_card_is_accounted_for(res):
    C, L = res.counters, res.levels
    n = len(L["backlog"])
    for s in sim.STOCKS:
        prev = 0
        for i in range(n):
            d = sum(C[f][i] * ((to == s) - (fr == s)) for f, (fr, to) in sim.FLOWS.items())
            assert L[s][i] - prev == d, (s, i)
            assert L[s][i] >= 0
            prev = L[s][i]
    made = 0
    for i in range(n):
        made += C["planned"][i] + C["reported"][i]
        assert sum(L[s][i] for s in sim.MEASURED_STOCKS) == made
    assert res.cards == sum(C["planned"]) + sum(C["reported"])
    assert all(sim.P["defect_days"][0] <= d <= sim.P["defect_days"][1] for d in res.defect_delays)


def test_the_eras_do_what_they_say(res):
    C, L = res.counters, res.levels
    freeze = range(141, 148)
    assert all(C["released"][d - 1] == 0 for d in freeze) and C["released"][147] > 20     # held, then let go at once
    assert max(L["testing"][d - 1] for d in freeze) > 2 * max(L["testing"][120:139])
    assert max(L["review"]) == sim.P["review_wip"]
    full = sum(1 for x in L["dev"][:91] if x >= 15 * sim.P["dev_wip_per_dev"])     # (rework and bugs may go over it)
    assert full > 20                                                                     # the WIP limit binds before the hiring
    assert max(L["backlog"][80:92]) > 1.5 * max(L["backlog"][150:])                      # and the backlog drains after it
    sprints = [d for d in range(sim.STEPS) if C["planned"][d]]
    assert sprints == list(range(0, sim.STEPS, 14))


def test_truth_json_is_current(res):
    path = BOARD / "truth.json"
    assert path.stat().st_size < 1_000_000
    truth = json.loads(path.read_text())
    assert truth == json.loads(json.dumps(sim.ground_truth(res)))
    sd = truth["sd_structure"]
    assert set(sd) >= {"moves", "outside", "links", "hidden", "echoes"}
    assert sorted((m["from"], m["to"]) for m in sd["moves"]) == sorted(
        [("backlog", "dev"), ("dev", "review"), ("review", "testing"), ("testing", "done"), ("testing", "dev"), ("bugs", "dev")])
    (echo,) = sd["echoes"]
    assert (echo["source"], echo["into"], echo["delay"]) == ("done", "bugs", 14)
    assert abs(echo["share_realised"] - sim.P["p_defect"]) < 0.04 and abs(echo["realised_delay"] - 14) < 1.5
    rate = sum(res.counters["reported"]) / sim.STEPS                  # Little's law for the unnoticed defects
    assert abs(echo["holds"] - rate * 14) < 0.25 * echo["holds"]


def test_same_seed_same_board(res):
    again = sim.run()
    assert again.levels == res.levels and again.counters == res.counters
    assert sim.run(7).levels != res.levels
    p = program("history")
    assert p.returncode == 0, p.stderr
    assert [json.loads(line) for line in p.stdout.splitlines()] == list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))
    assert program("history", "", "7").stdout != p.stdout


def test_a_live_run_plays_the_same_days_as_the_history(client, res):
    """Start (or Step) reads the board a day per tick: the run is the history, day by day."""
    assert client.post("/api/models/kanban/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/kanban/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/kanban/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid


def test_the_live_sensor_announces_the_hiring_and_ends_with_the_recording(res):
    m = model()

    def live(t):
        return program("live", json.dumps({"t": t, "stocks": m["stocks"], "flows": [{"id": "pulled"}]}))

    first = json.loads(live(92).stdout)
    assert first["era"] == sim.ERAS[1][3]
    assert first["levels"]["dev"] == res.levels["dev"][91]
    assert first["flows"] == {"pulled": res.counters["pulled"][91]}
    assert "era" not in json.loads(live(91).stdout)
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
    assert "defects" not in m["levels"]


LONG = 3 * sim.STEPS


@pytest.fixture(scope="module")
def long_res():
    return sim.run(steps=LONG)


def test_a_long_run_repeats_the_half_year(res, long_res):
    every_card_is_accounted_for(long_res)
    assert all(long_res.levels[s][:sim.STEPS] == res.levels[s] for s in sim.STOCKS), "the first half-year is the default run"
    assert long_res.eras[:len(res.eras)] == res.eras
    P = sim.PERIOD
    per = [[e for e in long_res.eras if k * P < e["t"] <= (k + 1) * P] for k in range(3)]
    assert len(per[1]) >= len(per[0]) and len(per[2]) >= len(per[0])
    assert per[1][0] == {"t": P + 1, "label": "Nine developers leave (15 developers)"}
    C = long_res.counters
    for k in (1, 2):
        freeze = range(k * P + 141, k * P + 148)
        assert all(C["released"][d - 1] == 0 for d in freeze) and C["released"][k * P + 147] > 20
        assert sim.config(k * P + 1) == (15, False) and sim.config(k * P + 92) == (24, False)
    sprints = [d for d in range(LONG) if C["planned"][d]]
    assert sprints == list(range(0, LONG, 14))
    assert long_res.levels["backlog"][P:2 * P] != long_res.levels["backlog"][2 * P:]   # fresh draws
    assert sim.LONG_STEPS >= 5 * sim.STEPS


def test_long_runs_are_deterministic(long_res):
    again = sim.run(steps=LONG)
    assert again.levels == long_res.levels and again.counters == long_res.counters and again.eras == long_res.eras
    assert sim.run(7, LONG).levels != long_res.levels
    m = sim.measured(steps=LONG)
    rows = history_rows("", str(sim.SEED), str(LONG))
    assert m["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS}
    assert m["eras"][1:] == [{"start": r["t"], "label": r["era"]} for r in rows if "era" in r]
