"""A whole model judged on single steps, in the form the engine steps it.

Copied from sdlab/discovery/strategies/censored/onestep.py at commit 89adae4 (CLAUDE.md invariant 11);
changed here: params() also counts a table effect's numbers (each point's value, and the position of
each point between the two ends).

`Model.change` (sdlab/discovery/simulate.py) applies every rate's floor at 0 and shares an emptied
stock among its outflows, so the one-step residual of a model with a floor or a cap is measured in
the model's real (kinked) form. The BIC counts each flow's numbers, and an outside inflow in pieces
as one value per piece and one change per cut.
"""

from __future__ import annotations

import math

import numpy as np

from ...simulate import Model


def model_inputs(inputs: dict | None, ids: list[str], t: list) -> dict | None:
    """Measured inputs ({name: value per step aligned with t}) as the simulator takes them; None without."""
    vals = {k: list(v) for k, v in (inputs or {}).items() if k not in ids}
    return {"t": list(t), "values": vals} if vals else None


def input_rows(inputs: dict | None, ids: list[str], t: list, T: int) -> tuple[list[str], np.ndarray]:
    """The inputs' names and their values during each step (t[k] to t[k + 1]: the value at t[k + 1],
    as the matrix and the simulator read them), names x T."""
    names = [k for k in (inputs or {}) if k not in ids]
    rows = [np.nan_to_num(np.asarray(inputs[k], dtype=float))[1 : T + 1] for k in names]
    return names, np.array(rows) if rows else np.zeros((0, T))


def levels(stocks: list[dict], run: dict) -> np.ndarray:
    t = run["t"]
    return np.nan_to_num(np.array([np.asarray(run["levels"].get(s["id"], [0] * len(t)), dtype=float) for s in stocks]))


def changes(flows: list[dict], ids: list[str], t: list, prev: np.ndarray, inputs: dict | None = None) -> np.ndarray:
    """What the flows add to each stock at every step (stocks x steps), from the levels at its start
    (and the measured inputs, model_inputs(), that the flows read)."""
    if not flows:
        return np.zeros_like(prev)
    times = np.asarray(t, dtype=float)[1 : prev.shape[1] + 1]
    return Model(flows, ids, inputs=inputs).change(prev, times)


def params(flows: list[dict]) -> int:
    """The numbers a model's flows carry (a piece's value and its cut each count one)."""
    p = 0
    for f in flows:
        if f.get("inflow"):
            p += 2 * len(f["inflow"]) - 1
            continue
        r = f.get("rate") or {}
        p += {"constant": 1, "proportional": 1, "gap": 2}.get(r.get("form"), 1 + len(r.get("terms") or []))
        p += int(f.get("threshold_params") or 0)
        for e in f.get("effects") or []:
            n = len(e.get("points") or [])
            p += n + max(0, n - 2) if e.get("shape") == "table" else 2
    return p


def row_rss(flows: list[dict], ids: list[str], t: list, prev: np.ndarray, dy: np.ndarray, inputs: dict | None = None) -> np.ndarray:
    return ((dy - changes(flows, ids, t, prev, inputs)) ** 2).sum(axis=1)


def outliers(flows: list[dict], ids: list[str], t: list, prev: np.ndarray, dy: np.ndarray, share: float = 0.01,
             inputs: dict | None = None) -> np.ndarray:
    """Per row, the steps (stocks x steps, True = left out) where a model's residual is among the
    largest `share`: one-step bursts (inflow spikes) that a Gaussian BIC would let decide alone."""
    r = np.abs(dy - changes(flows, ids, t, prev, inputs))
    k = int(share * r.shape[1])
    out = np.zeros_like(r, dtype=bool)
    if k < 1:
        return out
    idx = np.argpartition(-r, k - 1, axis=1)[:, :k]
    np.put_along_axis(out, idx, True, axis=1)
    return out


def bic(flows: list[dict], ids: list[str], t: list, prev: np.ndarray, dy: np.ndarray, floor: np.ndarray,
        skip: np.ndarray | None = None, inputs: dict | None = None) -> float:
    """Sum over the rows of T log(rss / T), plus log T per number, the rss over the steps not in
    `skip` (stocks x steps). `floor` (one per row) keeps an exact fit from counting as infinitely good."""
    T = prev.shape[1]
    sq = (dy - changes(flows, ids, t, prev, inputs)) ** 2
    if skip is not None:
        sq = np.where(skip, 0.0, sq)
    rss = np.maximum(sq.sum(axis=1), floor)
    return float(sum(T * math.log(r / T) for r in rss) + params(flows) * math.log(T))
