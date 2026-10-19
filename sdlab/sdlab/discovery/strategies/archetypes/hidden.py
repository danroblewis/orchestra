"""A hidden source: the SIR / diffusion archetype seen only downstream.

An epidemic is often measured only in its later stages (in bed, convalescent, reported): the
susceptible and infected pools are not measured. For each measured stock i the search offers two
unmeasured stocks feeding it, S -> I at beta x S x I and I -> i at gamma x I, with S's and I's
starting levels fitted, beside the measured stocks' own linear chain (each stock's drain and its
moves to the others), which backward elimination and forward selection then trim and extend. The
hidden terms stay; AICc counts their numbers and the two starting levels. Started from a small
grid (gamma, the basic reproduction number beta S0 / gamma, S0 in multiples of i's largest level),
since a free run of an epidemic is far from linear in its numbers.
"""

from __future__ import annotations

import itertools
import math
import time

import numpy as np

from .fit import Data, Fit, fit
from .search import backward, init_theta, stepwise
from .sim import run
from .terms import Term, arrays, library


def seed_terms(m: int, i: int) -> tuple[list[Term], list[Term]]:
    sus, inf = m, m + 1
    hid = [Term(sus, inf, (sus, inf)), Term(inf, i, (inf,))]
    chain = [Term(j, None, (j,)) for j in range(m)] + [Term(j, k, (j,)) for j in range(m) for k in range(m) if k != j]
    return hid, chain


def search_hidden(Y: np.ndarray, inj: np.ndarray, power: float, i: int, seconds: float, moves: bool = True, price: bool = True) -> Fit | None:
    deadline = time.perf_counter() + seconds
    m = Y.shape[0]
    D = Data(Y, np.hstack([inj, np.zeros((inj.shape[0], 2))]), power=power, hidden=2)
    hid, chain = seed_terms(m, i)
    terms = hid + chain
    top = max(1e-9, float(np.max(Y[i])))
    best = None
    for gamma, R0, mult in itertools.product((0.3, 0.7), (1.5, 3.0), (1.5, 4.0)):
        if time.perf_counter() > deadline:
            break
        S0 = mult * top
        I0 = max(1e-3 * top, float(max(Y[i, 1] - Y[i, 0], 0.0)) / gamma)
        th_h = np.array([R0 * gamma / S0, gamma])
        x0 = np.concatenate([Y[:, 0], [S0, I0]])
        th0 = np.concatenate([th_h, np.zeros(len(chain))])
        X = run(th0, x0, *arrays(terms), D.inj, D.T, D.cap)
        th = init_theta(terms, D, fixed=th_h, Z=np.vstack([Y, X[m:]]))
        f = fit(terms, D, th, x0)
        if best is None or (f.aicc, f.nll) < (best.aicc, best.nll):
            best = f
    if best is None:
        return None
    cache: dict = {}
    locked = frozenset(hid)
    cur, _ = backward(best, D, cache, deadline, locked)
    lib = library(m, moves=moves)
    cur = stepwise(D, lib, cur, cache, deadline, locked=locked)
    if price:
        extra = max(0.0, 2 * math.log(len(lib)) - 2)
        cur.score = cur.aicc + extra * (cur.size - len(locked))
    else:
        cur.score = cur.aicc
    cur.family = "hidden source"
    return cur
