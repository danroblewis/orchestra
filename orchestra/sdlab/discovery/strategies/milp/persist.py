"""A capacity regime that holds (docs/research/k8s-306-r3-six.md).

A MIN(a x X, b x Y) is a limit only if its regime (which side is the lesser) holds for stretches: the
demand is met for a while, then the capacity binds for a while, as the levels move. Where the two sides
are nearly proportional, or measurement error decides which is the lesser, the regime flips from step
to step and the MIN fits noise (306 meas: retries -> outside = MIN(0.58 retries, 0.04 queue), where
retries is about 0.08 x queue). The Wald-Wolfowitz runs test asks whether the regime sequence has fewer
runs than an independent sequence with the same shares would: a MIN is kept only where it does, by more
than RUNS_Z standard deviations; otherwise it is read as its demand alone (a x X) and refitted.
The same rule for every case; it reads only the levels and the fitted numbers.
"""

from __future__ import annotations

import math

import numpy as np

RUNS_Z = 3.0      # the regime sequence must have fewer runs than chance by this many standard deviations


def runs_z(regime: np.ndarray) -> float:
    """The runs test's z for a Boolean sequence (negative: fewer runs than chance, i.e. stretches)."""
    r = np.asarray(regime, bool)
    n1, n = int(r.sum()), len(r)
    n2 = n - n1
    if n1 == 0 or n2 == 0 or n < 3:
        return 0.0
    runs = 1 + int(np.count_nonzero(r[1:] != r[:-1]))
    mu = 1 + 2.0 * n1 * n2 / n
    var = 2.0 * n1 * n2 * (2.0 * n1 * n2 - n) / (n * n * (n - 1))
    return (runs - mu) / math.sqrt(var) if var > 0 else 0.0


def persistent(s, scale: np.ndarray):
    """s with every MIN part whose regime does not hold for stretches read as its demand alone, refitted."""
    changed = True
    while changed:
        changed = False
        offs = np.cumsum([0] + [2 if p[0] == "min" else 1 for p in s.parts])
        for i, p in enumerate(s.parts):
            if p[0] != "min":
                continue
            a, b = float(s.theta[offs[i]]), float(s.theta[offs[i] + 1])
            x, y = s.st.series(p[1]), s.st.series(p[3])
            if runs_z(a * x <= b * y) > -RUNS_Z:
                c = s.simplified(i)
                if c is not None:
                    c.refit(scale)
                    s, changed = c, True
                    break
    return s
