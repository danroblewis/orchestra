"""A hidden first-order delay in front of a measured stock's outside inflow (k8s-312, 2026-10-22; the user: "credit a
strategy's hidden stock").

What arrives in a stock is often what was asked for a while ago: nodes join some minutes after the autoscaler asks
for them, orders arrive after a lead time, hires start after notice. The asking is a function of today's levels (the
pods that cannot be placed, the stock short of its target); the arriving is that asking passed through a stage
nothing measures (DELAY1: a hidden stock H filled by the asking and emptied at H / tau into the stock). The program's
columns are today's levels, so it cannot write such an inflow, and the stock's row is left misfit (the outflow bent
to make up for it).

The mechanism, the same for every measured stock S whose outside inflow side is declared "estimate":
- the row's target is S's change less every flow on S other than its own outside flows;
- the inflow is (1 / tau) H with H_{k+1} = H_k + sum_j k_j g_j - H_k / tau, H_0 = 0 (k_j >= 0, by NNLS for a given
  tau); the drives g_j are chosen by forward selection (BIC) from the constant, the measured levels and inputs, and
  each room-limited move's unmet demand (room.py: what its source holds, or asks, beyond the room left,
  max(0, x - max(0, b Y - D)) for x = S or a S): the asking a capacity limit turns away;
- where S's outside outflow side is declared, the outflow is fitted with it: none, a drain c S, or a surplus
  c max(0, S - w . x) over a target read from other levels (any unit: nodes against pods / 2), with the target
  optionally floored at a minimum m (max(m, w . x): a pool's minimum size); its readers by forward selection;
- tau is scanned on a grid and polished with the outflow's numbers by least squares (the k_j profiled);
- the same search with no delay (the drives entering S directly) is the comparison: the hidden stock is written
  only when it beats that and the answer's own flows on S by MARGIN in BIC, and explains SHARE of their misfit
  above the levels' rounding.
Written as `outside -> H` (the drives), `H -> S` (proportional, 1 / tau) and `S -> outside` (the outflow form).
"""

from __future__ import annotations

import re

import numpy as np
from scipy.optimize import least_squares, nnls
from scipy.signal import lfilter

from .hinge import _amount, _env, _resolution
from .steps import Steps

MARGIN = 10.0        # BIC units the delayed inflow must win by (over the answer and over the same search without a delay)
SHARE = 0.5          # and the share of the answer's misfit above the rounding it explains
EVENTS = 5           # a surplus outflow binds, and does not, on at least this many steps (its floor m too)
TAU_GRID = (1.25, 1.6, 2.0, 2.5, 3.2, 4.0, 5.0, 6.5, 8.0, 11.0, 16.0, 24.0)
MAX_DRIVES = 3
MAX_READS = 3
ROUNDS = 3           # drives and outflow chosen in turn at most this many times
DEBUG = bool(__import__("os").environ.get("MILP_DEBUG"))
_ROOM = re.compile(r"^min\(([-\d.e+]+) \* (\w+), max\(0, ([-\d.e+]+) \* (\w+) - (\w+)\)\)$")


def _num(v: float) -> float:
    return float(f"{v:.6g}")


def _lag(G: np.ndarray, tau: float | None) -> np.ndarray:
    """Each drive column passed through the stage: H / tau with H_{k+1} = H_k + g_k - H_k / tau, H_0 = 0. No tau: the
    drives themselves (no delay)."""
    if tau is None:
        return G
    return lfilter([0.0, 1.0], [1.0, -(1.0 - 1.0 / tau)], G, axis=0) / tau


def _rooms(flows: list[dict]) -> list[tuple]:
    """(A, D, Y, a, b) of each room-limited move (room.py), from its record or its expression."""
    out = []
    for f in flows:
        fit = f.get("room_fit")
        expr = str((f.get("rate") or {}).get("expr") or "")
        m = _ROOM.match(expr.strip())
        if m and m.group(2) == f.get("from") and m.group(5) == f.get("to"):
            out.append((f["from"], f["to"], m.group(4), float(m.group(1)), float(m.group(3))))
        elif fit:
            out.append((f["from"], f["to"], fit["ceiling"], float(fit["a"]), float(fit["b"])))
    return out


