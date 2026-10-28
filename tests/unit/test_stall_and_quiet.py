"""Work that stopped moving, said in the model's terms (orchestra.model.stalled / resumed), and a
machine fallen silent past its own cadence (orchestra.machine.quiet). Neither needs the simulator."""

from datetime import UTC, datetime

from orchestra.config import Config, ConfigError
from orchestra.quiet import QuietWatch
from orchestra.sd.announce import announce
from orchestra.sd.model import Flow, Model, Stock
from orchestra.sd.stall import find
from orchestra.sd.store import ModelStore

T = 1_800_000_000.0
STEP = 60


def model() -> Model:
    return Model("system", "s", time_unit="minute", stocks=[Stock("q", "queue")],
                 flows=[Flow("in", "arrivals", None, "q"), Flow("out", "done", "q", None)])


def history(now: float, out_rate, in_rate=lambda t: 1.0, level=None) -> dict:
    ts = range(int(now) - 3600, int(now) + 1, STEP)
    level = level or (lambda t: 10 + max(0.0, t - (now - 900)) / 60)
    return {"stocks": {"q": [[t, level(t)] for t in ts]},
            "flows": {"in": [[t, in_rate(t)] for t in ts], "out": [[t, out_rate(t)] for t in ts]}}


def drains_until(stop: float):
    return lambda t: 1.0 if t < stop else 0.0


def test_a_stock_rising_with_its_outflow_stopped_is_stalled_and_its_outflow_too():
    now = T
    stalled, judged = find(model(), history(now, drains_until(now - 900)), now, 900, 0.1)
    assert set(stalled) == {"stock:q", "flow:out"} and {"stock:q", "flow:in", "flow:out"} <= judged
    q = stalled["stock:q"]
    assert q["kind"] == "stock" and q["rose_by"] > 0 and q["outflows"] == [{"flow": "out", "rate": 0.0, "usual": 1.0}]
    assert stalled["flow:out"]["usual"] == 1.0 and stalled["flow:out"]["rate"] == 0.0


def test_a_slow_but_moving_outflow_is_not_a_stalled_flow_and_a_draining_stock_is_not_stalled():
    now = T
    slow = lambda t: 1.0 if t < now - 900 else 0.05
    stalled, _ = find(model(), history(now, slow), now, 900, 0.1)
    assert set(stalled) == {"stock:q"}, "below a tenth of its usual rate: the stock is stalled; the flow still moves"
    stalled, _ = find(model(), history(now, lambda t: 1.0), now, 900, 0.1)
    assert stalled == {}


def run(tmp_path, histories):
    store, said = ModelStore.for_state(tmp_path), []
    for now, h in histories:
        announce(store, lambda ty, data, **ext: said.append((ty, ext.get("subject"), data)), model(), now, h,
                 hold=3, gap_s=0.0, after_s=600.0, every_s=300.0, stall_after=900.0, stall_share=0.1, diverge=False)
    return said


def test_a_stall_is_announced_once_with_its_subject_and_its_end_once(tmp_path):
    stop = T
    seq = [(T + 300 * k, history(T + 300 * k, drains_until(stop) if k < 6 else (lambda t: 0.0 if t < T + 1500 else 1.0),
                                 level=(lambda t: 10 + max(0.0, min(t, T + 1500) - stop) / 60) if k < 6 else None))
           for k in range(9)]
    said = run(tmp_path, seq)
    kinds = [(ty, subj) for ty, subj, _ in said]
    assert kinds.count(("orchestra.model.stalled", "stock:q")) == 1
    assert kinds.count(("orchestra.model.stalled", "flow:out")) == 1
    assert ("orchestra.model.resumed", "flow:out") in kinds
    first = next(d for ty, s, d in said if s == "stock:q")
    assert first["era"] is None and "era_start" in first and first["id"] == "q"


def test_a_model_not_saved_announces_nothing(tmp_path):
    m = model()
    m.discovery = {"not_saved": "a source is missing"}
    said = []
    announce(ModelStore.for_state(tmp_path), lambda *a, **k: said.append(a), m, T, history(T, drains_until(T - 900)),
             hold=3, gap_s=0.0, after_s=600.0, every_s=300.0, diverge=False)
    assert said == []


def test_stall_settings():
    c = Config.from_toml('[discovery]\nstall_after = "30m"\nstall_share = 0.2\n')
    assert c.stall_after == 1800.0 and c.stall_share == 0.2
    assert Config.from_toml("").stall_after == 900.0
    try:
        Config.from_toml("[discovery]\nstall_share = 2\n")
        raise AssertionError("a share of 2 is refused")
    except ConfigError:
        pass


def ev(source, t, type="thing.done", **data):
    return {"type": type, "source": source, "time": datetime.fromtimestamp(t, UTC).isoformat(), "data": data}


def test_a_machine_silent_past_its_own_cadence_is_quiet_once_until_heard_again():
    w = QuietWatch()
    for k in range(5):
        w.observe(ev("baker/1", T + 600 * k), now=T + 600 * k)      # a beat every 10 minutes
    last = T + 2400
    assert w.check(now=last + 600) == []                               # within 2.5 beats
    [q] = w.check(now=last + 1600)
    assert q["machine"] == "baker" and q["instance"] == "baker/1" and q["usual_gap"] == 600 and q["quiet_for"] == 1600
    assert w.check(now=last + 3000) == [], "announced once"
    w.observe(ev("baker/1", last + 3100), now=last + 3100)
    assert w.check(now=last + 3200) == []
    assert len(w.check(now=last + 3100 + 1600)) == 1, "heard again, then silent again: announced again"


def test_ad_hoc_machines_the_host_and_machines_quiet_before_the_start_are_not_announced():
    w = QuietWatch()
    for k in range(5):
        w.observe(ev("worker/1", T + 600 * k, "orchestra.machine.started", mode="ad hoc"), now=T + 600 * k)
        w.observe(ev("orchestra-host", T + 600 * k), now=T + 600 * k)
        w.observe(ev("old", T - 90_000 + 600 * k), now=T)
    w.settle(now=T + 2400)
    assert w.check(now=T + 100_000) == []
