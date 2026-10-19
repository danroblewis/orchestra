"""A hidden stage (or a chain of three) on one measured stock's inflow (docs/research/hidden_transit.md,
"Stages").

The pair search (A -> H -> B, both measured) cannot see a hidden stock whose sender is not a
measured stock: a supply line fed from outside by a gap of the stock it feeds (orders
c - g x X wait in H before arriving), a measured input that arrives through a delay (k x input
into H), or rework that leaves X, waits and comes back (X -> H -> X). In all three, one measured
row X reads

    X(t+1) - X(t) = d H_n(t) - kX X'(t) + sum_j b_j w_j(t) + (the kept flows)   X' = X with this step's injections
    H_1(t+1)      = (1 - d) H_1(t) + u(t),   u = sum_j a_j z_j(t)                 z: 1, X', measured inputs, levels read
    H_i(t+1)      = (1 - d) H_i(t) + d H_(i-1)(t)                                 (a chain of n = 1 or 3: DELAY1, DELAY3)

w: measured inputs and levels read that act at once (a shipment that is the demand). With d
given, H_n is a filter of the z's plus the decay of each stage's starting level, so X's row is
linear in the a's, the starting levels, kX and the b's: a least-squares profile over the delay,
polished by a bounded search. The terms are chosen by BIC over small subsets; the alternatives are
the same terms arriving at once (no H) and the main line's own row (its pieces cost their numbers).
A constant straight into X is not a term: it is u's constant, the starting levels absorbing the
difference. Exact fits tie at a floor (the levels' rounding), so the fewest numbers win among them.
With counts (whole numbers) each step is weighted by 1 / what moved through X in it (a count's
variance is its rate), as the found model moves it.

u = a x X alone (nothing else delayed) is the same row as a move X -> H at a with X's drain lowered
by a: it is written as the move (what leaves X and comes back: rework), X's drain never below 0,
unless X's whole loss is under half of a (then X would gain through H: fed from outside).

The injections are read as the engine applies them: added at the start of the step, before its
flows (so the step's flows read the level with the injection in it).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.signal import lfilter

from ...simulate import Model
from .pairs import flow_numbers

SINK = "__stage_amount__"
ORDERS = (1, 3)


def _plain_rate(f: dict) -> bool:
    return not (f.get("byTime") or f.get("effects") or f.get("uses"))


def row_flows(flows: list[dict], x: str) -> tuple[list[int], list[int]] | None:
    """(the flows the stage replaces: x's flows to and from outside; the rest). None when one of
    them is not a plain rate (eras, effects, co-flows: left as found)."""
    out = [i for i, f in enumerate(flows) if (f.get("to") == x and f.get("from") is None) or (f.get("from") == x and f.get("to") is None)]
    if not out or any(not _plain_rate(flows[i]) for i in out):
        return None
    return out, [i for i in range(len(flows)) if i not in set(out)]


def read_by(flows: list[dict], idx: list[int]) -> set[str]:
    """The levels (or inputs) the replaced flows read."""
    out = set()
    for i in idx:
        f = flows[i]
        r = f.get("rate") or {}
        if r.get("stock"):
            out.add(r["stock"])
        for term in r.get("terms") or []:
            if term.get("stock"):
                out.add(term["stock"])
        if f.get("driver"):
            out.add(f["driver"])
    return out


def pre_levels(run: dict, ids: list[str], injections: list[dict] | None) -> tuple[np.ndarray, np.ndarray]:
    """(levels at the start of each step, injections included: stocks x T; the injected amounts per
    step: stocks x T). Step k moves the levels from t[k] to t[k + 1]."""
    t = np.asarray(run["t"], dtype=float)
    L = np.nan_to_num(np.array([np.asarray(run["levels"][s], dtype=float) for s in ids]))
    T = L.shape[1] - 1
    inj = np.zeros((len(ids), T))
    for j in injections or []:
        if j.get("stock") not in ids:
            continue
        k = int(np.searchsorted(t, float(j["t"]))) - 1           # the step that ends at t == j.t
        if 0 <= k < T and abs(t[k + 1] - float(j["t"])) < 1e-9:
            inj[ids.index(j["stock"]), k] += float(j["amount"])
    return L[:, :-1] + inj, inj


def step_amounts(flows: list[dict], ids: list[str], t: list, P: np.ndarray, inputs: dict | None) -> np.ndarray:
    """Each flow's amount at every step from the start-of-step levels P (stocks x T), with the
    measured inputs (nothing caps it)."""
    T = P.shape[1]
    out = np.zeros((len(flows), T))
    tt = np.asarray(t, dtype=float)[1 : T + 1]
    L = np.vstack([P, np.zeros((1, T))])
    for i, f in enumerate(flows):
        m = Model([{**f, "from": None, "to": SINK, "ratio": 1}], ids + [SINK],
                  inputs={"t": list(t), "values": inputs} if inputs else None)
        out[i] = m.step(L.copy(), tt)[len(ids)]
    return out


def _filter(z: np.ndarray, d: float) -> np.ndarray:
    """One stage fed z, empty at first: G(k) = (1 - d) G(k - 1) + z(k - 1), G(0) = 0."""
    G = np.zeros(len(z))
    G[1:] = lfilter([1.0], [1.0, -(1.0 - d)], z[:-1])
    return G


def chain(u: np.ndarray, d: float, n: int) -> np.ndarray:
    """The chain's levels (n x len(u)) fed u into its first stage, every stage empty at first."""
    H = np.zeros((n, len(u)))
    feed = np.asarray(u, dtype=float)
    for i in range(n):
        H[i] = _filter(feed, d)
        feed = d * H[i]
    return H


def _columns(d: float, n: int, Z: np.ndarray, m: int) -> np.ndarray:
    """What arrives in X (d x the last stage) from each delayed term z, and from a unit starting
    level in each stage (with nothing fed)."""
    cols = []
    for z in Z:
        cols.append(d * chain(z, d, n)[-1])
    for i in range(n):
        H = (1.0 - d) ** np.arange(m)
        for _ in range(i + 1, n):
            H = _filter(d * H, d)
        cols.append(d * H)
    return np.array(cols)


def _design(d: float, n: int, Z: np.ndarray, X: np.ndarray | None, W: np.ndarray) -> np.ndarray:
    """X's row: what the chain delivers, X's own drain (X None: none), the direct terms."""
    return np.column_stack(list(_columns(d, n, Z, Z.shape[1])) + ([-X] if X is not None else []) + list(W))


def _ls(y, A, w=None):
    """Least squares, rows weighted by w (1 / each step's variance) when given."""
    if w is not None:
        s = np.sqrt(w)
        y, A = y * s, A * s[:, None]
    beta = np.linalg.lstsq(A, y, rcond=None)[0]
    r = y - A @ beta
    return float(r @ r), beta


def profile(y, n, Z, X, W, d_lo: float, d_hi: float, w=None, grid: int = 40) -> tuple[float, float, np.ndarray]:
    """(rss, d, beta) at the best rate per stage: a log grid, then a bounded search between its
    neighbours."""
    f = lambda v: _ls(y, _design(math.exp(v), n, Z, X, W), w)[0]   # noqa: E731
    lds = np.linspace(math.log(d_lo), math.log(d_hi), grid)
    vals = [f(v) for v in lds]
    i = int(np.argmin(vals))
    lo, hi = lds[max(0, i - 1)], lds[min(grid - 1, i + 1)]
    o = minimize_scalar(f, bounds=(lo, hi), method="bounded", options={"xatol": 1e-6})
    v = o.x if o.fun < vals[i] else lds[i]
    rss, beta = _ls(y, _design(math.exp(v), n, Z, X, W), w)
    return rss, math.exp(v), beta


def _bic(rss: float, n: int, k: int, floor: float) -> float:
    return n * math.log(max(rss, floor) / n) + k * math.log(n)


def _subsets(names: list[str], most: int, least: int = 1):
    for size in range(least, min(most, len(names)) + 1):
        yield from itertools.combinations(names, size)


def fit_stage(y: np.ndarray, X: np.ndarray, cands: dict[str, np.ndarray], direct: dict[str, np.ndarray], d_lo: float, d_hi: float,
              most: int = 3, w: np.ndarray | None = None) -> dict:
    """The best stage (by BIC) over the chain's order, subsets of u's terms and of the direct terms;
    and the best plain alternative (every term arriving at once)."""
    m = len(y)
    yw = y if w is None else y * np.sqrt(w)
    floor = m * 1e-8 + 1e-12 * float(yw @ yw)
    best, plain = None, None
    for sub in _subsets(list(cands), most):
        Z = np.array([cands[s] for s in sub])
        for dsub in _subsets(list(direct), 2, 0):
            W = np.array([direct[s] for s in dsub]).reshape(len(dsub), m)
            for n, drained in itertools.product(ORDERS, (True, False)):
                lo = max(d_lo, n * d_lo)                # the whole delay n / d at most as long as allowed
                hi = min(0.9, n * d_hi)                 # (each stage at least 1 / 0.9 steps)
                if lo >= hi:
                    continue
                rss, d, beta = profile(y, n, Z, X if drained else None, W, lo, hi, w)
                k = len(sub) + n + 1 + drained + len(dsub)
                bic = _bic(rss, m, k, floor)
                if best is None or bic < best["bic"]:
                    s = len(sub)
                    best = {"terms": dict(zip(sub, beta[:s].tolist())), "n": n, "d": d, "start": beta[s : s + n].tolist(),
                            "kX": float(beta[s + n]) if drained else 0.0, "direct": dict(zip(dsub, beta[s + n + drained :].tolist())),
                            "rss": rss, "k": k, "bic": bic}
        A = np.column_stack([cands[s] for s in sub] + [-X] + [direct[s] for s in direct if s not in sub])  # (at once, a term is in once)
        rss, beta = _ls(y, A, w)
        bic = _bic(rss, m, A.shape[1], floor)
        if plain is None or bic < plain["bic"]:
            plain = {"terms": dict(zip(sub, beta[: len(sub)].tolist())), "rss": rss, "bic": bic}
    return {"stage": best, "plain": plain, "floor": floor}


def hidden_levels(fit: dict, cands: dict[str, np.ndarray], m: int) -> np.ndarray:
    """The chain's stages at each measured time (n x (m + 1): at the start of each step and after
    the last)."""
    d, n = fit["d"], fit["n"]
    u = np.zeros(m + 1)
    for s, a in fit["terms"].items():
        u = u + a * np.append(cands[s], cands[s][-1])
    H = np.zeros((n, m + 1))
    for i in range(n):
        feed = u if i == 0 else d * H[i - 1]
        H[i] = _filter(feed, d) + fit["start"][i] * (1.0 - d) ** np.arange(m + 1)
    return H


def is_move(fit: dict, x: str) -> bool:
    """u is a x X alone and X loses at least half of a in all: written as a move X -> H."""
    a = fit["terms"].get(x, 0.0)
    return list(fit["terms"]) == [x] and a > 0 and fit["kX"] >= 0.5 * a


def write(flows: list[dict], keep: list[int], x: str, fit: dict, tag: str) -> tuple[list[dict], list[str]]:
    """The model with the stage (or chain) in place of x's outside flows, and the hidden stocks' ids."""
    out = [flows[i] for i in keep]
    n, d = fit["n"], fit["d"]
    hidden = [tag] if n == 1 else [f"{tag}s{i + 1}" for i in range(n)]
    mark = (lambda s: {"delay": {"id": tag, "stage": s, "of": n, "time": n / d}}) if n > 1 else (lambda s: {})   # noqa: E731
    terms = {s: a for s, a in fit["terms"].items() if s != "1"}
    c = fit["terms"].get("1", 0.0)
    if is_move(fit, x):
        out.append({"from": x, "to": hidden[0], "ratio": 1, "rate": {"form": "proportional", "stock": x, "k": float(terms[x])},
                    "hidden": hidden[0], **mark(0)})
        drain = max(0.0, fit["kX"] - terms[x])
    else:
        rate = ({"form": "linear", "c": float(c), "terms": [{"stock": s, "k": float(a)} for s, a in terms.items()]} if terms
                else {"form": "constant", "value": float(c)})
        out.append({"from": None, "to": hidden[0], "ratio": 1, "rate": rate, "hidden": hidden[0], **mark(0)})
        drain = fit["kX"]
    for s in range(n):
        to = hidden[s + 1] if s + 1 < n else x
        out.append({"from": hidden[s], "to": to, "ratio": 1, "rate": {"form": "proportional", "stock": hidden[s], "k": float(d)},
                    "hidden": hidden[s], **mark(s + 1)})
    if drain > 1e-6:
        out.append({"from": x, "to": None, "ratio": 1, "rate": {"form": "proportional", "stock": x, "k": float(drain)}})
    elif drain < -1e-6:
        out.append({"from": None, "to": x, "ratio": 1, "rate": {"form": "linear", "c": 0.0, "terms": [{"stock": x, "k": float(-drain)}]}})
    for s, b in fit["direct"].items():
        rate = {"form": "linear", "c": 0.0, "terms": [{"stock": s, "k": float(abs(b))}]}
        out.append({"from": None, "to": x, "ratio": 1, "rate": rate} if b > 0 else {"from": x, "to": None, "ratio": 1, "rate": rate})
    return out, hidden


def try_stock(flows: list[dict], ids: list[str], run: dict, x: str, injections: list[dict] | None, inputs: dict | None,
              d_lo: float, d_hi: float, counts: bool = False) -> dict | None:
    """The stage on x's inflow, its alternatives and the gain in BIC; None when x has no plain
    outside flows to replace."""
    split = row_flows(flows, x)
    if split is None:
        return None
    replaced, keep = split
    t = run["t"]
    P, inj = pre_levels(run, ids, injections)
    L = np.nan_to_num(np.array([np.asarray(run["levels"][s], dtype=float) for s in ids]))
    i = ids.index(x)
    m = P.shape[1]
    am = step_amounts(flows, ids, t, P, inputs)
    sign = np.array([(1.0 if f.get("to") == x else 0.0) - (float(f.get("ratio") or 1) if f.get("from") == x else 0.0)
                     - sum(float(u.get("per") or 0) for u in f.get("uses") or [] if u.get("stock") == x) for f in flows])
    kept = sum((sign[j] * am[j] for j in keep), np.zeros(m))
    found = sum((sign[j] * am[j] for j in replaced), np.zeros(m))
    y = np.diff(L[i]) - inj[i] - kept
    X = P[i]
    cands = {"1": np.ones(m), x: X}
    direct = {}
    for name, v in (inputs or {}).items():
        if name not in ids:
            cands[name] = direct[name] = np.nan_to_num(np.asarray(v, dtype=float))[1 : m + 1]
    for s in sorted(read_by(flows, replaced)):
        if s in ids and s != x:
            cands[s] = direct[s] = P[ids.index(s)]
    w = None
    if counts:                     # each step's change varies as much as what moved through X (counts)
        gross = sum((abs(sign[j]) * np.abs(am[j]) for j in range(len(flows))), np.zeros(m))
        w = 1.0 / np.maximum(1.0, gross)
    res = fit_stage(y, X, cands, direct, d_lo, d_hi, w=w)
    res["data"] = {"y": y, "X": X, "cands": cands, "direct": direct,
                   "gross": sum((abs(sign[j]) * np.abs(am[j]) for j in keep), np.zeros(m))}
    r = (y - found) * (np.sqrt(w) if w is not None else 1.0)
    k = sum(flow_numbers(flows[j]) for j in replaced)
    res["found"] = {"rss": float(r @ r), "bic": _bic(float(r @ r), m, k, res["floor"]), "k": k}
    res["gain"] = min(res["plain"]["bic"], res["found"]["bic"]) - res["stage"]["bic"]
    res["keep"] = keep
    return res
