"""The errors-in-variables refit (each strategy's own copy of eiv.py; lna's is tested here, the others are
byte-identical copies checked below): a drain fed by a measured input, with the levels measured with 5%
error, comes back unbiased; with counting noise or none the found numbers are kept."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from sdlab.discovery.strategies.lna import eiv

STRATEGIES = Path(__file__).resolve().parents[1] / "sdlab" / "discovery" / "strategies"


def _run(noise: str, n: int = 2000, seed: int = 3):
    rng = np.random.default_rng(seed)
    u = 300 + 70 * np.sin(np.arange(n) * 2 * np.pi / 60) + 150 * ((np.arange(n) // 50) % 3 == 0)
    x = np.empty(n)
    x[0] = 100.0
    for i in range(1, n):
        step = u[i] - 0.5 * x[i - 1]
        if noise == "counts":
            step = rng.poisson(u[i]) - rng.binomial(int(x[i - 1]), 0.5)
        x[i] = x[i - 1] + step
    y = x + (rng.normal(0, np.sqrt(1 + (0.05 * x) ** 2)) if noise == "meas" else 0)
    return {"t": list(range(n)), "levels": {"x": list(y)}}, {"inputs": {"u": list(u)}}


def _flows(a: float, b: float) -> list[dict]:
    return [{"from": "x", "to": None, "rate": {"form": "proportional", "stock": "x", "k": b}},
            {"from": None, "to": "x", "rate": {"form": "linear", "c": 0, "terms": [{"stock": "u", "k": a}]}, "input": "u"}]


def _ols(run: dict, opts: dict) -> tuple[float, float]:
    y, u = np.array(run["levels"]["x"]), np.array(opts["inputs"]["u"])
    a, mb = np.linalg.lstsq(np.c_[u[1:], y[:-1]], np.diff(y), rcond=None)[0]
    return float(a), float(-mb)


def test_measurement_error_is_undone():
    run, opts = _run("meas")
    a, b = _ols(run, opts)
    assert b > 0.55                                     # the one-step fit's bias
    flows, info = eiv.refit(_flows(a, b), [{"id": "x"}], run, opts)
    assert info["used"]
    assert abs(flows[0]["rate"]["k"] - 0.5) < 0.03 and abs(flows[1]["rate"]["terms"][0]["k"] - 1) < 0.06


def test_counting_noise_and_none_keep_the_numbers():
    for noise in ("counts", "none"):
        run, opts = _run(noise)
        a, b = _ols(run, opts)
        flows, info = eiv.refit(_flows(a, b), [{"id": "x"}], run, opts)
        assert not info.get("used")
        assert flows[0]["rate"]["k"] == b


def test_copies_are_identical():
    copies = sorted(STRATEGIES.glob("*/eiv.py"))
    assert len(copies) >= 30
    assert len({p.read_text() for p in copies}) == 1


def _counter_run(noise: str, n: int = 2000, seed: int = 4):
    """x as in _run, its drain counted by c (a counter: nothing leaves it), both measured with 5% error."""
    rng = np.random.default_rng(seed)
    run, opts = _run("none", n, seed)
    x = np.array(run["levels"]["x"])
    c = np.r_[0.0, np.cumsum(0.5 * x[:-1])]
    if noise == "meas":
        x = x + rng.normal(0, np.sqrt(1 + (0.05 * x) ** 2))
        c = c + rng.normal(0, np.sqrt(1 + (0.05 * c) ** 2))
    return {"t": run["t"], "levels": {"x": list(x), "c": list(c)}}, opts


def test_a_drain_the_counters_level_shows_becomes_a_move():
    run, opts = _counter_run("meas")
    flows, info = eiv.refit(_flows(1.0, 0.5), [{"id": "x"}, {"id": "c"}], run, opts)
    assert info["used"] and info["moved"] == ["x -> c"]
    assert [(f["from"], f["to"]) for f in flows if f["from"] == "x"] == [("x", "c")]


def test_without_measurement_error_the_drain_stays():
    run, opts = _counter_run("none")
    flows, info = eiv.refit(_flows(1.0, 0.5), [{"id": "x"}, {"id": "c"}], run, opts)
    assert "moved" not in info and flows[0]["to"] is None
