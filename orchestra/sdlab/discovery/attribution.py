"""Which stocks receive an outside inflow, and drains that do not absorb it: per-row tests and repairs.

For each row of a matrix model (matrix.identify_one's result):

  - counting noise (counting.py): the robust variance of the row's residuals in units of the throughput
    its terms imply. Far above 1: flows are missing (typically an inflow and a drain that cancel on
    average: the drain absorbed the inflow, so fed the true inflow the stock fills without limit);
    far below 1: a spurious pair (inflow pieces and a drain both too big).
  - partial-model simulation (partial.py): the row simulated alone, the other levels fed in as
    measured; robust error against holding the level.

A flagged row is refitted: its levels (the ones it reads, and its own as a drain) are measured within
short stretches with stretches where it does not hold down-weighted (stretches.py), then its outside
inflow is recovered with those numbers held: none, constant or changing (pieces), by BIC. The refit
replaces the row when it agrees better with the counting noise.
"""

from __future__ import annotations

import math

import numpy as np

from .changes import pelt
from .counting import gross, ratio, robust_var
from .flows import merge_by_label, read_flows
from .matrix import configurations, known_changes
from .partial import partial_error
from .regression import piece_values
from .stretches import stretch_fit


class Data:
    """The run as arrays: levels, single steps, configurations."""

    def __init__(self, stocks: list[dict], run: dict, opts: dict):
        self.stocks = stocks
        self.ids = [s["id"] for s in stocks]
        self.t = run["t"]
        self.levels = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(self.t)), dtype=float) for i in self.ids]))
        self.prev, self.dy = self.levels[:, :-1], np.diff(self.levels, axis=1)
        if opts.get("known"):
            self.dy = self.dy - known_changes(opts["known"], self.ids, len(self.t))[:, 1:]
        self.T = self.dy.shape[1]
        self.final = {s["id"] for s in stocks if s.get("final")}
        self.conf = None
        self.cfg = np.zeros(self.T, dtype=int)
        self.L = 1

    def with_eras(self, eras) -> "Data":
        conf = configurations(eras, self.t)
        if conf:
            self.conf, self.cfg, self.L = conf, conf[1], len(conf[0])
        return self


def columns(row: dict, d: Data) -> tuple[list[tuple[int, np.ndarray | None]], np.ndarray]:
    """A row's levels as columns (stock index, configuration mask or None) and their numbers."""
    keys = list(dict.fromkeys(k for c in row["coefL"] for k in c))
    cols, beta = [], []
    for k in keys:
        j = d.ids.index(k)
        vals = [c.get(k, 0.0) for c in row["coefL"]]
        if d.L == 1 or all(abs(v - vals[0]) < 1e-12 for v in vals):
            cols.append((j, None))
            beta.append(vals[0])
        else:
            for c in range(d.L):
                cols.append((j, d.cfg == c))
                beta.append(vals[c])
    return cols, np.array(beta, dtype=float)


def design(cols, d: Data) -> np.ndarray:
    if not cols:
        return np.zeros((0, d.T))
    return np.array([d.prev[j] if m is None else d.prev[j] * m for j, m in cols])


def inflow_series(pieces: list[dict], d: Data) -> np.ndarray:
    u = np.zeros(d.T)
    at = np.asarray(d.t[1:], dtype=float)
    for p in pieces or []:
        u[(at >= p["from"]) & (at <= p["to"])] = p["value"]
    return u


def recover_inflow(res: np.ndarray, d: Data, n_terms: int, opts: dict) -> list[dict]:
    """The outside inflow of what the levels leave unexplained, the levels' numbers held: none,
    constant or changing (pieces found by PELT), by BIC; a changing one only if its mean is clear of
    its own standard error (or the constant beats none)."""
    T = d.T
    log_t = math.log(T)
    bic = lambda rss, p: T * math.log(max(rss, 1e-12) / T) + p * log_t  # noqa: E731
    at = lambda k: d.t[k + 1]  # noqa: E731
    none = bic(float(res @ res), n_terms)
    c = res - res.mean()
    const = bic(float(c @ c), n_terms + 1)
    form, best = ("none", none) if none <= const else ("constant", const)
    cuts = [0, T]
    if opts.get("changes") is not False:
        cuts = pelt(res, opts.get("min_piece", 5), 1)
        if len(cuts) > 2:
            vals = piece_values(res, np.zeros((0, T)), [], np.zeros(0), cuts)
            seg = np.repeat(np.arange(len(vals)), np.diff(cuts))
            rr = res - np.array([v["v"] for v in vals])[seg]
            rss = float(rr @ rr)
            sc = bic(rss, n_terms + len(cuts) - 1)
            clear = abs(res.mean()) > 2 * math.sqrt(rss / T) / math.sqrt(T)
            if (form == "constant" or clear) and sc < best:
                form, best = "pieces", sc
    if form == "none":
        return []
    if form == "constant":
        cuts = [0, T]
    return [{"from": at(p["a"]), "to": at(p["b"] - 1), "value": p["v"]} for p in piece_values(res, np.zeros((0, T)), [], np.zeros(0), cuts)]


