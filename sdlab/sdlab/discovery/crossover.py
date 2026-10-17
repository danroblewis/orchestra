"""A model assembled row by row from the candidates' rows.

Every candidate of identify() makes its choices for all stocks at once (forward or backward search,
changing or constant outside inflows, trusting receivers or rows, numbers per era). Different stocks
may need different choices, so a model may take each stock's row from a different candidate: a
"gene" per stock is (the candidate whose fitted row it uses, whether conservation trusts receivers
for it). A mixture is assembled from the rows as fitted (before conservation), conservation and
the reading of flows are run on the mixture (matrix.finish), and the mixture is judged as a whole.

Search: start from the judge's pick, visit stocks worst first by their partial-model error
(partial.py), try every other distinct gene for the stock, and keep the best swap only if the whole
model's error falls by more than a margin (relative). A few sweeps.
"""

from __future__ import annotations

from .identify import judge
from .matrix import finish, raw_row
from .partial import partial_errors


def _row_key(row: dict, trust: bool, split: bool) -> tuple:
    coef = tuple(tuple(sorted((k, round(v, 9)) for k, v in c.items())) for c in row["coefL"])
    return (coef, tuple(row["cuts"] or ()), trust, split)


class Pool:
    """The candidates' fitted rows and how to assemble a model from a choice of them."""

    def __init__(self, cands: list[dict], stocks: list[dict], opts: dict):
        # cands: {"variant", "result"} with result from identify_one(..., keep_rows=True)
        self.cands, self.stocks, self.opts = cands, stocks, opts
        self.ids = [s["id"] for s in stocks]
        self.genes: list[list[tuple[int, bool]]] = []
        for s in range(len(self.ids)):
            seen, genes = set(), []
            for ci, c in enumerate(cands):
                v = c["variant"]
                row = c["result"]["raw_rows"][s]
                own = v.get("trust_receivers") is not False
                # trusting receivers or the row matters only for a row with a changing inflow
                changing = bool(row["cuts"]) and len(row["cuts"]) > 2
                for trust in (own, not own) if changing else (own,):
                    key = _row_key(row, trust if changing else None, bool(v.get("split_eras")))
                    if key not in seen:
                        seen.add(key)
                        genes.append((ci, trust))
            self.genes.append(genes)

    def start(self, ci: int) -> tuple:
        trust = self.cands[ci]["variant"].get("trust_receivers") is not False
        return tuple((ci, trust) for _ in self.ids)

    def assemble(self, mix: tuple) -> dict:
        split = [ci for ci, _ in mix if self.cands[ci]["variant"].get("split_eras")]
        ctx = self.cands[split[0] if split else mix[0][0]]["result"]["ctx"]
        L = ctx["L"]
        rows = []
        for s, (ci, trust) in enumerate(mix):
            r = raw_row(self.cands[ci]["result"]["raw_rows"][s])
            if len(r["coefL"]) != L:                # a row with one set of numbers in a model with eras
                r["coefL"] = [dict(r["coefL"][0]) for _ in range(L)]
            r["trust_receivers"] = trust
            rows.append(r)
        return finish(rows, ctx, self.opts)


def crossover(pool: Pool, start: tuple, run: dict, extra: list[dict], margin: float = 0.05, sweeps: int = 2,
              judge=judge) -> tuple[tuple, dict, float, list[dict]]:
    """Greedy per-stock swaps from `start`; returns the mixture, its model, its error and the swaps kept.
    `judge(flows, stocks, run)` scores a mixture (lower is better): identify's in-data judge by
    default; a stricter one (piece-proof, behaviour-consistency) can be passed in."""
    cache: dict[tuple, float] = {}               # errors only: a long run's models are large

    def score(mix):
        if mix not in cache:
            r = pool.assemble(mix)
            cache[mix] = judge(r["flows"] + extra if r["flows"] else [], pool.stocks, run)
        return None, cache[mix]

    cur = start
    r = pool.assemble(cur)
    e = score(cur)[1]
    swaps = []
    for _ in range(sweeps):
        changed = False
        part = partial_errors(r["flows"] + extra, pool.ids, run["t"], run["levels"]) if r["flows"] else {}
        order = sorted(range(len(pool.ids)), key=lambda s: -part.get(pool.ids[s], 0.0))
        for s in order:
            best = None
            for g in pool.genes[s]:
                if g == cur[s]:
                    continue
                mix = cur[:s] + (g,) + cur[s + 1:]
                rr, ee = score(mix)
                if best is None or ee < best[2]:
                    best = (mix, rr, ee)
            if best is not None and best[2] < e * (1 - margin):
                g = best[0][s]
                swaps.append({"stock": pool.ids[s], "from": pool.cands[cur[s][0]]["variant"]["name"], "to": pool.cands[g[0]]["variant"]["name"],
                              "trust_receivers": g[1], "error": [e, best[2]]})
                cur, e = best[0], best[2]
                r = pool.assemble(cur)
                changed = True
        if not changed:
            break
    return cur, r, e, swaps
