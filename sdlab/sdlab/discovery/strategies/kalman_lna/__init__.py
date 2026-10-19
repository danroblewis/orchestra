"""kalman_lna: discovery for levels that are reported, not known (docs/research/kalman_lna.md).

The stocks are hidden states that move by the flows, with counting noise as the process noise
(lna's linear noise approximation: each flow a Poisson draw, a move's draw shared by both ends),
and the reported levels are observations of them: with a measurement error (absolute and
relative), at uneven times (each interval spans its steps), as means over a window (weekly
reports), late (a reporting delay, read where announced injections or eras pin it), with gross
errors (left out), and with a stock counted at a scale (a bias, read where a move pins it). The
numbers come from the Kalman filter's likelihood, the flows from lna's atoms chosen by BIC
(run.py, search.py), unmeasured stocks between two measured ones as one more state (hidden.py).

Which reading the data need:
- points at uneven times, or one per window: the filter;
- every step, up to SMALL stocks (or announced injections): the filter's superset is fitted first
  (gross errors left out, a reporting delay read); a measurement error that gains LR_NOISE BIC
  prices sends the data to the filter (not where a stock sits at zero: floors are outside the
  atoms, and a measurement error would stand in for them);
- otherwise the base strategy, on the levels with the values the filter left out as gross errors
  replaced by their neighbours' mean; its answer stands unless the filter's search finds a
  reporting delay, or a scale where the base reads a link beside a move into the same stock.

The base is `combined` (opts "kalman_base"). Where the filter is chosen and fails or runs out of
time, the base's answer is returned. Beyond SMALL stocks, with every step reported, the data go to
the base unchanged.
"""

from __future__ import annotations

import numpy as np

from sdlab.discovery.strategies.combined.deadline import outer_left

# lna's atoms and flow writer are used by run.py, search.py and model.py; named here so that the
# ladder's strategy hash covers them (it follows `from sdlab.discovery.strategies.<name> import`)
from sdlab.discovery.strategies.combined import identify as combined
from sdlab.discovery.strategies.lna import atoms as _lna_atoms  # noqa: F401
from sdlab.discovery.strategies.lna import flows as _lna_flows  # noqa: F401

from .run import BUDGET, FAILURES, Session

CHECK = 30.0          # seconds for the check on data a measurement error may not touch

BASE = "combined"


def _base(name: str):
    if name == BASE:
        return combined
    from .. import load
    return load(name)


def _levels(stocks: list[dict], run: dict) -> tuple[np.ndarray, np.ndarray]:
    ids = [s["id"] for s in stocks]
    t = np.asarray(run["t"], dtype=float)
    Y = np.array([np.asarray(run["levels"].get(i, [np.nan] * len(t)), dtype=float) for i in ids]).T
    return t, Y


def cleaned(stocks: list[dict], run: dict, opts: dict, mask: np.ndarray) -> tuple[dict, int]:
    """The run with each value the filter left out as a gross error (mask False) replaced by the
    mean of its neighbours, and how many."""
    t, Y = _levels(stocks, run)
    bad = np.isfinite(Y) & ~mask
    bad[0] = bad[-1] = False
    if not bad.any():
        return run, 0
    Y2 = Y.copy()
    for i, s in zip(*np.nonzero(bad)):
        Y2[i, s] = 0.5 * (Y[i - 1, s] + Y[i + 1, s])
    ids = [s["id"] for s in stocks]
    return {**run, "levels": {i: Y2[:, k].tolist() for k, i in enumerate(ids)}}, int(bad.sum())


def scale_pattern(flows: list[dict]) -> bool:
    """A link into a stock beside a move into it from the stock the link reads: what a stock
    counted at a scale looks like to a method that knows the levels exactly."""
    moves = {(f.get("from"), f.get("to")) for f in flows if f.get("from") and f.get("to")}
    for f in flows:
        if f.get("from") is None and f.get("to"):
            r = f.get("rate") or {}
            reads = {r.get("stock")} | {x.get("stock") for x in r.get("terms") or []}
            if any((a, f["to"]) in moves for a in reads if a):
                return True
    return False


SMALL = 4             # with up to this many stocks, the filter's superset is fitted to test for a
                      # measurement error (beyond, only uneven reports send the data to the filter)
LR_NOISE = 4.0        # twice the log-likelihood the measurement error gains, in BIC prices of one number: 4 is
                      # twice what BIC asks of one number (clean ladder runs reach 2.4 at most)


FLOOR = 0.05          # beyond this share of points at zero, no measurement error is read (floors bind)


def noisy(ev: dict) -> bool:
    return ev["lr"] > LR_NOISE * ev["price"] and ev["floor"] <= FLOOR


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    base = _base(opts.get("kalman_base", BASE))
    t, Y = _levels(stocks, run)
    uneven = len(t) > 1 and (bool(np.any(np.diff(t) != 1)) or not np.isfinite(Y).all())
    ses = Session(stocks, run, opts)
    info: dict = {}
    left = outer_left()

    def allow(share, most):
        ses.allow(min(most, share * left) if left else most)

    def kalman(why):
        allow(0.6, BUDGET)
        try:
            got = ses.finish()
        except FAILURES as e:
            ses.trace.append(f"failed: {type(e).__name__}: {e}")
            return None
        return {**got, "kalman": {"reading": why, **info}}

    prepared = False
    if uneven or len(stocks) <= SMALL or opts.get("injections"):
        allow(0.6 if uneven else 0.25, BUDGET if uneven else CHECK)
        try:
            prepared = ses.prepare()
            if prepared and not uneven:
                info["evidence"] = ses.evidence()
        except FAILURES as e:
            ses.trace.append(f"failed: {type(e).__name__}: {e}")
            prepared = False
    if prepared and (uneven or noisy(info["evidence"])):
        got = kalman("uneven" if uneven else "meas")
        if got is not None:
            return got
    # gross errors replaced only where the filter has read the run (beyond SMALL stocks the data go to
    # the base as they are)
    clean, replaced = cleaned(stocks, run, opts, ses.pr.lay.mask) if prepared and not uneven else (run, 0)
    r = base(stocks, clean, opts)
    info.update(replaced=replaced)
    if prepared and not uneven:
        scaled = scale_pattern(r.get("flows") or [])
        if ses.lag or scaled:
            got = kalman("lag" if ses.lag else "scale")
            if got is not None and (got.get("lag") or got.get("scales")):
                return got
    return {**r, "kalman": {"reading": None, **info, "trace": ses.trace}}
