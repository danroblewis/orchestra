"""Evaluate the PromQL AST over a Dataset at a list of timestamps.

Every expression is evaluated at all output timestamps at once: a scalar is a
list of floats, an instant vector a list of `(labels, values)` with NaN where a
series has no value. An instant query is a range evaluation at one timestamp.

Deviation from Prometheus, because samples are 5 minutes apart: a range
window that holds a single sample is widened to include the sample before it,
so `rate(x[5m])` is the slope over the last two samples instead of nothing.
"""

import math
import operator
import re
from decimal import Decimal
from itertools import accumulate

from . import promql as P

NAN = math.nan
LOOKBACK = 300.0


class EvalError(Exception):
    pass


def _div(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return NAN if a == 0 or a != a else math.copysign(math.inf, a)


def _mod(a, b):
    try:
        return math.fmod(a, b)
    except (ValueError, ZeroDivisionError):
        return NAN


def _pow(a, b):
    try:
        return math.pow(a, b)
    except (ValueError, OverflowError):
        return NAN


ARITH = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": _div, "%": _mod, "^": _pow}
CMP = {"==": operator.eq, "!=": operator.ne, "<": operator.lt, ">": operator.gt, "<=": operator.le, ">=": operator.ge}


def _dense(vals):
    s = sum(vals)
    return s == s


def _drop_name(labels):
    return {k: v for k, v in labels.items() if k != "__name__"}


class Evaluator:
    def __init__(self, ds, times, jmax):
        self.ds = ds
        self.T = times
        self.jmax = jmax
        self.lookback = max(LOOKBACK, float(ds.step))

    def select(self, sel: P.Selector):
        ms = []
        for label, op, value in sel.matchers:
            rx = re.compile(value) if op in ("=~", "!~") else None
            ms.append((label, op, value, rx))
        pool = self.ds.by_metric.get(sel.name, []) if sel.name is not None else self.ds.series
        return [s for s in pool if all(_match(s.labels.get(lb, ""), op, v, rx) for lb, op, v, rx in ms)]

    def _grid(self, tt):
        return math.floor((tt - self.ds.start) / self.ds.step)

    def instant_index(self, offset):
        start, step, jmax, lb = self.ds.start, self.ds.step, self.jmax, self.lookback
        out = []
        for t in self.T:
            tt = t - offset
            j = min(self._grid(tt), jmax)
            out.append(j if j >= 0 and tt - (start + j * step) <= lb else -1)
        return out

    def range_index(self, offset, window, need2):
        """Per timestamp: (first, last) sample index of the window, or None."""
        start, step, jmax = self.ds.start, self.ds.step, self.jmax
        out = []
        for t in self.T:
            tt = t - offset
            jt = min(self._grid(tt), jmax)
            if jt < 0 or tt - (start + jt * step) >= window:
                out.append(None)
                continue
            jl = max(0, math.floor((tt - window - start) / step) + 1)
            if need2 and jt - jl < 1:
                jl = jt - 1
                if jl < 0:
                    out.append(None)
                    continue
            out.append((jl, jt))
        return out

    def eval(self, node):
        method = getattr(self, "eval_" + type(node).__name__)
        return method(node)

    def eval_Number(self, node):
        return ("scalar", [node.value] * len(self.T))

    def eval_String(self, node):
        return ("string", node.value)

    def eval_Selector(self, node):
        J = self.instant_index(node.offset)
        valid = [j for j in J if j >= 0]
        if not valid:
            return ("vector", [])
        lo, hi = min(valid), max(valid)
        steps = {b - a for a, b in zip(valid, valid[1:])}
        fast = len(valid) == len(J) and len(steps) <= 1 and (not steps or steps.pop() > 0)
        stride = (J[1] - J[0]) if len(J) > 1 else 1
        out = []
        for s in self.select(node):
            a = s.read(lo, hi + 1)
            if fast:
                vals = a[::stride].tolist()
            else:
                vals = [a[j - lo] if j >= 0 else NAN for j in J]
            out.append((s.labels, vals))
        return ("vector", out)

    def eval_MatrixSelector(self, node):
        raise EvalError("range vectors are only allowed as function arguments or as a whole instant query")

    def eval_Neg(self, node):
        kind, v = self.eval(node.expr)
        if kind == "scalar":
            return ("scalar", [-x for x in v])
        return ("vector", [(_drop_name(lb), [-x for x in vals]) for lb, vals in v])

    def eval_Call(self, node):
        f = node.func
        if f in P.RANGE_FUNCS:
            return self.range_func(f, node.args[0])
        args = [self.eval(a) for a in node.args]
        return self.instant_func(f, args)

    def range_func(self, f, m: P.MatrixSelector):
        w = m.range
        need2 = f in ("rate", "irate", "increase", "delta", "idelta", "deriv")
        idx = self.range_index(m.selector.offset, w, need2)
        valid = [p for p in idx if p]
        if not valid:
            return ("vector", [])
        lo = min(p[0] for p in valid)
        hi = max(p[1] for p in valid)
        plan = _Plan(f, [(p[0] - lo, p[1] - lo) if p else None for p in idx], w, self.ds.step)
        out = []
        for s in self.select(m.selector):
            out.append((_drop_name(s.labels), plan.run(s.read(lo, hi + 1).tolist())))
        return ("vector", out)

    def instant_func(self, f, args):
        T = self.T
        if f == "time":
            return ("scalar", [float(t) for t in T])
        if f == "vector":
            return ("vector", [({}, list(args[0][1]))])
        if f == "scalar":
            kind, v = args[0]
            out = []
            for k in range(len(T)):
                present = [vals[k] for _, vals in v if vals[k] == vals[k]]
                out.append(present[0] if len(present) == 1 else NAN)
            return ("scalar", out)
        kind, v = args[0]
        if kind != "vector":
            raise EvalError(f"expected instant vector argument in call to {f}")
        if f == "sort" or f == "sort_desc":
            rev = f == "sort_desc"
            return ("vector", sorted(v, key=lambda s: (s[1][-1] != s[1][-1], -s[1][-1] if rev else s[1][-1])))
        if f == "label_replace":
            return ("vector", _label_replace(v, args[1:]))
        if f == "timestamp":
            J = self.instant_index(0)  # approximate: the grid time of the sample in use
            ts = [self.ds.start + j * self.ds.step if j >= 0 else NAN for j in J]
            return ("vector", [(_drop_name(lb), [t if x == x else NAN for t, x in zip(ts, vals)]) for lb, vals in v])
        params = [a[1] for a in args[1:]]
        for p in params:
            if not isinstance(p, list):
                raise EvalError(f"expected scalar argument in call to {f}")
        fn = {
            "abs": abs,
            "ceil": math.ceil,
            "floor": math.floor,
            "sqrt": lambda x: math.sqrt(x) if x >= 0 else NAN,
            "exp": math.exp,
            "ln": lambda x: math.log(x) if x > 0 else NAN,
            "log2": lambda x: math.log2(x) if x > 0 else NAN,
            "log10": lambda x: math.log10(x) if x > 0 else NAN,
        }.get(f)
        out = []
        for lb, vals in v:
            if f == "round":
                to = params[0] if params else [1.0] * len(T)
                new = [math.floor(x / n + 0.5) * n if x == x and n else x for x, n in zip(vals, to)]
            elif f == "clamp_min":
                new = [max(x, lo) if x == x else x for x, lo in zip(vals, params[0])]
            elif f == "clamp_max":
                new = [min(x, hi) if x == x else x for x, hi in zip(vals, params[0])]
            elif f == "clamp":
                new = [min(max(x, lo), hi) if x == x else x for x, lo, hi in zip(vals, params[0], params[1])]
            else:
                new = [fn(x) if x == x and not math.isinf(x) else x for x in vals]
            out.append((_drop_name(lb), [float(x) for x in new]))
        return ("vector", out)

    def eval_Aggregate(self, node):
        kind, v = self.eval(node.expr)
        if kind != "vector":
            raise EvalError(f"expected instant vector in aggregation {node.op}")
        groups: dict[tuple, list] = {}
        glabels = {}
        for lb, vals in v:
            if node.without:
                key_lb = {k: x for k, x in lb.items() if k not in node.grouping and k != "__name__"}
            else:
                key_lb = {k: lb[k] for k in node.grouping if k in lb}
            key = tuple(sorted(key_lb.items()))
            groups.setdefault(key, []).append((lb, vals))
            glabels[key] = key_lb
        out = []
        if node.op in ("topk", "bottomk"):
            kind_p, kp = self.eval(node.param)
            if kind_p != "scalar":
                raise EvalError(f"expected scalar parameter for {node.op}")
            for members in groups.values():
                out.extend(_topk(members, kp, node.op == "topk"))
            return ("vector", out)
        for key, members in groups.items():
            out.append((glabels[key], _aggregate(node.op, [vals for _, vals in members])))
        return ("vector", out)

    def eval_Binary(self, node):
        if node.op in ("and", "or", "unless"):
            raise EvalError(f"set operator {node.op!r} is not supported")
        lk, lv = self.eval(node.lhs)
        rk, rv = self.eval(node.rhs)
        if lk == "string" or rk == "string":
            raise EvalError("binary expressions on strings are not supported")
        cmp = node.op in P.COMPARISONS
        if cmp and lk == "scalar" and rk == "scalar" and not node.bool_:
            raise EvalError("comparisons between scalars must use BOOL modifier")
        fn = CMP[node.op] if cmp else ARITH[node.op]
        if lk == "scalar" and rk == "scalar":
            return ("scalar", [float(fn(a, b)) for a, b in zip(lv, rv)])
        if lk == "vector" and rk == "vector":
            return ("vector", self._vector_vector(node, fn, cmp, lv, rv))
        vec, sc, vec_left = (lv, rv, True) if lk == "vector" else (rv, lv, False)
        out = []
        for lb, vals in vec:
            pairs = zip(vals, sc) if vec_left else zip(sc, vals)
            if cmp:
                if node.bool_:
                    new = [float(fn(a, b)) if x == x else NAN for (a, b), x in zip(pairs, vals)]
                    out.append((_drop_name(lb), new))
                else:
                    new = [x if fn(a, b) else NAN for (a, b), x in zip(pairs, vals)]
                    out.append((lb, new))
            else:
                new = list(map(fn, vals, sc)) if vec_left else list(map(fn, sc, vals))
                out.append((_drop_name(lb), new))
        return ("vector", out)

    def _vector_vector(self, node, fn, cmp, lv, rv):
        def sig(lb):
            if node.on is not None:
                return tuple(sorted((k, lb[k]) for k in node.on if k in lb))
            ign = set(node.ignoring or ()) | {"__name__"}
            return tuple(sorted((k, x) for k, x in lb.items() if k not in ign))

        right = {}
        for lb, vals in rv:
            key = sig(lb)
            if key in right:
                raise EvalError(
                    "found duplicate series for the match group on the right hand-side of the operation; many-to-many matching not allowed"
                )
            right[key] = vals
        out, seen = [], set()
        for lb, vals in lv:
            key = sig(lb)
            other = right.get(key)
            if other is None:
                continue
            if key in seen:
                raise EvalError(
                    "multiple matches for labels: many-to-one matching must be explicit (group_left/group_right)"
                )
            seen.add(key)
            if cmp and not node.bool_:
                out.append((lb, [a if fn(a, b) else NAN for a, b in zip(vals, other)]))
                continue
            if cmp:
                new = [float(fn(a, b)) if a == a and b == b else NAN for a, b in zip(vals, other)]
            else:
                new = list(map(fn, vals, other))
            if node.on is not None:
                labels = {k: lb[k] for k in node.on if k in lb}
            else:
                labels = {k: x for k, x in _drop_name(lb).items() if k not in (node.ignoring or ())}
            out.append((labels, new))
        return out


def _match(value, op, want, rx):
    if op == "=":
        return value == want
    if op == "!=":
        return value != want
    hit = rx.fullmatch(value) is not None
    return hit if op == "=~" else not hit


class _Plan:
    """How to turn one series' samples into a range function's values; shared by all series."""

    def __init__(self, f, rel, w, step):
        self.f, self.rel, self.w, self.step = f, rel, w, step
        valid = [k for k, p in enumerate(rel) if p]
        self.head, self.tail = valid[0], len(rel) - 1 - valid[-1]
        core = rel[self.head : len(rel) - self.tail]
        self.stride = core[1][1] - core[0][1] if len(core) > 1 else 1
        # windows one sample wide at evenly spaced points: plain deltas, sliced
        self.simple = (
            f in ("rate", "increase", "irate")
            and all(core)
            and all(p[1] - p[0] == 1 for p in core)
            and self.stride > 0
            and all(core[k + 1][1] - core[k][1] == self.stride for k in range(len(core) - 1))
        )
        self.core_len = len(core)
        self.first = core[0][1]
        if f in (
            "rate",
            "increase",
            "resets",
            "changes",
            "avg_over_time",
            "sum_over_time",
            "count_over_time",
            "delta",
            "deriv",
        ):
            per = {
                "rate": lambda i, j: 1.0 / ((j - i) * step),
                "increase": lambda i, j: w / ((j - i) * step),
                "delta": lambda i, j: w / ((j - i) * step),
                "deriv": lambda i, j: 1.0 / ((j - i) * step),
                "avg_over_time": lambda i, j: 1.0 / (j - i + 1),
            }.get(f, lambda i, j: 1.0)
            shift = 1 if f in ("avg_over_time", "sum_over_time", "count_over_time") else 0
            self.prep = [(p[0], p[1] + shift, per(*p)) if p else (0, 0, 0.0) for p in rel]

    def run(self, a):
        f, rel, prep = self.f, self.rel, getattr(self, "prep", None)
        if self.simple:
            pairs = zip(a[self.first - 1 :: self.stride], a[self.first :: self.stride])
            scale = self.w / self.step if f == "increase" else 1.0 / self.step
            core = [(y - x if y >= x else y) * scale for x, y in pairs][: self.core_len]
            return [NAN] * self.head + core + [NAN] * self.tail
        if f in ("rate", "increase", "resets", "changes"):
            if f == "changes":
                d = [float(y != x) for x, y in zip(a, a[1:])]
            elif f == "resets":
                d = [float(y < x) for x, y in zip(a, a[1:])]
            else:
                d = [(y - x if y >= x else y) for x, y in zip(a, a[1:])]
            C = list(accumulate(d, initial=0.0))
            return [(C[j] - C[i]) * k if k else NAN for i, j, k in prep]
        if f in ("avg_over_time", "sum_over_time"):
            C = list(accumulate(a, initial=0.0))
            return [(C[j] - C[i]) * k if k else NAN for i, j, k in prep]
        if f == "count_over_time":
            return [float(j - i) if k else NAN for i, j, k in prep]
        if f in ("delta", "deriv"):
            return [(a[j] - a[i]) * k if k else NAN for i, j, k in prep]
        step = self.step
        out = []
        for p in rel:
            if p is None:
                out.append(NAN)
                continue
            i, j = p
            if f == "max_over_time":
                out.append(max(a[i : j + 1]))
            elif f == "min_over_time":
                out.append(min(a[i : j + 1]))
            elif f == "last_over_time":
                out.append(a[j])
            elif f == "irate":
                x, y = a[j - 1], a[j]
                out.append((y - x if y >= x else y) / step)
            elif f == "idelta":
                out.append(a[j] - a[j - 1])
        return out


def _mask(vals):
    """None if every point has a value, else which points are missing."""
    return None if _dense(vals) else [x != x for x in vals]


def _aggregate(op, series):
    n = len(series[0])
    if op == "group":
        return [1.0 if any(v[k] == v[k] for v in series) else NAN for k in range(n)]
    if op in ("sum", "avg", "count"):
        acc = cnt = acc_mask = None  # while cnt is None, every series so far had the same gaps
        seen = 0
        for vals in series:
            mask = _mask(vals)
            if acc is None:
                acc, acc_mask = list(vals), mask
            elif cnt is None and mask == acc_mask:
                acc = list(map(operator.add, acc, vals))
            else:
                if cnt is None:
                    cnt = [0.0 if m else float(seen) for m in acc_mask] if acc_mask else [float(seen)] * n
                acc = [b if a != a else (a if b != b else a + b) for a, b in zip(acc, vals)]
                cnt = [c + (1.0 if b == b else 0.0) for c, b in zip(cnt, vals)]
            seen += 1
        if cnt is None:
            cnt = [0.0 if m else float(seen) for m in acc_mask] if acc_mask else [float(seen)] * n
        if op == "sum":
            return [x if c else NAN for x, c in zip(acc, cnt)]
        if op == "count":
            return [c if c else NAN for c in cnt]
        return [x / c if c else NAN for x, c in zip(acc, cnt)]
    pick = max if op == "max" else min
    acc, acc_mask = list(series[0]), _mask(series[0])
    for vals in series[1:]:
        if acc_mask is not False and _mask(vals) == acc_mask:
            acc = list(map(pick, acc, vals))
        else:
            acc_mask = False
            acc = [b if a != a else (a if b != b else pick(a, b)) for a, b in zip(acc, vals)]
    return acc


def _topk(members, kp, top):
    n = len(members[0][1])
    keep = [[NAN] * n for _ in members]
    for k in range(n):
        want = kp[k]
        if want != want or want < 1:
            continue
        present = [(vals[k], i) for i, (_, vals) in enumerate(members) if vals[k] == vals[k]]
        present.sort(key=lambda p: p[0], reverse=top)
        for x, i in present[: int(want)]:
            keep[i][k] = x
    return [(lb, vals) for (lb, _), vals in zip(members, keep)]


def _label_replace(v, args):
    try:
        dst, repl, src, regex = (a[1] for a in args)
    except ValueError:
        raise EvalError("label_replace needs (vector, dst_label, replacement, src_label, regex)") from None
    if not all(isinstance(x, str) for x in (dst, repl, src, regex)):
        raise EvalError("label_replace arguments must be strings")
    rx = re.compile(regex)
    py_repl = re.sub(r"\$\{?(\w+)\}?", r"\\g<\1>", repl)
    out = []
    for lb, vals in v:
        m = rx.fullmatch(lb.get(src, ""))
        if m:
            lb = dict(lb)
            value = m.expand(py_repl)
            if value:
                lb[dst] = value
            else:
                lb.pop(dst, None)
        out.append((lb, vals))
    return out


def fmt_value(v: float) -> str:
    if v != v:
        return "NaN"
    if math.isinf(v):
        return "+Inf" if v > 0 else "-Inf"
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    s = "%.10g" % v
    if "e" in s:
        s = format(Decimal(s), "f")
    return s


def fmt_values(vals):
    """fmt_value for many values at once (the common case is one C-level format)."""
    out = []
    for x in vals:
        v = "%.10g" % x
        if "e" in v or "n" in v:
            v = fmt_value(x)
        out.append(v)
    return out


def fmt_ts(t: float):
    return int(t) if t == int(t) else round(t, 3)


def evaluate(ds, text: str, times: list, jmax: int):
    """Parse and evaluate. Returns ("vector"|"scalar"|"string", value) or ("matrix", raw) for a top-level range selector."""
    node = P.parse(text)
    ev = Evaluator(ds, times, jmax)
    if isinstance(node, P.MatrixSelector):
        if len(times) != 1:
            raise EvalError('invalid expression type "range vector" for range query, must be Scalar or instant Vector')
        return ("matrix", _raw_matrix(ev, node, times[0]))
    return ev.eval(node)


def _raw_matrix(ev, node, t):
    idx = ev.range_index(node.selector.offset, node.range, False)[0]
    if idx is None:
        return []
    jl, jt = idx
    out = []
    for s in ev.select(node.selector):
        a = s.read(jl, jt + 1)
        pts = [[fmt_ts(ev.ds.start + (jl + k) * ev.ds.step), fmt_value(x)] for k, x in enumerate(a) if x == x]
        if pts:
            out.append({"metric": s.labels, "values": pts})
    return out
