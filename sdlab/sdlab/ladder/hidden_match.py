"""A found model's own hidden stock matched to the truth's (the user, 2026-10-21): credit a strategy's hidden stock.

A hidden stock is one the data never show. The scorer's older paths read two shapes of one: a path between
measured stocks (A -> H -> B, a DELAYn; parts._hidden_chains) and an information smoothing (parts._smoothings).
Any other hidden stock ("free": the truth's memory leak in kubernetes 310, filled from outside, drained by an
effect, read by the inflow to mem) was never scored: its flows were "not scored", and a found flow reading the
found model's own hidden stock could not be compared with the truth's flow reading the truth's.

Here each free found hidden stock H is matched to at most one free true hidden stock L, one to one:

- **connections**: H and L must share a measured neighbour (a measured stock a flow touching it moves things
  to or from, or whose flow reads it through its rate or an effect);
- **behaviour**: H's implied trajectory (its own flows stepped with the measured stocks and inputs at their
  measured values, as skill.observe does; started from 0, then once more from where the fit puts L's start)
  against L's true level, up to the scale and offset the data cannot fix: least squares H = alpha + beta L,
  beta > 0, R^2 >= MATCH_R2. The best R^2 is matched first.

A matched H is then written in L's coordinates (H = alpha + beta L) and renamed L: a rate reading H reads
alpha + beta L (its constant and coefficient change), a flow between H and outside carries 1 / beta of its
amount (H moves beta per unit of L), a flow between H and a measured stock keeps its amount (the measured
stock sees it; the scale is then fixed by the data), an effect of H has its table read at (x - alpha) / beta, a
co-flow drawn from H is per / beta. The scorer then scores L's flows and the flows reading L as it scores a
measured stock's, on L's true level, with the ordinary tolerances (rel, floor; no oracle covers a free hidden
stock, so there is no measured SE to use and none wider is invented). The truth's own flows of L are parts
only when L is matched; unmatched, they stay "not scored" as before, so a model without a hidden stock is
scored exactly as before. An unmatched found hidden stock that happens to share a true hidden stock's name
is renamed apart (`<name>__found`), so it is never read on the truth's level by accident.
"""

from __future__ import annotations

import re

import numpy as np

from .parts import _hidden_chains, _smoothings, linear_form

MATCH_R2 = 0.9                      # the behaviour gate: H's trajectory explains 90% of L's variance (affinely)


def _reads(f: dict) -> set[str]:
    """Every name a flow's rate (all its segments), effects and co-flows read."""
    out: set[str] = set()
    rates = [f.get("rate")] + [g.get("rate") for g in f.get("byTime") or []] + list(f.get("rates") or [])
    for r in rates:
        r = r or {}
        if r.get("stock"):
            out.add(r["stock"])
        out |= {x.get("stock") for x in r.get("terms") or [] if x.get("stock")}
        if r.get("form") == "expr":
            out |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", str(r.get("expr") or "")))
    out |= {e.get("stock") for e in f.get("effects") or [] if e.get("stock")}
    out |= {u.get("stock") for u in f.get("uses") or [] if u.get("stock")}
    return out


def free_hidden(flows: list[dict], measured: set, inputs: set, t: list) -> list[str]:
    """The unmeasured stocks of these flows (ends, or read and moved) that neither a hidden path between
    measured stocks nor an information smoothing takes."""
    plain = [f for f in flows if not f.get("via")]
    ends = {x for f in plain for x in (f.get("from"), f.get("to")) if x and x not in measured and x not in inputs}
    if not ends:
        return []
    _, used = _hidden_chains(plain, measured)
    w = (t[1] if len(t) > 1 else t[0], t[-1])
    smooth, smooth_used = _smoothings(plain, measured, inputs, w)
    taken = set(smooth) | {x for i in used | smooth_used for x in (plain[i].get("from"), plain[i].get("to")) if x and x not in measured}
    return sorted(ends - taken)


def connections(flows: list[dict], h: str, measured: set) -> set[str]:
    """The measured stocks h exchanges with, and the measured ends of the flows that read h."""
    out: set[str] = set()
    for f in flows:
        a, b = f.get("from"), f.get("to")
        if h in (a, b):
            out |= {x for x in (a, b) if x in measured}
        elif h in _reads(f):
            out |= {x for x in (a, b) if x in measured}
    return out


