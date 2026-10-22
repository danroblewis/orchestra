"""kalman_lna's batched subset fits (subsets.py, k8s-312 round 2) choose what the one-at-a-time searches chose."""

import itertools
import math

import numpy as np

from sdlab.discovery.strategies.kalman_lna import rows, subsets


def _lstsq(A, y):
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    e = y - A @ b
    return b, float(e @ e)


def _sparse_ref(X, y, floor, cols):
    """rows._sparse before 312 round 2 (ac5443e): every subset fitted alone."""
    n = X.shape[0]
    logn = math.log(n)
    bic = lambda sse, k: n * math.log((sse + floor) / n) + k * logn  # noqa: E731
    best = (bic(float(y @ y), 0), (), np.zeros(0), float(y @ y))
    by_size = {}
    for k in range(1, min(rows.SUB, len(cols)) + 1):
        for sub in itertools.combinations(cols, k):
            b, sse = _lstsq(X[:, sub], y)
            if k not in by_size or sse < by_size[k][3]:
                by_size[k] = (bic(sse, k), sub, b, sse)
    for got in by_size.values():
        if got[0] < best[0]:
            best = got
    cur = by_size.get(min(rows.SUB, len(cols)))
    while cur is not None and len(cur[1]) < min(rows.MOST_TERMS, len(cols)):
        step = None
        for j in cols:
            if j in cur[1]:
                continue
            sub = tuple(sorted(cur[1] + (j,)))
            b, sse = _lstsq(X[:, sub], y)
            if step is None or sse < step[3]:
                step = (bic(sse, len(sub)), sub, b, sse)
        if step is None or step[3] >= cur[3] * (1 - 1e-9):
            break
        cur = step
        if cur[0] < best[0]:
            best = cur
    return best


def _data(seed, n=400, p=10):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, p)).cumsum(axis=0)
    X[:, 3] = 2 * X[:, 1] - X[:, 2] + 1e-6 * rng.normal(size=n)       # nearly collinear
    X[:, 4] = np.round(X[:, 4], 1)
    X[:, -1] = 1.0
    return X, rng


def test_sparse_matches_one_at_a_time():
    for seed in range(6):
        X, rng = _data(seed)
        y = np.round(1.5 * X[:, 1] - 0.3 * X[:, 5] + 2.0 + (0.01 if seed % 2 else 0.0) * rng.normal(size=len(X)), 4)
        floor = 1e-8 * float(y @ y)
        new, ref = rows._sparse(X, y, floor), _sparse_ref(X, y, floor, list(range(X.shape[1])))
        assert new[1] == ref[1]
        assert np.allclose(new[2], ref[2], rtol=1e-9, atol=1e-12)


def test_hinge_rereads_match_one_at_a_time():
    X, rng = _data(7)
    z = 0.4 * X[:, 2] - 0.2 * X[:, 6] + 1.0
    r = np.maximum(0.0, z) + 1e-3 * rng.normal(size=len(X))
    on = r > 0.05
    C = np.array(list(itertools.combinations(range(X.shape[1]), 2)))
    B, _ = subsets.fits(X, r, C, rows=on)
    B2, s2, ok = subsets.reread(X, r, C, B, rows.MIN_ON, lambda P: np.maximum(0.0, P))
    for i, sub in enumerate(C):
        act = X[:, sub] @ B[i] > 0
        assert ok[i] == (act.sum() >= rows.MIN_ON)
        if ok[i]:
            b, _ = _lstsq(X[act][:, sub], r[act])
            assert np.allclose(B2[i], b, rtol=1e-6, atol=1e-9)
            assert math.isclose(s2[i], float(((r - np.maximum(0.0, X[:, sub] @ b)) ** 2).sum()), rel_tol=1e-6)
