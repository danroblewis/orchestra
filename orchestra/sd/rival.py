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
were chosen on the whole window, which favours it, not the net flow.

What is published is what was judged: each shape times its scale fitted on the whole window, as
the net flow's coefficients are. So the scales must keep the direction SD Lab gave each flow, on
the whole window and on each half (``ScaleFlips``): a flow into the level whose scale is below zero
is an outflow, and publishing it as SD Lab wrote it would show the opposite of what was judged.
A flow whose shape moves less than ``NEGLIGIBLE`` of the level's changes is no flow at all (a
coefficient of 1e-23), and a scale fitted to it would invent one: it is left out before judging.
The published flows' pull on the net flow's driver must have the sign of the net flow's own
coefficient on it, the evidence that made the level a stock."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..sdlab.discovery.simulate import Model, levels_array
from .rates import on, times

NEGLIGIBLE = 0.01       # a flow whose shape moves less than this share of the level's changes moves nothing


@dataclass
class Verdict:
    """Why SD Lab's flows lose to the fitted net flow (empty: they win), the scale each flow that
    won is published at (by its index in the flows given), and the flows left out as moving
    nothing, with why."""

    why: str = ""
    scales: dict[int, float] = field(default_factory=dict)
    negligible: dict[int, str] = field(default_factory=dict)


def _held_out(x: np.ndarray, y: np.ndarray) -> tuple[float, list[np.ndarray]]:
    """The squared error of predicting each half of ``y`` from a least-squares fit of ``x`` on the
    other half, summed over both ways, and the coefficients fitted on each half."""
    h = len(y) // 2
    err, coefs = 0.0, []
    for fit, test in ((slice(0, h), slice(h, None)), (slice(h, None), slice(0, h))):
        coef, *_ = np.linalg.lstsq(x[fit], y[fit], rcond=None)
        err += float(((y[test] - x[test] @ coef) ** 2).sum())
        coefs.append(coef)
    return err, coefs


def _name(f: dict, i: int) -> str:
    return f"{f.get('from') or 'outside'} → {f.get('to') or 'outside'} ({(f.get('rate') or {}).get('form', '?')}, flow {i + 1})"


def judge(stock, flows: list[dict], ids: list[str], run: dict, inputs: dict | None, coarse: float, driver: list[float] | None) -> Verdict:
    """Whether SD Lab's ``flows`` into or out of ``stock`` (rates per step of ``coarse`` seconds, on
    the group ``ids`` and ``run`` it was given) predict the held-out halves better than the stock's
    fitted net flow, and at what scale each is published. ``driver``: the net flow's driver on the
    same grid."""
    nf = stock.evidence["net_flow"]
    if nf.get("driver") and driver is None:
        return Verdict(f"its net flow's driver {nf['driver']} was not on SD Lab's grid, so its flows could not be judged against it")
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
    y = np.array([A[i, s + m] - A[i, s] for s in starts])
    sd = np.array([[moves[j, s:s + m].sum() for j in range(len(flows))] for s in starts]).reshape(len(starts), len(flows))
    moved = float(np.abs(y).sum()) or 1e-12
    negligible = {j: f"it moves {float(np.abs(sd[:, j]).sum()) / moved:.2g} of the level's changes, less than the {NEGLIGIBLE:.0%} a flow must"
                  for j in range(len(flows)) if float(np.abs(sd[:, j]).sum()) < NEGLIGIBLE * moved}
    kept = [j for j in range(len(flows)) if j not in negligible]
    if not kept:
        return Verdict("none of its flows moves the level: each moves less than "
                       f"{NEGLIGIBLE:.0%} of its changes", negligible=negligible)
    if len(starts) < 2 * (max(cols, len(kept)) + 1):
        return Verdict("too few stretches on SD Lab's grid to judge its flows against the fitted net flow on held-out data",
                       negligible=negligible)
    sd = sd[:, kept]
    net = np.array([[1.0, *([float(np.mean(driver[s:s + m + 1]))] if has_driver else []), *([A[i, s]] if own else [])] for s in starts])
    (theirs, halves), (ours, _) = _held_out(sd, y), _held_out(net, y)
    if theirs >= ours:
        return Verdict(f"its flows predicted the held-out half worse than the fitted net flow (squared error {theirs:.4g} against "
                       f"{ours:.4g}, each fitted on one half of the window and judged on the other)", negligible=negligible)
    whole, *_ = np.linalg.lstsq(sd, y, rcond=None)
    for col, j in enumerate(kept):
        fitted = [float(whole[col]), *(float(h[col]) for h in halves)]
        if min(fitted) <= 0:
            return Verdict(f"the scale fitted to {_name(flows[j], j)} is {min(fitted):.3g} (on the whole window and each half: "
                           f"{', '.join(f'{v:.3g}' for v in fitted)}): below zero it moves the level the other way from how "
                           "SD Lab wrote it, so what would be published is not what was judged", negligible=negligible)
    scales = {j: float(whole[col]) for col, j in enumerate(kept)}
    scaled = {j: times(flows[j].get("rate") or {}, s) for j, s in scales.items()}
    if any(r is None for r in scaled.values()):
        return Verdict("its flows predicted the held-out halves better, but a form of theirs cannot be scaled to the fit that was judged",
                       negligible=negligible)
    d = (nf.get("driver") or "").removeprefix("input:")
    if has_driver and d:
        pulls = [on(scaled[j], d) for j in kept]
        if all(p is not None for p in pulls):
            pull = sum(sign[j] * p for j, p in zip(kept, pulls))
            a = float(nf["params"]["a"])
            if pull and a and (pull > 0) != (a > 0):
                return Verdict(f"its flows predicted the held-out halves better, but they move the level {'up' if pull > 0 else 'down'} "
                               f"as {d} rises ({pull:.3g} per step), against the fitted net flow's {a:.3g} that made it a stock",
                               negligible=negligible)
    return Verdict("", scales, negligible)