def trajectory(flows: list[dict], hidden: list[str], data: dict, start: dict | None = None) -> dict[str, np.ndarray] | None:
    """Each hidden stock's level over the run (aligned with t): the flows touching them stepped with the
    measured stocks and inputs at their measured values (skill.observe with the ladder's simulator, which
    evaluates expressions); None when they cannot be run."""
    from ..discovery.simulate import levels_array
    from . import sim

    ids = list(data["levels"])
    hset = set(hidden)
    sub = [f for f in flows if (f.get("from") in hset or f.get("to") in hset or any(u.get("stock") in hset for u in f.get("uses") or []))
           and not f.get("via")]
    if not sub:
        return None
    t = list(data["t"])
    inputs = {"t": t, "values": data["inputs"]} if data.get("inputs") else None
    try:
        model = sim.found_model(sub, ids + list(hidden), inputs=inputs)
        A = levels_array(data["levels"], ids)
        S, n = A.shape
        H = np.zeros((len(hidden), n))
        H[:, 0] = [float((start or {}).get(h) or 0.0) for h in hidden]
        L = np.zeros((S + len(hidden), 1))
        tt = np.asarray(t, dtype=float)
        for k in range(1, n):
            L[:S, 0] = A[:, k - 1]
            L[S:, 0] = H[:, k - 1]
            H[:, k] = model.step(L, tt[k: k + 1])[S:, 0]
    except Exception:                                         # noqa: BLE001 (a form the simulator cannot run)
        return None
    if not np.all(np.isfinite(H)):
        return None
    return {h: H[i] for i, h in enumerate(hidden)}