class _Row:
    """S's row: the target, the drive pool, the outflow's reader pool, and the fit of one structure."""

    def __init__(self, st: Steps, S: str, target: np.ndarray, drives: list, readers: list, has_out: bool, floor2: float):
        self.st, self.S, self.y, self.has_out, self.floor2 = st, S, target, has_out, floor2
        self.lv = st.series(S)
        self.drives, self.readers = drives, readers           # [(name, column)], [(name, column)]
        self.n = len(target)

    def outflow(self, form: tuple, p: np.ndarray) -> np.ndarray:
        kind, rd, floored = form
        if kind == "none":
            return np.zeros(self.n)
        c = float(np.exp(np.clip(p[0], -30.0, 3.0)))
        if kind == "drain":
            return c * self.lv
        tgt = sum(p[1 + i] * self.readers[r][1] for i, r in enumerate(rd)) if rd else np.zeros(self.n)
        if floored:
            tgt = np.maximum(p[1 + len(rd)], tgt)
        return c * np.maximum(0.0, self.lv - tgt)

    def fit(self, dr: list, form: tuple, delayed: bool, start: dict | None = None):
        """(bic, tau, k, outflow numbers, residual) of drives dr (pool indexes) and an outflow form, or None."""
        G = np.column_stack([self.drives[j][1] for j in dr]) if dr else np.zeros((self.n, 0))
        kind, rd, floored = form
        n_out = 0 if kind == "none" else 1 if kind == "drain" else 1 + len(rd) + (1 if floored else 0)

        def inner(tau, q):
            F = _lag(G, tau)
            want = self.y + self.outflow(form, q)
            if F.shape[1]:
                k, _ = nnls(F, want, maxiter=50 * F.shape[1] + 50)
                return want - F @ k, k
            return want, np.zeros(0)

        def tau_of(x):
            return float(np.exp(np.clip(x[0], -6.0, 6.0))) + 1.0 if delayed else None

        def resid(x):
            tau = tau_of(x)
            return inner(tau, x[1:] if delayed else x)[0]

        starts = []
        for tau0 in (TAU_GRID if delayed else (None,)):
            for q0 in self._starts(form, start):
                x0 = np.r_[[np.log(tau0 - 1.0)] if delayed else [], q0]
                starts.append((float(np.sum(resid(x0) ** 2)), x0))
        starts.sort(key=lambda z: z[0])
        best = None
        for _, x0 in starts[:3]:
            if len(x0):
                r = least_squares(resid, x0, method="trf", x_scale="jac", max_nfev=300)
                x = r.x
            else:
                x = x0
            e, k = inner(tau_of(x), x[1:] if delayed else x)
            rss = max(float(e @ e), self.n * self.floor2)
            p = int(np.sum(k > 0)) + n_out + (1 if delayed else 0)
            bic = self.n * np.log(rss / self.n) + p * np.log(self.n)
            if best is None or bic < best[0]:
                best = (bic, tau_of(x), k, x[1:] if delayed else x, e)
        return best

    def _starts(self, form: tuple, start: dict | None) -> list:
        """Starting outflow numbers: from a fitted form (start: {"form", "q"}; its readers' weights carried over by
        reader, a new one at 0), and a grid."""
        kind, rd, floored = form
        if kind == "none":
            return [np.zeros(0)]
        if kind == "drain":
            return [np.array([np.log(c)]) for c in (0.01, 0.1)]
        out = []
        if start and start.get("form") and start["form"][0] == "surplus":
            _, prd, pfl = start["form"]
            q = start["q"]
            w = np.array([q[1 + prd.index(r)] if r in prd else 0.0 for r in rd])
            ms = [q[1 + len(prd)]] if pfl else list(np.quantile(self.lv, [0.05, 0.3, 0.6]))
            out += [np.r_[q[0], w, m] for m in ms] if floored else [np.r_[q[0], w]]
        last = self.readers[rd[-1]][1] if rd else np.ones(self.n)
        ratio = self.lv / np.maximum(np.abs(last), 1e-9)
        ws = [np.r_[np.zeros(len(rd) - 1), [np.quantile(ratio, q)]] for q in (0.1, 0.3, 0.5, 0.7, 0.9)]
        for w in ws:
            for c in (0.01, 0.05, 0.2):
                if floored:
                    for m in np.quantile(self.lv, [0.05, 0.3, 0.6]):
                        out.append(np.r_[np.log(c), w, m])
                else:
                    out.append(np.r_[np.log(c), w])
        return out

    def binds_ok(self, form: tuple, q: np.ndarray) -> bool:
        """A surplus binds and does not, each on EVENTS steps (else it is a drain or nothing); its floor binds on EVENTS."""
        kind, rd, floored = form
        if kind != "surplus":
            return True
        tgt = sum(q[1 + i] * self.readers[r][1] for i, r in enumerate(rd)) if rd else np.zeros(self.n)
        full = np.maximum(q[1 + len(rd)], tgt) if floored else tgt
        on = self.lv > full
        if int(np.sum(on)) < EVENTS or int(np.sum(~on)) < EVENTS:
            return False
        return not floored or int(np.sum(on & (q[1 + len(rd)] > tgt))) >= EVENTS


