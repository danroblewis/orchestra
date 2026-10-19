# Vendored for combined2 from sdlab/discovery/strategies/structures/discover.py at commit 7e0a2bf (HEAD 05ae898); imports
# rewritten to these copies, otherwise unchanged (CLAUDE.md invariant 11). Re-vendor rather than edit.
"""The structure search: plain and bilinear terms first, then hidden Erlang chains of each order and
delay on a grid, refined; the lowest BIC wins."""

from __future__ import annotations

import math
import time

import numpy as np

from sdlab.discovery.strategies.combined2._vendored.combined import judge as J
from .fit import OutOfTime, Problem, conventions, fit, search, variance
from . import rowwise
from .gaps import gap_stage
from .terms import Rows, Term, chain_terms, library
from .write import to_flows

ORDERS = (1, 2, 3, 4)
MAX_PIECES = 30          # the base's inflow pieces are offered only up to this many (more: the base fits pieces to
                         # what it misses, and each costs a fit in every backward pass: 145-161 pieces timed out)
CELLS = 3e7              # stocks x steps x terms the screening may hold (about 240 MB)
MIN_DELAY = 3.0          # a shorter chain is not offered: with measurement noise (or a lag) on the levels, the changes'
                         # serial correlation is fitted by a chain of 1-2 steps (082 and 087 meas: chains of 1.2-2 steps
                         # beat combined by a hair on the judge and replaced right models)
STEP = 0.02              # the delay grid's spacing (log): a chain that fits exactly does so only within a few %


def prepare(stocks: list[dict], run: dict, opts: dict) -> tuple[J.Data, Rows, list[str]]:
    data = J.Data(stocks, run, opts.get("injections"), opts.get("inputs"))
    names = list(data.ids) + list(data.inputs)
    T = data.T
    U = np.zeros((0, T))
    if data.inputs:
        U = np.array([np.nan_to_num(np.asarray(v, dtype=float))[1:T + 1] for v in data.inputs.values()])
        if U.shape[1] < T:                                   # (held at the last value)
            U = np.hstack([U, np.repeat(U[:, -1:], T - U.shape[1], axis=1)])
    return data, Rows(np.nan_to_num(data.prev), U), names


def _refined(p: Problem, lib: list[Term], cur, rounds: int = 2):
    """With counts, the variance is re-read from the model found and the search run again from it."""
    for _ in range(rounds if p.counts else 0):
        p.var = variance(p, cur)
        cur = search(p, lib, cur.terms)
    return cur


def _retau(terms: list[Term], tau: float) -> list[Term]:
    return [Term(t.kind, t.src, t.dst, t.x, (t.chain[0], float(tau)), t.stage, t.sign) if t.chain else t for t in terms]


def base_pieces(flows: list[dict] | None, ids: list[str], t: list) -> dict[int, list[tuple[int, int]]]:
    """The places where the base model's outside inflows change ({stock index: [(a, b) steps]}):
    an unannounced schedule's pieces, which the search does not find on its own. A piece from time
    F to T covers the steps k whose end t[k + 1] is in [F, T]."""
    ends = np.asarray(t[1:], dtype=float)
    out: dict[int, list[tuple[int, int]]] = {}
    for f in flows or []:
        if f.get("from") is not None or f.get("to") not in ids or not f.get("inflow"):
            continue
        b = ids.index(f["to"])
        for g in f["inflow"]:
            ks = np.flatnonzero((ends >= float(g["from"])) & (ends <= float(g["to"])))
            if len(ks):
                out.setdefault(b, []).append((int(ks[0]), int(ks[-1]) + 1))
    return {b: sorted(set(v)) for b, v in out.items() if len(set(v)) > 1}


def closed(dy: np.ndarray, q: float) -> bool:
    """Every step's changes add up to nothing (the injections taken out): nothing enters or leaves,
    so only moves are offered (a closed market's N + A is constant, which makes a constant, N and A
    collinear and lets outflows and links stand in for the moves)."""
    return dy.shape[0] >= 2 and float(np.abs(dy.sum(axis=0)).max()) <= 2 * q * dy.shape[0] + 1e-9


