"""Whether SD Lab's flows for a stock with a fitted net flow predict its level better than that net flow.

An SD Lab strategy is given the levels no counters balance that are stocks by their fitted net flow
(``sd.netflow``), and answers with flows in its own, richer forms. Those forms have passed none of
the net flow's refutations, so they take its place only when they predict the level's changes
better on data they were not fitted on. The window is cut into the net flow's own stretches and
split in halves, as ``sd.netflow`` splits it: each model is fitted on one half and judged on the
other, both ways, and the smaller error on the held-out halves wins.

The net flow's form (``c``, its driver, the level) is refitted on each half by least squares.
SD Lab's flows keep the shapes the strategy gave them, and each gets one scale fitted on the half:
a strategy cannot be run again on half a window inside the discovery's deadline, and its shapes
were chosen on the whole window, which favours it, not the net flow."""

from __future__ import annotations

import numpy as np

from ..sdlab.discovery.simulate import Model, levels_array


def _held_out(x: np.ndarray, y: np.ndarray) -> float:
    """The squared error of predicting each half of ``y`` from a least-squares fit of ``x`` on the
    other half, summed over both ways."""
    h = len(y) // 2
    err = 0.0
    for fit, test in ((slice(0, h), slice(h, None)), (slice(h, None), slice(0, h))):
        coef, *_ = np.linalg.lstsq(x[fit], y[fit], rcond=None)
        err += float(((y[test] - x[test] @ coef) ** 2).sum())
    return err


def judge(stock, flows: list[dict], ids: list[str], run: dict, inputs: dict | None, coarse: float, driver: list[float] | None) -> str:
    """Why SD Lab's ``flows`` into or out of ``stock`` (rates per step of ``coarse`` seconds, on the
    group ``ids`` and ``run`` it was given) lose to the stock's fitted net flow, or nothing when they
    predict the held-out halves better. ``driver``: the net flow's driver on the same grid."""
    nf = stock.evidence["net_flow"]
    if nf.get("driver") and driver is None:
        return f"its net flow's driver {nf['driver']} was not on SD Lab's grid, so its flows could not be judged against it"
    A = levels_array(run["levels"], ids)
    i, n = ids.index(stock.id), A.shape[1] - 1
    t = np.asarray(run["t"], dtype=float)
    given = {"t": run["t"], "values": inputs} if inputs else None
    # each flow's amount per step, as SD Lab's simulator moves it (outflows sharing what the stock
    # holds), signed for this stock; not a step of the levels, which floors them at zero
    amounts = Model(flows, ids, inputs=given)._amounts(A[:, :-1], t[1:])
    sign = [(f.get("to") == stock.id) - float(f.get("ratio") or 1) * (f.get("from") == stock.id) for f in flows]
    moves = np.nan_to_num(np.array([s * np.asarray(a, dtype=float) for s, a in zip(sign, amounts)]), posinf=0.0, neginf=0.0)
    m = max(1, round(float(nf["stretch_s"]) / coarse))
    starts = list(range(0, n - m + 1, m))
    own, has_driver = "b" in nf["params"], "a" in nf["params"]
    cols = 1 + has_driver + own
    if len(starts) < 2 * (max(cols, len(flows)) + 1):
        return "too few stretches on SD Lab's grid to judge its flows against the fitted net flow on held-out data"
    y = np.array([A[i, s + m] - A[i, s] for s in starts])
    sd = np.array([[moves[j, s:s + m].sum() for j in range(len(flows))] for s in starts])
    net = np.array([[1.0, *([float(np.mean(driver[s:s + m + 1]))] if has_driver else []), *([A[i, s]] if own else [])] for s in starts])
    theirs, ours = _held_out(sd, y), _held_out(net, y)
    if theirs < ours:
        return ""
    return (f"its flows predicted the held-out half worse than the fitted net flow (squared error {theirs:.4g} against "
            f"{ours:.4g}, each fitted on one half of the window and judged on the other)")
