"""A row that reads a hidden integrator and per-unit columns (k8s 310, 2026-10-22, docs/research/fixes/310-structures.md).

A measured stock S whose outside inflow the current answer leaves far from exact (its row's residual more than
GATE x the data's quantum) is refitted on a wider library, beside its own level and the other measured levels:

- **per-unit columns** X / max(1, Y), for every pair of measured stocks that are not counters (a quantity per
  pod, per server; a counter's running total is no quantity per unit): the engine's own safe ratio, written
  as an expression; counters are not offered as level columns either (a running total that only grows is a
  trend, not a reader);
- **a hidden integrator** H, filled from outside at 1 a step (its scale is free: the row's coefficient carries
  it) and drained at d_t x H, where the drain fraction d_t is a constant a (a log grid, refined by golden
  section) or a table effect the answer already carries on some flow (counted.py's threshold tables: what
  removes a share of one stock may free the same share of a stock the data do not show). H's level is linear
  in its start h0, so the row reads two columns per drain (the response to the inflow and to the start).

The columns are chosen by forward selection on BIC (the hidden block priced as 3 numbers: its coefficient,
its start and its drain), and the new row replaces the answer's outside flows of S when it beats the row
they make by PRICE x log n. S's outside sides follow the declared boundary: a negative own-level term is
S's outflow where S declares one, every other term is its inflow. H is written as a stock with its two
flows (outside -> H = 1, H -> outside = k x H [x table]); its estimated level goes out as inferred_levels.
Moves on S are left alone (their amounts are taken out of the row first).
"""

from __future__ import annotations

import math

import numpy as np

from . import judge as J

GATE = 100.0         # the row's residual rms, in quanta, above which it is refitted
PRICE = 2.0          # the new row must beat the old by PRICE x log n
MAX_TERMS = 7        # columns beyond the constant
A_GRID = np.exp(np.linspace(math.log(1e-3), math.log(0.5), 24))


def _tab(x: np.ndarray, pts: list) -> np.ndarray:
    a = np.array([float(p[0]) for p in pts])
    b = np.array([float(p[1]) for p in pts])
    o = np.argsort(a)
    return np.maximum(0.0, np.interp(x, a[o], b[o]))


def _rate_amount(r: dict | None, X: dict, n: int) -> np.ndarray | None:
    """A plain rate's amount per step on the measured states (None for a form this cannot read)."""
    if r is None:
        return np.zeros(n)
    f = r.get("form")
    if f == "constant":
        return np.full(n, float(r.get("value") or 0.0))
    if f == "proportional":
        s = X.get(r.get("stock"))
        return None if s is None else float(r.get("k") or 0.0) * s
    if f == "linear" or "terms" in r:
        out = np.full(n, float(r.get("c") or 0.0))
        for t in r.get("terms") or []:
            s = X.get(t.get("stock"))
            if s is None:
                return None
            out = out + float(t.get("k") or 0.0) * s
        return out
    if f == "expr" and r.get("expr"):                  # (k8s 311) a MIN, room or controller form (exprs.py)
        from . import exprs
        return exprs.amount(r["expr"], X, n)
    return None


def _amount(f: dict, X: dict, n: int) -> np.ndarray | None:
    if f.get("byTime") or f.get("via") or f.get("uses"):
        return None
    if len(f.get("inflow") or []) > 1:
        return None         # (censored port) an inflow in pieces: its rate field is not what it moves (024's pieces)
    a = _rate_amount(f.get("rate"), X, n)
    if a is None:
        return None
    for e in f.get("effects") or []:
        x = X.get(e.get("stock"))
        if x is None or e.get("shape") != "table" or not e.get("points"):
            return None
        a = a * _tab(x, e["points"])
    return a if f.get("two_way") else np.maximum(0.0, a)


