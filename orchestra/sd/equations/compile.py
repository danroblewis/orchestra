"""An equation (``language.Parsed``) compiled into numpy closures, evaluated for many states at
once: every column of the frame is one state (a member of the band, a candidate of the inverse
solver).

A ``Frame`` holds what a rate reads at one step: the rows of levels and inputs (``R``, rows x
columns, the row of each name in ``index``), each flow's parameters (scalars or one value per
column), each flow's measured rate (``observed``), the step's length in time units (``g``) and the
state of every ``smooth`` and ``delay``. ``advance`` moves that state on after the step."""

from __future__ import annotations

import ast

import numpy as np

from .language import BINARY, SMALL, Parsed

ONE = {"abs": np.abs, "exp": np.exp, "log": np.log, "sqrt": np.sqrt, "ceil": np.ceil, "floor": np.floor, "integer": np.trunc,
       "ln": np.log, "log10": np.log10, "sin": np.sin, "cos": np.cos, "tan": np.tan, "arcsin": np.arcsin, "arccos": np.arccos,
       "arctan": np.arctan, "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh, "not_": lambda x: (x == 0).astype(float)}


class Frame:
    def __init__(self, index: dict[str, int], g: float, columns: int):
        self.index = index
        self.g = g
        self.columns = columns
        self.R = np.zeros((len(index), columns))
        self.params: dict[str, dict] = {}            # flow id -> {name: scalar or array}
        self.observed: dict[str, np.ndarray] = {}    # flow id -> its measured rate now
        self.state: dict[tuple, object] = {}         # (flow, slot) -> smooth level, or delay buffer
        self.pending: dict[tuple, tuple] = {}        # (flow, slot) -> (kind, x, tau) to move on after the step

    def advance(self) -> None:
        for key, (kind, x, tau) in self.pending.items():
            if kind == "smooth":
                s = self.state[key]
                self.state[key] = s + (x - s) * np.minimum(1.0, self.g / np.maximum(tau, SMALL))
            else:
                self.state[key].append(np.array(x, dtype=float))
        self.pending.clear()


def _bcast(x, n: int):
    return np.broadcast_to(np.asarray(x, dtype=float), (n,))


def compile_rate(parsed: Parsed, flow: str):
    """A closure ``f(frame) -> rate per time unit``, one value per column (before the floor)."""
    slots = [0]

    def c(node):
        if isinstance(node, ast.Expression):
            return c(node.body)
        if isinstance(node, ast.Constant):
            v = float(node.value)
            return lambda fr: v
        if isinstance(node, ast.Name):
            return name(node.id)
        if isinstance(node, ast.UnaryOp):
            a = c(node.operand)
            return (lambda fr: -a(fr)) if isinstance(node.op, ast.USub) else a
        if isinstance(node, ast.BinOp):
            a, b, op = c(node.left), c(node.right), BINARY[type(node.op)]
            if op == "+":
                return lambda fr: a(fr) + b(fr)
            if op == "-":
                return lambda fr: a(fr) - b(fr)
            if op == "*":
                return lambda fr: a(fr) * b(fr)
            if op == "/":
                return lambda fr: np.divide(a(fr), b(fr))
            return lambda fr: np.power(np.asarray(a(fr), dtype=float), b(fr))
        if isinstance(node, ast.Compare):
            a, b = c(node.left), c(node.comparators[0])
            op = {ast.Lt: np.less, ast.LtE: np.less_equal, ast.Gt: np.greater, ast.GtE: np.greater_equal,
                  ast.Eq: np.equal, ast.NotEq: np.not_equal}[type(node.ops[0])]
            return lambda fr: op(a(fr), b(fr)).astype(float)
        return call(node)

    def name(n: str):
        if n in parsed.params:
            return lambda fr: fr.params[flow][n]
        key = f"stock:{n}" if n in parsed.stocks else f"input:{n}"
        return row(key)

    def row(key: str):
        return lambda fr: fr.R[fr.index[key]]

    def call(node: ast.Call):
        fn = node.func.id
        if fn in ("stock", "input"):
            return row(f"{fn}:{node.args[0].value}")
        if fn == "observed":
            return lambda fr: fr.observed.get(flow, 0.0)
        if fn == "lookup":
            x = c(node.args[0])
            pts = [(float(ast.literal_eval(e.elts[0])), float(ast.literal_eval(e.elts[1]))) for e in node.args[1].elts]
            xs, ys = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
            return lambda fr: np.interp(x(fr), xs, ys)
        args = [c(a) for a in node.args]
        if fn in ("min", "max"):
            red = np.minimum if fn == "min" else np.maximum

            def mm(fr):
                out = args[0](fr)
                for a in args[1:]:
                    out = red(out, a(fr))
                return out
            return mm
        if fn in ONE:
            f, a = ONE[fn], args[0]
            return lambda fr: f(np.asarray(a(fr), dtype=float))
        if fn in ("and_", "or_"):
            red = np.logical_and if fn == "and_" else np.logical_or

            def logic(fr):
                out = np.asarray(args[0](fr)) != 0
                for a in args[1:]:
                    out = red(out, np.asarray(a(fr)) != 0)
                return out.astype(float)
            return logic
        if fn == "power":
            a, b = args
            return lambda fr: np.power(np.asarray(a(fr), dtype=float), b(fr))
        if fn in ("quantum", "modulo"):
            a, b = args

            def quantum(fr):
                x, q = np.asarray(a(fr), dtype=float), np.asarray(b(fr), dtype=float)
                qq = np.where(q < 1e-6, x, q * np.trunc(np.divide(x, np.where(q < 1e-6, 1.0, q))))
                return qq if fn == "quantum" else x - qq
            return quantum
        if fn == "xidz":
            a, b, x = args

            def xidz(fr):
                d = np.asarray(b(fr), dtype=float)
                safe = np.abs(d) >= 1e-6
                return np.where(safe, np.divide(a(fr), np.where(safe, d, 1.0)), x(fr))
            return xidz
        if fn == "clip":
            x, lo, hi = args
            return lambda fr: np.minimum(hi(fr), np.maximum(lo(fr), x(fr)))
        if fn == "if_then_else":
            k, a, b = args
            return lambda fr: np.where(np.asarray(k(fr)) != 0, a(fr), b(fr))
        if fn == "zidz":
            a, b = args

            def zidz(fr):
                d = np.asarray(b(fr), dtype=float)
                safe = np.abs(d) >= SMALL
                return np.where(safe, np.divide(a(fr), np.where(safe, d, 1.0)), 0.0)
            return zidz
        slots[0] += 1
        key = (flow, slots[0])
        x, tau = args
        if fn == "smooth":
            def smooth(fr):
                v, t = _bcast(x(fr), fr.columns), tau(fr)
                if key not in fr.state:
                    fr.state[key] = v.copy()
                fr.pending[key] = ("smooth", v, t)
                return fr.state[key]
            return smooth

        def delay(fr):
            v, t = _bcast(x(fr), fr.columns), tau(fr)
            buf = fr.state.setdefault(key, [])
            k = max(0, round(float(np.mean(t)) / fr.g)) if fr.g > 0 else 0
            fr.pending[key] = ("delay", v, t)
            past = [*buf, v]
            return past[max(0, len(past) - 1 - k)]
        return delay

    return c(parsed.tree)
