import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

from orchestra.bus.file import FileBus
from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.web.core_explore import Explorer, emitter


def _core(tmp_path, key="p1"):
    bus = FileBus(tmp_path / "events.jsonl")
    return SimpleNamespace(project=SimpleNamespace(key=key), metrics=FileMetrics(tmp_path / "metrics.jsonl"),
                           events=SimpleNamespace(bus=bus), _pool=ThreadPoolExecutor(2))


def test_emitter_names_the_machine():
    assert emitter({"type": "order.baked", "source": "baker/2"}) == "baker/2"
    assert emitter({"type": "note_added", "by": "someone"}) == "(no source)"      # before the envelope: not attributed


def test_catalog_and_query_are_scoped_to_the_project(tmp_path):
    core = _core(tmp_path)
    now = time.time()
    core.metrics.write([Point("orchestra_events_total", v, now - 3600 + 600 * i, {"project": "p1", "flow": "a"}) for i, v in enumerate([0, 1, 3, 3, 6])]
                       + [Point("orchestra_events_total", 9, now, {"project": "other", "flow": "a"})])
    ex = Explorer(core)
    cat = ex.catalog()
    assert cat["ok"] and cat["series"] == 1 and cat["points"] == 5
    assert cat["metrics"][0]["labels"]["flow"]["arity"] == 1
    q = ex.query('increase(orchestra_events_total{flow="a"}[1h])', 2)
    assert q["ok"] and q["engine"].startswith("orchestra") and q["lines"][0]["label"] == '{flow="a"}'
    assert max(v for _, v in q["lines"][0]["points"]) == 6.0      # p1's counter only: "other" is not seen
    bad = ex.query("sum(((", 2)
    assert bad["ok"] is False and bad["error"]


def test_events_counts_types_and_emitters(tmp_path):
    core = _core(tmp_path)
    ts = datetime.now(UTC).isoformat()
    for ev in [{"type": "order.baked", "source": "baker/1"}, {"type": "order.baked", "source": "baker/1"}, {"type": "order.placed"}]:
        core.events.bus.append({**ev, "ts": ts})
    d = Explorer(core).events(1)
    assert d["ok"] and d["total"] == 3 and d["in_range"] == 3
    assert {m["machine"]: m["events"] for m in d["machines"]} == {"baker/1": 2, "(no source)": 1}
    assert d["types"][0]["type"] == "order.baked"


def test_a_missing_metrics_store_shows_as_an_error(tmp_path):
    core = _core(tmp_path)
    core.metrics = None
    out = Explorer(core).catalog()
    assert out["ok"] is False and "could not be opened" in out["error"]


def test_emitters_leave_out_instruments_the_host_announced_as_the_machines_page_does(tmp_path):
    from orchestra.web.machines import machines_view

    core = _core(tmp_path)
    ts = datetime.now(UTC).isoformat()
    evs = [{"type": "orchestra.machine.started", "source": "weather", "data": {"collector": "weather", "mode": "scheduled"}},
           {"type": "orchestra.machine.started", "source": "baker/1", "data": {"mode": "continuous"}},
           {"type": "order.baked", "source": "baker/1"}]
    for ev in evs:
        core.events.bus.append({**ev, "time": ts})
    d = Explorer(core).events(1)
    assert {m["machine"] for m in d["machines"]} == {"baker/1"} and d["instruments"] == ["weather"]
    assert d["total"] == 3                                                # still events on the bus, counted by type
    started = next(t for t in d["types"] if t["type"] == "orchestra.machine.started")
    assert started["in_range"] == 2 and [m for m, _ in started["machines"]] == ["baker/1"]
    on_page = {m["id"] for m in machines_view([{**e, "time": ts} for e in evs])["machines"]}
    assert "weather" not in on_page and "baker" in on_page
