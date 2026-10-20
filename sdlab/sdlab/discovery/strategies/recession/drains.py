"""Drains measured where nothing flows in: recession analysis on a found matrix.

The recession strategy's own copy of sdlab/discovery/recession.py (pinned; copied at bcb7192, last
changed in ef98017). Changed here: a row's readers are looked up among the stocks' levels and the
measured inputs (reader_columns), and a row's number on an input is kept as an input flow; the shared
module looked every reader up among the stocks only and crashed (ValueError) on any case with a
measured input.

In a row's one-step fit, a stock's drain and its unannounced outside inflow are confounded: the inflow
is taken out piece by piece (each piece's mean), and short or misplaced pieces bias the drain. But
where the outside inflow stops (doors close, a season ends, a delivery has not come), the level decays
freely and its drain can be read off the recession with no inflow model at all (Kirchner 2009, run
backwards: fix the storage-discharge law first, then recover the input with it fixed).

Per row with an outside inflow:
  1. the steps where the inflow sits at its lowest level ("quiet" steps) are found in what the row's
     levels leave unexplained (fine pieces; those at the bottom of their distribution);
  2. the row's levels are fitted on the quiet steps only, with one constant for the quiet level of the
     inflow, dropped when it is indistinguishable from 0 (then the fit has no inflow term at all);
     1 and 2 repeat with the new numbers until the quiet steps settle;
  3. the quiet numbers are kept only if there are enough quiet steps and they differ from the row's
     own by more than 2 standard errors;
  4. the outside inflow is then measured on all steps with those numbers fixed (never the other way
     round: the levels are not refitted on the pieces).
"""

from __future__ import annotations

import numpy as np

from ...changes import pelt
from ...flows import merge_by_label, read_flows
from ...matrix import configurations, input_flows, known_changes
from ...regression import fit_subset, piece_values, row_sums, stepwise


def _noise_sd(r: np.ndarray) -> float:
    return float(np.sqrt(np.sum(np.diff(r) ** 2) / (2 * max(1, len(r) - 1)))) or 1.0


def quiet_steps(res: np.ndarray, min_len: int = 2, share: float = 0.1, width: float = 2.0, trim: int = 0) -> np.ndarray:
    """The steps whose outside inflow sits at its lowest level: res (what the levels leave unexplained)
    is cut into fine pieces; a piece is quiet when its value is within `width` standard errors of the
    weighted `share` quantile of the pieces' values."""
    cuts = pelt(res, min_len, 1)
    vals = np.array([res[a:b].mean() for a, b in zip(cuts[:-1], cuts[1:])])
    w = np.diff(cuts).astype(float)
    order = np.argsort(vals)
    cum = np.cumsum(w[order]) / w.sum()
    q = vals[order][np.searchsorted(cum, share)]
    # the noise within pieces (successive differences would count the inflow's switches too)
    within = sum(float(((res[a:b] - v) ** 2).sum()) for (a, b), v in zip(zip(cuts[:-1], cuts[1:]), vals))
    sd = float(np.sqrt(within / max(1, len(res) - len(vals)))) or _noise_sd(res)
    mask = np.zeros(len(res), bool)
    for (a, b), v, n in zip(zip(cuts[:-1], cuts[1:]), vals, w):
        if v <= q + width * sd / np.sqrt(n):
            mask[a:b] = True
    if trim:
        # a quiet stretch's first and last steps are where a misplaced change would sit
        edge = np.diff(np.concatenate([[False], mask, [False]]).astype(int))
        for a, b in zip(np.flatnonzero(edge == 1), np.flatnonzero(edge == -1)):
            mask[a: min(b, a + trim)] = False
            mask[max(a, b - trim): b] = False
    return mask


