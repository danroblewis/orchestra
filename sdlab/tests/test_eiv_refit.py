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
