"""(earned_pieces, vendored at a3a5e01) Conservation decided by all the rows at once, with counting noise as evidence.

The matrix fits each stock's row alone and then sets a drain to what the receivers are seen to take
unless the source's row clearly objects (matrix.conserve). Two things are lost that way:

- the receivers' numbers are measured too: when the source's row and the receivers' rows disagree,
  the shared number (the move) should come from both, each by its precision;
- whole things move (counting noise), so a row's residual variance is the stock's gross throughput:
  everything in plus everything out. An exit beside a move changes the throughput the source's row
  claims, and that is seen in the residuals even when the levels barely move (a stock that sits at its
  equilibrium, where an inflow and a drain trade off one for one).

Here every row keeps the columns and outside-inflow pieces it was fitted with; the numbers are
fitted jointly by weighted least squares, each step weighted by 1 / its throughput, and with a set
of ties: for a tied source a (in each configuration), a's own number is minus the sum of what its
same-unit receivers gain from a (no exit to outside). Each source is tied or freed by BIC on the
counting likelihood: residuals Gaussian with variance phi x gross, phi shared by the stocks of a
unit (the noise process is the same), so -2 log L = sum log(phi g) + e^2 / (phi g).
"""

from __future__ import annotations

import math

import numpy as np

from ...changes import pelt

FLOOR = 0.5          # the least throughput a step can have (half a thing): counting.gross's floor


def _weighted_demean(a: np.ndarray, w: np.ndarray, cuts: list[int] | None) -> np.ndarray:
    """a (columns x steps, or steps) less each piece's weighted mean; unchanged without pieces."""
    if not cuts:
        return a
    out = np.array(a, dtype=float, copy=True)
    for lo, hi in zip(cuts[:-1], cuts[1:]):
        ww = w[lo:hi]
        m = (out[..., lo:hi] * ww).sum(-1) / ww.sum()
        out[..., lo:hi] -= m[..., None] if out.ndim > 1 else m
    return out


def _piece_means(r: np.ndarray, w: np.ndarray, cuts: list[int] | None) -> np.ndarray:
    """Each step's outside inflow: its piece's weighted mean of r (0 without pieces)."""
    u = np.zeros_like(r)
    if cuts:
        for lo, hi in zip(cuts[:-1], cuts[1:]):
            u[lo:hi] = (r[lo:hi] * w[lo:hi]).sum() / w[lo:hi].sum()
    return u


