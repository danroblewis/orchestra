"""The noise-tolerant structure search of z3robust: Z3 in place of z3exact's exact equality
(docs/research/z3robust.md).

**The equations Z3 reads** (`Compressed`, the default): every one-step equation, rotated. With the columns
X = U diag(d) V' (gross steps left out first: a residual of the all-column fit beyond GROSS robust noise
levels in some stock), a stock's squared misfit is ||U'y - diag(d) V' k||^2 plus a constant no structure
changes, so q = rank(X) rows per stock carry every step's evidence, and under the true structure each
rotated residual is one step's noise (white). Each stock's rows are divided by its noise level sigma_s
(the robust scatter of its all-column one-step residuals, never below the data's rounding). `Blocks`
(sums of consecutive steps) is the alternative tried first; it averaged away the fluctuations that
identify drains near equilibrium.

**The search** (encoding "band", the default): an epsilon band that grows with the noise. Every stock's
rotated residuals must lie in an L1 ball of 0.8 q + BALL_Z x 0.6 sqrt(q) noise units (what q unit normal
residuals reach; doubled, then quadrupled, when nothing fits), with a Boolean per term (its number is 0
unless included). Z3 (a Solver with an AtMost(k) assumption, k lowered from the last structure found
until "unsat") finds the fewest terms that fit, then lists the other structures of that size; those, and
the warm start (backward elimination on L1 + price), are compared on L1 + PRICE_Q sqrt(log T) per term,
with each structure's L1-optimal numbers (HiGHS). The other encodings were measured and are kept for
comparison (`compare.py`): "weighted" (one OMT objective, L1 beyond a band + If(b, price, 0), local
branching around the warm start), "maxsmt" (a hard band with soft outlier marks and soft terms, MaxRes),
"ladder" (the L1 as a staircase of soft constraints). Z3's optimiser timed out on 18-30 candidates
where the cardinality search takes seconds.

A declared "input" inflow's number is fixed at 1; a link (an outside term reading another stock) is an
inflow (its number >= 0); a one-sided outside flow is kept at or above 0 on SIGN_STEPS steps. At most
MAX_TERMS candidates (`screen`), coefficients rounded to enough significant digits for the equations'
size in noise units, and a timeout; solve_guarded runs Z3 in a forked process and kills it past its
timeout (Z3 does not always honour it).
"""

from __future__ import annotations

import math
import time
from fractions import Fraction

import numpy as np
import z3

from . import core

BLOCKS = 40           # equations per stock given to Z3 at most
MIN_PER_ERA = 8       # at least this many blocks per announced era (when it has that many steps)
MAX_TERMS = 30        # candidate terms given to Z3 at most (screened above that)
T_SCREEN = 2.5        # a (stock, column) pair is a candidate when its least-squares number's |t| exceeds this
Z_BAND = 1.0          # the epsilon band, in noise units
PRICE = 1.0           # a term's price, x log(n S) (n blocks, S stocks)
DIGITS = 6            # significant digits of the coefficients Z3 reads (at least)
MAX_DIGITS = 15       # at most
MAD = 1.4826          # a normal scatter from the median absolute deviation
HARD_BAND = 4.0       # maxsmt: every block not marked an outlier is within this many noise units
OUTLIER = 3.0         # maxsmt: a block marked an outlier costs this (in the term price's units)
LEVELS = 8            # ladder: soft constraints per residual
STAIR = 1.0           # ladder: a stair's width in noise units (each stair crossed costs 1)
Q_BAND = 0.0          # compressed: the band on a rotated residual, in noise units
PRICE_Q = 1.0         # compressed: a term's price, x sqrt(log T)
SIGN_STEPS = 24       # compressed: steps a one-sided outside flow is kept >= 0 on
GROSS = 5.0           # compressed: a step whose all-column residual exceeds this many robust noise levels is left out
OPTSMT = "basic"      # Z3's optsmt engine ('basic' or 'symba')
NEAR = 2              # weighted: the first radius of switches around the incumbent Z3 searches
RADIUS_STEP = 2       # weighted: the radius grows by this when Z3 finds nothing better within it
BALL_Z = 1.0          # band: a row's L1 ball is 0.8 q + BALL_Z x 0.6 sqrt(q) noise units (q rotated equations)
WIDEN = (1.0, 2.0, 4.0)  # band: the ball's scales tried in turn while nothing fits
ENUM_SECONDS = 5.0    # band: seconds spent listing the other smallest structures at most
TIE = 0.5             # band: structures within this of the best L1 + price are rivals the data cannot rank;
                      # of those, the fewest moves (a move claims conservation between two stocks)