def _search(row: _Row, delayed: bool) -> tuple:
    """Forward selection, alternating: the drives under the outflow as it stands (a drain, or nothing, at first), then
    the outflow's form and readers under those drives (each step trying the target with and without its minimum), until
    neither changes (at most ROUNDS). (bic, drives, form, fit)."""
    base_form = ("drain", (), False) if row.has_out else ("none", (), False)

    def drives_for(form, start):
        dr, cur = [], row.fit([], form, delayed, start)
        for _ in range(MAX_DRIVES):
            step = None
            for j in range(len(row.drives)):
                if j in dr:
                    continue
                r = row.fit(dr + [j], form, delayed, start)
                if r is not None and (step is None or r[0] < step[0][0]):
                    step = (r, j)
            if step is None or (cur is not None and step[0][0] >= cur[0] - 2.0):
                break
            dr, cur = dr + [step[1]], step[0]
        return dr, cur

    def outflow_for(dr, form0, cur0):
        form, cur = base_form, row.fit(dr, base_form, delayed, None)
        rd: list = []
        for _ in range(MAX_READS):
            step = None
            for i in range(len(row.readers)):
                if i in rd:
                    continue
                for fl in (False, True):
                    f2 = ("surplus", tuple(rd + [i]), fl)
                    r = row.fit(dr, f2, delayed, {"form": form, "q": cur[3]} if form[0] == "surplus" else None)
                    if r is not None and row.binds_ok(f2, r[3]) and (step is None or r[0] < step[0][0]):
                        step = (r, f2)
            if step is None or step[0][0] >= cur[0] - 2.0:
                break
            cur, form = step
            rd = list(form[1])
        if form[0] == "surplus" and not form[2]:           # the target's minimum, on the readers chosen
            f2 = ("surplus", form[1], True)
            r = row.fit(dr, f2, delayed, {"form": form, "q": cur[3]})
            if r is not None and row.binds_ok(f2, r[3]) and r[0] < cur[0] - 2.0:
                cur, form = r, f2
        if cur0 is not None and cur0[0] < cur[0]:
            return form0, cur0
        return form, cur

    form = base_form
    dr, cur = drives_for(form, None)
    if cur is None or not dr:
        return (np.inf, [], base_form, None)
    if row.has_out:
        for _ in range(ROUNDS):
            form2, cur = outflow_for(dr, form, cur)
            dr2, cur2 = drives_for(form2, {"form": form2, "q": cur[3]})
            done = form2 == form and sorted(dr2) == sorted(dr)
            form = form2
            if cur2 is None or not dr2 or cur2[0] >= cur[0]:
                break
            dr, cur = dr2, cur2
            if done:
                break
    return (cur[0], dr, form, cur)


def _drive_expr(name) -> str:
    kind, x = name
    if kind == "c":
        return "1"
    if kind == "x":
        return x
    src, dst, y, a, b = x
    head = src if a is None else f"{_num(a)!r} * {src}"
    return f"max(0, {head} - max(0, {_num(b)!r} * {y} - {dst}))"


def _out_expr(row: _Row, form: tuple, q: np.ndarray) -> dict | None:
    kind, rd, floored = form
    if kind == "none":
        return None
    c = _num(float(np.exp(np.clip(q[0], -30.0, 3.0))))
    if kind == "drain":
        return {"form": "proportional", "stock": row.S, "k": c}
    terms = [f"{_num(float(q[1 + i]))!r} * {row.readers[r][0] or 1}" for i, r in enumerate(rd)]
    tgt = " + ".join(terms).replace("+ -", "- ") or "0"
    tgt = f"max({_num(float(q[1 + len(rd)]))!r}, {tgt})" if floored else f"({tgt})"
    return {"form": "expr", "expr": f"{c!r} * max(0, {row.S} - {tgt})"}


