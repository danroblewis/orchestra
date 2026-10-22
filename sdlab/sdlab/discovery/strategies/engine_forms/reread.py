"""An exact re-read of noise-free rows (k8s-309, docs/research/fixes/309-engine_forms.md).

Where the levels are known exactly, the true flows reproduce every stock's one-step change to the
data's rounding. When the answer leaves some stock's changes clearly unexplained, the stocks of that
stock's unit (the only ones a move can join) are read again row by row, from the levels alone:

1. Each row is the smallest set of columns (every measured level, every measured input, a constant)
   whose least-squares fit reproduces it exactly (best subset, up to MAX_TERMS columns).
2. A row no linear set reproduces is tried as a linear part plus one floored linear flow (the engine
   floors every rate at 0): the linear part (up to 3 columns) is exact on at least half of the steps,
   the rest of the change has one sign (an inflow, or an outflow), and on the steps where it is not
   zero it is a linear function of the columns (up to MAX_TERMS) that is <= 0 on every other step.
   It is written as that linear rate on the declared side: the engine's floor makes it the hinge.
3. The rows' linear terms are joined into flows column by column: a column read negatively by its own
   stock's row (or by one row only) is a source, and the rows of the same unit that read it
   positively receive moves from it, up to what it gives; the rest of each term is an outside flow
   on that stock's side. Terms of one pair are merged into one flow (one flow per pair and side).
4. A row neither form reproduces keeps its own outside flows from the answer (its moves go).
5. (k8s-310) A counter (a final stock) whose row no linear set reproduces, but which is exactly a level
   times a table of another level (X x T(Y), T piecewise linear with 1-2 inner knots), is a measured
   flow: its one-step change becomes one more column the other rows may read. A term on that column
   joins as any other (its source the row reading it negatively, its receivers the same-unit rows
   reading it positively), is written as the counter's own rate (X x T(Y), scaled by the term's
   number), and the counter itself gets it as its outside inflow.
6. (k-311) Two rows of one unit that neither form reproduces are read as a pair joined by a floored-MIN
   move (a start limited by the room left): their sum, where the move cancels, is linear plus at most one
   floored inflow and one floored outflow on declared sides; what is left of one row is lin + s x
   max(0, min(u, v)), read from its linear pieces (found by a seeded exact-sample search, each column's
   rounding counted only where it moves) and fitted on every step at once; the other row must be the
   sum's rest less the same move. The move is written as an expression, min(u, max(0, v)) when u never
   goes below 0. Runs only where some moving row is exact. Column sets more collinear than COND read
   nothing (their huge numbers scaled the rounding tolerance until a counter's row looked linear).

The block is replaced only when every row the answer explained is still explained, at least one row
it did not explain now is, and nothing leaves the declared boundary. On data with noise no row is
reproduced to its rounding, so nothing changes there. Reads only the levels, inputs, units and the
boundary.
"""

from __future__ import annotations

import copy
import itertools

import numpy as np
from scipy.optimize import least_squares, nnls

from ._kalman import boundary as _boundary

MAX_TERMS = 4          # columns one rate may read
BASE_TERMS = 3         # columns of a hinge row's linear part
REL = 1e-6             # a row is reproduced when its rms residual is below this share of its rms change ...
ROUND = 3.0            # ... or below ROUND x the rounding of what it reads (where rounding is fine: FINE)
FINE = 1e-3            # the rounding counts only where it is below this share of the row's largest change
SNAP = 1e-4           # a term's remainder below this share of the column's largest number is the fit's precision
COND = 1e6             # (k-311) a column set more collinear than this (scaled columns' condition number) reads nothing:
                       # its huge numbers would scale the rounding tolerance up until any row is "exact"
QUIET = 0.5            # a hinge's linear part holds exactly on at least this share of the steps
SAMPLES = 300          # (k-311) random step sets a linear piece's numbers are solved on (regime)
SMALL = 5              # (k-312) the fewest steps a last linear piece (fewer than a piece's share) is read from
SCREEN = 256           # (k8s-317) column sets of each size an exact reader checks, the smallest misfits first (_Rows.ranked)
                       # 256, not 64 (2026-10-22, coordinator; found by port-sindy): at 64 the near-collinear counters crowd
                       # out the pods rows' true set on 311 and the block is refused: 311 none-short and none-long passed
                       # before 2bca23f and failed after it (job 399); 128 keeps it, 256 for margin
EACH = 2.0             # (k8s-316) on finely rounded data, a branch fit's every step is within EACH x its ROUND x rounding


def _posed(A: np.ndarray) -> bool:
    """Are these columns (steps x columns) clearly independent? (COND)"""
    if A.shape[1] < 2:
        return True
    n = np.sqrt(np.sum(A ** 2, axis=0))
    if np.any(n <= 0):
        return False
    return bool(np.linalg.cond(A / n) <= COND)


def _quantum(a: np.ndarray) -> float:
    a = np.abs(a[np.isfinite(a)])
    for e in range(0, 9):
        q = 10.0 ** -e
        if np.all(np.abs(a / q - np.round(a / q)) < 1e-6):
            return q
    return 0.0