def discover(stocks: list[dict], run: dict, opts: dict, seconds: float = 60.0, chains: bool = True, products: bool = True,
             base_flows: list[dict] | None = None) -> dict | None:
    began = time.monotonic()
    data, rows, names = prepare(stocks, run, opts)
    S, T = len(data.ids), data.T
    if T < 30 or S == 0:
        return None
    unit = [s.get("unit") or "" for s in stocks]
    final = {k for k, s in enumerate(stocks) if s.get("final")}
    group = [s.get("group") for s in stocks]
    m = rows.R.shape[0] - S
    p = Problem(rows, np.nan_to_num(data.dy), data.counts, data.q, deadline=began + seconds)
    lib = library(S, m, unit, final, group, products=products)
    if products and S * T * len(lib) > CELLS:
        products = False                                 # (too large to screen: plain terms only)
        lib = library(S, m, unit, final, group, products=False)
    if S * T * len(lib) > CELLS:
        return None
    trace: dict = {}
    shut = closed(p.dy, data.q)
    if shut:
        lib = [t for t in lib if t.kind == "move"]
        trace["closed"] = True
    try:
        base = None
        for first in rowwise.starts(rows, p.dy, p.var, p.counts, p.eps, S, m, unit, final, products):
            if shut:
                first = [t for t in first if t.kind == "move"]
            p.check()
            g = search(p, lib, first)
            if base is None or g.bic < base.bic:
                base = g
        trace["first_bic"] = base.bic
        if not shut:
            base = gap_stage(p, lib, base, S, m)
        pieces = {} if shut else base_pieces(base_flows, list(data.ids), list(run["t"]))
        if pieces and sum(len(v) for v in pieces.values()) <= MAX_PIECES:
            pterms = [Term("in", dst=b, span=sp) for b, sps in pieces.items() for sp in sps]
            g = search(p, lib + pterms, [t for t in base.terms if not (t.kind == "in" and t.dst in pieces)] + pterms)
            trace["pieces"] = {"bic": round(g.bic, 3), "without": round(base.bic, 3), "n": len(pterms)}
            if g.bic < base.bic:
                base, lib = g, lib + pterms
        base = _refined(p, lib, base)
        best = base
        trace["plain_bic"] = base.bic
        if chains and not shut:
            best = _chains(p, lib, base, S, m, unit, final, T, trace)
    except OutOfTime:
        return None
    try:
        best = conventions(p, best, lib)
    except OutOfTime:
        pass
    flows, inferred = to_flows(best.live(), names, rows, S, list(run["t"]))
    return {"flows": flows, "inferred_levels": inferred, "bic": best.bic, "nll": best.nll, "numbers": best.numbers,
            "terms": [_show(t, th, names) for t, th in best.live()], "trace": trace, "seconds": round(time.monotonic() - began, 2)}


def _golden(f, a: float, b: float, iters: int = 40) -> float:
    """The minimum of f on [a, b] (log delays)."""
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(d)
    return (a + b) / 2


def doubled(terms: list[Term]) -> bool:
    """A's loss passing through a chain into B while B also gets A's level at once (a move or a
    link from A): one transfer read twice, the instant share and the delayed one (measurement
    noise on the levels makes this fit; 087 meas)."""
    for t in terms:
        if t.kind == "chain" and t.src is not None:
            a, b = t.src, t.dst
            if any(u.dst == b and u.x == (a,) and u.kind in ("move", "link") for u in terms):
                return True
    return False


def _sharp(p: Problem, f) -> float:
    """The fit's likelihood without the noise-free floor (where a chain fits to the data's rounding,
    the floor would flatten the delay's optimum)."""
    if p.counts:
        return f.nll
    return float(0.5 * p.T * np.log(np.maximum((f.resid ** 2).mean(axis=1), 1e-300)).sum())