ENUM_CAP = 12         # band: smallest structures compared at most
WARM_CONTENDS = True  # band: the warm start's structure is compared with Z3's on L1 + price
GRACE = 3.0           # seconds past Z3's timeout before its process is killed
SIGN_PENALTY = 1e6    # warm start: the objective's penalty per link with a negative number
FLOOR = 1e-7          # a stock's noise level is at least this x its typical level and change


class Blocks:
    """The block equations of a problem: X (blocks x columns), Y (stocks x blocks), the steps of each block,
    and each stock's rounding tolerance on a block."""

    def __init__(self, p: core.Problem, n: int | None = None):
        n = BLOCKS if n is None else n
        Xs, Ys = core._floats(p)
        T = p.steps
        era = np.zeros(T, dtype=int)
        for c, col in enumerate(p.cols):
            if col.kind == "const" and col.era is not None:
                era[Xs[:, c] != 0] = col.era
        groups = []
        for e in sorted(set(era.tolist())):
            idx = np.flatnonzero(era == e)
            nb = min(len(idx), max(MIN_PER_ERA, int(round(n * len(idx) / T))))
            groups += [g for g in np.array_split(idx, nb) if len(g)]
        self.steps = groups
        self.X = np.array([Xs[g].sum(axis=0) for g in groups])
        self.Y = np.array([Ys[:, g].sum(axis=1) for g in groups]).T
        m = max(len(g) for g in groups)
        h = float(p.h)
        self.eps = np.array([2 * h + m * max(0.0, float(e) - 2 * h) for e in p.eps])
        self.m = m
        self.signs = self.X

    def band(self, r: int, sigma: np.ndarray) -> float:
        return max(Z_BAND, float(self.eps[r]) / sigma[r])

    def price(self) -> float:
        return PRICE * math.log(max(2, self.n * self.Y.shape[0]))

    @property
    def n(self) -> int:
        return self.X.shape[0]


class Compressed:
    """The rotated equations of a problem (all its steps, Z3 reads few rows): with X = U diag(d) V' (the
    one-step columns, the gross steps left out), each stock's squared misfit is ||U'y - diag(d) V' k||^2 plus
    a constant that no structure changes, so the q rows diag(d) V' (q: X's rank) and U'y carry every step's
    evidence. Under the true structure each rotated residual is the noise of one step (white: U is
    orthonormal), so the L1 of the rotated residuals, in noise units, ranks structures, and a term worth
    |t| standard errors moves it by about |t|. Gross steps (a residual of the all-column fit beyond GROSS
    robust noise levels in some stock) are left out first: the robust part."""

    def __init__(self, p: core.Problem):
        Xs, Ys = core._floats(p)
        A = Xs[:, _base(p)]
        T, q = A.shape
        keep = np.ones(T, dtype=bool)
        sig = []
        for r in range(len(p.ids)):
            a, *_ = np.linalg.lstsq(A, Ys[r], rcond=None)
            res = Ys[r] - A @ a
            s = MAD * float(np.median(np.abs(res - np.median(res)))) * math.sqrt(T / max(1, T - q))
            s = max(s, float(p.eps[r]))           # never below the rounding (noise-free data: no gross steps)
            sig.append(s)
            if s > 0:
                keep &= np.abs(res - np.median(res)) <= GROSS * s
        if keep.mean() < 0.8:
            keep[:] = True
        self.keep = keep
        U, d, Vt = np.linalg.svd(Xs[keep], full_matrices=False)
        rank = int((d > d[0] * 1e-10).sum()) if len(d) else 0
        self.X = d[:rank, None] * Vt[:rank]                # (q, columns): every column, the whole-run ones too
        self.Y = (U[:, :rank].T @ Ys[:, keep].T).T          # (stocks, q)
        self.eps = np.array([float(e) for e in p.eps])     # a rotated residual's rounding is one step's
        self.m = int(keep.sum())
        self.gross = int((~keep).sum())
        self.raw_sigma = np.array(sig)
        self.T = T
        ks = np.flatnonzero(keep)
        self.signs = Xs[ks[np.unique(np.round(np.linspace(0, len(ks) - 1, min(len(ks), SIGN_STEPS))).astype(int))]]

    def band(self, r: int, sigma: np.ndarray) -> float:
        return max(Q_BAND, min(1.0, float(self.eps[r]) / sigma[r]))

    def price(self) -> float:
        """Inclusion when the term is worth more than PRICE_Q x sqrt(log T) standard errors (BIC's threshold
        is sqrt(log T); the rotated L1 moves by about |t|)."""
        return PRICE_Q * math.sqrt(math.log(max(2, self.T)))

    @property
    def n(self) -> int:
        return self.X.shape[0]


