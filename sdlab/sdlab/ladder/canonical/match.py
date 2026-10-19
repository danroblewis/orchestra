"""Match the reader's flow rates (read.py: sympy, auxiliaries inlined) onto SD Lab's rate forms and
write them in the case format (docs/LADDER.md, "The format").

    rate_text(expr, src, readers, scale_of) -> "0.0003 * S * effect(I, linear, normal=100, max=1000)"

A rate is a product: a number, at most one factor that is linear in several stocks, and factors that
each read one stock (or input, or smoothing) linearly, a + b x Y, or through a lookup of a + b x Y. Then:

- the linear factor, or one one-stock factor (the flow's source first), is the rate: constant,
  proportional (k x Y), gap ((goal - Y) / time) or linear (c + k1 x Y1 + ...);
- every other factor is an effect: b x Y is effect(Y, linear, normal=n, max=M) (Y / n, n folded into
  the rate; M far above any level seen, so the cap never binds), 1 + b x Y with b < 0 is a table
  through (0, 1) and its root (beyond the root SD Lab's floor at 0 is the factor's own floor), any
  other a + b x Y a table through two points far apart, and a lookup of a + b x Y a table on Y through
  the lookup's points.

Anything else raises read.Blocked naming the missing feature: a ratio of stocks, a non-integer power,
a product of two sums, MIN/MAX, IF THEN ELSE, SQRT, EXP/LN, ... (a placeholder that reads only TIME
never gets here: pysd_import makes it a measured input first).
"""

from __future__ import annotations

import math

import sympy as sp

from .read import Blocked

# the function placeholders (read.py) by the feature the format lacks
FEATURES = {
    "F_min": "MIN / MAX", "F_max": "MIN / MAX", "F_if_then_else": "IF THEN ELSE", "F_sqrt": "SQRT",
    "F_exp": "EXP / LN / LOG", "F_ln": "EXP / LN / LOG", "F_log": "EXP / LN / LOG", "F_power": "a non-integer power",
    "F_abs": "ABS", "F_integer": "INTEGER / MODULO / QUANTUM", "F_modulo": "INTEGER / MODULO / QUANTUM",
    "F_quantum": "INTEGER / MODULO / QUANTUM", "F_xidz": "XIDZ / ZIDZ (guarded division)",
    "F_zidz": "XIDZ / ZIDZ (guarded division)", "F_sin": "trigonometry of a stock", "F_cos": "trigonometry of a stock",
    "F_tan": "trigonometry of a stock", "F_arcsin": "trigonometry of a stock", "F_arccos": "trigonometry of a stock",
    "F_arctan": "trigonometry of a stock", "F_sinh": "trigonometry of a stock", "F_cosh": "trigonometry of a stock",
    "F_tanh": "trigonometry of a stock", "F_random_uniform": "random functions", "F_random_normal": "random functions",
    "F_random_0_1": "random functions", "F_random_exponential": "random functions",
    "F_step": "STEP / PULSE / RAMP of a stock", "F_pulse": "STEP / PULSE / RAMP of a stock",
    "F_ramp": "STEP / PULSE / RAMP of a stock", "F_pulse_train": "STEP / PULSE / RAMP of a stock",
}
F_RATIO = "division by a stock (a ratio)"
F_POWER = "a non-integer power"
F_POLY = "a nonlinear polynomial (not a product of linear factors)"
F_SUMS = "a product of two sums of stocks"
F_LOOKUP_EXPR = "a lookup of an expression of several stocks"
F_NEGATIVE = "a two-way flow (a rate goes negative)"


def fmt(x) -> str:
    """A number as the case format writes it: the shortest repr that round-trips, ints without .0."""
    f = float(x)
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(f)


def feature_of(fn) -> str:
    name = type(fn).__name__
    if name.startswith("F_cmp"):
        return "IF THEN ELSE"
    return FEATURES.get(name, f"the function {name.removeprefix('F_').upper()}")


def _nice_up(x: float) -> float:
    """A round number at least x (1, 2 or 5 times a power of 10)."""
    if x <= 0:
        return 1.0
    e = math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * 10 ** e >= x * (1 - 1e-12):
            return float(m * 10 ** e)
    return float(10 ** (e + 1))


def _check_atoms(e, lookups: dict, readers: set) -> None:
    for fn in e.atoms(sp.Function):
        name = type(fn).__name__
        if name in lookups:
            continue
        raise Blocked(feature_of(fn), str(fn)[:80])
    for p in e.atoms(sp.Pow):
        if p.base.free_symbols & readers:
            if not p.exp.is_Integer:
                raise Blocked(F_POWER, str(p)[:80])
            if p.exp < 0:
                raise Blocked(F_RATIO, str(p)[:80])


def _affine(e, readers: set):
    """(a, b, Y) when e = a + b Y for one reader Y; None otherwise."""
    syms = e.free_symbols & readers
    if len(syms) != 1 or e.free_symbols - readers:
        return None
    (y,) = syms
    try:
        p = sp.Poly(e, y)
    except sp.PolynomialError:
        return None
    if p.degree() != 1 or any(c.free_symbols for c in p.all_coeffs()):
        return None
    b, a = p.all_coeffs()
    return a, b, y


