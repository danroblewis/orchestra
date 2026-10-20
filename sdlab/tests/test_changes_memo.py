"""changes.pelt's memo (approved by the user, 2026-10-20) gives exactly what the uncached search gives."""

import numpy as np

from sdlab.discovery import changes


def test_memo_returns_the_same_cuts_as_the_search():
    rng = np.random.default_rng(0)
    for _ in range(200):
        n = int(rng.integers(5, 400))
        r = rng.normal(size=n) + np.repeat(rng.normal(scale=3, size=4), -(-n // 4))[:n]
        if rng.random() < 0.2:
            r[rng.integers(0, n)] = np.nan
        min_len, mult = int(rng.integers(1, 8)), float(rng.choice([0.5, 1, 2, 3.5]))
        want = changes._pelt(np.nan_to_num(np.asarray(r, dtype=float)), min_len, mult)
        assert changes.pelt(r, min_len, mult) == want
        got = changes.pelt(r.copy(), min_len, mult)          # from memory
        assert got == want
        got.append(-1)                                       # a caller changing its list does not change the memo
        assert changes.pelt(r, min_len, mult) == want


def test_memo_is_bounded():
    for i in range(changes._MEMO_SIZE + 50):
        changes.pelt(np.arange(10.0) + i, 2, 1.0)
    assert len(changes._MEMO) <= changes._MEMO_SIZE
