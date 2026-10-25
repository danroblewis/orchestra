"""Discovery strategies: Orchestra's conservation step, and SD Lab's strategies behind it."""

import pytest
from test_discover import simulate  # pytest puts this folder on the path

from orchestra.metrics.file import FileMetrics
from orchestra.sd.strategies import (
    CONSERVATION,
    _reads,
    _scale,
    available,
    discover_with,
    sd_installed,
)


def test_rates_per_step_become_rates_per_time_unit():
    f = 2.0                                     # 30 s steps, per minute
    assert _scale({"form": "constant", "value": 3}, f)["value"] == 6
    assert _scale({"form": "proportional", "stock": "s", "k": 0.1}, f)["k"] == 0.2
    lin = _scale({"form": "linear", "c": 1, "terms": [{"stock": "a", "k": 0.5}]}, f)
    assert lin["c"] == 2 and lin["terms"][0]["k"] == 1.0
    assert _scale({"form": "gap", "stock": "s", "goal": 10, "time": 4}, f)["time"] == 2


def test_what_a_rate_reads():
    rate = {"form": "linear", "c": 0, "terms": [{"stock": "a", "k": 1}, {"stock": "b", "k": -1}],
            "effects": [{"stock": "c", "shape": "linear"}, {"stock": "a"}]}
    assert _reads(rate) == ["a", "b", "c"]


def test_conservation_is_always_available():
    names = [s["name"] for s in available()["strategies"]]
    assert names[0] == CONSERVATION
    if sd_installed():
        assert {"kalman_lna", "combined2", "matrix_v2"} <= set(names)


@pytest.mark.skipif(not sd_installed(), reason="SD Lab's strategies need orchestra[sd]")
def test_an_sdlab_strategy_finds_equations_for_the_measured_flows(tmp_path):
    store = FileMetrics(tmp_path / "m.jsonl")
    start, end = simulate(store, minutes=90)
    m = discover_with(store.dump("", {"project": "p"}), start=start, end=end, step=30, strategy="matrix_v2")
    assert m.check() == []
    assert m.discovery["strategy"] == "matrix_v2" and m.discovery["sd_flows"] > 0
    by_id = {f.id: f for f in m.flows}
    # SD Lab's flows land on Orchestra's counters (and so on their machines)
    from_sdlab = [f for f in m.flows if f.current() and f.current().method == "sdlab:matrix_v2" and f.measured_by]
    assert from_sdlab, [(f.id, f.current().method) for f in m.flows]
    assert all(f.current().spec.get("form") for f in from_sdlab)
    machines = {mc.id: set(mc.attributed) for mc in m.machines}
    assert machines and all(fid in by_id for fids in machines.values() for fid in fids)
