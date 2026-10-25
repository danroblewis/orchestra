"""Expression rates evaluated on many steps at once (k8s 311, docs/research/fixes/311-structures.md).

The answer's later stages write rates the engine reads as expressions: a capacity limit `min(a X, b Y)`
(capmin.py), a room limit `min(a X, max(0, b Y - d Z))` (room.py), a controller `max(0, ceil(cpu / 192.5) -
desired)` (controller.py). The shared discovery simulator (simulate.Model, which the judge and the row stages
run on) reads an expression rate as 0, so every stage after those forms was judging a model without them: on
311 the judge saw no `pending -> ready` at all, and a kill move ready -> pending made its rows worse, not
better (the pods it moves were never seen to start again).

`amount(expr, X, n)` evaluates the expression (the engine's grammar, sdlab.sdtruth_expr.parse) on arrays of
the levels and inputs; `rate(expr, index)` is the same as a callable for simulate.Model's parts. Forms this
cannot run (flow(id), lookups, functions it does not list) give None, and the callers treat the flow as one
they cannot read, as before.
"""

from __future__ import annotations

import numpy as np

from orchestra.sdlab.sdtruth_expr import parse

ONE = {"abs": np.abs, "sqrt": np.sqrt, "exp": np.exp, "ln": np.log, "ceil": np.ceil, "floor": np.floor,
       "integer": np.trunc, "sin": np.sin, "cos": np.cos, "tanh": np.tanh}
CMP = {"<": np.less, "<=": np.less_equal, ">": np.greater, ">=": np.greater_equal, "==": np.equal, "!=": np.not_equal}


class Unreadable(Exception):
    pass


def _ev(node, get, n):
    kind = node[0]
    if kind == "num":
        return np.full(n, float(node[1]))
    if kind == "name":
        v = get(node[1])
        if v is None:
            raise Unreadable(node[1])
        return np.asarray(v, dtype=float)
    if kind == "neg":
        return -_ev(node[1], get, n)
    if kind == "bin":
        op, a, b = node[1], _ev(node[2], get, n), _ev(node[3], get, n)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            with np.errstate(divide="ignore", invalid="ignore"):
                return a / b
        if op == "^":
            return np.power(a, b)
        if op in CMP:
            return CMP[op](a, b).astype(float)
        raise Unreadable(op)
    if kind == "call":
        name, args = node[1], node[2]
        if name in ONE and len(args) == 1:
            return ONE[name](_ev(args[0], get, n))
        if name == "min":
            return np.minimum.reduce([_ev(a, get, n) for a in args])
        if name == "max":
            return np.maximum.reduce([_ev(a, get, n) for a in args])
        if name == "if_then_else" and len(args) == 3:
            c, a, b = (_ev(x, get, n) for x in args)
            return np.where(c != 0, a, b)
    raise Unreadable(str(node)[:80])


_TREES: dict[str, tuple] = {}


def _tree(expr: str):
    if expr not in _TREES:
        _TREES[expr] = parse(expr)
    return _TREES[expr]


def amount(expr: str, X: dict, n: int) -> np.ndarray | None:
    """The expression on every step (X: {name: array of n}), not floored; None where it cannot be read."""
    try:
        return np.broadcast_to(_ev(_tree(expr), X.get, n), (n,)).astype(float)
    except Exception:                                      # noqa: BLE001  (a form this cannot run)
        return None


class Rate:
    """An expression rate as simulate.Model's parts call one: rate(R, seg) on R (rows: the index's names,
    columns: states), floored at 0 as the engine floors every rate."""

    def __init__(self, expr: str, index: dict[str, int]):
        self.expr, self.index = expr, index
        self.form = "expr"

    def __call__(self, R: np.ndarray, seg: np.ndarray) -> np.ndarray:
        n = R.shape[1]
        v = amount(self.expr, {k: R[i] for k, i in self.index.items() if i < R.shape[0]}, n)
        return np.zeros(n) if v is None else np.maximum(0.0, np.nan_to_num(v))