def _chains(p: Problem, lib: list[Term], base, S, m, unit, final, T, trace):
    """The best model with one hidden chain. For each order, the delay is chosen by the rows' own
    regressions on every feature with the chain's (rowwise.profile: cheap and smooth), on a log
    grid from MIN_DELAY steps to T / 10 and then by golden section around the best;
    at that delay the joint search runs from the rows' reading and from the plain model, and the
    delay is refined again with the terms kept. Models are compared under the plain model's
    variance."""
    lo_t, hi_t = math.log(MIN_DELAY), math.log(max(2 * MIN_DELAY, T / 10))
    taus = np.exp(np.linspace(lo_t, hi_t, max(12, min(250, int((hi_t - lo_t) / STEP)))))
    var0 = p.var.copy()
    best, where = base, None
    prof = {}
    for n in ORDERS:
        p.check()
        def crit(lt, n=n):
            p.check()
            return rowwise.profile(p.rows, p.dy, var0, p.counts, 1e-300, S, m, (n, math.exp(lt)), final)
        grid = [(crit(math.log(t)), t) for t in taus if n / t <= 1]
        if not grid:
            continue
        k = int(np.argmin([g[0] for g in grid]))
        lo = math.log(max(n, MIN_DELAY, grid[max(0, k - 1)][1]))
        hi = math.log(grid[min(len(grid) - 1, k + 1)][1])
        tau = math.exp(_golden(crit, lo, hi)) if hi > lo else grid[k][1]
        prof[n] = round(tau, 4)
        ext = lib + chain_terms(S, m, n, tau, unit, final)
        first = rowwise.start(p.rows, p.dy, var0, p.counts, p.eps, S, m, unit, final, True, (n, float(tau)))
        for st in (first, base.terms):
            g = search(p, ext, st)
            if g.bic < best.bic and any(t.kind == "chain" for t in g.terms):
                best, where = g, (n, tau)
    trace["profile"] = prof
    if where is None:
        return base
    n, tau = where
    terms = list(best.terms)
    width = 1.3
    for _ in range(3):                 # the delay with the terms kept, then the terms at that delay
        lt = _golden(lambda x: _sharp(p, fit(p, _retau(terms, math.exp(x)))), math.log(max(n, MIN_DELAY, tau / width)), math.log(tau * width))
        tau = math.exp(lt)
        ext = lib + chain_terms(S, m, n, tau, unit, final)
        cur = into_chain(p, search(p, ext, _retau(terms, tau)))
        if set(cur.terms) == set(_retau(terms, tau)):
            break
        terms, width = list(cur.terms), 1.05
    trace["chain"] = {"order": n, "delay": round(tau, 4)}
    if cur.bic >= base.bic or doubled(cur.terms):
        return base
    return _refined(p, ext, cur)


def into_chain(p: Problem, cur):
    """A stock fed through an outside chain: each of its outside-inflow terms is read as part of the
    chain's feed (what is ordered arrives through the supply line) when the likelihood cannot tell
    the two apart (within one unit of BIC)."""
    for _ in range(len(cur.terms)):
        th = dict(zip(cur.terms, cur.theta))
        chains = {t.chain_key(): t for t in cur.terms if t.kind == "chain" and t.src is None}
        done = False
        for t in cur.terms:
            if not t.pooled or t.kind == "goal" or t.span is not None:
                continue
            ch = next((c for k, c in chains.items() if k[1] == t.dst), None)
            if ch is None:
                continue
            same = [u for u in cur.terms if u.kind == "chain" and u.src is None and u.dst == t.dst and u.x == t.x and u.chain == ch.chain]
            net = th[t] * (-1.0 if t.kind == "gap" else 1.0) + sum(th[u] * u.sign for u in same)
            alt = Term("chain", dst=t.dst, x=t.x, chain=ch.chain, sign=1.0 if net >= 0 else -1.0)
            rest = [u for u in cur.terms if u != t and u not in same] + [alt]
            g = fit(p, rest)
            if g.bic <= cur.bic + 1.0:
                cur, done = g, True
                break
        if not done:
            return cur
    return cur


def _show(t: Term, th: float, names: list[str]) -> str:
    nm = lambda i: "outside" if i is None else names[i]  # noqa: E731
    x = "*".join(names[i] for i in t.x) or "1"
    ch = f" chain{t.chain}" if t.chain else ""
    st = f" stage {t.stage}" if t.kind == "init" else ""
    return f"{t.kind} {nm(t.src)}->{nm(t.dst)} [{x}]{' -' if t.sign < 0 else ''}{ch}{st} = {th:.6g}"
