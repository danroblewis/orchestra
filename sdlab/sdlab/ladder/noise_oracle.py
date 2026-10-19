"""The scorer's oracle for the noisy variants (noise.py): how precisely the data pin each true number
down, when the levels are reported with error, with gaps, weekly, late, with outliers or biased.
The same interface as oracle.Oracle (ok, se, part_se) and hidden_oracle.HiddenOracle (ok, part_se,
hidden_se), so score.equations and analysis use it unchanged: the scorer allows a found number z
standard errors, as before; only the standard errors know the noise.

**The standard error.** The one the counts variant would allow on the run underneath (the linear
oracle, or the hidden oracle, on the clean counts run), times what the noise costs:

    SE = SE_counts(clean run) x SE_kalman(reported data) / SE_kalman(clean run)

where SE_kalman is the Kalman filter's standard error of the truth's own structure (noise_kf.py)
on the data as reported and on every step of the clean run. The ratio is the measured loss of
information (1 when nothing is lost: the sweep's 0% point is the counts variant), so a tolerance
widens by exactly what the noise takes, never by a fixed amount, and the noisy variants are judged
on the same footing as `counts`.

A number the noisy data cannot pin down (the bias makes it a product with something else) gets no
allowance (SE None): it is scored by the relative tolerance alone, and the analysis calls the cell
unidentifiable.

**How it is reached.** score.py and analysis.py build their oracle as `Oracle(truth_flows, data,
wins)` and `HiddenOracle(truth_flows, data, wins, noise)`. install() (run when sdlab.ladder is
imported) replaces those two names in both modules with factories that return the oracle here for
a noisy variant's data (it has an `observation`) and the original class for everything else, so
the scorer's code, and with it the score hash of every stored result, is unchanged.
"""

from __future__ import annotations

import math

import numpy as np

from . import noise_kf
from .hidden_oracle import HiddenOracle as _Hidden
from .oracle import Oracle as _Linear
from .parts import ONE


def clean_view(data: dict) -> dict:
    """The clean counts run under a noisy variant's data, observed exactly at every step (the
    Kalman model's reference)."""
    c = data["clean"]
    n = len(c["t"])
    return {"t": c["t"], "levels": c["levels"], "all_levels": c.get("all_levels") or c["levels"],
            **({"injections": c["injections"]} if c.get("injections") else {}),
            "observation": {"kind": "clean", "at": list(range(n)), "span": 1, "outliers": [], "bias": {}}, "clean": c}


class _Kalman:
    """SEs of the truth's numbers, parts and linear system on one Kalman model."""

    def __init__(self, m: noise_kf.SSM | None):
        self.m = m
        self._b = self._p = self._e = None
        self._extra: dict = {}

    def _bound(self):
        if self._b is None:
            self._b = self.m.bound()
        return self._b

    def _table(self, which: str):
        if which == "parts":
            if self._p is None:
                keys, vals, D = self.m.jacobian(self.m.part_values)
                self._p = ({k: i for i, k in enumerate(keys)}, vals, D)
            return self._p
        if self._e is None:
            keys, vals, D = self.m.jacobian(self.m.entry_values)
            self._e = ({k: i for i, k in enumerate(keys)}, vals, D)
        return self._e

    def se(self, which: str, key) -> float | None | bool:
        """The SE of a number the truth has (None: not pinned down), or False when it is not a
        function of the truth's numbers (a number the truth lacks)."""
        if self.m is None:
            return None
        index, vals, D = self._table(which)
        i = index.get(key)
        if i is None or not np.any(D[i]):
            return False
        C, null = self._bound()
        g = D[i]
        if null.size and np.abs(g @ null).max() > 1e-6 * max(abs(vals[i]), 1e-9):
            return None
        return float(math.sqrt(max(float(g @ C @ g), 0.0)))

    def extra_se(self, rows: dict, col: str) -> float | None:
        """The SE of one more number added to the truth: rows {stock: sign} change by it times col's
        level (or by it, col "1"), over the whole run."""
        if self.m is None:
            return None
        key = noise_kf._freeze((rows, col, None))
        if key not in self._extra:
            C, null = self.m.bound([(rows, col, None)])
            ok = not (null.size and np.abs(null[-1]).max() > 1e-6)
            self._extra[key] = float(math.sqrt(max(C[-1, -1], 0.0))) if ok else None
        return self._extra[key]


