"""kalman_bayes: kalman_lna with a posterior in place of one best fit (docs/research/kalman_bayes.md).

A copy of kalman_lna as at commit e8edf28 (every module of this package but bag.py, ekf.py, mcmc.py and
posterior.py, imports rewritten to this package; `_point` below is kalman_lna's identify). On top:
1. the discovery is run again on contiguous blocks of the run (bag.py): each flow's inclusion
   probability, and the structure of the flows kept in most blocks;
2. that structure's numbers are sampled (posterior.py: kalman_lna's state-space likelihood written on
   the flows, adaptive Metropolis); the posterior-median model is returned, every number with its
   posterior summary ("<key>_post") and every flow with its inclusion probability ("inclusion").

What follows is kalman_lna's own description.

kalman_lna: discovery for levels that are reported, not known (docs/research/kalman_lna.md).

The stocks are hidden states that move by the flows, with counting noise as the process noise
(lna's linear noise approximation: each flow a Poisson draw, a move's draw shared by both ends),
and the reported levels are observations of them: with a measurement error (absolute and
relative), at uneven times (each interval spans its steps), as means over a window (weekly
reports), late (a reporting delay, read where announced injections pin it), with gross
errors (left out), and with a stock counted at a scale (a bias, read where a move pins it). The
numbers come from the Kalman filter's likelihood, the flows from lna's atoms chosen by BIC
(run.py, search.py), unmeasured stocks between two measured ones as one more state (hidden.py).

Which reading the data need:
- points at uneven times, or one per window: the filter;
- every step, up to SMALL stocks (or announced injections): the filter's superset is fitted first
  (gross errors left out, a reporting delay read); a measurement error that gains LR_NOISE BIC
  prices sends the data to the filter (not where a stock sits at zero, nor where the atoms leave
  much variance beyond counting noise even with the error read: floors, effects and co-flows are
  outside the atoms, and a measurement error would stand in for them);
- gross errors the filter sees (a standardised innovation beyond 10, where counting noise and a
  misfit of the atoms stay below 6): the filter, which leaves them out;
- otherwise the base strategy's answer, unless the filter's search finds a reporting delay
  (injections), or a scale where the base reads a link beside a move into the same stock.

The base is its own copy of `combined` (as at commit ec2f9e8, in _vendored/). Where the filter is chosen and fails or runs out of
time, the base's answer is returned. Beyond SMALL stocks, with every step reported, the data go to
the base unchanged.
"""

from __future__ import annotations

import numpy as np

# combined and lna (and what they reach) as copies, vendored at commit ec2f9e8 (_vendored/): no other
# strategy is imported (sdlab/CLAUDE.md invariant 11), so changing them never changes this one
from ._vendored.combined import identify as combined
from ._vendored.combined.deadline import outer_left
from .run import BUDGET, FAILURES, Session

CHECK = 30.0          # seconds for the check on data a measurement error may not touch

BASE = "combined"


def _base(name: str):
    if name != BASE:
        raise ValueError(f"kalman_lna's base is its own copy of {BASE}, not {name!r}")
    return combined


def _levels(stocks: list[dict], run: dict) -> tuple[np.ndarray, np.ndarray]:
    ids = [s["id"] for s in stocks]
    t = np.asarray(run["t"], dtype=float)
    Y = np.array([np.asarray(run["levels"].get(i, [np.nan] * len(t)), dtype=float) for i in ids]).T
    return t, Y


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


MISFIT = 0.3          # nor where, with the error read, the atoms still leave this share of a stock's
                      # step variance unexplained (effects, co-flows, caps: an error would stand in)


def _closer(filtered: dict, based: dict, stocks: list[dict], run: dict, opts: dict) -> dict:
    """The filter's answer, or the base's where its flows (numbers refitted for a measurement error) run
    closer to the data over 5, 20 and 100 steps (a filter's model with a stock nobody measures is kept:
    the judge runs on the measured levels only)."""
    from .eiv import _known, judge, refit

    ids = [s["id"] for s in stocks]
    if not _known(filtered.get("flows") or [], set(ids) | set(opts.get("inputs") or {})):
        return filtered
    mine = judge(filtered.get("flows") or [], ids, run, opts)
    theirs = judge(refit(based.get("flows") or [], stocks, run, opts)[0], ids, run, opts)
    if theirs < mine:
        return {**based, "kalman": {**filtered["kalman"], "reading": None, "filter_judged": [mine, theirs]}}
    return {**filtered, "kalman": {**filtered["kalman"], "filter_judged": [mine, theirs]}}


def noisy(ev: dict) -> bool:
    return ev["lr"] > LR_NOISE * ev["price"] and ev["floor"] <= FLOOR and ev["misfit"] <= MISFIT