class System:
    """The rows (as matrix.identify_one fitted them: columns X, chosen set, col -> (stock index,
    configuration or -1), cuts) and the system they share (ids, units, configurations)."""

    def __init__(self, rows: list[dict], ids: list[str], unit: dict, final: set, dy: np.ndarray, cfg: np.ndarray, L: int,
                 counting: bool = False, min_piece: int = 5, scale: str = "unit", pelt=pelt):
        self.pelt = pelt                  # the change scan (exact.ops' floored one on exact data)
        self.min_piece, self.scale = min_piece, scale     # scale: one phi per unit's rows, or per row
        self.counting = counting          # False: stacked least squares (one variance for a unit's rows)
        self.rows, self.ids, self.unit, self.final, self.dy, self.cfg, self.L = rows, ids, unit, final, dy, cfg, L
        self.S, self.T = len(ids), dy.shape[1]
        # every free number: (row index, column index q in the row's X)
        self.free = [(s, q) for s, r in enumerate(rows) for q in r["set"]]

    def configs(self, a: int) -> list[int]:
        """The configurations in which source a can be tied: its own level is in its row and some
        same-unit row gains from it."""
        if self.ids[a] in self.final:
            return []
        return [c for c in range(self.L) if self._reading(a, a, c) and any(self._reading(s, a, c) for s in self._same_unit(a))]

    def ties(self) -> list[int]:
        """The sources a tie can be made for (in every configuration it can be made in at once)."""
        return [a for a in range(self.S) if self.configs(a)]

    def changing(self, a: int) -> bool:
        """Whether row a's outside inflow is in pieces."""
        cuts = self.rows[a]["cuts"]
        return bool(cuts) and len(cuts) > 2

    def own(self, fit: dict, a: int, c: int) -> float:
        """a's own number in configuration c, in a fit (minus its drain)."""
        r = self.rows[a]
        return float(sum(fit["beta"][a][r["set"].index(q)] for q in self._reading(a, a, c)))

    def gain(self, fit: dict, a: int, c: int) -> float:
        """What a's same-unit receivers gain per unit of a's level in configuration c, in a fit."""
        total = 0.0
        for s in self._same_unit(a):
            r = self.rows[s]
            for q in self._reading(s, a, c):
                total += float(fit["beta"][s][r["set"].index(q)])
        return total

    def _same_unit(self, a: int) -> list[int]:
        return [s for s in range(self.S) if s != a and self.unit[self.ids[s]] == self.unit[self.ids[a]]]

    def _reading(self, s: int, j: int, c: int) -> list[int]:
        """Row s's chosen columns that read stock j's level in configuration c."""
        r = self.rows[s]
        return [q for q in r["set"] if r["col"][q][0] == j and r["col"][q][1] in (-1, c)]

    def fit(self, tied: set, honest: bool = False, iters: int = 3, gross: list | None = None) -> dict:
        """Numbers for every row, by weighted least squares (weights 1 / throughput, iterated), with
        a tied source's own number (in a configuration) minus what its same-unit receivers gain from
        it; the residuals, throughputs and -2 log L of the counting likelihood.

        honest: every changing row's pieces are found again beside its numbers at the textbook
        price (2 x log n a change, and 2 parameters each in the count): cheap pieces can stand in
        for a drain (or co-adapt with a biased one), so they must not decide a tie.

        gross: fixed throughputs (one array per row), used for the weights and in the likelihood
        instead of being refitted from this fit's numbers. Fits compared for a tie share them, so
        the comparison is nested: a tie can only raise -2 log L (decide)."""
        mult, per_change = (2, 2) if honest else (1, 1)
        index = {p: i for i, p in enumerate(self.free)}
        P = len(self.free)
        A = []
        for a, c in sorted((a, c) for a in tied for c in self.configs(a)):
            row = np.zeros(P)
            for q in self._reading(a, a, c):
                row[index[(a, q)]] += 1.0
            for s in self._same_unit(a):
                for q in self._reading(s, a, c):
                    row[index[(s, q)]] += 1.0
            A.append(row)
        A = np.array(A) if A else np.zeros((0, P))
        # a tied source whose outside inflow changes cannot tell its drain from the changes (pieces
        # bias it): the receivers alone measure the tied number, and the source's other numbers are
        # then fitted with it held
        held = {a for a in tied if self.changing(a)}
        cuts = [r["cuts"] for r in self.rows]
        w = [1.0 / g for g in gross] if gross is not None else [np.ones(self.T) for _ in self.rows]
        theta = np.zeros(P)
        for _ in range(iters):
            G = np.zeros((P, P))
            b = np.zeros(P)
            for s, r in enumerate(self.rows):
                cols = r["set"]
                if not cols or s in held:
                    continue
                idx = [index[(s, q)] for q in cols]
                X = _weighted_demean(r["X"][cols], w[s], cuts[s])
                y = _weighted_demean(self.dy[s], w[s], cuts[s])
                Xw = X * w[s]
                G[np.ix_(idx, idx)] += Xw @ X.T
                b[idx] += Xw @ y
            G[np.diag_indices_from(G)] += 1e-9 * (np.abs(np.diag(G)) + 1)
            K = np.block([[G, A.T], [A, np.zeros((len(A), len(A)))]])
            rhs = np.concatenate([b, np.zeros(len(A))])
            try:
                theta = np.linalg.solve(K, rhs)[:P]
            except np.linalg.LinAlgError:
                theta = np.linalg.lstsq(K, rhs, rcond=None)[0][:P]
            for a in held:
                r = self.rows[a]
                own = [q for q in r["set"] if r["col"][q][0] == a]
                rest = [q for q in r["set"] if r["col"][q][0] != a]
                y = self.dy[a] - sum((theta[index[(a, q)]] * r["X"][q] for q in own), np.zeros(self.T))
                # the pieces are found again with the drain held (found beside the row's own,
                # biased drain, they would favour it), then the row's other numbers refitted
                for _ in range(2):
                    left = y - sum((theta[index[(a, q)]] * r["X"][q] for q in rest), np.zeros(self.T))
                    cuts[a] = self.pelt(left, self.min_piece, mult)
                    if not rest:
                        break
                    X = _weighted_demean(r["X"][rest], w[a], cuts[a])
                    Xw = X * w[a]
                    Gr = Xw @ X.T
                    Gr[np.diag_indices_from(Gr)] += 1e-9 * (np.abs(np.diag(Gr)) + 1)
                    sol = np.linalg.lstsq(Gr, Xw @ _weighted_demean(y, w[a], cuts[a]), rcond=None)[0]
                    for q, v in zip(rest, sol):
                        theta[index[(a, q)]] = v
            if honest:
                for s, r in enumerate(self.rows):
                    if s in held or not self.changing(s):
                        continue
                    cols = r["set"]
                    left = self.dy[s] - (np.array([theta[index[(s, q)]] for q in cols]) @ r["X"][cols] if cols else 0.0)
                    cuts[s] = self.pelt(left, self.min_piece, mult)
            out = self._evaluate(theta, index, w, cuts, gross)
            if gross is None:
                w = [1.0 / g for g in out["gross"]]
        out["P"] = P - len(A) + sum(1 + per_change * (len(c) - 2) if c else 0 for c in cuts)
        out["cuts"] = cuts
        out["tied"] = set(tied)
        out["theta"] = theta
        return out

    def shared(self, fit: dict) -> np.ndarray:
        """The rows' noise at each step as one covariance (T x S x S), inverted. A row's variance is
        its throughput in the fit (gross); a move j -> s (a same-unit column of row s reading j with a
        positive number) is one count that leaves j and arrives in s, so its flow m is in both rows'
        variances and minus rho m is their covariance: Sigma = D + rho sum m (e_s - e_j)(e_s - e_j)',
        with D what is left of the throughputs (at least a tenth), so it is positive definite. rho
        (0 to 1, one per unit) is read off the fit's residuals: how much the move's rows really do
        share noise (1 for counting noise; 0 when a level's noise is its own, as with measurement
        noise, or when the move is a link). Without counting noise the rows are independent."""
        S, T = self.S, self.T
        eye = np.broadcast_to(np.eye(S), (T, S, S)).copy()
        if not self.counting:
            return eye
        g = np.array(fit["gross"], dtype=float)
        e = np.array(fit["res"], dtype=float)
        m = np.zeros((S, S, T))
        for s, r in enumerate(self.rows):
            for k, q in enumerate(r["set"]):
                j = r["col"][q][0]
                if j < S and j != s and self.unit[self.ids[j]] == self.unit[self.ids[s]] and fit["beta"][s][k] > 0:
                    m[j, s] += fit["beta"][s][k] * np.abs(r["X"][q])
        m = m + m.transpose(1, 0, 2)
        rho = np.zeros(S)
        for un in dict.fromkeys(self.unit[i] for i in self.ids):
            ss = [s for s in range(S) if self.unit[self.ids[s]] == un]
            phi = float(np.mean([(e[s] ** 2 / g[s]).mean() for s in ss]))
            mm = sum(float(m[a, b].sum()) for a in ss for b in ss if a < b)
            if mm > 0 and phi > 0:
                cross = sum(float((e[a] * e[b]).sum()) for a in ss for b in ss if a < b and m[a, b].any())
                rho[ss] = min(1.0, max(0.0, -cross / (phi * mm)))
        m = m * np.sqrt(rho[:, None, None] * rho[None, :, None])
        d = np.maximum(g - m.sum(1), 0.1 * g)
        sig = -m.transpose(2, 0, 1)
        i = np.arange(S)
        sig[:, i, i] = (d + m.sum(1)).T
        return np.linalg.inv(sig)

    def shared_nll(self, tied: set, W: np.ndarray, cuts: list) -> float:
        """-2 log L (less what is the same for every fit) of the rows fitted together by generalised
        least squares with the noise covariance W^-1 (shared), with the ties as constraints and each
        row's pieces (cuts) as its own levels; one variance scale per unit. With W fixed, a tie can
        only raise it."""
        S, T = self.S, self.T
        index = {p: i for i, p in enumerate(self.free)}
        Q = len(self.free)
        blocks = []
        for s, r in enumerate(self.rows):
            ix = [index[(s, q)] for q in r["set"]]
            X = [r["X"][q] for q in r["set"]]
            c = cuts[s]
            if c:
                for lo, hi in zip(c[:-1], c[1:]):
                    x = np.zeros(T)
                    x[lo:hi] = 1.0
                    X.append(x)
                    ix.append(Q)
                    Q += 1
            blocks.append((ix, np.array(X) if X else np.zeros((0, T))))
        groups = [[s for s in range(S) if self.unit[self.ids[s]] == un] for un in dict.fromkeys(self.unit[i] for i in self.ids)]
        G = np.zeros((Q, Q))
        b = np.zeros(Q)
        for ss in groups:
            for s in ss:
                ix, X = blocks[s]
                if not ix:
                    continue
                for j in ss:
                    XW = X * W[:, s, j]
                    b[ix] += XW @ self.dy[j]
                    jx, Xj = blocks[j]
                    if jx:
                        G[np.ix_(ix, jx)] += XW @ Xj.T
        A = []
        for a, c in sorted((a, c) for a in tied for c in self.configs(a)):
            row = np.zeros(Q)
            for q in self._reading(a, a, c):
                row[index[(a, q)]] += 1.0
            for s in self._same_unit(a):
                for q in self._reading(s, a, c):
                    row[index[(s, q)]] += 1.0
            A.append(row)
        A = np.array(A) if A else np.zeros((0, Q))
        G[np.diag_indices_from(G)] += 1e-9 * (np.abs(np.diag(G)) + 1)
        K = np.block([[G, A.T], [A, np.zeros((len(A), len(A)))]])
        rhs = np.concatenate([b, np.zeros(len(A))])
        try:
            theta = np.linalg.solve(K, rhs)[:Q]
        except np.linalg.LinAlgError:
            theta = np.linalg.lstsq(K, rhs, rcond=None)[0][:Q]
        e = np.array([self.dy[s] - (theta[ix] @ X if ix else 0.0) for s, (ix, X) in enumerate(blocks)])
        nll = 0.0
        for ss in groups:
            z = float(np.einsum("st,tsk,kt->", e[ss], W[:, ss][:, :, ss], e[ss]))
            n = len(ss) * T
            nll += n * math.log(max(z / n, 1e-300))
        return nll

    def _evaluate(self, theta, index, w, cuts, fixed=None) -> dict:
        betas, res, gross, inflow = [], [], [], []
        for s, r in enumerate(self.rows):
            cols = r["set"]
            beta = np.array([theta[index[(s, q)]] for q in cols]) if cols else np.zeros(0)
            fitted = beta @ r["X"][cols] if cols else np.zeros(self.T)
            u = _piece_means(self.dy[s] - fitted, w[s], cuts[s])
            e = self.dy[s] - fitted - u
            g = np.abs(u) + (np.abs(beta) @ np.abs(r["X"][cols]) if cols else 0.0)
            betas.append(beta)
            res.append(e)
            gross.append(fixed[s] if fixed is not None else np.maximum(FLOOR, g) if self.counting else np.ones(self.T))
            inflow.append(u)
        # phi per unit (or per row), then -2 log L
        nll = 0.0
        groups = [[s] for s in range(self.S)] if self.scale == "row" else \
            [[s for s in range(self.S) if self.unit[self.ids[s]] == un] for un in dict.fromkeys(self.unit[i] for i in self.ids)]
        for ss in groups:
            z = np.concatenate([res[s] ** 2 / gross[s] for s in ss])
            lg = sum(float(np.log(gross[s]).sum()) for s in ss)
            phi = max(float(z.mean()), 1e-300)
            nll += lg + z.size * (math.log(phi) + 1)
        return {"beta": betas, "res": res, "gross": gross, "inflow": inflow, "nll": nll}


