"""A grammar of effect curves: the shapes a stock's level may take in multiplying a flow's rate.

Each curve is a function of u = level / scale (scale: the level's high end in the data, so u runs
over about [0, 1] whatever the stock's units). A flow's rate k x A x (b + (1 - b) x s(u)) is linear
in two columns, A and A x s(u), so only the shape s has to be searched; its floor b and the flow's
number k come out of least squares. Shapes: rising and falling, saturating, accelerating, S-shaped,
clamped.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Curve:
    name: str
    kind: str
    a: float = 0.0
    b: float = 0.0
    top: float | None = None           # turned over: top - s(u)

    def turned(self, top: float) -> Curve:
        return Curve(f"turned {self.name}", self.kind, self.a, self.b, top)

    def __call__(self, u: np.ndarray) -> np.ndarray:
        v = self._shape(np.maximum(0.0, u))
        return v if self.top is None else self.top - v

    def _shape(self, u: np.ndarray) -> np.ndarray:
        a, b = self.a, self.b
        if self.kind == "lin":
            return u
        if self.kind == "sat":                       # 1 - e^(-u/a): rises fast, then levels off
            return 1 - np.exp(-u / a)
        if self.kind == "mm":                        # u / (u + a)
            return u / (u + a)
        if self.kind == "acc":                       # e^((u-1)/a): accelerating
            return np.exp(np.minimum(50.0, (u - 1) / a))
        if self.kind == "decay":                     # e^(-u/a)
            return np.exp(-u / a)
        if self.kind == "rise":                      # logistic around a, width b
            return 1 / (1 + np.exp(-np.clip((u - a) / b, -50, 50)))
        if self.kind == "fall":
            return 1 / (1 + np.exp(np.clip((u - a) / b, -50, 50)))
        if self.kind == "cap":                       # min(1, u / a): linear up to a, then flat
            return np.minimum(1.0, u / a)
        if self.kind == "floor":                     # max(0, u - a): nothing below a
            return np.maximum(0.0, u - a)
        if self.kind == "cut":                       # min(1, max(0, (a - u) / b)): stops near a
            return np.clip((a - u) / b, 0.0, 1.0)
        raise ValueError(self.kind)


def grammar() -> list[Curve]:
    out = [Curve("lin", "lin")]
    out += [Curve(f"sat {a}", "sat", a) for a in (0.08, 0.15, 0.25, 0.4, 0.7)]
    out += [Curve(f"mm {a}", "mm", a) for a in (0.1, 0.3, 1.0)]
    out += [Curve(f"acc {a}", "acc", a) for a in (0.15, 0.3, 0.6)]
    out += [Curve(f"decay {a}", "decay", a) for a in (0.1, 0.2, 0.4, 0.8)]
    for m in (0.2, 0.35, 0.5, 0.65, 0.8, 0.95):
        for w in (0.03, 0.07, 0.15):
            out.append(Curve(f"rise {m}/{w}", "rise", m, w))
            out.append(Curve(f"fall {m}/{w}", "fall", m, w))
    out += [Curve(f"cap {a}", "cap", a) for a in (0.3, 0.5, 0.7)]
    out += [Curve(f"floor {a}", "floor", a) for a in (0.3, 0.5, 0.7)]
    out += [Curve(f"cut {a}/{b}", "cut", a, b) for a in (0.8, 0.95) for b in (0.1, 0.25)]
    return out