def reader_columns(prev: np.ndarray, ids: list[str], t: list, opts: dict) -> tuple[np.ndarray, list[str]]:
    """Every series a row's numbers may read, and their names: the stocks' levels at the start of each
    step, then the measured inputs (opts "inputs") during it (the value at the step's end), as the
    matrix method builds them. An input is a known regressor of the row, never a stock."""
    inputs = [(k, np.nan_to_num(np.asarray(v, dtype=float))[1: len(t)]) for k, v in (opts.get("inputs") or {}).items() if k not in ids]
    if not inputs:
        return prev, list(ids)
    return np.vstack([prev] + [v[None, :] for _, v in inputs]), list(ids) + [k for k, _ in inputs]


def _columns(row: dict, ids: list[str], prev: np.ndarray, cfg: np.ndarray, L: int, names: list[str] | None = None) -> list[tuple[str, int, np.ndarray]]:
    """The row's readers as columns: (name, configuration or -1 for all, values). A reader whose number
    differs by configuration gets one column per configuration. prev, names: every series the row may
    read (the stocks' levels, then any measured inputs: reader_columns); names defaults to ids."""
    names = names or ids
    out = []
    used = list(dict.fromkeys(j for c in row["coefL"] for j in c))
    s = ids.index(row["id"])
    if ids[s] not in used:
        used.append(ids[s])
    for j in used:
        x = prev[names.index(j)]
        vals = [row["coefL"][c].get(j, 0.0) for c in range(L)]
        if L > 1 and max(vals) - min(vals) > 1e-12:
            out += [(j, c, np.where(cfg == c, x, 0.0)) for c in range(L)]
        else:
            out.append((j, -1, x))
    return out


def recession_row(y: np.ndarray, cols: list, current: np.ndarray, own: list[int], opts: dict) -> dict | None:
    """The quiet fit of one row: y its changes, cols its levels' columns, current its numbers now.
    Returns {"beta", "c", "quiet"} when the quiet numbers are kept, else None."""
    T = len(y)
    X = np.array([c[2] for c in cols])
    p_all = list(range(len(cols)))
    beta = current.copy()
    mask = None
    for _ in range(opts.get("recession_iterations", 4)):
        res = y - beta @ X
        nxt = quiet_steps(res, opts.get("recession_min_len", 2), opts.get("recession_share", 0.1), opts.get("recession_width", 2.0), opts.get("recession_trim", 0))
        if mask is not None and (nxt == mask).all():
            break
        mask = nxt
        n = int(mask.sum())
        if n < max(opts.get("recession_min_steps", 20), 5 * (len(cols) + 1)) or n > 0.9 * T:
            return None
        Xq = np.vstack([X[:, mask], np.ones(n)])
        sums = row_sums(y[mask], Xq, None)
        # which of the row's levels the quiet steps support (its own always stays), plus the constant
        cands = p_all + ([len(cols)] if opts.get("recession_constant", True) else [])
        chosen = stepwise(sums, cands, cands, np.log(n), 4 * len(cols))
        chosen = sorted(set(chosen) | set(own))
        f = fit_subset(sums, chosen)
        if len(cols) in chosen:
            k = chosen.index(len(cols))
            if abs(f.beta[k]) < 2 * f.se[k]:
                chosen = [q for q in chosen if q != len(cols)]
                f = fit_subset(sums, chosen)
        beta = np.zeros(len(cols))
        c = 0.0
        se = np.full(len(cols), np.inf)
        for q, b, e in zip(chosen, f.beta, f.se):
            if q == len(cols):
                c = float(b)
            else:
                beta[q], se[q] = b, e
    if mask is None:
        return None
    # zero only: the quiet steps must be truly quiet (no inflow at all, as the brief has it), not just
    # the inflow's lowest level (selecting steps by a low residual selects on the noise too)
    if opts.get("recession_zero_only") and c != 0:
        return None
    # the quiet steps must pin the drain down: a level that sits still while the inflow is quiet
    # (at an equilibrium) cannot be told from the quiet level of the inflow
    for q in own:
        if not se[q] <= opts.get("recession_precision", 0.25) * abs(beta[q]):
            return None
    # kept only if the quiet numbers differ from the row's own by more than 2 standard errors
    diff = np.abs(beta - current)
    if not np.any(diff[np.isfinite(se)] > opts.get("recession_se", 2.0) * se[np.isfinite(se)]) and not np.any((current != 0) & ~np.isfinite(se)):
        return None
    return {"beta": beta, "c": c, "quiet": mask}