class _Rows:
    fine = FINE            # (k-312) the rounding counts where it is below this share of a row's largest change

    def __init__(self, data, cols: np.ndarray, names: list[str], q: float):
        self.data, self.Z, self.names, self.q = data, cols, names, q
        self._posed_full: dict = {}                       # (k8s-317) a column set's conditioning, once per set
        self._combos: dict = {}

    def posed(self, sub) -> bool:
        """_posed of these columns over every step, remembered: it does not depend on the row (k8s-317)."""
        key = tuple(sub)
        got = self._posed_full.get(key)
        if got is None:
            got = self._posed_full[key] = _posed(self.Z[list(sub)].T)
        return got

    def ranked(self, y: np.ndarray, n: int, on: np.ndarray | None = None, pool=None, posed_on: bool = False) -> list[tuple]:
        """(k8s-317, a screen) The n-column sets of `pool` (default: every column) in the order of their least-squares
        misfit to y on the steps `on`, the SCREEN best of them only. Solved for every set at once from the columns'
        Gram matrix (normal equations, columns scaled), so the exact readers below check only the sets that can
        reproduce y: a set that does is among the smallest misfits, and the readers' own exact test is unchanged.
        A set more collinear than COND (over every step, or over `on` where posed_on) is left out, as _posed does."""
        pool = list(range(self.Z.shape[0])) if pool is None else list(pool)
        key = (n, tuple(pool))
        c = self._combos.get(key)
        if c is None:
            c = self._combos[key] = np.array(list(itertools.combinations(pool, n)), dtype=int).reshape(-1, n)
        if len(c) <= SCREEN:
            return [tuple(int(j) for j in row) for row in c]
        Zs = self.Z if on is None else self.Z[:, on]
        yy = y if on is None else y[on]
        nrm = np.sqrt(np.sum(Zs ** 2, axis=1))
        ok = nrm > 0
        Zn = Zs / np.where(ok, nrm, 1.0)[:, None]
        G = Zn @ Zn.T
        b = Zn @ yy
        GS = G[c[:, :, None], c[:, None, :]]
        bS = b[c]
        good = np.all(ok[c], axis=1)
        if n >= 2:
            if posed_on or on is None:
                ev = np.linalg.eigvalsh(GS)
                good &= ev[:, 0] > 0
                good &= np.sqrt(np.abs(ev[:, -1]) / np.maximum(ev[:, 0], 1e-300)) <= COND
            else:
                good &= np.array([self.posed(tuple(row)) for row in c]) if len(c) <= 4 * SCREEN else self._posed_all(c)
        eye = np.eye(n)[None, :, :]
        try:
            k = np.linalg.solve(GS + 1e-14 * eye, bS[:, :, None])[:, :, 0]
        except np.linalg.LinAlgError:
            k = np.einsum("mij,mj->mi", np.linalg.pinv(GS), bS)
        rss = float(yy @ yy) - np.sum(bS * k, axis=1)
        rss[~good] = np.inf
        order = np.argsort(rss, kind="stable")[:SCREEN]
        return [tuple(int(j) for j in c[i]) for i in order if np.isfinite(rss[i])]

    def _posed_all(self, c: np.ndarray) -> np.ndarray:
        """_posed over every step for each column set of c (rows of c), batched and remembered by c's shape."""
        key = ("all", c.shape, int(c.sum()), int(c[-1].sum()))
        got = self._posed_full.get(key)
        if got is None:
            nrm = np.sqrt(np.sum(self.Z ** 2, axis=1))
            ok = nrm > 0
            Zn = self.Z / np.where(ok, nrm, 1.0)[:, None]
            GS = (Zn @ Zn.T)[c[:, :, None], c[:, None, :]]
            ev = np.linalg.eigvalsh(GS)
            got = np.all(ok[c], axis=1) & (ev[:, 0] > 0) & (np.sqrt(np.abs(ev[:, -1]) / np.maximum(ev[:, 0], 1e-300)) <= COND)
            self._posed_full[key] = got
        return got

    def tol(self, y: np.ndarray, k: np.ndarray | None = None) -> float:
        """The rms residual below which y counts as reproduced (k: the numbers its fit reads)."""
        scale = float(np.sqrt(np.mean(y ** 2)))
        t = REL * scale
        if self.q and self.q <= self.fine * float(np.max(np.abs(y))):
            t = max(t, ROUND * self.q * (1.0 + (float(np.sum(np.abs(k))) if k is not None else 0.0)))
        return t

    def exact(self, y: np.ndarray, rows: np.ndarray | None = None, most: int = MAX_TERMS, least: int = 0):
        """The smallest column set reproducing y (on rows), as (indices, numbers), or None."""
        Z = self.Z if rows is None else self.Z[:, rows]
        yy = y if rows is None else y[rows]
        if len(yy) < 5:
            return None
        for n in range(least, most + 1):
            best = None
            subs = [()] if n == 0 else self.ranked(y, n, on=rows, posed_on=True)   # (k8s-317) the screen
            for sub in subs:
                if n == 0:
                    k, r = np.zeros(0), yy
                else:
                    A = Z[list(sub)].T
                    if not (self.posed(sub) if rows is None else _posed(A)):
                        continue
                    k, *_ = np.linalg.lstsq(A, yy, rcond=None)
                    r = yy - A @ k
                rms = float(np.sqrt(np.mean(r ** 2)))
                if rms <= self.tol(yy, k) and (best is None or rms < best[2]):
                    best = (list(sub), k, rms)
            if best is not None:
                return best[0], best[1]
        return None

    def floored(self, r: np.ndarray, most: int = MAX_TERMS):
        """The smallest column set w with max(0, Z w) = r on every step, as (indices, numbers), or None.
        Fitted by censored least squares: every step at first, then without the steps where r is 0 and
        Z w is clearly below 0 (the floor binds there), until they stop changing. (k8s-317) Remembered by r:
        a row still on most steps leaves the same r under every linear part that reads nothing there."""
        key = (r.tobytes(), most)
        memo = self.__dict__.setdefault("_floored", {})
        if key not in memo:
            memo[key] = self._floored_read(r, most)
        return memo[key]

    def _floored_read(self, r: np.ndarray, most: int):
        T = len(r)
        zero = np.abs(r) <= self.tol(r)
        pool = [j for j, c in enumerate(self.names) if not c.startswith(COUNT)]   # a counted flow is an amount, never floored
        moving = ~zero                                    # (k8s-317) where r is not 0 the rate is Z w itself: the screen
        for n in range(1, most + 1):
            best = None
            subs = self.ranked(r, n, on=moving, pool=pool) if moving.sum() > n + 1 else itertools.combinations(pool, n)
            for sub in subs:
                A = self.Z[list(sub)].T
                if not self.posed(sub):
                    continue                              # (k-312) collinear columns read nothing here either (COND)
                use = np.ones(T, bool)
                for _ in range(12):
                    w, *_ = np.linalg.lstsq(A[use], r[use], rcond=None)
                    h = A @ w
                    new = ~(zero & (h < -self.tol(r, w)))
                    if np.array_equal(new, use) or new.sum() < n + 2:
                        break
                    use = new
                rms = float(np.sqrt(np.mean((np.maximum(0.0, h) - r) ** 2)))
                if rms <= self.tol(r, w) and (best is None or rms < best[2]):
                    best = (list(sub), w, rms)
            if best is not None:
                return best[0], best[1]
        return None

    def hinge(self, y: np.ndarray):
        """(linear part, sign, hinge part) for y = linear + sign x max(0, hinge), or None."""
        T = len(y)
        best = None
        for n in range(0, BASE_TERMS + 1):
            for sub in itertools.combinations(range(self.Z.shape[0]), n):
                A = self.Z[list(sub)].T if n else np.zeros((T, 0))
                keep = np.ones(T, bool)
                k = np.zeros(n)
                while n:                                # backward trimming: the steps where the hinge is 0
                    k, *_ = np.linalg.lstsq(A[keep], y[keep], rcond=None)
                    r = y - A @ k
                    if np.sqrt(np.mean(r[keep] ** 2)) <= self.tol(y[keep], k) or keep.sum() < QUIET * T:
                        break
                    on = np.flatnonzero(keep)
                    drop = on[np.argsort(-np.abs(r[on]), kind="stable")[:max(1, len(on) // 20)]]
                    keep[drop] = False
                r = y - (A @ k if n else 0.0)
                keep = np.abs(r) <= max(self.tol(y[keep], k), 1e-300)
                if keep.sum() < QUIET * T or keep.all():
                    continue
                rest = r[~keep]
                sign = 1.0 if np.all(rest > 0) else (-1.0 if np.all(rest < 0) else 0.0)
                if not sign:
                    continue
                got = self.floored(sign * r)
                if got is None:
                    continue
                idx, w = got
                cost = n + len(idx)
                if best is None or cost < best[0]:
                    best = (cost, (list(sub), k), sign, (idx, w))
            if best is not None and best[0] <= n + 1:
                break
        return None if best is None else best[1:]


    def regime(self, y: np.ndarray, use: np.ndarray, most: int = BASE_TERMS, share: float = 0.05, least: int | None = None):
        """The linear piece of y exact on the most steps of `use` (at least `share` of all steps), as
        (indices, numbers, mask of the steps it holds on), or None. Exact data: for each column set, the
        numbers solved exactly on SAMPLES random sets of as many steps (a seeded draw), the one exact on the
        most steps kept and refitted on them (least squares over a mixture of pieces fits none of them)."""
        T = len(y)
        least = max(5, int(share * T)) if least is None else least
        on = np.flatnonzero(use)
        if len(on) < least:
            return None
        rng = np.random.default_rng(0)
        scale = REL * float(np.sqrt(np.mean(y[on] ** 2)))
        fine = bool(self.q and self.q <= self.fine * float(np.max(np.abs(y[on]))))
        best = None
        for n in range(1, most + 1):
            picks = np.array([rng.choice(on, n, replace=False) for _ in range(SAMPLES)])
            for sub in itertools.combinations(range(self.Z.shape[0]), n):
                Zs = self.Z[list(sub)]
                M = np.transpose(Zs[:, picks], (1, 2, 0))          # samples x steps x columns
                k = np.einsum("sij,sj->si", np.linalg.pinv(M), y[picks])
                r = np.abs(y[on][None, :] - k @ Zs[:, on])
                moves = (np.abs(Zs[:, on]) > 0).astype(float)       # a column rounds only where it is not 0
                tol = np.maximum(scale, ROUND * self.q * (1.0 + np.abs(k) @ moves)) if fine else np.full(r.shape, scale)
                cnt = (r <= tol).sum(1)
                j = int(np.argmax(cnt))
                if cnt[j] < least or (best is not None and cnt[j] <= best[2].sum()):
                    continue
                hold = np.zeros(T, bool)
                hold[on[r[j] <= tol[j]]] = True
                A = Zs.T
                if not _posed(A[hold]):
                    continue
                nz = (np.abs(Zs) > 0).astype(float)
                for _ in range(2):
                    kk, *_ = np.linalg.lstsq(A[hold], y[hold], rcond=None)
                    tk = np.maximum(scale, ROUND * self.q * (1.0 + np.abs(kk) @ nz)) if fine else np.full(T, scale)
                    hold = use & (np.abs(y - A @ kk) <= tk)
                    if hold.sum() < least:
                        break
                if hold.sum() >= least and (best is None or hold.sum() > best[2].sum()):
                    best = (list(sub), kk, hold)
        return best

    def pieces(self, y: np.ndarray, most: int = 3, relaxed: bool = False):
        """y's largest linear pieces, peeled one after another (each on the steps the earlier ones leave),
        every column a piece does not need dropped: [(indices, mask)]."""
        use, out = np.ones(len(y), bool), []
        for _ in range(most):
            got = self.regime(y, use)
            if got is None and out and relaxed and use.sum() >= SMALL:   # (k-312) a branch that binds on few steps:
                got = self.regime(y, use, least=max(SMALL, int(0.05 * use.sum())))   # a share of the steps left
            if got is None:
                break
            sub, _, hold = got
            for j in list(sub):                              # a column the piece holds as well without
                rest = [c for c in sub if c != j]
                if not rest:
                    continue
                A = self.Z[rest].T
                k, *_ = np.linalg.lstsq(A[hold], y[hold], rcond=None)
                if float(np.sqrt(np.mean((y[hold] - A[hold] @ k) ** 2))) <= self.tol(y[hold], k):
                    sub = rest
            out.append((list(sub), hold))
            use = use & ~hold
            if use.sum() < 5:
                break
        return out

    def two_regimes(self, y: np.ndarray):
        """y = lin + s x max(0, min(u, v)), read from its linear pieces: one piece is lin (where the floor
        binds; or, with two pieces only, their common columns), the others lin + s u and lin + s v. The
        numbers are fitted on every step at once, each step on the branch it is on, until the branches stop
        changing; the result must be exact on every step. (lin, s, u, v) as {column index: number}, or None."""
        strict = self.pieces(y)
        got = self._two_regimes(y, strict)
        if got is None:                                  # (k-312) again with a later piece read from a share of
            relaxed = self.pieces(y, relaxed=True)       # the steps left (a branch binding on under 5% of all)
            if len(relaxed) > len(strict):
                got = self._two_regimes(y, relaxed)
        return got

    def _two_regimes(self, y: np.ndarray, regs: list):
        T = len(y)
        if len(regs) < 2:
            return None
        roles = []
        for perm in itertools.permutations(range(len(regs))):
            if len(regs) >= 3:
                roles.append((regs[perm[0]], regs[perm[1]], regs[perm[2]]))
            if perm[-1] != len(regs) - 1 or len(regs) == 2:
                roles.append((None, regs[perm[0]], regs[perm[1]]))
        vanish = lambda P, Q, lc: [c for c in P[0] if c not in lc and not np.any(np.abs(self.Z[c][Q[1]]) > (self.q or 0.0))]  # noqa: E731
        more = []                                              # (k-312) two pieces: lin is their common columns, and also
        for F, U, V in roles:                                  # each column one piece reads that is 0 on the other's steps
            common = [c for c in U[0] if c in V[0]]            # (dropped there as unneeded: it may be lin's)
            if F is None and vanish(U, V, common) + vanish(V, U, common):
                more.append((F, U, V, True))
        keep = [(F, U, V, False, c) for F, U, V in roles if F is None for c in U[0] if c in V[0]]
        for role in roles + more + keep:                       # (k8s-316) keep: a column both pieces read is lin's and
            F, U, V = role[:3]                                 # also stays in V's branch (a cap 80 - 0.2 x the receiver)
            if F is not None:
                lc, uc, vc = list(F[0]), list(U[0]), list(V[0])
            else:
                lc = [c for c in U[0] if c in V[0]]
                if len(role) == 4 and role[3]:
                    lc = lc + vanish(U, V, lc) + vanish(V, U, lc)
                uc, vc = [c for c in U[0] if c not in lc], [c for c in V[0] if c not in lc]
                if len(role) == 5:
                    vc = vc + [role[4]]
            if not uc or not vc:
                continue
            act = np.full(T, -1)
            if F is not None:
                act[F[1]] = 0
            act[U[1]], act[V[1]] = 1, 2
            for s in (1.0, -1.0):
                got = self._branches(y, lc, uc, vc, s, act, F is not None)
                if got is None:
                    continue
                cols, a = [lc, uc, vc], got[1]
                for part in (1, 2, 0):                       # the fewest columns that stay exact (a column every
                    for c in list(cols[part]):               # branch holds is lin's, never u's or v's)
                        if part and len(cols[part]) == 1:
                            continue
                        trial = [list(x) for x in cols]
                        trial[part].remove(c)
                        g2 = self._branches(y, *trial, s, a, F is not None)
                        if g2 is not None:
                            cols, got, a = trial, g2, g2[1]
                kl, ku, kv = got[0]
                lc, uc, vc = cols
                return ({i: float(x) for i, x in zip(lc, kl)}, s, {i: float(x) for i, x in zip(uc, ku)},
                        {i: float(x) for i, x in zip(vc, kv)})
        return None

    def _branches(self, y, lc, uc, vc, s, act, floor):
        """The numbers of lin + s max(0, min(u, v)) fitted on every step at once, each step on its branch
        (act: 0 the floor, 1 u, 2 v, -1 unknown), the branches re-read until they stop changing:
        ((lin, u, v numbers), branches) when exact on every step, else None."""
        T = len(y)
        a = act.copy()
        for _ in range(5):
            on = a >= 0
            D = np.zeros((T, len(lc) + len(uc) + len(vc)))
            D[:, :len(lc)] = self.Z[lc].T
            D[a == 1, len(lc):len(lc) + len(uc)] = s * self.Z[uc].T[a == 1]
            D[a == 2, len(lc) + len(uc):] = s * self.Z[vc].T[a == 2]
            if on.sum() <= D.shape[1]:
                return None
            k, *_ = np.linalg.lstsq(D[on], y[on], rcond=None)
            kl, ku, kv = k[:len(lc)], k[len(lc):len(lc) + len(uc)], k[len(lc) + len(uc):]
            L0, Uv, Vv = self.Z[lc].T @ kl, self.Z[uc].T @ ku, self.Z[vc].T @ kv
            m = np.minimum(Uv, Vv)
            b = np.where(m <= 0, 0 if floor else -1, np.where(Uv <= Vv, 1, 2))
            res = L0 + s * np.maximum(0.0, m) - y
            if float(np.sqrt(np.mean(res ** 2))) <= self.tol(y, k) and self._each(y, res, k, lc + uc + vc):
                return (kl, ku, kv), b
            if np.array_equal(b, a):
                return None
            a = b
        return None

    def _each(self, y: np.ndarray, res: np.ndarray, k: np.ndarray, cols: list) -> bool:
        """(k8s-316) On finely rounded data, is every step's residual within its rounding? The rms check alone lets
        a branch drop a column that matters on a few steps only (the pool's cap 80 - 0.2 x active, where active
        sits at 80 on every capped step but the first of each spell: one step in 300 off by 0.018, rms 0.001).
        A step's rounding is the change's and each rounded column's (the constant is not rounded) times its number."""
        if not (self.q and self.q <= self.fine * float(np.max(np.abs(y)))):
            return True
        w = sum(abs(float(x)) for c, x in zip(cols, k) if self.names[c] != "1")
        return float(np.max(np.abs(res))) <= EACH * ROUND * self.q * (1.0 + w)

    def hinges(self, y: np.ndarray):
        """y = linear + max(0, h_in) - max(0, h_out), one or both hinges present: (linear part, [(sign,
        hinge part)]), or None. The linear part (up to BASE_TERMS columns) holds exactly on at least QUIET
        of the steps; what is left is split by sign, and each sign's part is one floored linear function."""
        T = len(y)
        best = None
        for n in range(0, BASE_TERMS + 1):
            for sub in itertools.combinations(range(self.Z.shape[0]), n):
                A = self.Z[list(sub)].T if n else np.zeros((T, 0))
                keep = np.ones(T, bool)
                k = np.zeros(n)
                while n:
                    k, *_ = np.linalg.lstsq(A[keep], y[keep], rcond=None)
                    r = y - A @ k
                    if np.sqrt(np.mean(r[keep] ** 2)) <= self.tol(y[keep], k) or keep.sum() < QUIET * T:
                        break
                    on = np.flatnonzero(keep)
                    keep[on[np.argsort(-np.abs(r[on]), kind="stable")[:max(1, len(on) // 20)]]] = False
                r = y - (A @ k if n else 0.0)
                quiet = np.abs(r) <= max(self.tol(y[keep], k), 1e-300)
                if quiet.sum() < QUIET * T or quiet.all():
                    continue
                parts, cost = [], n
                for sign in (1.0, -1.0):
                    part = np.where(quiet, 0.0, np.maximum(0.0, sign * r))
                    if not np.any(part > 0):
                        continue
                    got = self.floored(part)
                    if got is None:
                        parts = None
                        break
                    parts.append((sign, got))
                    cost += len(got[0])
                if not parts:
                    continue
                if best is None or cost < best[0]:
                    best = (cost, (list(sub), k), parts)
            if best is not None:
                break
        return None if best is None else best[1:]


COUNT = "flow:"        # the column of a counter's one-step change (a measured flow)
INNER = (1, 2)         # inner knots tried for a counter's table


def _lin_expr(d: dict, names: list[str]) -> str:
    parts = [repr(float(v)) if names[i] == "1" else f"{float(v)!r} * {names[i]}" for i, v in d.items() if v]
    return " + ".join(parts) or "0"


def _pair(a: str, b: str, y: dict, rows: "_Rows", may) -> dict | None:
    """(k-311) Two rows of one unit that neither form reproduces, read as a pair joined by a floored-MIN move:
    their sum (the move cancels) is linear plus at most one floored inflow and one floored outflow, each on
    a declared side of one of the two; what is left of one row is lin + s x max(0, min(u, v)) (two_regimes),
    and the other row is the sum's linear part less that lin, less the same move. Returns the pieces or None."""
    names, T = rows.names, len(y[a])
    ysum = y[a] + y[b]
    e = rows.exact(ysum)
    if e is not None:
        lin_sum, hs = {i: float(v) for i, v in zip(*e)}, []
    else:
        h = rows.hinges(ysum)
        if h is None:
            return None
        (sub, k), hs = h
        lin_sum = {i: float(v) for i, v in zip(sub, k)}
    ev = lambda d: sum((w * rows.Z[i] for i, w in d.items()), np.zeros(T))  # noqa: E731
    for owners in itertools.product((a, b), repeat=len(hs)):
        if any(not may(s, "in" if sign > 0 else "out") for s, (sign, _) in zip(owners, hs)):
            continue
        if len(set(owners)) < len(owners):
            continue                                     # one hinge a stock
        r = {a: y[a].copy(), b: y[b].copy()}
        hinge_of = {}
        for s, (sign, (idx, w)) in zip(owners, hs):
            amt = np.maximum(0.0, rows.Z[idx].T @ w)
            r[s] -= sign * amt
            hinge_of[s] = (sign, {i: float(v) for i, v in zip(idx, w)})
        for fitted, other in ((a, b), (b, a)):
            got = rows.two_regimes(r[fitted])
            if got is None:
                continue
            lin_g, s, u, v = got                         # r[fitted] = lin_g + s m, m = max(0, min(u, v)) >= 0
            U, V = ev(u), ev(v)
            m = np.maximum(0.0, np.minimum(U, V))
            lin_o = {i: lin_sum.get(i, 0.0) - lin_g.get(i, 0.0) for i in set(lin_sum) | set(lin_g)}
            lin_o = {i: x for i, x in lin_o.items() if abs(x) > 1e-12}
            if float(np.sqrt(np.mean((ev(lin_o) - s * m - r[other]) ** 2))) > rows.tol(r[other], np.array(list(lin_o.values()) or [0.0])):
                continue
            tu, tv = _lin_expr(u, names), _lin_expr(v, names)
            if np.all(U >= -rows.tol(U)) and np.all(V >= -rows.tol(V)):
                expr = f"min({tu}, {tv})"                  # (k8s-316) a floor that never binds is not written (the engine floors the rate)
            elif np.all(U >= -rows.tol(U)):
                expr = f"min({tu}, max(0, {tv}))"          # the argument that never goes below 0 needs no floor
            elif np.all(V >= -rows.tol(V)):
                expr = f"min(max(0, {tu}), {tv})"
            else:
                expr = f"max(0, min({tu}, {tv}))"
            src, dst = (other, fitted) if s > 0 else (fitted, other)
            return {"lin": {fitted: lin_g, other: lin_o}, "hinges": hinge_of,
                    "move": {"id": f"reread_min:{src}:{dst}", "from": src, "to": dst, "rate": {"form": "expr", "expr": expr}},
                    "numbers": np.array(list(lin_g.values()) + list(u.values()) + list(v.values()))}
    return None


def _hats(z: np.ndarray, knots: np.ndarray) -> np.ndarray:
    out = np.zeros((len(z), len(knots)))
    for j in range(len(knots)):
        e = np.zeros(len(knots))
        e[j] = 1.0
        out[:, j] = np.interp(z, knots, e)
    return out


def _table(y: np.ndarray, x: np.ndarray, z: np.ndarray, inner: int):
    """Knots and heights (>= 0) of y = x T(z) with `inner` inner knots placed where the table bends, and
    the rms residual."""
    lo, hi = float(z.min()), float(z.max())

    def fit(u):
        kn = np.concatenate([[lo], np.sort(np.clip(u, lo + 1e-9 * (hi - lo), hi - 1e-9 * (hi - lo))), [hi]])
        if np.any(np.diff(kn) <= 1e-9 * (hi - lo)):
            return kn, None, np.full(len(y), 1e6)
        H = _hats(z, kn) * x[:, None]
        h, _ = nnls(H, y)
        return kn, h, H @ h - y

    on = y > 1e-12 * float(np.max(np.abs(y)))
    starts = set(np.quantile(z, np.linspace(0, 1, 14)[1:-1]).tolist())   # a grid where the data are, and where the table starts
    if on.any() and (~on).any():
        starts |= {float(z[on].min()), float(z[~on].max())}
    best = None
    for start in sorted(a for a in starts if lo < a < hi):   # the first knot from the grid, then refined
        u0 = np.linspace(start, hi, inner + 1)[:-1] if inner > 1 else np.array([start])
        r = float(np.sqrt(np.mean(fit(u0)[2] ** 2)))
        if best is None or r < best[0]:
            best = (r, u0)
    if best is None:   # no starting knot lies strictly inside the data's range (e.g. Y sits on its extremes)
        return None
    try:
        u = least_squares(lambda v: fit(v)[2], best[1], method="trf", diff_step=1e-4, max_nfev=200).x
    except (ValueError, np.linalg.LinAlgError):
        u = best[1]
    kn, h, res = fit(u)
    return (kn, h, float(np.sqrt(np.mean(res ** 2)))) if h is not None else None


def _counter_rate(y: np.ndarray, rows: "_Rows", ids: list[str], L: np.ndarray, skip: str):
    """A counter's row as X x T(Y) reproduced to the row's tolerance: (rate, effects) or None."""
    if not np.any(np.abs(y) > rows.tol(y)) or np.any(y < -rows.tol(y)):
        return None
    tol = rows.tol(y)
    found = None
    for inner in INNER:
        for xi, X in enumerate(ids):
            x = L[xi]
            if X == skip or np.any(x < 0) or np.any((x <= 0) & (np.abs(y) > tol)):
                continue
            for zi, Y in enumerate(ids):
                z = L[zi]
                if Y == skip or Y == X or np.ptp(z) <= 0:
                    continue
                kn16 = np.quantile(z, np.linspace(0, 1, 16))   # a quick screen: some table of Y at all
                on = np.abs(y) > tol
                if on.any() and (~on).any():                   # (k-311) and the table's onset, where the counter starts
                    kn16 = np.concatenate([kn16, [z[on].min(), z[~on & (z < z[on].min())].max() if np.any(~on & (z < z[on].min())) else z.min()]])
                kn16 = np.unique(kn16)
                H = _hats(z, kn16) * x[:, None]
                h16, _ = nnls(H, y)
                if float(np.sqrt(np.mean((H @ h16 - y) ** 2))) > 0.05 * float(np.sqrt(np.mean(y ** 2))):
                    continue
                got = _table(y, x, z, inner)
                if got is None or got[2] > tol:
                    continue
                if found is None or got[2] < found[0]:
                    kn, h, rms = got
                    found = (rms, X, Y, [[float(a), float(b)] for a, b in zip(kn, h)])
        if found is not None:
            break
    if found is None:
        return None
    _, X, Y, pts = found
    return {"form": "proportional", "stock": X, "k": 1.0}, [{"stock": Y, "shape": "table", "points": pts}]


def _rate(terms: dict, names: list[str]) -> dict:
    c = float(terms.pop("1", 0.0))
    ts = [{"stock": k, "k": float(v)} for k, v in terms.items() if v]
    if not c and len(ts) == 1:
        return {"form": "proportional", "stock": ts[0]["stock"], "k": ts[0]["k"]}
    if not ts:
        return {"form": "constant", "value": c}
    return {"form": "linear", "c": c, "terms": ts}


def _flow(a, b, rate: dict, inputs: set) -> dict:
    f = {"from": a, "to": b, "rate": rate}
    reads = {rate.get("stock")} | {t.get("stock") for t in rate.get("terms") or []}
    reads.discard(None)
    if a is None and len(reads) == 1 and reads <= inputs and rate.get("form") == "proportional":
        f["input"] = next(iter(reads))
    return f


def _block(block: list[str], y: dict, rows: _Rows, unit: dict, final: set, inputs: set, fixed=(), counted=None, may=None):
    """The block's flows from its rows, and the rows they do not reproduce."""
    names = rows.names
    lin, hinges, left, tols = {}, {}, [], {}
    for s in block:
        got = rows.exact(y[s])
        if got is not None:
            lin[s] = {names[i]: float(k) for i, k in zip(*got)}
            tols[s] = rows.tol(y[s], got[1])
            continue
        if s in final:
            left.append(s)
            continue
        h = rows.hinge(y[s])
        if h is None:
            left.append(s)
            continue
        (sub, k), sign, (idx, w) = h
        lin[s] = {names[i]: float(v) for i, v in zip(sub, k)}
        hinges[s] = (sign, {names[i]: float(v) for i, v in zip(idx, w)})
        tols[s] = rows.tol(y[s], np.concatenate([k, w]))
    moves = []
    if may is not None:                                   # (k-312) two rows of one unit with equal and opposite hinges
        for a, b in itertools.combinations([s for s in block if s in hinges], 2):   # carry one amount from one to the
            (sa, wa), (sb, wb) = hinges.get(a, (0, None)), hinges.get(b, (0, None))  # other: a move, read as a pair
            if wa is None or wb is None or sa != -sb or unit.get(a) != unit.get(b) or set(wa) != set(wb):
                continue
            if any(abs(wa[c] - wb[c]) > 1e-3 * max(abs(wa[c]), abs(wb[c])) for c in wa):
                continue
            got = _pair(a, b, y, rows, may)
            if got is None:
                continue
            for s in (a, b):
                hinges.pop(s)
                lin[s] = {names[i]: float(v) for i, v in got["lin"][s].items()}
                if s in got["hinges"]:
                    sign, w = got["hinges"][s]
                    hinges[s] = (sign, {names[i]: float(v) for i, v in w.items()})
                tols[s] = rows.tol(y[s], got["numbers"])
            moves.append(got["move"])
    if may is not None:                                   # (k-312) a row left and a hinged row of its unit: the hinge
        for a in [s for s in left if s not in final]:     # may be one side of a MIN move between them
            for b in [s for s in block if s in hinges and unit.get(s) == unit.get(a)]:
                if a not in left or b not in hinges:
                    continue
                got = _pair(a, b, y, rows, may)
                if got is None:
                    continue
                left.remove(a)
                hinges.pop(b)
                for s in (a, b):
                    lin[s] = {names[i]: float(v) for i, v in got["lin"][s].items()}
                    if s in got["hinges"]:
                        sign, w = got["hinges"][s]
                        hinges[s] = (sign, {names[i]: float(v) for i, v in w.items()})
                    tols[s] = rows.tol(y[s], got["numbers"])
                moves.append(got["move"])
    if may is not None:                                   # (k-311) two rows left: a pair joined by a floored-MIN move
        free = [s for s in left if s not in final]
        for a, b in itertools.combinations(free, 2):
            if a not in left or b not in left or unit.get(a) != unit.get(b):
                continue
            got = _pair(a, b, y, rows, may)
            if got is None:
                continue
            for s in (a, b):
                left.remove(s)
                lin[s] = {names[i]: float(v) for i, v in got["lin"][s].items()}
                if s in got["hinges"]:
                    sign, w = got["hinges"][s]
                    hinges[s] = (sign, {names[i]: float(v) for i, v in w.items()})
                tols[s] = rows.tol(y[s], got["numbers"])
            moves.append(got["move"])
    pair: dict = {}

    def add(a, b, col, v):
        pair.setdefault((a, b), {})
        pair[(a, b)][col] = pair[(a, b)].get(col, 0.0) + v

    size_of = lambda c: float(np.sqrt(np.mean(rows.Z[names.index(c)] ** 2)))  # noqa: E731
    cols = sorted({c for d in lin.values() for c in d})
    for col in cols:
        got = {s: d[col] for s, d in lin.items() if abs(d.get(col, 0.0)) > 0}
        lin_col = dict(got)
        neg = [s for s, v in got.items() if v < 0]
        pos = [s for s, v in got.items() if v > 0]
        src = col if col in neg else (neg[0] if len(neg) == 1 else None)
        if src is not None and src in final:
            src = None
        if src is not None:
            give = -got[src]
            for p in sorted(pos, key=lambda s: -got[s]):
                if unit.get(p) != unit.get(src) or give <= 0 or col == COUNT + p:   # a counter counts: its own column is its inflow
                    continue
                m = min(got[p], give)
                if m <= SNAP * max(abs(x) for x in lin_col.values()) and m * size_of(col) <= tols[p]:
                    continue                              # (k-311) a move at the fit's precision is no move
                add(src, p, col, m)
                give -= m
                got[p] -= m
            got[src] = -give
        big = max(abs(v) for v in lin_col.values())
        size = float(np.sqrt(np.mean(rows.Z[names.index(col)] ** 2)))
        for s, v in got.items():
            if abs(v) > SNAP * big and abs(v) * size > tols[s]:   # what is left of a matched term at the fit's precision is no flow
                if v > 0:
                    add(None, s, col, v)
                else:
                    add(s, None, col, -v)
    flows = []
    counted = counted or {}
    for (a, b), terms in pair.items():
        for col in [c for c in terms if c.startswith(COUNT)]:
            v = terms.pop(col)
            if col[len(COUNT):] not in counted:
                return None
            rate, eff = counted[col[len(COUNT):]]
            flows.append({"from": a, "to": b, "rate": {**rate, "k": float(rate["k"]) * v}, "effects": copy.deepcopy(eff)})
        if not terms:
            continue
        if a is None and b in fixed and set(terms) <= inputs and len(terms) == 1:
            (n_, k_), = terms.items()
            if abs(k_ - 1.0) <= 1e-3:
                terms = {n_: 1.0}                         # a side declared "input" is 1 x the input (boundary.py)
        flows.append(_flow(a, b, _rate(dict(terms), names), inputs))
    for s, (sign, w) in hinges.items():
        key = (None, s) if sign > 0 else (s, None)
        if key in pair:
            return None                                   # a hinge and a linear outside flow on one side
        flows.append(_flow(*key, _rate(dict(w), names), inputs))
    return flows + moves, left, tols


def _bridges(bad: list[str], stocks: list[dict], run: dict) -> list[tuple[str, str]]:
    """(k8s-316) Pairs (x, z) of unexplained rows that the declared boundary joins across units (capmin.forced_pairs:
    each the only non-final stock of its unit, x with no outside outflow declared, z with no outside inflow), so what
    leaves x can only go into z. A move joins stocks of one unit everywhere else (pgbouncer's waiting clients getting
    pool connections: queries -> connections)."""
    from .capmin import forced_pairs

    return [(x, z) for x, z in forced_pairs(stocks, run) if x in bad and z in bad]


def _per_side(flows: list[dict], b) -> list[dict]:
    """(k8s-316) One flow per declared side: an outside flow of plain linear terms on a stock whose side the
    boundary declares n > 1 times (estimate) is split into n flows when it has exactly n terms and no constant,
    one term each (the two services' queries into one wait queue). Anything else is left as it is."""
    out = []
    for f in flows:
        r = f.get("rate") or {}
        side = ("in", f.get("to")) if f.get("from") is None else ("out", f.get("from")) if f.get("to") is None else None
        n = b.limit.get((side[1], side[0])) if side else None
        terms = r.get("terms") or []
        if not n or n < 2 or r.get("form") != "linear" or float(r.get("c") or 0.0) or len(terms) != n or f.get("effects"):
            out.append(f)
            continue
        for t in terms:
            g = {k: v for k, v in f.items() if k not in ("rate", "input", "id")}
            g["rate"] = {"form": "proportional", "stock": t["stock"], "k": float(t["k"])}
            out.append(g)
    return out


def apply(result: dict, stocks: list[dict], run: dict, opts: dict | None, log: list | None = None) -> dict:
    """The result with each unit's flows read again from its rows where the answer leaves a row of
    exact data unexplained (see the module docstring)."""
    if not isinstance(result, dict) or not result.get("flows"):
        return result
    opts = opts or {}
    data = _boundary.Data(stocks, run, opts)
    if not data.usable:
        return result
    ids = data.ids
    t = [float(x) for x in run["t"]]
    at = {x: i for i, x in enumerate(t)}
    ins = []
    for name, v in (opts.get("inputs") or {}).items():
        if name in ids or str(name).startswith("capmin__"):
            continue
        v = np.asarray(v, dtype=float)
        if len(v) != len(t):
            continue
        ins.append((name, np.array([v[at[float(x)]] for x in data.tt])))
    from .hidden import _change                           # expression rates (a MIN) evaluated as the engine does (k-311)
    try:
        resid = data.dy - _change(result["flows"], data, dict(ins))
    except Exception:                                     # noqa: BLE001  (an expression reading what is not measured)
        try:
            resid = data.dy - data.change(result["flows"])
        except Exception:                                 # noqa: BLE001  (a flow the simulator cannot evaluate)
            return result
    names = ids + [n for n, _ in ins] + ["1"]
    Z = np.vstack([data.L] + [u[None, :] for _, u in ins] + [np.ones((1, data.T))])
    levels = np.array([np.asarray(run["levels"][i], dtype=float) for i in ids])
    rows = _Rows(data, Z, names, _quantum(levels))
    final = {s["id"] for s in stocks if s.get("final")}
    counted = {}
    for i, s in enumerate(ids):                           # counters that are a level times a table (5.)
        if s in final and rows.exact(data.dy[i]) is None:
            got = _counter_rate(data.dy[i], rows, ids, data.L, s)
            if got is not None:
                counted[s] = got
    if counted:
        names = names + [COUNT + s for s in counted]
        Z = np.vstack([Z] + [data.dy[ids.index(s)][None, :] for s in counted])
        rows = _Rows(data, Z, names, rows.q)
    ok, exact_any = {}, bool(counted)
    for i, s in enumerate(ids):
        e = rows.exact(data.dy[i])
        if e is not None and np.any(np.abs(data.dy[i]) > rows.tol(data.dy[i])):
            exact_any = True                              # some row that moves is reproduced: the data are exact
        ok[s] = float(np.sqrt(np.mean(resid[i] ** 2))) <= 2 * rows.tol(data.dy[i], None if e is None else e[1])   # as the check below
    bad = [s for s in ids if not ok[s]]
    if not bad:
        return result
    unit = {s["id"]: s.get("unit") or "" for s in stocks}
    inputs = {n for n, _ in ins}
    b = _boundary.Boundary(run)
    flows = copy.deepcopy(result["flows"])
    trace = []

    def read(block: list[str], unit_of: dict, label: str, ok: dict) -> None:
        nonlocal flows
        inside = set(block)
        touches = lambda f: bool({f.get("from"), f.get("to")} & inside)  # noqa: E731
        kept = [f for f in flows if not touches(f)]
        y = {s: data.dy[ids.index(s)] for s in block}
        got = _block(block, y, rows, unit_of, final, inputs, set(b.fixed), counted,
                     may=(lambda s_, side: b.may(s_, side, "estimate")) if exact_any else None)
        if got is None:
            return
        new, left, tols = got
        moved = lambda s_: any(s_ in (f.get("from"), f.get("to")) and f.get("from") is not None  # noqa: E731
                               and f.get("to") is not None for f in flows)
        if any(ok[s] and moved(s) for s in left) or not any(s not in left for s in block if not ok[s]):
            return
        own = [f for f in flows if touches(f) and ((f.get("from") in left and f.get("to") is None)
                                                  or (f.get("to") in left and f.get("from") is None))]
        new = _per_side(new, b)
        cand = kept + new + own
        if _boundary.violations(new, ids, b, inputs | {n for n in (opts.get("inputs") or {})}):
            return
        try:
            r2 = data.dy - _change(cand, data, dict(ins))
        except Exception:                                 # noqa: BLE001
            return
        if any(float(np.sqrt(np.mean(r2[ids.index(s)] ** 2))) > 2 * tols[s] for s in block if s not in left):
            return                                        # the written flows (floored by the engine) must reproduce the rows
        flows = cand
        trace.append(f"{label}: {len(new)} flows re-read from {len(block) - len(left)} exact rows; kept {left}")

    for u in sorted({unit[s] for s in bad}):
        read([s for s in ids if unit[s] == u], unit, u, ok)
    if b.declared:                                        # (k8s-316) a move the declared boundary forces across units
        try:
            r3 = data.dy - _change(flows, data, dict(ins))
        except Exception:                                 # noqa: BLE001
            r3 = None
        if r3 is not None:
            ok3 = {s: float(np.sqrt(np.mean(r3[i] ** 2))) <= 2 * rows.tol(data.dy[i]) or ok[s] for i, s in enumerate(ids)}
            for x, z in _bridges([s for s in ids if not ok3[s]], stocks, run):
                if not ok3[x] and not ok3[z]:
                    read([x, z], {**unit, z: unit[x]}, f"{unit[x]} -> {unit[z]}", ok3)
                    try:
                        r3 = data.dy - _change(flows, data, dict(ins))
                        ok3 = {s: float(np.sqrt(np.mean(r3[i] ** 2))) <= 2 * rows.tol(data.dy[i]) or ok3[s] for i, s in enumerate(ids)}
                    except Exception:                     # noqa: BLE001
                        break
    if not trace:
        return result
    out = dict(result)
    out["flows"] = flows
    out["reread"] = trace
    if log is not None:
        log.extend(trace)
    return out