def _affine(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Least squares x = alpha + beta y: (alpha, beta, R^2)."""
    yc = y - y.mean()
    vy = float((yc * yc).sum())
    if vy <= 1e-12:
        return 0.0, 0.0, 0.0
    beta = float((yc * (x - x.mean())).sum()) / vy
    alpha = float(x.mean() - beta * y.mean())
    res = x - alpha - beta * y
    vx = float(((x - x.mean()) ** 2).sum())
    r2 = 1.0 - float((res * res).sum()) / vx if vx > 1e-12 else 0.0
    return alpha, beta, r2


def _scale_only(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Least squares x = beta y (no offset): (0, beta, R^2 against x's variance)."""
    yy = float(y @ y)
    beta = float(x @ y) / yy if yy > 1e-12 else 0.0
    res = x - beta * y
    vx = float(((x - x.mean()) ** 2).sum())
    return 0.0, beta, (1.0 - float(res @ res) / vx if vx > 1e-12 else 0.0)


def _offset_kept(x0: np.ndarray, f0: tuple, x1: np.ndarray, f1: tuple, y: np.ndarray) -> bool:
    """Does the run fix an offset between H's zero and the truth's? The offset's fit (f1, trajectory x1) against
    none (f0, x0) by BIC on the residuals, with the effective number of steps of autocorrelated residuals
    (n (1 - rho) / (1 + rho), rho their lag-1 correlation: a trajectory run open-loop on a noisy run drifts)."""
    r0, r1 = x0 - f0[1] * y, x1 - f1[0] - f1[1] * y
    s0, s1 = float(r0 @ r0), float(r1 @ r1)
    scale = float(((y - y.mean()) ** 2).sum()) or 1.0
    if s0 <= 1e-12 * scale:
        return False
    if s1 <= 1e-12 * scale:
        return True
    rho = float(np.corrcoef(r1[:-1], r1[1:])[0, 1]) if len(r1) > 2 and r1[:-1].std() > 0 and r1[1:].std() > 0 else 0.0
    n = max(2.0, len(y) * (1 - max(0.0, rho)) / (1 + max(0.0, rho)))
    return n * np.log(s0 / s1) > 2 * np.log(n)


def _fit_start(flows: list[dict], hidden: list[str], H: str, traj: dict, data: dict, y: np.ndarray) -> tuple[float, float, float]:
    """H's start (the data do not show it) and its map onto the truth's level y, h = alpha + beta L.

    With an offset: the start consistent with its own fit, h0 = alpha + beta y[0], where (alpha, beta) is the
    least-squares map of H's trajectory from h0 onto y (a root of alpha(h0) + beta(h0) y[0] - h0, bracketed on a
    grid of starts spanning y's range in H's units; the root with the best fit). Without one (alpha = 0): h0 =
    beta y[0], beta fitted from that start (a few rounds). The offset is kept only where the run fixes it
    (_offset_kept): when H's own flows do not read its level a start only shifts the trajectory, and on a noisy
    run an open-loop trajectory drifts by more than any offset could explain. (alpha, beta, R^2)."""
    from scipy.optimize import brentq

    def run(h0):
        tr = trajectory(flows, hidden, data, start={**{k: v[0] for k, v in traj.items()}, H: h0})
        return None if tr is None else tr[H][: len(y)]

    def fit(h0):
        x = run(h0)
        return None if x is None else _affine(x, y)

    a0, b0, r0 = _affine(traj[H][: len(y)], y)
    if b0 <= 0:
        return a0, b0, r0
    # no offset: h0 = beta y[0]
    beta, x0 = _scale_only(traj[H][: len(y)], y)[1], traj[H][: len(y)]
    for _ in range(4):
        x = run(beta * float(y[0]))
        if x is None:
            break
        x0, beta = x, _scale_only(x, y)[1]
    f0 = _scale_only(x0, y)
    # an offset: the consistent start
    span = float(y.max() - y.min()) or 1.0
    grid = list(a0 + b0 * np.linspace(float(y.min()) - 0.5 * span, float(y.max()) + 0.5 * span, 13))
    fits = [fit(h) for h in grid]
    gap = lambda f, h: f[0] + f[1] * float(y[0]) - h          # noqa: E731
    roots = []
    for (h1, g1), (h2, g2) in zip(zip(grid, fits), zip(grid[1:], fits[1:])):
        if g1 is None or g2 is None or g1[1] <= 0 or g2[1] <= 0 or np.sign(gap(g1, h1)) == np.sign(gap(g2, h2)):
            continue
        try:
            h0 = brentq(lambda h: (lambda f: gap(f, h) if f is not None else np.nan)(fit(h)), h1, h2, xtol=1e-9 * b0 * span, maxiter=60)
        except (ValueError, RuntimeError):
            continue
        x = run(h0)
        if x is not None:
            f = _affine(x, y)
            if f[1] > 0:
                roots.append((f, x))
    if roots:
        f1, x1 = max(roots, key=lambda r: r[0][2])
        if f0[1] <= 0 or _offset_kept(x0, f0, x1, f1, y):
            return f1
    return f0 if f0[1] > 0 else (a0, b0, r0)


# ---- writing a found hidden stock in the truth's coordinates ----

class _Cannot(Exception):
    pass


def _num(v: float) -> str:
    return repr(float(v))


def _rate(r: dict | None, h: str, new: str, alpha: float, beta: float, d: float) -> dict | None:
    """A rate with h = alpha + beta new substituted, divided by d."""
    if r is None:
        return None
    reads_h = r.get("stock") == h or any(x.get("stock") == h for x in r.get("terms") or []) or \
        (r.get("form") == "expr" and re.search(rf"\b{re.escape(h)}\b", str(r.get("expr") or "")))
    if not reads_h and d == 1.0:
        return r
    if r.get("form") == "expr":
        e = re.sub(rf"\b{re.escape(h)}\b", f"({_num(alpha)} + {_num(beta)} * {new})", str(r.get("expr") or ""))
        return {**r, "expr": e if d == 1.0 else f"({e}) / {_num(d)}"}
    lf = linear_form(r)
    if lf is None:
        raise _Cannot(f"rate form {r.get('form')}")
    c, ks = lf[0], dict(lf[1])
    if h in ks:
        k = ks.pop(h)
        c += k * alpha
        ks[new] = ks.get(new, 0.0) + k * beta
    return {"form": "linear", "c": c / d, "terms": [{"stock": j, "k": k / d} for j, k in ks.items()]}


def _effect(e: dict, h: str, new: str, alpha: float, beta: float) -> dict:
    if e.get("stock") != h:
        return e
    if e.get("shape") == "table" and e.get("points"):
        pts = e["points"]
    else:                                                     # level / normal clamped to [min, max]: the same curve as a table
        n = max(1e-9, float(e.get("normal") or 1))
        lo = float(e["min"]) if e.get("min") is not None else 0.0
        hi = float(e["max"]) if e.get("max") is not None else 1.0
        if lo < 0 or hi < lo:
            raise _Cannot("an effect curve below 0")
        pts = [[lo * n, lo], [hi * n, hi]]
    return {**e, "stock": new, "shape": "table", "points": sorted([(float(x) - alpha) / beta, float(y)] for x, y in pts)}


def rewrite(flows: list[dict], h: str, new: str, alpha: float, beta: float, measured: set) -> list[dict]:
    """The flows with hidden stock h written as alpha + beta x new (module docstring); _Cannot when a form
    cannot be rewritten."""
    out = []
    for f in flows:
        a, b = f.get("from"), f.get("to")
        touches = h in (a, b)
        if not touches and h not in _reads(f):
            out.append(f)
            continue
        if f.get("via") or f.get("merged") or (touches and f.get("ratio") not in (None, 1, 1.0)):
            raise _Cannot("a hidden path, merged flow or ratio on it")
        other = b if a == h else a
        d = beta if touches and other not in measured else 1.0      # between h and outside (or another hidden stock): 1 / beta of it
        g = {**f}
        if a == h:
            g["from"] = new
        if b == h:
            g["to"] = new
        if f.get("rate") is not None:
            g["rate"] = _rate(f.get("rate"), h, new, alpha, beta, d)
        if f.get("rates"):
            g["rates"] = [_rate(r, h, new, alpha, beta, d) for r in f["rates"]]
        if f.get("byTime"):
            g["byTime"] = [{**s, "rate": _rate(s.get("rate"), h, new, alpha, beta, d)} for s in f["byTime"]]
        if f.get("inflow"):
            g["inflow"] = [{**s, "value": float(s.get("value") or 0) / d} for s in f["inflow"]]
        if f.get("effects"):
            g["effects"] = [_effect(e, h, new, alpha, beta) for e in f["effects"]]
        if f.get("uses"):
            g["uses"] = [{**u, "stock": new, "per": float(u.get("per") or 0) / beta} if u.get("stock") == h else u for u in f["uses"]]
        out.append(g)
    return out


def match(truth_flows: list[dict], found_flows: list[dict], data: dict, measured: set, inputs: set) -> tuple[list[dict], dict, list[str]]:
    """(found flows with each matched hidden stock written as the truth's, {true name: {found, alpha, beta, r2}},
    notes). Nothing changes for a truth without free hidden stocks or a found model without them."""
    t = list(data["t"])
    lv = data.get("all_levels") or {}
    true_h = [h for h in free_hidden(truth_flows, measured, inputs, t) if h in lv]
    found_h = free_hidden(found_flows, measured, inputs, t)
    notes: list[str] = []
    if not found_h:
        return found_flows, {}, notes
    flows = found_flows
    for h in [x for x in found_h if x in lv]:                   # a found name that is the truth's: renamed apart first
        flows = rewrite(flows, h, f"{h}__found", 0.0, 1.0, measured)
        found_h[found_h.index(h)] = f"{h}__found"
    if not true_h:
        return flows, {}, notes
    traj = trajectory(flows, found_h, data)
    if traj is None:
        notes.append(f"found hidden stock(s) {', '.join(found_h)}: could not be stepped on the run, not matched")
        return flows, {}, notes
    cand = []
    for L in true_h:
        y = np.asarray(lv[L], dtype=float)[: len(t)]
        cl = connections(truth_flows, L, measured)
        for H in found_h:
            if not (connections(flows, H, measured) & cl):
                continue
            alpha, beta, r2 = _fit_start(flows, found_h, H, traj, data, y)
            cand.append((r2, L, H, alpha, beta))
    cand.sort(key=lambda c: -c[0])
    out: dict = {}
    for r2, L, H, alpha, beta in cand:
        if L in out or any(m["found"] == H for m in out.values()):
            continue
        if beta <= 0 or r2 < MATCH_R2:
            notes.append(f"found hidden stock {H} not matched to the truth's {L}: its trajectory explains {max(0.0, r2):.3g} of {L}'s"
                         f" (needs {MATCH_R2}){'' if beta > 0 else ', with the opposite sign'}")
            continue
        try:
            flows = rewrite(flows, H, L, alpha, beta, measured)
        except _Cannot as e:
            notes.append(f"found hidden stock {H} not matched to the truth's {L}: {e} cannot be rewritten")
            continue
        out[L] = {"found": H, "alpha": alpha, "beta": beta, "r2": r2}
        notes.append(f"found hidden stock {H} matched to the truth's {L} (level = {alpha:.4g} + {beta:.4g} x {L}, R^2 {r2:.4f}): "
                     f"its flows and the flows reading it are scored as a measured stock's")
    return flows, out, notes
