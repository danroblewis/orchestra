"""engine_forms reread (k8s-317): the batched screen of column sets finds what the brute-force search finds."""

import itertools

import numpy as np

from sdlab.discovery.strategies.engine_forms import reread


def _rows(T=300, C=30, seed=1):
    rng = np.random.default_rng(seed)
    Z = np.cumsum(rng.normal(size=(C, T)), axis=1) + 50.0
    Z = np.round(Z, 4)
    Z = np.vstack([Z, np.ones((1, T))])
    return reread._Rows(None, Z, [f"x{i}" for i in range(C)] + ["1"], 1e-4)


def test_the_screen_keeps_the_exact_column_set_among_many():
    rows = _rows()
    y = 0.3 * rows.Z[4] - 0.68 * rows.Z[17] + 0.6 * rows.Z[22] + 0.2 * rows.Z[29]
    got = rows.exact(y)
    assert got is not None and sorted(got[0]) == [4, 17, 22, 29]
    assert np.allclose(sorted(got[1]), sorted([0.3, -0.68, 0.6, 0.2]))
    assert (4, 17, 22, 29) == rows.ranked(y, 4)[0]


def test_a_floored_rate_is_found_through_the_screen():
    rows = _rows(seed=2)
    h = 0.5 * rows.Z[3] - 0.4 * rows.Z[11] - 2.0 * rows.Z[-1]
    r = np.maximum(0.0, h)
    assert np.any(r == 0) and np.any(r > 0)
    got = rows.floored(r)
    assert got is not None
    w = np.zeros(rows.Z.shape[0])
    w[list(got[0])] = got[1]
    assert np.allclose(np.maximum(0.0, w @ rows.Z), r, atol=1e-6)


def test_the_posed_cache_agrees_with_posed():
    rows = _rows(C=8, seed=3)
    for sub in itertools.combinations(range(rows.Z.shape[0]), 3):
        assert rows.posed(sub) == reread._posed(rows.Z[list(sub)].T)