def decide(system: System, log_t: float, trace: bool = False) -> dict:
    """Tie or free each source (in all its configurations at once), one change at a time while BIC
    on the counting likelihood improves, starting from every source free; every decision is made
    with changing rows' pieces found at the textbook price (System.fit, honest).

    A source whose own inflow is steady is judged on the rows' joint likelihood
    (System.shared_nll): a move's count leaves its source and arrives in its receiver, so the two
    rows share noise, and the noise covariance is the free fit's, held fixed (quasi-likelihood: the
    variance weighs the residuals but is not evidence about the numbers), so the tied and free
    fits are nested and the step is a likelihood-ratio test. Before, each fit's throughputs were
    refitted from its own numbers: a tie could lower -2 log L by claiming more variance (305
    counts-long: a give-up drain folded into the retry move at 4 sd; the retries stock empties
    every step, so its outflow is far less noisy than its throughput says), and the rows were
    taken as independent (305 counts-short: 2.0 sd row by row, 2.9 sd together).
    A source whose inflow changes (pieces) cannot tell its drain from the changes, so its own row's
    numbers are no evidence against a tie; it is judged as before, on each fit's own throughputs
    and pieces, where the throughput a tie implies is the evidence (an intake changing every 30
    steps: sd-pipeline). The model is then fitted with the chosen ties and the cheap pieces: a
    changing row keeps the matrix's pieces when free, and gets pieces found with its drain held
    when tied."""
    cands = system.ties()
    tied: set = set()
    free = system.fit(tied, honest=True)
    W = system.shared(free)

    def price(ts: set) -> tuple[float, float]:
        """(BIC on each fit's own throughputs, BIC on the shared likelihood with the free fit's)."""
        own = system.fit(ts, honest=True)
        held = system.fit(ts, honest=True, gross=free["gross"])
        return own["nll"] + own["P"] * log_t, system.shared_nll(ts, W, held["cuts"]) + held["P"] * log_t

    score = price(tied)
    while True:
        step = None
        for t in cands:
            trial = tied ^ {t}
            sc = price(trial)
            k = 0 if system.changing(t) else 1
            gain = score[k] - sc[k]
            if trace:
                print(f"    tie {system.ids[t]} {'on' if t in trial else 'off'}: gain {gain:.2f} ({'own' if k == 0 else 'shared'})")
            if gain > 1e-9 and (step is None or gain > step[1]):
                step = (trial, gain, sc)
        if step is None:
            break
        tied, score = step[0], step[2]
    return system.fit(tied)
