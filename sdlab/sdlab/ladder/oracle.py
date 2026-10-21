"""The oracle: the true model's own structure fitted by least squares on the run, to say how precisely
the data pins each number down (its standard error). The scorer allows a found number to be off by
z standard errors (z = 3), as well as by the relative tolerance: with counting noise a short run
cannot pin a rate to 10% even for someone who knows the structure, and a method should not fail for
what the data cannot say.

Each measured stock's step change (less announced injections) is regressed on the levels at the
start of the step that the truth's equations make it depend on (and a constant if it has one); a
number that changes between windows (eras, schedule changes) gets one column per window. A part
not in the truth (a found extra term) is tested by adding its column to the stock's regression.

Only for a truth that is a linear system of the measured stocks (no effects, no hidden stocks);
otherwise there is no oracle and the tolerances alone apply. Measured inputs (data["inputs"]) are
columns as the levels are: a number on an input is regressed on the input's value in the step.

A whole flow (sim.py: an expression, a two-way flow, a rate reading a switch) that is piecewise linear
on the run (a MIN of two linear arms: kubernetes 306, 2026-10-21) is no obstacle: its form in every
step is known from the truth at the step's state (parts.piecewise), so each regime's numbers are
columns of their own, nonzero only on that regime's steps (the time-varying linearisation; each regime
gets its own numbers, so a number two regimes share is counted twice: the SEs are at worst a little
wide). They are fitted with the rest but are not reported: the whole flow is compared by its amount,
and se(stock, col) stays the number of the truth's linear flows on that column.
"""

from __future__ import annotations

import numpy as np

from .parts import ONE, linear_system, piecewise


class Oracle:
    def __init__(self, truth_flows: list[dict], data: dict, wins: list[tuple[int, int]]):
        self.ids = list(data["levels"])
        inputs = {k: v for k, v in (data.get("inputs") or {}).items() if k not in self.ids}
        self.cols = self.ids + list(inputs)                    # the readers: the levels, then the inputs
        whole = [f for f in truth_flows if f.get("whole")]
        self.systems = [linear_system([f for f in truth_flows if not f.get("whole")], self.cols, w) for w in wins]
        self.ok = len(data["t"]) > 3 and all(s is not None for s in self.systems)
        self.cache: dict[tuple, dict] = {}
        self.regimes: list[list[np.ndarray]] = [[] for _ in self.ids]    # per measured stock: the whole flows' columns
        if not self.ok:
            return
        t = data["t"]
        lv = np.array([np.asarray(data["levels"][s], dtype=float) for s in self.ids])
        inj = np.zeros_like(lv)
        index = {v: i for i, v in enumerate(t)}
        for j in data.get("injections") or []:
            if j.get("stock") in self.ids and j["t"] in index:
                inj[self.ids.index(j["stock"]), index[j["t"]]] += float(j["amount"])
        self.prev = lv[:, :-1] + inj[:, 1:]
        if inputs:                                             # an input's value during the step (at its end time)
            self.prev = np.vstack([self.prev] + [np.asarray(v, dtype=float)[None, 1: len(t)] for v in inputs.values()])
        self.dy = np.diff(lv, axis=1) - inj[:, 1:]
        steps = np.asarray(t[1:])
        self.win = np.zeros(len(steps), dtype=int)
        for w, (a, b) in enumerate(wins):
            self.win[(steps >= a) & (steps <= b)] = w
        self.W = len(wins)
        for f in whole:
            if not self._add_whole(f, data):
                self.ok = False
                return

    def _add_whole(self, f: dict, data: dict) -> bool:
        """A whole flow's regime columns on the rows it moves (False: not piecewise linear in the
        measured stocks and inputs, or it touches an unmeasured stock)."""
        idx = {s: i for i, s in enumerate(self.ids)}
        if f.get("via") or f.get("effects") or any(x and x not in idx for x in (f.get("from"), f.get("to"))):
            return False
        got = piecewise(f, data, self.cols, self.prev)
        if got is None:
            return False
        regime, forms = got
        cols = []
        for q, (c, ks) in enumerate(forms):
            on = (regime == q).astype(float)
            cols += ([on] if c else []) + [on * self.prev[self.cols.index(j)] for j in ks]
        rows = [(f.get("to"), 1.0), (f.get("from"), -float(f.get("ratio") or 1))]
        rows += [(u.get("stock"), -float(u.get("per") or 0)) for u in f.get("uses") or [] if u.get("stock") in idx]
        for st, sign in rows:
            if st and sign:
                self.regimes[idx[st]] += cols
        return True

    def _entry(self, i: int, col: str) -> list[float]:
        j = None if col == ONE else self.cols.index(col)
        return [float(u[i]) if j is None else float(B[i, j]) for B, u in self.systems]

    def _fit(self, i: int, extra: tuple) -> dict:
        key = (i, extra)
        if key in self.cache:
            return self.cache[key]
        cols, X = [], []
        base = [c for c in [ONE, *self.cols] if any(abs(v) > 0 for v in self._entry(i, c))]
        for c in list(dict.fromkeys(base + list(extra))):
            x = np.ones(self.dy.shape[1]) if c == ONE else self.prev[self.cols.index(c)]
            vals = self._entry(i, c)
            if c in base and any(abs(v - vals[0]) > 1e-12 for v in vals):
                for w in range(self.W):
                    m = self.win == w
                    if m.any():
                        cols.append((c, w))
                        X.append(np.where(m, x, 0.0))
            else:
                cols.append((c, None))
                X.append(x)
        for x in self.regimes[i]:                                  # a whole flow's regimes: fitted, not reported
            if not any(np.array_equal(x, y) for y in X):
                cols.append((None, None))
                X.append(x)
        out: dict = {}
        if X:
            A = np.array(X).T
            y = self.dy[i]
            n, p = A.shape
            beta, *_ = np.linalg.lstsq(A, y, rcond=None)
            rss = float(((y - A @ beta) ** 2).sum())
            s2 = rss / max(1, n - p)
            cov = s2 * np.linalg.pinv(A.T @ A)
            se = np.sqrt(np.maximum(0.0, np.diag(cov)))
            for (c, w), b, e in zip(cols, beta, se):
                if c is None:
                    continue
                d = out.setdefault(c, {"est": [None] * self.W, "se": [None] * self.W})
                for ww in range(self.W) if w is None else [w]:
                    d["est"][ww], d["se"][ww] = float(b), float(e)
        self.cache[key] = out
        return out

    def se(self, stock: str, col: str, window: int) -> float | None:
        """Standard error of the number for `col` (a stock id or "1") in `stock`'s change, in a window;
        None without an oracle."""
        if not self.ok or stock not in self.ids or (col != ONE and col not in self.cols):
            return None
        i = self.ids.index(stock)
        fit = self._fit(i, ())
        if col not in fit:
            fit = self._fit(i, (col,))
        v = (fit.get(col) or {}).get("se") or [None] * self.W
        return v[window]

    def part_se(self, key: tuple, true_keys: list[tuple], window: int) -> float | None:
        """A flow part's standard error: from the changes of the stocks it touches (and, for an
        outflow, of the stocks the same stock is seen to move things to, which separate the two)."""
        if not self.ok or key[0] != "flow":
            return None
        _, a, b, j = key
        rows = [x for x in (a, b) if x]
        if b is None and a:
            rows += [k[2] for k in true_keys if k[0] == "flow" and k[1] == a and k[2] and k[3] == j]
        ses = [self.se(r, j, window) for r in dict.fromkeys(rows)]
        if any(s is None for s in ses) or not ses:
            return None
        return float(np.sqrt(sum(s * s for s in ses)))