def refine(flows: list[dict], stocks: list[dict], run: dict, opts: dict | None, skip=()) -> tuple[list[dict], dict]:
    opts = opts or {}
    if not run.get("boundary_declared"):
        return flows, {}
    bd = run.get("boundary") or {}
    st = Steps(stocks, run, opts)
    if st.T < 20:
        return flows, {}
    env = _env(st)
    pos = {s: i for i, s in enumerate(st.ids)}
    measured = [s for s in st.ids if s not in st.final]
    out = list(flows)
    notes = []
    for S in st.ids:
        if S in st.final or S in (skip or ()) or "estimate" not in ((bd.get(S) or {}).get("in") or []):
            continue
        has_out = "estimate" in ((bd.get(S) or {}).get("out") or [])
        on = [i for i, f in enumerate(out) if S in (f.get("from"), f.get("to"))]
        own = [i for i in on if (out[i].get("from") is None and out[i].get("to") == S) or (has_out and out[i].get("from") == S and out[i].get("to") is None)]
        amounts = {i: _amount(out[i], st, env) for i in on}
        if any(a is None for a in amounts.values()):
            notes.append({"stock": S, "note": "a flow on it could not be evaluated"})
            continue
        target = st.dy[pos[S]].copy()
        for i in on:
            if i in own:
                continue
            target += amounts[i] if out[i].get("from") == S else -amounts[i]
        cur = target - sum((amounts[i] if out[i].get("to") == S else -amounts[i]) for i in own) if own else target
        n = st.T
        res = 0.0 if st.counts else _resolution(np.asarray(run["levels"][S], dtype=float))
        floor2 = max((res / np.sqrt(6.0)) ** 2, (1e-6 * float(np.mean(np.abs(st.L[pos[S]])) + 1e-12)) ** 2)
        noise = n * floor2
        if st.counts:
            gross = sum(np.abs(amounts[i]) for i in on)
            noise = max(noise, float(np.sum(gross)))
        rss_cur = float(cur @ cur)
        if rss_cur <= noise * 1.01:
            continue
        p_cur = sum(_numbers(out[i]) for i in own)
        bic_cur = n * np.log(max(rss_cur, n * floor2) / n) + p_cur * np.log(n)
        drives = [(("c", None), np.ones(n))]
        drives += [(("x", x), st.series(x)) for x in measured + sorted(st.inputs) if x != S]
        for A, D, Y, a, b in _rooms(out):
            if A in pos and D in pos and (Y in pos or Y in st.inputs):
                room = np.maximum(0.0, b * st.series(Y) - st.series(D))
                for aa in (None, a):
                    col = np.maximum(0.0, (1.0 if aa is None else aa) * st.series(A) - room)
                    if np.ptp(col) > 0:
                        drives.append((("room", (A, D, Y, aa, b)), col))
        readers = [(None, np.ones(n))] + [(x, st.series(x)) for x in measured + sorted(st.inputs) if x != S]
        row = _Row(st, S, target, drives, readers, has_out, floor2)
        flat = _search(row, delayed=False)
        lagged = _search(row, delayed=True)
        if DEBUG:
            print("delay", S, "current", round(bic_cur, 1), p_cur, "no delay", round(flat[0], 1), "delay", round(lagged[0], 1),
                  [row.drives[j][0] for j in lagged[1]], lagged[2], None if lagged[3] is None else (round(lagged[3][1], 4), lagged[3][2], lagged[3][3]))
        if lagged[3] is None:
            continue
        bic, dr, form, (_, tau, k, q, e) = lagged
        rss_new = float(e @ e)
        excess = max(rss_cur - noise, 1e-300)
        keep = bic < bic_cur - MARGIN and bic < flat[0] - MARGIN and rss_cur - rss_new >= SHARE * excess and np.any(k > 0)
        notes.append({"stock": S, "kept": bool(keep), "bic": round(float(bic), 1), "current": round(float(bic_cur), 1),
                      "no_delay": round(float(flat[0]), 1), **({"tau": _num(tau)} if keep else {})})
        if not keep:
            continue
        hname = f"{S}_delay"
        while hname in pos:
            hname += "_"
        parts = [(row.drives[j][0], float(kj)) for j, kj in zip(dr, k) if kj > 0]
        if all(nm[0] in ("c", "x") for nm, _ in parts):
            c0 = sum(kj for nm, kj in parts if nm[0] == "c")
            terms = [{"stock": nm[1], "k": _num(kj)} for nm, kj in parts if nm[0] == "x"]
            rate_in = {"form": "linear", "c": _num(c0), "terms": terms} if terms else {"form": "constant", "value": _num(c0)}
        else:
            rate_in = {"form": "expr", "expr": " + ".join(f"{_num(kj)!r} * {_drive_expr(nm)}" for nm, kj in parts)}
        new = [{"from": None, "to": hname, "ratio": 1, "id": f"milp:delay:outside->{hname}", "rate": rate_in},
               {"from": hname, "to": S, "ratio": 1, "id": f"milp:delay:{hname}->{S}", "rate": {"form": "proportional", "stock": hname, "k": _num(1.0 / tau)}}]
        r_out = _out_expr(row, form, q)
        if r_out is not None:
            new.append({"from": S, "to": None, "ratio": 1, "id": f"milp:delay:{S}->outside", "rate": r_out})
        out = [f for i, f in enumerate(out) if i not in own] + new
    return out, ({"rows": notes} if notes else {})


def _numbers(f: dict) -> int:
    """The numbers a flow carries (each schedule segment's; an expression's literals)."""
    def n(r):
        r = r or {}
        if r.get("form") == "linear":
            return len(r.get("terms") or []) + (1 if r.get("c") else 0)
        if r.get("form") == "expr":
            return max(1, len(re.findall(r"(?<![A-Za-z_])\d+\.?\d*(?:e[-+]?\d+)?", str(r.get("expr")))))
        return 1
    segs = f.get("byTime") or [{"rate": f.get("rate")}]
    return sum(n(g.get("rate")) for g in segs) + sum(len(e.get("points") or []) for e in f.get("effects") or [])
