"""milp's whole-unit controller rule (quantized.py, k8s-308): found from the data, rejected on Poisson counts."""

import numpy as np

from sdlab.discovery.strategies.milp import quantized


def _hpa(n=400, seed=1):
    rng = np.random.default_rng(seed)
    x = 1500 + 900 * np.sin(np.arange(n) / 25.0) + rng.normal(0, 30, n)
    r = np.zeros(n)
    r[0] = 9
    for k in range(n - 1):
        up = max(0.0, min(16.0, np.ceil(x[k] / 192.5)) - r[k])
        dn = 1.0 * (r[k] > max(3.0, np.ceil(x[k] / 157.5)))
        r[k + 1] = r[k] + up - dn
    return x, r


def test_rule_found_and_fits_every_step():
    x, r = _hpa()
    stocks = [{"id": "cpu"}, {"id": "ready"}]
    run = {"t": list(range(len(x))), "levels": {"cpu": list(x), "ready": list(r)},
           "boundary": {"ready": {"in": ["estimate"], "out": ["estimate"]}, "cpu": {"in": ["estimate"], "out": ["estimate"]}},
           "boundary_declared": True}
    known, notes = quantized.find(stocks, run)
    assert set(known) == {"ready"}
    assert np.allclose(known["ready"]["amount"], np.diff(r))
    exprs = [f["rate"]["expr"] for f in known["ready"]["flows"]]
    assert any("ceil(cpu /" in e and "ready" in e for e in exprs)


def test_poisson_counts_rejected():
    rng = np.random.default_rng(2)
    n = 400
    x = 1000 + rng.integers(0, 50, n).astype(float)
    s = np.zeros(n)
    s[0] = 5
    for k in range(n - 1):
        s[k + 1] = s[k] + rng.poisson(0.2) - rng.binomial(int(s[k]), 0.04)
    run = {"t": list(range(n)), "levels": {"x": list(x), "s": list(s)}}
    known, _ = quantized.find([{"id": "x"}, {"id": "s"}], run)
    assert "s" not in known