def _base(p: core.Problem) -> list[int]:
    """The columns without the whole-run copies (those are sums of the per-era ones)."""
    eras = any(col.era is not None for col in p.cols)
    return [c for c, col in enumerate(p.cols) if not (eras and col.era is None)]


def noise_scales(p: core.Problem, B) -> np.ndarray:
    """Per stock, the noise level of its block equation: 1.4826 x the median absolute deviation of the
    residuals of its block change regressed on every (per-era) column, x sqrt(n / (n - columns)); at least
    the rounding tolerance / Z_BAND and FLOOR x its typical level and change (per block)."""
    if isinstance(B, Compressed):          # the steps' own scatter (computed with the compression)
        Xs, Ys = core._floats(p)
        lv = float(np.abs(Xs[:, [c for c, col in enumerate(p.cols) if col.kind == "stock"]]).mean())
        return np.array([max(B.raw_sigma[r], float(B.eps[r]) / Z_BAND if Z_BAND else float(B.eps[r]),
                             FLOOR * (lv + float(np.sqrt(np.mean(Ys[r] ** 2)))), 1e-12) for r in range(len(p.ids))])
    cols = _base(p)
    A = B.X[:, cols]
    n, q = A.shape
    lv = float(np.abs(B.X[:, [c for c, col in enumerate(p.cols) if col.kind == "stock"]]).mean()) if B.X.size else 1.0
    out = []
    for r in range(len(p.ids)):
        a, *_ = np.linalg.lstsq(A, B.Y[r], rcond=None)
        res = B.Y[r] - A @ a
        s = MAD * float(np.median(np.abs(res - np.median(res)))) * math.sqrt(n / max(1, n - q))
        fl = max(float(B.eps[r]) / Z_BAND, FLOOR * (lv + float(np.sqrt(np.mean(B.Y[r] ** 2)))), 1e-12)
        out.append(max(s, fl))
    return np.array(out)


def screen(p: core.Problem, B: Blocks, sigma: np.ndarray, cap: int | None = None) -> list[int]:
    """The candidate terms Z3 is given: all of them when there are at most cap; else those touching a (stock,
    column) pair whose least-squares number (the stock's change on every per-era column) has |t| > T_SCREEN
    (a whole-run column: any of its eras' pairs; a move: in both its rows), ranked by that |t| (a move: the
    smaller of its two), at most cap."""
    cap = MAX_TERMS if cap is None else cap
    if len(p.terms) <= cap:
        return list(range(len(p.terms)))
    base = _base(p)
    tv = np.zeros((len(p.ids), len(p.cols)))
    A = B.X[:, base]
    for r in range(len(p.ids)):
        a, *_ = np.linalg.lstsq(A, B.Y[r], rcond=None)
        res = B.Y[r] - A @ a
        s2 = float(res @ res) / max(1, len(res) - len(base))
        cov = np.linalg.pinv(A.T @ A) * max(s2, (sigma[r] ** 2) * 1e-6)
        tv[r, base] = np.abs(a) / np.sqrt(np.maximum(np.diag(cov), 1e-300))
    for c, col in enumerate(p.cols):
        if c not in base:          # whole-run column: its eras' largest |t|
            same = [o for o in base if p.cols[o].name == col.name and p.cols[o].kind == col.kind]
            tv[:, c] = tv[:, same].max(axis=1) if same else 0.0
    score = []
    for m, t in enumerate(p.terms):        # a move needs its column clearly in both of its rows (else it is an
        rows = [r for r, sid in enumerate(p.ids) if core._contrib(p, t, sid)]     # outside term in the one)
        score.append((min(tv[r, t.col] for r in rows), m))
    return sorted(m for b, m in sorted(score, reverse=True)[:cap] if b > T_SCREEN)


_digits = [DIGITS]                # the digits of the solve in progress (set by solve)


def _q(v: float) -> z3.ArithRef:
    f = Fraction(f"{v:.{_digits[0]}g}") if v else Fraction(0)
    return z3.RealVal(f"{f.numerator}/{f.denominator}")


def _val(v) -> float | None:
    if z3.is_rational_value(v):
        return float(Fraction(v.numerator_as_long(), v.denominator_as_long()))
    try:
        return float(v.as_decimal(15).rstrip("?"))
    except Exception:  # noqa: BLE001
        return None


ENCODINGS = ("band", "weighted", "maxsmt", "ladder")


