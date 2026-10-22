"""combined2 on a wide record (k8s-317, docs/research/fixes/317-combined2.md): the searches that grow with the number
of measured columns (capmin's limit search and kink surface, hinge's column sets, lagrow's active-set paths) take
their wide-record paths only above 24 columns, and those paths still find a plain floored rate."""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies.combined2 import capmin, hinge


def _cols(k: int, n: int = 300, seed: int = 1) -> dict:
    rng = np.random.default_rng(seed)
    return {f"s{i}": 50 + np.cumsum(rng.normal(size=n)) for i in range(k)}


def test_narrow_design_keeps_every_product():
    cols = _cols(10)
    read = np.array(list(cols.values()))
    B, Q = capmin._design(list(cols), read, {}, {}, np.arange(301.0), 300)
    assert Q is not None and Q.shape[1] == B.shape[1] + 10 * 11 // 2


def test_wide_design_uses_the_local_surface():
    cols = _cols(30)
    read = np.array(list(cols.values()))
    B, Q = capmin._design(list(cols), read, {}, {}, np.arange(301.0), 300)
    assert Q is None
    K = capmin._kinkq(B, Q, (read[0], read[1]), list(read))
    assert K.shape == (300, B.shape[1] + 2 * 30)


def test_fast_hfit_matches_lstsq():
    cols = _cols(3)
    Z = np.column_stack([cols["s0"], cols["s1"], np.ones(300)])
    y = np.maximum(0.0, cols["s0"] - cols["s1"])
    slow, fast = hinge.hfit(Z, y), hinge.hfit(Z, y, fast=True)
    assert abs(slow[0] - fast[0]) <= 1e-6 * max(1.0, slow[0])
    assert np.allclose(slow[1], fast[1], atol=1e-6)


def test_wide_fit_side_finds_the_gap():
    cols = _cols(30, seed=3)
    cols["s9"] = cols["s4"] + 5 * np.sin(np.arange(300) / 15.0) + 0.3 * np.cos(np.arange(300) / 4.0)
    y = np.maximum(0.0, 0.7 * cols["s4"] - 0.7 * cols["s9"])
    assert np.mean(y <= 0) > 0.1
    got = hinge.fit_side(y, cols, 300, 1e-9)
    assert set(got["w"]) == {"s4", "s9"} and abs(got["w"]["s4"] - 0.7) < 1e-6 and abs(got["w"]["s9"] + 0.7) < 1e-6


def test_passes_stop_inside_the_callers_time(monkeypatch):
    """Under a caller's timer with less than RESERVE left, the pick is answered as it is (no pass runs)."""
    import signal

    import sdlab.discovery.strategies.combined2 as C

    monkeypatch.setattr(C, "RESERVE", 1e6)
    r = {"flows": [{"from": None, "to": "a", "rate": {"form": "constant", "value": 1.0}}]}
    signal.signal(signal.SIGALRM, lambda *_: None)
    signal.setitimer(signal.ITIMER_REAL, 30.0)
    try:
        got = C._passes(r, [{"id": "a"}], {"t": [0, 1], "levels": {"a": [0.0, 1.0]}}, {}, {}, None)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
    assert got["flows"] == r["flows"] and got["passes_skipped"] == 16
