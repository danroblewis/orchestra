"""The output-error model kept inside the announced boundary (boundary.py, docs/research/declared-boundary.md).

The per-step model reads columns (fit.columns: levels, inputs, the constant, products, square
roots), and write.to_flows turns what a row reads into flows: a stock's own negative number is a
drain, moved into same-unit stocks that gain from it as far as it goes and to outside for the rest;
the constant, inputs, products and other-unit levels are outside inflows or outflows. So the
boundary is a restriction on the columns, applied when the search starts (Spec(region=...)) and
kept by every spec built from it (products, roots, hinges):

- the constant, products and hinges only on a stock with an `estimate` side (pieces_ok);
- inputs only on a stock with a `measured` side (inputs_ok);
- a level of another unit, or of a final stock (which never sends: reading it is a link), only on a
  stock with an `estimate` side (links_ok);
- a square root of another stock of another unit only where pieces_ok;
- a stock with no `estimate` outflow is tied: its own number is not free but minus what its
  same-unit receivers gain from it (Spec.tie), so its drain is all moves.

With no boundary declared nothing is restricted (every side open): the search is as before, and
the outside flows it keeps are priced as boundary claims on the final answer (boundary.apply).
"""

from __future__ import annotations

import numpy as np

from .boundary import Boundary


class Region:
    def __init__(self, b: Boundary, stocks: list[dict]):
        self.b = b
        self.ids = [s["id"] for s in stocks]
        self.units = [s.get("unit") or "" for s in stocks]
        self.final = {k for k, s in enumerate(stocks) if s.get("final")}
        S = len(self.ids)
        # a final stock never sends (it has no receivers: tied, its own number is 0)
        self.ties = {a: [s for s in range(S) if s != a and self.units[s] == self.units[a] and a not in self.final]
                     for a in range(S) if b.must_tie(self.ids[a])}

    def mask(self, spec) -> np.ndarray:
        """Which columns each row may read (S x spec.P)."""
        S, m, b, ids = spec.S, spec.m, self.b, self.ids
        M = np.ones((S, spec.P), bool)
        for i in range(S):
            pieces, links = b.pieces_ok(ids[i]), b.links_ok(ids[i])
            for j in range(S):
                # another stock's level: a move from it (same unit, it can send) or a link (outside)
                if j != i and not links and (self.units[j] != self.units[i] or j in self.final):
                    M[i, j] = False
            M[i, S:S + m] = b.inputs_ok(ids[i])
            M[i, S + m] = pieces
            k = S + m + 1
            M[i, k:k + len(spec.products)] = pieces
            k += len(spec.products)
            for p, a in enumerate(spec.roots):
                M[i, k + p] = pieces or a == i or self.units[a] == self.units[i]
            if i in self.ties:
                M[i, i] = False
        return M

    def hinge_ok(self, i: int) -> bool:
        return self.b.pieces_ok(self.ids[i])