def _lsq(p: core.Problem, B, sup: list[int], sigma: np.ndarray, fixed: dict[int, float]) -> dict:
    """Least-squares numbers of a structure on the equations Z3 reads (rows in noise units, jointly)."""
    S, n = B.Y.shape
    G = np.zeros((S * n, len(sup)))
    for j, m in enumerate(sup):
        t = p.terms[m]
        for r, sid in enumerate(p.ids):
            sg = core._contrib(p, t, sid)
            if sg:
                G[r * n:(r + 1) * n, j] = sg * B.X[:, t.col] / sigma[r]
    y = (B.Y / sigma[:, None]).reshape(-1)
    fx = np.array([fixed.get(m, 0.0) for m in sup])
    free = [j for j, m in enumerate(sup) if m not in fixed]
    k = fx.copy()
    if free:
        k[free], *_ = np.linalg.lstsq(G[:, free], y - G @ fx, rcond=None)
    return {m: float(v) for m, v in zip(sup, k)}


def link(p: core.Problem, m: int) -> bool:
    """Is term m a link (an outside term on one stock reading another stock's level)? A link is an inflow
    (its number at or above 0): an outflow is driven by its own stock (SD's convention; a negative link is
    a move or a drain in disguise)."""
    t = p.terms[m]
    c = p.cols[t.col]
    return t.kind == "outside" and c.kind == "stock" and c.name != t.a


def gap_row(p: core.Problem, m: int, sup) -> bool:
    """Does the stock of term m have an outside constant in sup? Then a negative link on it is a goal gap
    (an inflow c - k X), not a drain in disguise."""
    a = p.terms[m].a
    return any(p.terms[x].kind == "outside" and p.terms[x].a == a and p.cols[p.terms[x].col].kind == "const" for x in sup)


def unsigned(p: core.Problem, m: int, sup) -> bool:
    """Must term m's number be at or above 0? A link outside a goal gap."""
    return link(p, m) and not gap_row(p, m, sup)


IDLE_EVENTS = 5       # a one-sided outside flow moves something on at least this many steps (else it is no flow)
IDLE_IN_WARM = False  # the warm start penalises idle flows too (tried: it changed 310's warm start and lost 310 none)


def idle(p: core.Problem, sup: list[int], nums: dict) -> list[int]:
    """(port-z3robust) The terms of each one-sided outside flow (a declared side) whose amount is above 0 on fewer
    than IDLE_EVENTS steps of the record: the engine floors a rate at 0, so such a flow moves nothing, and as the
    answer's own reading of the side it kept the floored gap search (post/hinge.py) from fitting the side
    (k8s-311 none-long: ready's outflow read as -176 x mem by the warm start, which Z3's sign rows would refuse)."""
    X, _ = core._floats(p)
    groups: dict = {}
    for m in sup:
        t = p.terms[m]
        if t.kind == "outside" and len(t.sides) == 1:
            groups.setdefault((t.a, t.sides[0]), []).append(m)
    out = []
    for (_, side), ms in groups.items():
        v = sum(nums[m] * X[:, p.terms[m].col] for m in ms)
        amt = v if side == "in" else -v
        if int((amt > 1e-9 * (float(np.abs(amt).max()) + 1e-300)).sum()) < IDLE_EVENTS:
            out += ms
    return out


def _signed(p: core.Problem, B, sup: list[int], nums: dict, sigma: np.ndarray, price: float) -> float:
    """objective() plus SIGN_PENALTY per link with a negative number and per term of an idle one-sided flow."""
    return (objective(p, B, sup, nums, sigma, price) + SIGN_PENALTY * sum(1 for m in sup if unsigned(p, m, sup) and nums[m] < 0)
            + (SIGN_PENALTY * len(idle(p, sup, nums)) if IDLE_IN_WARM else 0.0))


def warm(p: core.Problem, B, cand: list[int], sigma: np.ndarray, fixed: dict[int, float], price: float) -> tuple[list[int], dict, float]:
    """A first structure (an upper bound for Z3): backward elimination from every candidate, numbers by least
    squares, each round dropping the term whose removal lowers the objective most."""
    sup = list(cand)
    nums = _lsq(p, B, sup, sigma, fixed)
    best = _signed(p, B, sup, nums, sigma, price)
    while sup:
        trials = []
        for m in sup:
            s2 = [x for x in sup if x != m]
            n2 = _lsq(p, B, s2, sigma, fixed)
            trials.append((_signed(p, B, s2, n2, sigma, price), s2, n2))
        o, s2, n2 = min(trials, key=lambda x: x[0])
        if o >= best:
            break
        best, sup, nums = o, s2, n2
    for m in cand:                     # two outside terms on one column with a move between them: the move
        t = p.terms[m]
        if t.kind != "move" or m in sup:
            continue
        pair = [x for x in sup if p.terms[x].kind == "outside" and p.terms[x].col == t.col and p.terms[x].a in (t.a, t.b)]
        if len({p.terms[x].a for x in pair}) < 2:
            continue
        for drop in ([pair[0]], [pair[1]], pair):
            s2 = [x for x in sup if x not in drop] + [m]
            n2 = _lsq(p, B, s2, sigma, fixed)
            o = _signed(p, B, s2, n2, sigma, price)
            if o < best:
                best, sup, nums = o, s2, n2
                break
    return sup, nums, best


