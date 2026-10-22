"""milp's block refit (refit.Structure.refit, k8s-317): the least squares solved block by block gives the
joint fit's numbers, and blocks never split a stock's row."""

import numpy as np

from sdlab.discovery.strategies.milp.program import Column
from sdlab.discovery.strategies.milp.refit import Structure
from sdlab.discovery.strategies.milp.steps import Steps


def _two_chains(n=300, seed=3):
    rng = np.random.default_rng(seed)
    a, b, c, d = [np.zeros(n) for _ in range(4)]
    a[0], b[0], c[0], d[0] = 50, 20, 40, 10
    u = 30 + 10 * np.sin(np.arange(n) / 9.0)
    for k in range(n - 1):
        a[k + 1] = a[k] + u[k] - 0.4 * a[k] + rng.normal(0, 0.1)
        b[k + 1] = b[k] + 0.4 * a[k] - 0.3 * b[k] + rng.normal(0, 0.1)
        c[k + 1] = c[k] + 0.1 * b[k] - 0.2 * c[k] + rng.normal(0, 0.1)    # reads b: a link, not a coupling
        d[k + 1] = d[k] + 0.2 * c[k] - 0.5 * d[k] + rng.normal(0, 0.1)
    stocks = [{"id": x, "unit": "u"} for x in "abcd"]
    run = {"t": list(range(n)), "levels": {"a": list(a), "b": list(b), "c": list(c), "d": list(d)}}
    return Steps(stocks, run, {"inputs": {"u": list(u)}})


def _col(src, dst, reader):
    return Column(src, dst, None, 10.0, 1, None, None, ("term", reader))


def test_blocks_match_joint_fit():
    st = _two_chains()
    chosen = [(_col(None, "a", "u"), 0.5), (_col("a", "b", "a"), 0.1), (_col("b", None, "b"), 0.1),
              (_col(None, "c", "b"), 0.5), (_col("c", "d", "c"), 0.1), (_col("d", None, "d"), 0.1)]
    s = Structure(st, chosen)
    assert sorted(len(ix) for ix, _ in s.blocks()) == [3, 3]
    scale = np.ones_like(st.dy) * 0.1
    joint = Structure(st, chosen)
    joint._refit(scale)
    s.refit(scale)
    assert np.allclose(s.theta, joint.theta, atol=1e-6)