def apply(stocks: list[dict], run: dict, result: dict, opts: dict) -> dict | None:
    """A copy of result (identify_one's) with every row that has an outside inflow refitted on its quiet
    steps; None when no row changes."""
    if not result.get("matrix"):
        return None
    ids = [s["id"] for s in stocks]
    t = run["t"]
    lv = np.nan_to_num(np.array([np.asarray(run["levels"].get(i, [0] * len(t)), dtype=float) for i in ids]))
    prev, dy = lv[:, :-1], np.diff(lv, axis=1)
    columns, names = reader_columns(prev, ids, t, opts)
    if opts.get("known"):
        dy = dy - known_changes(opts["known"], ids, len(t))[:, 1:]
    T = dy.shape[1]
    labels = result.get("eras") or [None]
    L = len(labels)
    conf = configurations(opts.get("eras"), t) if L > 1 else None
    cfg = conf[1] if conf else np.zeros(T, dtype=int)
    final = {s["id"] for s in stocks if s.get("final")}
    at = lambda k: t[k + 1]  # noqa: E731
    rows = [dict(r, coefL=[dict(c) for c in r["coefL"]]) for r in result["matrix"]]
    changed = []
    for row in rows:
        sid = row["id"]
        if sid in final or not row.get("inflow") or (row.get("conserved") and opts.get("recession_conserved") is not True):
            continue
        s = ids.index(sid)
        cols = _columns(row, ids, columns, cfg, L, names)
        cur = np.array([row["coefL"][c if c >= 0 else 0].get(j, 0.0) for j, c, _ in cols])
        own = [q for q, (j, _, _) in enumerate(cols) if j == sid and row["coefL"][0].get(sid)]
        got = recession_row(dy[s], cols, cur, own, opts)
        if got is None:
            continue
        coef_l: list[dict] = [{} for _ in range(L)]
        for (j, c, _), b in zip(cols, got["beta"]):
            if b == 0:
                continue
            for cc in range(L):
                if c < 0 or c == cc:
                    coef_l[cc][j] = float(b)
        X = np.array([c[2] for c in cols])
        res = dy[s] - got["beta"] @ X
        cuts = pelt(res, opts.get("recession_piece", opts.get("min_piece", 5)), 1) if opts.get("changes") is not False else [0, T]
        row["coefL"], row["coef"] = coef_l, coef_l[0]
        row["cuts"] = cuts
        row["inflow"] = [{"from": at(p["a"]), "to": at(p["b"] - 1), "value": p["v"]} for p in piece_values(res, X, [], np.zeros(0), cuts)]
        row["recession"] = {"quiet": int(got["quiet"].sum()), "constant": got["c"]}
        changed.append(sid)
        if opts.get("trace") == sid:
            print(f"  {sid} recession: {int(got['quiet'].sum())} quiet steps, quiet level {got['c']:.3f};", ", ".join(f"{j}{'@' + str(c) if c >= 0 else ''} {b:.4f}" for (j, c, _), b in zip(cols, got["beta"])))
    if not changed:
        return None
    per_label = [read_flows(stocks, [{"id": r["id"], "coef": r["coefL"][c], "inflow": r["inflow"] if c == 0 else []} for r in rows], prev, opts.get("tol", 0.003)) for c in range(L)]
    for c, fl in enumerate(per_label):                    # a row's number on a measured input, as the matrix method reads it
        fl += input_flows(rows, c, names[len(ids):], columns, names)
    flows = merge_by_label(per_label, labels, conf[2]) if L > 1 else per_label[0]
    return {**result, "flows": flows, "matrix": rows, "recession": changed}