def solve(p: core.Problem, B: Blocks, cand: list[int], sigma: np.ndarray, fixed: dict[int, float], timeout: float,
          encoding: str = "maxsmt", price: float | None = None) -> dict:
    """Z3's optimum over the candidate terms on the block equations: {support, numbers (per term, the data's
    units), objective (the L1 beyond the band + the price of the terms), status, seconds, n}. fixed: {term:
    number} included at that number when chosen (a declared input at 1)."""
    if encoding not in ENCODINGS:
        raise ValueError(f"encoding: one of {ENCODINGS}")
    began = time.perf_counter()
    Xs, Ys = B.X, B.Y
    n, S = B.n, len(p.ids)
    price = B.price() if price is None else price
    sc = np.abs(Xs).max(axis=0)
    sc[sc == 0] = 1.0
    band = [B.band(r, sigma) for r in range(S)]
    # enough digits that rounding a coefficient moves a residual by well under a noise unit: the equations'
    # size in noise units (1e5 and more on noise-free data) sets how many are needed
    top = float(np.abs(Ys / sigma[:, None]).max()) if Ys.size else 1.0
    _digits[0] = int(min(MAX_DIGITS, max(DIGITS, 3 + math.ceil(math.log10(max(1.0, top))))))
    SX = B.signs                                   # the rows a one-sided outside flow is kept >= 0 on
    ssc = np.abs(SX).max(axis=0)
    ssc[ssc == 0] = 1.0
    if encoding == "band":          # feasibility under cardinality assumptions: a plain Solver (Optimize's check
        opt = z3.Solver()           # was far slower on the same constraints: 43#4 counts, k = 28 timed out)
    else:
        opt = z3.Optimize()
        opt.set("optsmt_engine", OPTSMT)
    opt.set("timeout", max(1, int(timeout * 1000)))
    b = {m: z3.Bool(f"b{m}") for m in cand}
    w = {m: z3.Real(f"w{m}") for m in cand}        # the term's number x its column's scale
    for m in cand:
        if m in fixed:
            opt.add(z3.Implies(b[m], w[m] == _q(fixed[m] * sc[p.terms[m].col])))
        opt.add(z3.Implies(z3.Not(b[m]), w[m] == 0))
        if link(p, m):                 # a link is an inflow, unless its stock has a constant inflow (a goal gap)
            consts = [b[x] for x in cand if p.terms[x].kind == "outside" and p.terms[x].a == p.terms[m].a
                      and p.cols[p.terms[x].col].kind == "const"]
            opt.add(z3.Or([w[m] >= 0] + consts))
    us, row_us = [], {}
    for r, sid in enumerate(p.ids):
        parts = [(m, sg) for m in cand if (sg := core._contrib(p, p.terms[m], sid))]
        sided = {side: [m for m in cand if p.terms[m].kind == "outside" and p.terms[m].a == sid and p.terms[m].sides == (side,)]
                 for side in ("in", "out")}
        e = _q(band[r])
        for i in range(n):
            terms = [w[m] * _q(sg * Xs[i, p.terms[m].col] / sc[p.terms[m].col] / sigma[r]) for m, sg in parts
                     if Xs[i, p.terms[m].col] != 0]
            res = _q(Ys[r, i] / sigma[r]) - (z3.Sum(terms) if terms else z3.RealVal(0))
            u = z3.Real(f"u{r}_{i}")
            opt.add(u >= 0, u >= res - e, u >= -res - e)
            us.append(u)
            row_us.setdefault(r, []).append(u)
            if encoding == "maxsmt":           # the band is hard except on a block marked as an outlier (soft)
                o = z3.Bool(f"o{r}_{i}")
                opt.add(z3.Or(o, u <= _q(HARD_BAND - band[r])))
                opt.add_soft(z3.Not(o), weight=f"{OUTLIER:.6f}", id="cost")
            elif encoding == "ladder":         # the L1 beyond the band as a staircase (truncated at LEVELS)
                for j in range(LEVELS):
                    opt.add_soft(u <= _q(STAIR * j), weight="1", id="cost")
        for i in range(SX.shape[0]):
            for side, sign in (("in", 1), ("out", -1)):
                ms = [m for m in sided[side] if SX[i, p.terms[m].col] != 0]
                if ms:
                    opt.add(z3.Sum([w[m] * _q(sign * SX[i, p.terms[m].col] / sc[p.terms[m].col] / sigma[r]) for m in ms]) >= -e)
    fit = z3.Sum(us) if us else z3.RealVal(0)
    wsup, wnums, ub = warm(p, B, cand, sigma, fixed, price)
    out = {"n": n, "m": B.m, "price": price, "candidates": len(cand), "encoding": encoding,
           "warm": {"terms": len(wsup), "objective": ub}}

    def read(model) -> tuple[list[int], dict, float]:
        sup, nums = [], {}
        for m in cand:
            if z3.is_true(model.eval(b[m], model_completion=True)):
                sup.append(m)
                nums[m] = (_val(model.eval(w[m], model_completion=True)) or 0.0) / sc[p.terms[m].col]
        resid = _val(model.eval(fit, model_completion=True))
        return sup, nums, (resid if resid is not None else objective(p, B, sup, nums, sigma, 0.0)) + price * len(sup)

    deadline = began + timeout
    if encoding == "band":
        return {**out, **_band(p, B, cand, sigma, opt, b, w, sc, row_us, read, price, deadline, wsup, wnums, ub, fixed),
                "seconds": round(time.perf_counter() - began, 3)}
    if encoding != "weighted":
        for m in cand:
            opt.add_soft(z3.Not(b[m]), weight=f"{price:.6f}", id="cost")
        opt.minimize(fit)                      # lexicographic: the MaxSMT cost first, then the L1 residual
        opt.set("timeout", max(1, int((deadline - time.perf_counter()) * 1000)))
        got = opt.check()
        try:
            model = opt.model()
        except z3.Z3Exception:
            model = None
        out["status"] = str(got)
        if model is None or not len(model):
            return {**out, "support": wsup, "numbers": wnums, "objective": ub, "from": "warm start",
                    "seconds": round(time.perf_counter() - began, 3)}
        sup, nums, obj = read(model)
        return {**out, "support": sup, "numbers": nums, "objective": obj, "seconds": round(time.perf_counter() - began, 3)}
    # weighted: Z3 minimises the objective exactly within a radius of switches around the incumbent (local
    # branching); an improvement recentres it, no improvement widens the radius; a radius that reaches every
    # candidate (or a "sat" at it) is the global optimum over the candidates
    total = fit + z3.Sum([z3.If(b[m], _q(price), 0) for m in cand])
    opt.minimize(total)
    inc, inc_nums, inc_obj = list(wsup), dict(wnums), ub
    radius, rounds, proved, status = NEAR or len(cand), 0, False, "unknown"
    while time.perf_counter() < deadline - 0.05:
        on = set(inc)
        opt.push()
        opt.add(total <= _q(inc_obj * (1 + 1e-9) + 1e-9))
        if radius < len(cand):
            opt.add(z3.AtMost(*[z3.Not(b[m]) if m in on else b[m] for m in cand], radius))
        opt.set("timeout", max(1, int((deadline - time.perf_counter()) * 1000)))
        got = opt.check()
        rounds += 1
        model = None
        if got == z3.sat:
            try:
                model = opt.model()
            except z3.Z3Exception:
                model = None
        opt.pop()
        if got != z3.sat:
            status = "unknown (timeout)" if got == z3.unknown else str(got)
            break
        sup, nums, obj = read(model)
        if obj < inc_obj - 1e-6 * max(1.0, abs(inc_obj)):
            inc, inc_nums, inc_obj = sup, nums, obj
            continue                                         # recentre, same radius
        if radius >= len(cand):
            proved, status = True, "optimal"
            break
        radius = min(len(cand), radius + RADIUS_STEP)
    out.update(status=status, proved=proved, radius=radius, rounds=rounds)
    return {**out, "support": inc, "numbers": inc_nums, "objective": inc_obj,
            "from": "z3" if (inc != wsup or proved) else "warm start (Z3 found nothing better)",
            "seconds": round(time.perf_counter() - began, 3)}