class _Base:
    def __init__(self, data: dict, wins: list[tuple[int, int]]):
        self.noisy = _Kalman(noise_kf.model(data, wins))
        self.clean = _Kalman(noise_kf.model(clean_view(data), wins) if self.noisy.m is not None else None)
        c = data["clean"]
        self.flows = c["flows"]
        self.cdata = {"t": c["t"], "levels": c["levels"], "all_levels": c.get("all_levels") or c["levels"],
                      **({"injections": c["injections"]} if c.get("injections") else {})}

    def _ratio(self, which: str, key) -> float | None | bool:
        """SE_kalman(reported) / SE_kalman(clean); None: the reported data do not pin it down;
        False: not one of the truth's numbers."""
        a = self.noisy.se(which, key)
        if a is None or a is False:
            return a
        b = self.clean.se(which, key)
        return a / b if b else None

    def _extra_ratio(self, rows: dict, col: str) -> float | None:
        a, b = self.noisy.extra_se(rows, col), self.clean.extra_se(rows, col)
        return a / b if a is not None and b else None


def _times(base: float | None, ratio) -> float | None:
    return None if base is None or ratio is None or ratio is False else base * ratio


class KalmanOracle(_Base):
    """oracle.Oracle for a noisy run of a truth without hidden stocks."""

    def __init__(self, truth_flows: list[dict], data: dict, wins: list[tuple[int, int]]):
        super().__init__(data, wins)
        self.ids = list(data["levels"])
        self.W = len(wins)
        self.linear = _Linear(self.flows, self.cdata, wins)
        self.ok = self.noisy.m is not None and not self.noisy.m.hidden and self.linear.ok and len(data["t"]) > 3

    def se(self, stock: str, col: str, window: int) -> float | None:
        if not self.ok or stock not in self.ids or (col != ONE and col not in self.ids):
            return None
        r = self._ratio("entries", (window, stock, col))
        if r is False:
            r = self._extra_ratio({stock: 1.0}, col)
        return _times(self.linear.se(stock, col, window), r)

    def part_se(self, key: tuple, true_keys: list[tuple], window: int) -> float | None:
        if not self.ok or key[0] != "flow":
            return None
        r = self._ratio("parts", (window, key, None))
        if r is False:
            _, a, b, j = key
            rows = {s: v for s, v in ((b, 1.0), (a, -1.0)) if s}
            r = self._extra_ratio(rows, j) if rows else None
        return _times(self.linear.part_se(key, true_keys, window), r)


class KalmanHidden(_Base):
    """hidden_oracle.HiddenOracle for a noisy run of a truth with a hidden stock."""

    def __init__(self, truth_flows: list[dict], data: dict, wins: list[tuple[int, int]], noise: str):
        super().__init__(data, wins)
        self.hidden = _Hidden(self.flows, self.cdata, wins, "counts")
        self.ok = self.noisy.m is not None and bool(self.noisy.m.hidden) and self.hidden.ok

    def part_se(self, key: tuple, window: int) -> float | None:
        if not self.ok or key[0] != "flow":
            return None
        return _times(self.hidden.part_se(key, window), self._ratio("parts", (window, key, None)))

    def hidden_se(self, key: tuple, window: int) -> dict | None:
        if not self.ok or key[0] != "hidden":
            return None
        base = self.hidden.hidden_se(key, window) or {}
        return {sub: _times(base.get(sub), self._ratio("parts", (window, key, sub))) for sub in ("k_in", "delay")}


def _noisy(data) -> bool:
    return isinstance(data, dict) and bool(data.get("observation"))


def install() -> None:
    """Route score.py's and analysis.py's oracles to the ones here for noisy data (idempotent)."""
    from . import analysis, score
    for mod in (score, analysis):
        if getattr(mod.Oracle, "_noise_router", False):
            continue
        base, hidden = mod.Oracle, mod.HiddenOracle

        def oracle(truth_flows, data, wins, _base=base):
            return KalmanOracle(truth_flows, data, wins) if _noisy(data) else _base(truth_flows, data, wins)

        def hidden_oracle(truth_flows, data, wins, noise, _base=hidden):
            return KalmanHidden(truth_flows, data, wins, noise) if _noisy(data) else _base(truth_flows, data, wins, noise)

        oracle._noise_router = hidden_oracle._noise_router = True
        mod.Oracle, mod.HiddenOracle = oracle, hidden_oracle