def diagnose(s: int, row: dict, d: Data, opts: dict) -> dict:
    cols, beta = columns(row, d)
    X = design(cols, d)
    u = inflow_series(row["inflow"], d)
    res = d.dy[s] - (beta @ X if len(beta) else 0.0) - u
    z = ratio(res, gross(beta, X, u))
    part = partial_error(s, cols, beta, u, d.levels, opts.get("partial_h", 20)) if opts.get("partial", True) else float("nan")
    return {"z": z, "partial": part}


def refit(s: int, row: dict, d: Data, opts: dict) -> dict:
    """The row's levels (and its own, as a drain) measured within stretches, then its inflow
    recovered with them held."""
    cols, _ = columns(row, d)
    sid = d.ids[s]
    if sid not in d.final and not any(j == s for j, _ in cols):
        cols = cols + [(s, None)]
    X = design(cols, d)
    y = d.dy[s]
    own = [q for q, (j, m) in enumerate(cols) if j == s and m is None]
    fit = stretch_fit(y, X, opts.get("stretch", 25), own=own[0] if own and opts.get("bias_correct", True) else None)
    beta = fit["beta"]
    if sid not in d.final and opts.get("drain_sign", True):
        # a stock's own number is a drain (or nothing): a positive one here is a stretch artefact
        for q, (j, _) in enumerate(cols):
            if j == s and beta[q] > 0:
                beta[q] = 0.0
    res = y - (beta @ X if len(beta) else 0.0)
    inflow = recover_inflow(res, d, len(beta), opts)
    coef_l: list[dict] = [{} for _ in range(d.L)]
    for (j, m), b in zip(cols, beta):
        for c in range(d.L):
            if m is None or (d.cfg == c).any() and bool(m[d.cfg == c].all()):
                coef_l[c][d.ids[j]] = coef_l[c].get(d.ids[j], 0.0) + float(b)
    return {**row, "coefL": coef_l, "coef": coef_l[0], "inflow": inflow, "repaired": True}


def repair(rows: list[dict], d: Data, opts: dict) -> tuple[list[dict], list[dict]]:
    """Every row tested; a flagged row refitted and replaced when the refit agrees better with the
    counting noise and (opts["accept"] = "strict", the default) is no longer flagged and does not
    track its stock worse alone (partial error at most 0.1 above the old row's). Returns the new rows
    and a report per row."""
    hi, lo = opts.get("missing", 4.0), opts.get("spurious", 0.25)
    out, report = [], []
    for s, row in enumerate(rows):
        dg = diagnose(s, row, d, opts)
        flagged = dg["z"] > hi or dg["z"] < lo or (opts.get("partial_flag", False) and dg["partial"] > 1)
        entry = {"id": row["id"], **dg, "flagged": flagged, "replaced": False}
        if flagged and robust_var(d.dy[s]) > 0:          # a level that rarely moves says nothing here
            new = refit(s, row, d, opts)
            dn = diagnose(s, new, d, opts)
            entry.update({"z_new": dn["z"], "partial_new": dn["partial"]})
            better = abs(math.log(max(dn["z"], 1e-9))) < abs(math.log(max(dg["z"], 1e-9)))
            if opts.get("accept", "strict") == "strict":
                better = better and lo <= dn["z"] <= hi and dn["partial"] <= dg["partial"] + 0.1
            if better:
                row = new
                entry["replaced"] = True
        out.append(row)
        report.append(entry)
    return out, report


def to_flows(rows: list[dict], d: Data, tol: float = 0.003) -> list[dict]:
    """Flows read off the rows, as matrix.identify_one does."""
    per_label = [read_flows(d.stocks, [{"id": r["id"], "coef": r["coefL"][c], "inflow": r["inflow"] if c == 0 else []} for r in rows], d.prev, tol) for c in range(d.L)]
    return merge_by_label(per_label, d.conf[0], d.conf[2]) if d.L > 1 else per_label[0]