def ball(q: int) -> float:
    """A row's L1 ball in noise units: the expected L1 of q unit normal residuals (0.8 q) + BALL_Z of its
    standard deviations (0.6 sqrt(q))."""
    return 0.8 * q + BALL_Z * 0.6 * math.sqrt(q)


def l1_numbers(p: core.Problem, B, sup: list[int], sigma: np.ndarray, fixed: dict[int, float]) -> tuple[dict, float]:
    """The structure's numbers minimising the L1 of its residuals (in noise units, every row jointly; HiGHS)
    and that L1."""
    from scipy.optimize import linprog
    S, n = B.Y.shape
    free = [m for m in sup if m not in fixed]
    G = np.zeros((S * n, len(free)))
    y = (B.Y / sigma[:, None]).reshape(-1).copy()
    for r, sid in enumerate(p.ids):
        for m in sup:
            sg = core._contrib(p, p.terms[m], sid)
            if sg:
                col = sg * B.X[:, p.terms[m].col] / sigma[r]
                if m in fixed:
                    y[r * n:(r + 1) * n] -= fixed[m] * col
                else:
                    G[r * n:(r + 1) * n, free.index(m)] = col
    N, k = G.shape
    if not k:
        return {m: fixed[m] for m in sup}, float(np.abs(y).sum())
    scl = np.abs(G).max(axis=0)
    scl[scl == 0] = 1.0
    c = np.concatenate([np.zeros(k), np.ones(N)])
    A = np.block([[G / scl, -np.eye(N)], [-G / scl, -np.eye(N)]])
    lp = linprog(c, A_ub=A, b_ub=np.concatenate([y, -y]), bounds=[(0, None) if unsigned(p, m, sup) else (None, None) for m in free]
                 + [(0, None)] * N, method="highs")
    if lp.status != 0:
        nums = _lsq(p, B, sup, sigma, fixed)
        return nums, objective(p, B, sup, nums, sigma, 0.0)
    nums = {m: fixed[m] for m in sup if m in fixed}
    nums.update({m: float(v) for m, v in zip(free, lp.x[:k] / scl)})
    return nums, float(lp.fun)