def _identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    opts = dict(opts or {})
    base = _base(opts.get("kalman_base", BASE))
    t, Y = _levels(stocks, run)
    uneven = len(t) > 1 and (bool(np.any(np.diff(t) != 1)) or not np.isfinite(Y).all())
    ses = Session(stocks, run, opts)
    info: dict = {}
    def allow(share, most):
        left = outer_left()                    # what the caller's timer leaves now
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
    gross = int(ses.gross.sum()) if prepared else 0
    if prepared and (uneven or noisy(info["evidence"]) or gross):
        why = "uneven" if uneven else "meas" if noisy(info["evidence"]) else "outliers"
        got = kalman(why)
        if got is not None and why != "meas":
            return got
        if got is not None:
            # the filter's atoms read no measured input: its model is weighed against the base's, with the
            # base's numbers refitted for the measurement error (eiv.py), on the judge's multi-step error
            # (which a measurement error does not bias); the base's answer is kept only when it runs closer
            r = base(stocks, run, dict(opts))
            return _closer(got, r, stocks, run, opts)
    r = base(stocks, run, opts)
    if prepared and not uneven:
        scaled = scale_pattern(r.get("flows") or [])
        if ses.lag or scaled:
            got = kalman("lag" if ses.lag else "scale")
            if got is not None and (got.get("lag") or got.get("scales")):
                return got
    return {**r, "kalman": {"reading": None, **info, "trace": ses.trace}}


def _point(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """kalman_lna's answer: the above with its numbers refitted by instrumental variables where the
    levels carry measurement error (eiv.py)."""
    from .eiv import apply

    return apply(_identify(stocks, run, dict(opts or {})), stocks, run, opts)


BUDGET_BAYES = 300.0  # seconds for the whole strategy without a caller's timer (opts "bayes_budget")
USE = 0.85            # share of the caller's time the strategy plans to use (the rest is margin)
BAG_SHARE = 0.5       # of what the point answer leaves, at most this share for the blocks
BAG_TIMES = 6.0       # and at most this many times the full run's own time (8 blocks of 70% take about 5.6)
EACH = 2.0            # a block may take this many times the full run's own time (at least 10 s)
MCMC_MOST = 90.0      # seconds at most for the posterior (mode, Hessian, chain)


def identify(stocks: list[dict], run: dict, opts: dict | None = None) -> dict:
    """kalman_lna's answer; the structure of the flows most blocks find (bag.py) in its place where that
    structure's BIC on the whole run is lower; and the numbers replaced by their posterior medians
    (posterior.py)."""
    import time

    from . import bag
    from ._vendored.combined.deadline import Overrun, deadline
    from .posterior import mode, sample

    opts = dict(opts or {})
    began = time.monotonic()
    left = outer_left()
    until = began + USE * (left if left else float(opts.get("bayes_budget", BUDGET_BAYES)))
    r = _point(stocks, run, opts)
    took = time.monotonic() - began
    if not isinstance(r, dict) or not r.get("flows"):
        return r
    info: dict = {"seconds": {"point": round(took, 2)}}

    def one(st, rr, oo, seconds):
        try:
            with deadline(seconds):
                return _point(st, rr, oo)
        except (Overrun, Exception):                       # noqa: BLE001  (a block that cannot be read is left out)
            return None

    t1 = time.monotonic()
    bag_until = t1 + min(BAG_SHARE * max(0.0, until - t1), 20.0 + BAG_TIMES * took)
    members = bag.ensemble(one, stocks, run, opts, max(10.0, EACH * took), bag_until)
    info["seconds"]["blocks"] = round(time.monotonic() - t1, 2)
    inc, bagged = None, None
    if len(members) >= bag.MIN_BLOCKS:
        inc = bag.inclusion(r["flows"], members)
        bagged, dropped, added = bag.bagged(r["flows"], members, inc)
        info.update(blocks=len(members), inclusion={bag.label(k): round(p, 3) for k, p in inc.items()}, dropped=dropped, added=added)
        if not dropped and not added:
            bagged = None
    else:
        info.update(blocks=len(members), skipped_blocks=f"{len(members)} blocks in the time (fewer than {bag.MIN_BLOCKS})")
    t2 = time.monotonic()
    end = min(until, t2 + MCMC_MOST)
    post, pinfo = None, {}
    try:
        # the found structure's mode; the blocks' structure's mode on the same reports, kept when its BIC
        # (the noise numbers counted) is lower: the blocks propose, the whole run's evidence decides
        m = mode(r["flows"], stocks, run, opts, r, t2 + 0.3 * (end - t2))
        info["structure"] = "found"
        if m is not None and bagged:
            mb = mode(bagged, stocks, run, opts, r, t2 + 0.5 * (end - t2), mask=m.lik.mask)
            info["bic"] = {"found": round(m.bic(), 2), "blocks": round(mb.bic(), 2) if mb else None}
            if mb is not None and mb.bic() < m.bic():
                m, info["structure"] = mb, "blocks"
        if m is not None:
            post, pinfo = sample(m, end)
        else:
            pinfo = {"skipped": "no numbers, or a likelihood not finite at the found numbers"}
    except (np.linalg.LinAlgError, FloatingPointError, ValueError, ZeroDivisionError) as e:
        post, pinfo = None, {"skipped": f"{type(e).__name__}: {e}"[:200]}
    info["seconds"]["posterior"] = round(time.monotonic() - t2, 2)
    info["mcmc"] = pinfo
    if post is None:
        # no posterior: the point answer stands (its own structure and numbers)
        return {**r, "posterior": {**info, "returned": "point"}}
    if inc is not None:
        for f in post:
            f["inclusion"] = round(inc.get(bag.key(f), 0.0), 3)
    return {**r, "flows": post, "method": "kalman_bayes", "posterior": {**info, "returned": "posterior median"}}