def _linear(e, readers: set):
    """{"c": c, "k": {Y: k}} when e is linear in the readers; None otherwise."""
    syms = e.free_symbols & readers
    if e.free_symbols - readers:
        return None
    try:
        p = sp.Poly(e, *sorted(syms, key=str))
    except sp.PolynomialError:
        return None
    if p.total_degree() > 1:
        return None
    k = {y: p.coeff_monomial(y) for y in syms}
    return {"c": p.coeff_monomial(1), "k": k}


def rate_text(expr, src: str | None, readers: dict, scale_of: dict, lookups: dict) -> str:
    """The rate in the case format. readers: sympy symbol -> its text (a stock id, an input name, or
    smooth(...)); scale_of: symbol -> the largest level it reaches in the source's run (for effect
    ranges)."""
    rs = set(readers)
    e = sp.sympify(expr)
    _check_atoms(e, lookups, rs)
    num, den = sp.fraction(sp.together(e))
    if den.free_symbols & rs:
        raise Blocked(F_RATIO, str(e)[:80])
    if den.free_symbols:
        raise Blocked("an expression that is not a rate", str(e)[:80])
    coef, factors = sp.factor_list(sp.expand(num))
    c = sp.Rational(coef) / den if den.is_Rational else coef / den
    linears, ones, effects = [], [], []
    for f, mult in factors:
        if not (f.free_symbols & rs):
            c = c * f ** mult
            continue
        name = type(f).__name__
        if name in lookups:
            arg = f.args[0]
            aff = _affine(arg, rs)
            if aff is None:
                raise Blocked(F_LOOKUP_EXPR, str(f)[:80])
            effects += [("lookup", name, aff)] * mult
            continue
        aff = _affine(f, rs)
        if aff is not None:
            ones += [aff] * mult
            continue
        lin = _linear(f, rs)
        if lin is not None:
            linears += [lin] * mult
            continue
        if any(type(a).__name__ in lookups for a in f.atoms(sp.Function)):
            raise Blocked("a lookup inside a sum (a sum of effects)", str(f)[:80])
        raise Blocked(F_POLY, str(f)[:80])
    if len(linears) > 1:
        raise Blocked(F_SUMS, str(e)[:80])
    rate = None
    if linears:
        rate = ("linear", linears[0])
    elif ones:
        src_sym = next((s for s, t in readers.items() if t == src), None)
        order = sorted(range(len(ones)), key=lambda i: (ones[i][0] != 0, ones[i][2] != src_sym, i))
        rate = ("one", ones.pop(order[0]))
    eff_text = []
    for a, b, y in ones:
        if a == 0:
            n = _nice_up(scale_of.get(y, 1.0) or 1.0) / 10 if scale_of.get(y) else 1.0
            n = n if n > 0 else 1.0
            c = c * b * sp.Rational(fmt(n))
            top = _nice_up(100 * max(scale_of.get(y, 1.0), 1.0) / n)
            eff_text.append(f"effect({readers[y]}, linear, normal={fmt(n)}, max={fmt(top)})")
        else:
            c = c * a
            r = b / a
            hi = float(-1 / r) if r < 0 else _nice_up(100 * max(scale_of.get(y, 1.0), 1.0))
            eff_text.append(f"effect({readers[y]}, table, [[0, 1], [{fmt(hi)}, {fmt(1 + float(r) * hi)}]])")
    for _, name, (a, b, y) in effects:
        xs, ys = lookups[name]
        pts = sorted(((x - float(a)) / float(b), v) for x, v in zip(xs, ys))
        eff_text.append(f"effect({readers[y]}, table, [{', '.join(f'[{fmt(x)}, {fmt(v)}]' for x, v in pts)}])")
    base = _rate_base(rate, c, readers)
    return " * ".join([base] + eff_text)


def _rate_base(rate, c, readers: dict) -> str:
    if rate is None:
        if c <= 0:
            raise Blocked(F_NEGATIVE, fmt(c))
        return fmt(c)
    kind, r = rate
    if kind == "one":
        a, b, y = r
        a, b = c * a, c * b
        if a == 0:
            if b <= 0:
                raise Blocked(F_NEGATIVE, f"{fmt(b)} * {readers[y]}")
            return readers[y] if b == 1 else f"{fmt(b)} * {readers[y]}"
        if a > 0 and b < 0:
            time = -1 / b
            return f"({fmt(a * time)} - {readers[y]}) / {fmt(time)}"
        return _linear_text(a, {y: b}, readers)
    return _linear_text(c * r["c"], {y: c * k for y, k in r["k"].items()}, readers)


def _linear_text(c, ks: dict, readers: dict) -> str:
    parts = [] if c == 0 else [fmt(c)]
    for y in sorted(ks, key=lambda s: readers[s]):
        k = ks[y]
        if k == 0:
            continue
        term = readers[y] if abs(k) == 1 else f"{fmt(abs(k))} * {readers[y]}"
        parts.append(("- " if k < 0 else "+ ") + term if parts else ("-" if k < 0 else "") + term)
    if not parts:
        raise Blocked(F_NEGATIVE, "0")
    return " ".join(parts)