def _band(p, B, cand, sigma, opt, b, w, sc, row_us, read, price, deadline, wsup, wnums, ub, fixed) -> dict:
    """The epsilon-band search: every row's rotated residuals within its L1 ball (hard), and the fewest
    terms: Z3 asked "does a structure of at most k terms fit?" (an AtMost(k) assumption: SAT with linear
    real arithmetic, far faster here than Z3's MaxSMT engines, which timed out on 30 candidates), k
    bisected between 0 and the size of the last structure found; then every other structure of that size
    within the band (each found one and its supersets blocked, ask again). Of those, the least L1 + price
    is kept (and compared with the warm start's)."""
    R = ball(B.n)
    widen = z3.Real("widen")             # the ball's scale: 1, or wider when nothing fits (the epsilon grows)
    for r, u in row_us.items():
        opt.add(z3.Sum(u) <= widen * _q(max(R, R * float(B.eps[r]) / sigma[r])))
    bs = [b[m] for m in cand]
    limits: dict = {}

    def fits(k: int, until: float | None = None):
        if k not in limits:
            limits[k] = z3.Bool(f"atmost{k}")
            opt.add(z3.Implies(limits[k], z3.AtMost(*bs, k)))
        left = (until or deadline) - time.perf_counter()
        if left <= 0.05:
            return z3.unknown, None
        opt.set("timeout", max(1, int(left * 1000)))
        got = opt.check(limits[k])
        if got != z3.sat:
            return got, None
        model = opt.model()
        return got, [m for m in cand if z3.is_true(model.eval(b[m], model_completion=True))]

    found, kmin, status, checks = [], None, "unknown (timeout)", 0
    scale = 1.0
    for scale in WIDEN:                  # the band as estimated, then wider while nothing fits at all
        opt.push()
        opt.add(widen == _q(scale))
        got, sup = fits(len(cand))
        checks += 1
        if got != z3.unsat:
            break
        opt.pop()
    if got == z3.sat:
        best, proved = sup, False
        while True:                      # downward: each answer is a structure smaller than the last
            got, sup = fits(len(best) - 1) if best else (z3.unsat, None)
            checks += 1
            if got == z3.sat:
                best = sup
            else:
                proved = got == z3.unsat
                break
        kmin = len(best)
        found = [best]
        opt.add(z3.Or([z3.Not(b[m]) for m in best]) if best else z3.BoolVal(False))
        stop = min(deadline, time.perf_counter() + ENUM_SECONDS)
        while proved and len(found) < ENUM_CAP and time.perf_counter() < stop:
            got, sup = fits(kmin, stop)
            checks += 1
            if got != z3.sat:
                break
            found.append(sup)
            opt.add(z3.Or([z3.Not(b[m]) for m in sup]) if sup else z3.BoolVal(False))
        status = ("proved smallest, all listed" if got == z3.unsat else "proved smallest" if proved else
                  "smallest not proved (timeout)") + (f" (band x {scale:g})" if scale != 1.0 else "")
    elif got == z3.unsat:
        status = f"nothing fits the band (x {scale:g})"
    scored = []
    for sup in found:
        nums, l1 = l1_numbers(p, B, sup, sigma, fixed)
        scored.append((l1 + price * len(sup), 0, sup, nums, "z3 (fewest terms within the band)"))
    if WARM_CONTENDS or not found:          # the backward elimination's structure competes on the same objective
        nums, l1 = l1_numbers(p, B, wsup, sigma, fixed)
        scored.append((l1 + price * len(wsup), 1, wsup, nums, "warm start (backward elimination)"))
    scored.sort(key=lambda x: (x[0], x[1]))
    near = [x for x in scored if x[0] <= scored[0][0] + TIE]      # data-equivalent rivals: the fewest moves
    obj, _, sup, nums, src = min(near, key=lambda x: (sum(p.terms[m].kind == "move" for m in x[2]), x[0], x[1]))
    return {"status": status, "support": sup, "numbers": nums, "objective": obj, "from": src, "smallest": len(found),
            "k_min": kmin, "ball": R, "checks": checks}