def _integrator(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """H's level before each step for inflow 1 from 0 (psi) and for a start of 1 with no inflow (phi):
    H' = H + c - d H."""
    n = len(d)
    psi, phi = np.zeros(n), np.zeros(n)
    h1, h0 = 0.0, 1.0
    for i in range(n):
        psi[i], phi[i] = h1, h0
        h1 = h1 + 1.0 - d[i] * h1
        h0 = h0 - d[i] * h0
    return psi, phi


def _bic(sse: float, n: int, k: int, floor: float) -> float:
    return n * math.log(max(sse, floor) / n) + k * math.log(n)


def _lsq(A: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    sc = np.maximum(np.abs(A).max(axis=0), 1e-300)
    b = np.linalg.lstsq(A / sc, y, rcond=None)[0] / sc
    r = y - A @ b
    return b, float(r @ r)


def _neff(r: np.ndarray) -> float:
    """The residuals' effective number of steps, n (1 - rho) / (1 + rho) with rho their lag-1 correlation: a
    systematic misfit (a table fitted a little off) leaves runs of residuals that many junk columns can each
    explain a sliver of; independent rounding leaves n."""
    n = len(r)
    if n < 3 or r[:-1].std() <= 0 or r[1:].std() <= 0:
        return float(n)
    rho = max(0.0, float(np.corrcoef(r[:-1], r[1:])[0, 1]))
    return max(2.0, n * (1 - rho) / (1 + rho))


def _select(y: np.ndarray, base: list, C: np.ndarray, names: list[str], floor: float) -> tuple[list[str], float]:
    """Forward selection of C's columns beside the base columns on BIC (each column one number; it must gain
    log n): (the chosen names, the final SSE). The gain of each candidate is its squared projection on the
    residual after the chosen span is taken out of it."""
    n = len(y)
    Q, _ = np.linalg.qr(np.column_stack(base))
    r = y - Q @ (Q.T @ y)
    sse = float(r @ r)
    chosen: list[str] = []
    Cp = C - Q @ (Q.T @ C) if C.shape[1] else C
    for _ in range(MAX_TERMS):
        if not Cp.shape[1]:
            break
        nrm = (Cp * Cp).sum(axis=0)
        ok = nrm > 1e-10 * np.maximum(1e-300, (C * C).sum(axis=0))
        gain = np.where(ok, (Cp.T @ r) ** 2 / np.where(ok, nrm, 1.0), -1.0)
        for k in chosen:
            gain[names.index(k)] = -1.0
        j = int(np.argmax(gain))
        if gain[j] <= 0:
            break
        new_sse = sse - float(gain[j])
        if not _neff(r) * math.log(max(sse, floor) / max(new_sse, floor)) > PRICE * math.log(n):
            break
        q = Cp[:, j] / math.sqrt(nrm[j])
        r = r - q * float(q @ r)
        Cp = Cp - np.outer(q, q @ Cp)
        sse = float(r @ r)
        chosen.append(names[j])
    return chosen, sse


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None) -> dict:
    if not isinstance(result, dict) or not result.get("flows") or (opts or {}).get("eras"):
        return result                                 # (k8s 311) injections are taken into the rows (steps.py)
    try:
        return _apply(result, stocks, run, opts or {})
    except Exception as e:                            # noqa: BLE001  (the answer stands as it was)
        return {**result, "hidden_rows": {"error": f"{type(e).__name__}: {e}"[:300]}}


def _apply(result: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    ids = [s["id"] for s in stocks]
    L = {k: np.asarray(run["levels"][k], dtype=float) for k in ids if k in run.get("levels", {})}
    T = min(len(v) for v in L.values())
    if T < 30:
        return result
    n = T - 1
    X = {k: v[:n] for k, v in L.items()}
    for k, v in (opts.get("inputs") or {}).items():
        if k not in X and len(v) >= T:
            X[k] = np.asarray(v, dtype=float)[1:T]            # an input's value during the step
    dy = {k: np.diff(v[:T]) for k, v in L.items()}
    from . import steps
    steps.adjust(X, dy, run, opts, n)
    quantum = J.quantum(np.vstack([v[:T] for v in L.values()]))
    declared = bool(run.get("boundary_declared"))
    bound = run.get("boundary") or {}
    finals = {s["id"] for s in stocks if s.get("final")}
    flows = list(result["flows"])
    measured = set(L)
    hidden_now = {x for f in flows for x in (f.get("from"), f.get("to")) if x and x not in measured}

    # table effects the answer carries (counted.py's thresholds, the engine's own tables)
    tables, seen = [], set()
    for f in flows:
        for e in f.get("effects") or []:
            if e.get("shape") == "table" and e.get("points") and e.get("stock") in X:
                key = (e["stock"], tuple(tuple(p) for p in e["points"]))
                if key not in seen:
                    seen.add(key)
                    tables.append((e["stock"], e["points"]))

    # a counter's running total is no reader either: it only grows, so a term on it is a trend standing in for
    # a misfit (310 none-short: -0.042 x oom_kills_total in mem's inflow), and it runs away off the run
    levels_cols = {k: v for k, v in X.items() if np.ptp(v) > 0 and k not in finals}
    ratio_cols = {}
    for a in L:
        for b in L:
            if a == b or a in finals or b in finals or np.ptp(X[b]) <= 0 or np.min(X[b]) < 0:
                continue
            c = X[a] / np.maximum(1.0, X[b])
            if np.ptp(c) > 0 and np.max(X[b]) > 1:
                ratio_cols[f"{a} / max(1, {b})"] = c
    notes, inferred = [], {}
    for S in ids:
        if S not in L or S in finals or S in hidden_now:
            continue
        sides = bound.get(S) or {}
        if declared and "estimate" not in (sides.get("in") or []):
            continue
        on = [f for f in flows if S in (f.get("from"), f.get("to"))]
        moves = [f for f in on if f.get("from") and f.get("to")]
        outs = [f for f in on if f not in moves]
        if any(f.get("from") not in measured and f.get("from") or f.get("to") not in measured and f.get("to") for f in moves):
            continue
        mv = np.zeros(n)
        ok = True
        for f in moves:
            a = _amount(f, X, n)
            if a is None:
                ok = False
                break
            mv += a * (1.0 if f.get("to") == S else -float(f.get("ratio") or 1.0))
        cur = np.zeros(n)
        for f in outs:
            a = _amount(f, X, n)
            if a is None:
                ok = False                                      # a form this cannot read (a controller's expression)
                break
            cur += a if f.get("to") == S else -a
        if not ok:
            continue
        y = dy[S] - mv
        r0 = y - cur
        rms = float(np.sqrt(np.mean(r0 ** 2)))
        if rms <= GATE * quantum:
            continue
        floor = n * (quantum ** 2) / 12.0
        k_cur = sum(1 + len((f.get("rate") or {}).get("terms") or []) + len(f.get("effects") or []) for f in outs)
        bic_cur = _bic(float(r0 @ r0), n, k_cur, floor)

        # the hidden blocks: (drain spec, psi, phi)
        blocks = []
        for a in A_GRID:
            psi, phi = _integrator(np.full(n, a))
            blocks.append(({"a": float(a)}, psi, phi))
        for xs, pts in tables:
            psi, phi = _integrator(np.clip(_tab(X[xs], pts), 0.0, 1.0))
            blocks.append(({"table": (xs, pts)}, psi, phi))
        cands = {**{k: v for k, v in levels_cols.items() if k != S},
                 **{k: v for k, v in ratio_cols.items() if not k.startswith(f"{S} /")}}
        names = list(cands)
        C = np.column_stack([cands[k] for k in names]) if names else np.zeros((n, 0))
        top = None
        for i, (spec, psi, phi) in enumerate(blocks):  # each drain: the row seeded with [1, S, psi, phi], then forward selection
            base = [np.ones(n), X[S], psi, phi]
            chosen, sse = _select(y, base, C, names, floor)
            v = _bic(sse, n, len(base) + 1 + len(chosen), floor)
            if top is None or v < top[0]:
                top = (v, i, chosen)
        if top is None:
            continue
        hb, chosen = top[1], top[2]
        if "a" in blocks[hb][0]:                                    # refine the constant drain by golden section
            Abase = np.column_stack([np.ones(n), X[S]] + [cands[k] for k in chosen])

            def f_of(la):
                psi, phi = _integrator(np.full(n, math.exp(la)))
                return _lsq(np.column_stack([Abase, psi, phi]), y)[1]

            i0 = int(np.argmin([abs(math.log(blocks[hb][0]["a"]) - math.log(g)) for g in A_GRID]))
            lo = math.log(A_GRID[max(0, i0 - 1)])
            hi = math.log(A_GRID[min(len(A_GRID) - 1, i0 + 1)])
            g = (math.sqrt(5) - 1) / 2
            c1, c2 = hi - g * (hi - lo), lo + g * (hi - lo)
            f1, f2 = f_of(c1), f_of(c2)
            for _ in range(40):
                if f1 < f2:
                    hi, c2, f2 = c2, c1, f1
                    c1 = hi - g * (hi - lo)
                    f1 = f_of(c1)
                else:
                    lo, c1, f1 = c1, c2, f2
                    c2 = lo + g * (hi - lo)
                    f2 = f_of(c2)
            a = math.exp((lo + hi) / 2)
            psi, phi = _integrator(np.full(n, a))
            blocks[hb] = ({"a": a}, psi, phi)
        # what the same search makes of the row with the integrator's start transient alone (its response to
        # h0, no inflow): a constant drain's integrator is a constant plus that transient, so it earns nothing
        # here; a drain that switches (a table) does
        spec, psi, phi = blocks[hb]
        plain, sse_plain = _select(y, [np.ones(n), X[S], phi], C, names, floor)
        Ap = np.column_stack([np.ones(n), X[S], phi] + [cands[k] for k in plain])
        r_plain = y - Ap @ _lsq(Ap, y)[0]
        chosen = ["1", S] + chosen
        A = np.column_stack([np.ones(n), X[S]] + [cands[k] for k in chosen[2:]] + [blocks[hb][1], blocks[hb][2]])
        b, sse = _lsq(A, y)
        k_new = A.shape[1] + 1
        bic_new = _bic(sse, n, k_new, floor)
        # the hidden integrator must earn its place against the same search without it (3 numbers, on the
        # effective length of what the search without it leaves)
        k_plain = 3 + len(plain)
        gain_h = _neff(r_plain) * math.log(max(sse_plain, floor) / max(sse, floor)) - (k_new - k_plain) * math.log(n)
        note = {"stock": S, "columns": chosen[1:], "hidden": None, "bic_old": round(bic_cur, 2), "bic_new": round(bic_new, 2), "kept": False}
        note["hidden_gain"] = round(gain_h, 2)
        bh_, bp_ = float(b[-2]), float(b[-1])
        h0_ = bp_ / bh_ if abs(bh_) > 1e-12 else math.inf
        note["start"] = round(h0_, 4) if math.isfinite(h0_) else None
        # a start beyond what the inflow fills over the whole run: the fit uses the start's decay as a
        # transient (a misfit elsewhere in the row), not a stock filled from outside
        if not bic_new < bic_cur - PRICE * math.log(n) or not gain_h > PRICE * math.log(n) or not h0_ <= n:
            notes.append(note)
            continue
        coef = dict(zip(chosen, b[: len(chosen)]))
        H = None
        if hb is not None:
            bh, bp = float(b[len(chosen)]), float(b[len(chosen) + 1])
            if abs(bh) > 1e-12:
                H = f"h_{S}"
                h0 = bp / bh
                spec = blocks[hb][0]
                if h0 < 0:                                             # a start below 0: start empty, refit
                    A2 = np.column_stack([A[:, : len(chosen)], blocks[hb][1]])
                    b2, _ = _lsq(A2, y)
                    coef = dict(zip(chosen, b2[: len(chosen)]))
                    bh, h0 = float(b2[len(chosen)]), 0.0
                psi, phi = blocks[hb][1], blocks[hb][2]
                level = psi + h0 * phi
                d_last = (spec["a"] if "a" in spec else float(np.clip(_tab(X[spec["table"][0]][-1:], spec["table"][1])[0], 0, 1)))
                inferred[H] = [float(v) for v in level] + [float(level[-1] + 1.0 - d_last * level[-1])]
                note["hidden"] = {"stock": H, "start": h0, "coef": bh, **({"drain": spec["a"]} if "a" in spec else {"drain_table": spec["table"][0]})}
        # write S's outside flows
        own = float(coef.pop(S, 0.0))
        out_ok = (not declared) or "estimate" in (sides.get("out") or [])
        new = []
        terms_in = {k: v for k, v in coef.items() if k != "1"}
        if own < 0 and out_ok:
            new.append({"id": f"hidden_rows_{S}_out", "from": S, "to": None, "ratio": 1,
                        "rate": {"form": "proportional", "stock": S, "k": -own}})
        elif own != 0:
            terms_in[S] = own
        c0 = float(coef.get("1", 0.0))
        if H is not None:
            terms_in[H] = float(bh)
        if any(" / max(1, " in k for k in terms_in):
            expr = " + ".join([repr(float(c0))] + [f"{float(v)!r} * {k}" for k, v in terms_in.items()])
            rate = {"form": "expr", "expr": expr}
        else:
            rate = {"form": "linear", "c": c0, "terms": [{"stock": k, "k": float(v)} for k, v in terms_in.items()]}
        new.insert(0, {"id": f"hidden_rows_{S}_in", "from": None, "to": S, "ratio": 1, "rate": rate})
        if H is not None:
            spec = blocks[hb][0]
            new.append({"id": f"hidden_rows_{H}_in", "from": None, "to": H, "ratio": 1, "rate": {"form": "constant", "value": 1.0}})
            drain = {"id": f"hidden_rows_{H}_out", "from": H, "to": None, "ratio": 1,
                     "rate": {"form": "proportional", "stock": H, "k": float(spec.get("a", 1.0))}}
            if "table" in spec:
                drain["effects"] = [{"stock": spec["table"][0], "shape": "table", "points": [list(p) for p in spec["table"][1]]}]
            new.append(drain)
        flows = [f for f in flows if f not in outs] + new
        hidden_now |= {H} if H else set()
        note["kept"] = True
        notes.append(note)
    if not notes:
        return result
    out = {**result, "flows": flows, "hidden_rows": notes}
    if inferred:
        out["inferred_levels"] = {**(result.get("inferred_levels") or {}), **inferred}
    return out
