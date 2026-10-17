"""The measured web shop: 30 services, 6 queues and 6 worker pools, simulated per request with a
known call graph that the model is never told (see sdlab/examples/shop/README.md)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdlab.server import EXAMPLES, create_app, validate

SHOP = EXAMPLES / "shop"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "shop-run.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sim = load("shop_sim", SHOP / "machines" / "sim.py")
sys.path.insert(0, str(SHOP / "machines"))   # history.py imports sim by its file name:
sys.modules.pop("sim", None)                   # not another example's sim imported before it,
history_mod = load("shop_history", SHOP / "machines" / "history.py")
sys.modules.pop("sim", None)                   # nor this one for the examples after it
sys.path.remove(str(SHOP / "machines"))


@pytest.fixture(scope="module")
def res():
    return sim.cached()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLAB_HOME", str(tmp_path))
    return TestClient(create_app())


def model() -> dict:
    return json.loads((EXAMPLES / "shop.json").read_text())


def program(name: str, stdin: str = "", *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SHOP / "machines" / f"{name}.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=120, cwd=SHOP / "machines")


def test_the_model_is_the_measured_stocks_only():
    m = model()
    assert validate(m) == []
    assert [s["id"] for s in m["stocks"]] and {s["id"] for s in m["stocks"]} == set(sim.MEASURED_STOCKS)
    assert len(sim.SERVICES) == 30 and len(sim.QUEUES) == 6 and len(sim.POOLS) == 6
    units = {s["id"]: s["unit"] for s in m["stocks"]}
    assert all(units[s] == "requests" for s in sim.SERVICES)
    # a worker's job is the message it took off the queue: same unit, so discovery can find the
    # one-for-one flow from a queue into its pool
    assert all(units[q] == "messages" for q in sim.QUEUES) and all(units[p] == "messages" for p in sim.POOLS)
    assert {s.get("group") for s in m["stocks"]} == {"shop"}, "one group: discovery may relate any two stocks"
    assert not any(s.get("final") for s in m["stocks"])
    assert m["flows"] == [] and m["machines"] == []
    assert m["history"] == {"program": "shop/history"} and m["sensors"] == [{"program": "shop/live"}]
    assert (m["time_unit"], m["horizon"], m["dt"]) == ("second", 300, 1)
    xs = {s["id"]: s["x"] for s in m["stocks"]}
    assert max(xs[s] for s in sim.SERVICES) < min(xs[q] for q in sim.QUEUES)
    assert max(xs[q] for q in sim.QUEUES) < min(xs[p] for p in sim.POOLS)
    assert all(xs[e] <= xs["api_gateway"] < xs["checkout"] < xs["payment"] < xs["fraud_check"] for e in ("web_frontend", "mobile_api"))


def test_the_description_names_no_edges():
    text = model()["description"].lower()
    names = [n for n, *_ in sim.SERVICES.values()] + list(sim.QUEUES.values()) + [v[0] for v in sim.POOLS.values()]
    named = [n for n in names + list(sim.MEASURED_STOCKS) if n.lower() in text]
    assert named == [], f"the description gives away who is who: {named}"


def test_the_history_prints_only_what_is_measured(res):
    stdin = json.dumps({"stocks": [{"id": s} for s in [*sim.MEASURED_STOCKS[:5], "secret"]],
                        "flows": [{"id": f} for f in ["calls__checkout__payment", "consumed__order_placed", "bogus"]]})
    p = program("history", stdin)
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert all(list(r["levels"]) == sim.MEASURED_STOCKS[:5] for r in rows)
    assert all(set(r["flows"]) == {"calls__checkout__payment", "consumed__order_placed"} for r in rows)
    assert [r["flows"]["calls__checkout__payment"] for r in rows] == res.counters["calls__checkout__payment"]
    assert [r["levels"]["web_frontend"] for r in rows] == res.levels["web_frontend"]
    assert [(r["t"], r["era"]) for r in rows if "era" in r] == [(e["t"], e["label"]) for e in res.eras[1:]]
    # the example model itself has no flows: levels only, every stock
    rows = list(history_mod.lines(res, *history_mod.wanted(json.dumps(model()))))
    assert all("flows" not in r and set(r["levels"]) == set(sim.MEASURED_STOCKS) for r in rows)


def test_import_gives_the_simulated_dashboard(client, res):
    snap = client.post("/api/models/shop/live/import").json()
    s = snap["series"]
    assert s["t"] == list(range(1, sim.STEPS + 1))
    assert set(s["levels"]) == set(sim.MEASURED_STOCKS)
    for sid in sim.MEASURED_STOCKS:
        assert s["levels"][sid] == res.levels[sid], sid
    assert s["rates"] == {}
    assert [(e["start"], e["label"]) for e in snap["eras"]] == [(e["t"], e["label"]) for e in res.eras]


def test_the_fixture_is_the_imported_run(res):
    assert FIXTURE.stat().st_size < 15_000_000
    run = json.loads(FIXTURE.read_text())
    assert run["t"] == list(range(1, sim.STEPS + 1))
    assert run["levels"] == {sid: res.levels[sid] for sid in sim.MEASURED_STOCKS}
    assert run["rates"] == {}
    assert run["counters"] == res.counters and set(run["counters"]) == set(sim.COUNTERS)
    assert [(e["start"], e["label"]) for e in run["eras"]] == [(e["t"], e["label"]) for e in res.eras]


def test_every_request_and_message_is_accounted_for(res):
    accounted(res)


def accounted(res):
    """Conservation inside the simulator: every stock changes by exactly what arrived minus what left."""
    C, L = res.counters, res.levels
    n = len(L["web_frontend"])

    def check(stock, ins, outs):
        prev = 0
        for i in range(n):
            assert L[stock][i] - prev == sum(c[i] for c in ins) - sum(c[i] for c in outs), (stock, i)
            assert L[stock][i] >= 0
            prev = L[stock][i]

    for s in sim.SERVICES:
        ins = [C[f"calls__{a}__{b}"] for a, b, _ in sim.CALLS if b == s]
        ins += [C[f"calls__{p}__{x}"] for p, v in sim.POOLS.items() for x, _ in v[4] if x == s]
        ins += [C[f"external__{s}"]] if s in sim.EDGE else []
        assert ins, f"{s} gets no traffic"
        check(s, ins, [C[f"handled__{s}"]])
    for q in sim.QUEUES:
        edges = [C[f"produced__{p}__{qq}"] for p, qq, _ in sim.PRODUCES if qq == q]
        assert edges and [sum(x) for x in zip(*edges)] == C[f"produced__{q}"]
        check(q, edges, [C[f"consumed__{q}"]])
    for p, (_, q, *_rest) in sim.POOLS.items():
        check(p, [C[f"consumed__{q}"]], [C[f"done__{p}"]])
        biggest = max(sz[p] for _, sz, _ in sim.SCALING if p in sz)
        assert max(L[p]) <= biggest
    total_in = sum(map(sum, (C[f"external__{e}"] for e in sim.EDGE))) + sum(sum(C[f"calls__{a}__{b}"]) for a, b, _ in sim.CALLS) \
        + sum(sum(C[f"calls__{p}__{s}"]) for p, v in sim.POOLS.items() for s, _ in v[4])
    assert total_in == res.requests == sum(sum(C[f"handled__{s}"]) + L[s][-1] for s in sim.SERVICES)
    assert res.messages == sum(sum(C[f"produced__{q}"]) for q in sim.QUEUES)


def test_the_outage_builds_a_backlog_that_drains_at_full_speed(res):
    q, p = "email_requested", "email_workers"
    a, b = sim.OUTAGE["from"], sim.OUTAGE["to"]
    assert sim.OUTAGE["pool"] == p
    lag, consumed = res.levels[q], res.counters[f"consumed__{q}"]
    assert sum(consumed[a:b]) == 0 and res.levels[p][a + 30] == 0     # nobody works (in-flight jobs finish first)
    assert lag[a] < 50 and lag[b - 1] > 3000
    drain = consumed[b + 10:b + 300]
    assert abs(sum(drain) / len(drain) - 12 / sim.POOLS[p][2]) < 1.0    # 12 workers, 1 s jobs: ~12 a second
    assert lag[b + 700] < 50                                          # drained in about ten minutes


def test_the_graph_is_what_the_truth_says(res):
    g = sim.ground_truth(res)
    sd = g["sd_structure"]
    assert len(sim.topo_order()) == len(sim.MEASURED_STOCKS)          # acyclic
    assert len(sd["driven_inflows"]) == len(sim.CALLS) + g["sizes"]["worker_calls"] + len(sim.PRODUCES)
    assert sorted((f["from"], f["to"]) for f in sd["flows"] if f["to"]) == sorted((v[1], p) for p, v in sim.POOLS.items())
    assert {f["from"] for f in sd["flows"] if f["to"] is None} == set(sim.SERVICES) | set(sim.POOLS)
    for x in sd["driven_inflows"]:                                     # Little's law: realised k is the nominal one
        if x["driver"] not in ("payment", "recommendations", "image_service"):    # these queue in the flash sale
            assert abs(x["k_realised"] - x["k_nominal"]) < 0.06 * x["k_nominal"] + 0.01, x
    for s in sim.SERVICES:                                             # nothing sits idle at zero all the time
        assert sum(res.levels[s]) / sim.STEPS > 0.5, s


def test_truth_json_is_current(res):
    path = SHOP / "truth.json"
    assert path.stat().st_size < 1_000_000
    assert json.loads(path.read_text()) == json.loads(json.dumps(sim.ground_truth(res)))


def test_same_seed_same_shop(res):
    again = sim.run()
    assert again.levels == res.levels and again.counters == res.counters
    assert sim.run(7).levels != res.levels
    p = program("history")
    assert p.returncode == 0, p.stderr
    rows = [json.loads(line) for line in p.stdout.splitlines()]
    assert rows == list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))
    assert sim.measured()["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS}


def test_a_live_run_plays_the_same_seconds_as_the_history(client, res):
    """Start (or Step) reads the dashboard a second per tick: the run is the history, second by second."""
    assert client.post("/api/models/shop/live/reset").status_code == 200
    for _ in range(3):
        snap = client.post("/api/models/shop/live/step").json()
    assert not snap["errors"], snap["errors"]
    L = client.get("/api/models/shop/live?since=0").json()["series"]
    for sid in sim.MEASURED_STOCKS:
        assert L["levels"][sid] == res.levels[sid][:3], sid


def test_the_live_sensor_announces_scaling_and_ends_with_the_recording(res):
    m = model()

    def live(t):
        return program("live", json.dumps({"t": t, "stocks": m["stocks"], "flows": [{"id": "done__email_workers"}]}))

    first = json.loads(live(4801).stdout)
    assert first["era"] == "email-workers outage (0 workers)"
    assert first["levels"]["email_requested"] == res.levels["email_requested"][4800]
    assert first["flows"] == {"done__email_workers": res.counters["done__email_workers"][4800]}
    assert "era" not in json.loads(live(4800).stdout)
    end = live(sim.STEPS + 1)
    assert end.returncode != 0 and "recording ends" in end.stderr


def test_measured_is_what_the_history_prints(res):
    rows = list(history_mod.lines(res, list(sim.MEASURED_STOCKS), []))       # what the program prints (test_same_seed_same_shop)
    m = sim.measured()
    assert m["t"] == [r["t"] for r in rows] == list(range(1, sim.STEPS + 1))
    assert m["levels"] == {s: [r["levels"][s] for r in rows] for s in sim.MEASURED_STOCKS}
    assert m["eras"][0]["start"] == 1 and m["eras"][1:] == [{"start": r["t"], "label": r["era"]} for r in rows if "era" in r]
    assert m["counters"] == res.counters                     # what the live feed can print as measured flows


@pytest.fixture(scope="module")
def long():
    return sim.run(steps=3 * sim.STEPS)


def test_a_long_run_starts_with_the_default_run_and_keeps_every_request(long, res):
    n = 3 * sim.STEPS
    assert all(len(v) == n for v in long.levels.values()) and all(len(v) == n for v in long.counters.values())
    assert {s: v[:sim.STEPS] for s, v in long.levels.items()} == res.levels
    accounted(long)
    for c in sim.COUNTERS:                                   # every edge keeps carrying traffic on the third day
        assert sum(long.counters[c][2 * sim.STEPS:]) > 0, c


def test_a_long_run_keeps_its_days_coming(long):
    first = [e for e in long.eras if e["t"] <= sim.STEPS]
    for k in (1, 2):
        eras = [e for e in long.eras if k * sim.STEPS < e["t"] <= (k + 1) * sim.STEPS]
        assert len(eras) >= len(first), k
        assert eras[0] == {"t": k * sim.STEPS + 1, "label": sim.NEW_DAY}
        assert [e["label"] for e in eras[1:]] == [e["label"] for e in first[1:]]
        day = long.days[k]
        a, b = day["outage"]["from"], day["outage"]["to"]          # the outage comes back, and drains
        q = "email_requested"
        assert sum(long.counters[f"consumed__{q}"][a:b]) == 0 and long.levels[q][b - 1] > 2000
        assert long.levels[q][min(b + 900, (k + 1) * sim.STEPS - 1)] < 100
        f0, f1, _ = day["flash_sale"]                                # the flash sale doubles web traffic
        before = sum(long.counters["external__web_frontend"][f0 - 600:f0 - 300])
        assert sum(long.counters["external__web_frontend"][f0 + 60:f0 + 360]) > 1.6 * before
    assert [e["t"] - sim.STEPS for e in long.eras[6:12]] != [e["t"] for e in long.eras[:6]], "a new day moves its events"


def test_a_long_run_is_deterministic():
    n = sim.STEPS + 900
    again = sim.run(steps=n)
    assert sim.measured(steps=n) == {"t": list(range(1, n + 1)), "levels": again.levels,
                                     "eras": [{"start": e["t"], "label": e["label"]} for e in again.eras],
                                     "counters": again.counters}
    assert [e["label"] for e in again.eras][-1] == sim.NEW_DAY