def objective(p: core.Problem, B: Blocks, sup: list[int], nums: dict, sigma: np.ndarray, price: float) -> float:
    """The weighted objective of a structure with these numbers on the blocks (floats)."""
    pred = np.zeros_like(B.Y)
    for m in sup:
        t = p.terms[m]
        for r, sid in enumerate(p.ids):
            sg = core._contrib(p, t, sid)
            if sg:
                pred[r] += sg * nums[m] * B.X[:, t.col]
    tot = 0.0
    for r in range(len(p.ids)):
        band = B.band(r, sigma)
        tot += float(np.maximum(0.0, np.abs(B.Y[r] - pred[r]) / sigma[r] - band).sum())
    return tot + price * len(sup)


def step_sigma(p: core.Problem, sup: list[int], sigma: np.ndarray, B: Blocks) -> np.ndarray:
    """Per stock, a one-step scale for the refit's row weights: the scatter of the one-step residuals of the
    chosen structure's all-column least-squares row (1.4826 x MAD), at least the block level / sqrt(m)."""
    X, Y = core._floats(p)
    A = X[:, _base(p)]
    out = []
    for r in range(len(p.ids)):
        a, *_ = np.linalg.lstsq(A, Y[r], rcond=None)
        res = Y[r] - A @ a
        out.append(max(MAD * float(np.median(np.abs(res - np.median(res)))), float(p.eps[r]), 1e-12))
    return np.array(out)


def solve_guarded(p: core.Problem, B, cand: list[int], sigma: np.ndarray, fixed: dict[int, float], timeout: float,
                  encoding: str = "band") -> dict:
    """solve() in a forked child process, killed GRACE seconds after its timeout: Z3 does not always honour
    its own timeout (a 25 s limit once ran 131 s on case 306), and the ladder's item timeout is 120 s. If the
    child is killed or fails, the warm start (backward elimination) is returned, labelled so."""
    import multiprocessing as mp
    try:
        ctx = mp.get_context("fork")
    except ValueError:                         # no fork (not expected on the pool's machines): in process
        return solve(p, B, cand, sigma, fixed, timeout, encoding=encoding)
    began = time.perf_counter()
    rx, tx = ctx.Pipe(duplex=False)

    def child():
        try:
            got = solve(p, B, cand, sigma, fixed, timeout, encoding=encoding)
            tx.send({k: v for k, v in got.items()})
        except Exception as e:  # noqa: BLE001
            tx.send({"error": repr(e)})
        finally:
            tx.close()

    proc = ctx.Process(target=child, daemon=True)
    proc.start()
    tx.close()
    got = None
    if rx.poll(timeout + GRACE):
        try:
            got = rx.recv()
        except EOFError:
            got = None
    if proc.is_alive():
        proc.kill()
    proc.join(1.0)
    if got is None or "error" in got:
        price = B.price()
        wsup, wnums, ub = warm(p, B, cand, sigma, fixed, price)
        return {"status": "killed (Z3 past its timeout)" if got is None else f"error {got['error'][:200]}", "n": B.n, "m": B.m,
                "price": price, "candidates": len(cand), "encoding": encoding, "support": wsup, "numbers": wnums,
                "objective": ub, "from": "warm start (Z3 did not return)", "warm": {"terms": len(wsup), "objective": ub},
                "seconds": round(time.perf_counter() - began, 3)}
    return got
