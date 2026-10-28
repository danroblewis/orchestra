"""Which balances make stocks: the evidence a balance must show, and each stock's trust.

``sd.discover`` finds, for every level, the counters that best balance it. A balance is accepted as
a stock's only when the evidence for it holds (``sd.identify``):

- it is judged on enough units for the counters it uses (``identify.MIN_UNITS``, ``UNITS_PER_TERM``);
- its counters are chosen again on each half of the window, or are of the same events as those
  chosen (counters only the whole window chose are dropped, and the rest must still fit at
  ``MIN_R2``);
- a balance the operator declared (``sd.pins``) is chosen by no search: nothing is dropped, its
  fit on each half is its held-out evidence, and its shift null moves the level against the
  declared counters alone; otherwise it passes the same gates;
- it fits at ``MIN_R2``, or, judged on a slow counter's writes (``identify.two_clocks``), its misses are timing (``identify.timing_limited``: they cancel from one unit
  to the next) and it fits at ``identify.JITTER_R2``;
- it is exact (``Identification.is_exact``: in ``identify.FLAG_EXACT`` of the units anything moved in),
  or, short of exact:
  - its choice on one half predicts the other half at R² ``HELD_OUT`` or better, both ways
    (``HELD_OUT_TIMING`` for a balance whose misses are timing, when both halves chose its counters:
    timing holds R² down on each half as on the whole);
  - it reproduces the level over time: the running total of what it misses spreads no more than
    ``CUM_RATIO`` of the level's own spread;
  - the shift null (the level moved in time against the same counters, searched the same way)
    fits as well in no more than ``P_NULL`` of the shifts;
  - its halves chose the same counters (``Identification.stable``), unless its misses are timing:
    a balance on a slow counter's writes is judged on a few dozen stretches, and each half's own
    search among them is noisier than the balance (the email queue across two stores). Over the
    lab's 24 windows, no balance of a true stock's own flows was unstable and inexact on one store;
    every one that was is a decoy's, a junk counter's or a coincidence of two byte counts.

A level whose balance fails is left out with the reason, which begins as every unbalanced level's
does (``sd.netflow.NET_FLOW``), so its net flow is still fitted: it may be a stock, honestly labelled
a net flow with its own trust.

A count of reporters balanced by its own turnover (``sd.construction``) is no evidence: it is kept
only as a count of pods in a place, marked ``by_construction`` with no R², and left out when it is
split by what happened to a request.

The thresholds were set on the metrics lab's hidden truth over ten windows (calm, incident,
rollout, night and two shifted by minutes) and its null runs (``orchestra-metrics-lab``
``reports/05-identification.md``): the values that keep every balance of a true stock's own flows
those windows found, and refuse the most balances with an unrelated counter in them."""

from __future__ import annotations

from . import stocktrust
from .balance import LeastSquares, columns
from .construction import constructed, no_place
from .identify import identify, two_clocks
from .netflow import NET_FLOW

MIN_R2 = 0.9            # as sd.discover: a balance must fit this well, after the halves' vote
HELD_OUT = 0.5          # short of exact: its choice on each half predicts the other at least this well
HELD_OUT_TIMING = 0.25  # ... a balance whose misses are timing (identify.timing_limited), when both halves chose its counters
CUM_RATIO = 0.5         # ... its running residual spreads no more than this share of the level's spread
P_NULL = 0.2            # ... and the shift null fits as well in no more than this share of shifts


def gate(idn) -> str:
    """Why an identified balance is still no stock's, or nothing."""
    if idn.why:
        return idn.why
    if idn.r2 < MIN_R2 and not idn.timing:
        return (f"without the counters only the whole window chose ({', '.join(c.key for c, _ in idn.dropped)}) it fits at "
                f"R² {idn.r2:.2f}")
    if idn.is_exact or idn.declared:
        return ""
    timing = idn.timing and idn.stable is not False      # its R² on changes is held down by timing, not by a wrong choice
    if idn.held_out_r2 is not None and idn.held_out_r2 < (HELD_OUT_TIMING if timing else HELD_OUT):
        return f"chosen on either half of the window, it predicts the other half at R² {idn.held_out_r2:.2f}"
    if idn.stable is False and not idn.timing:
        return ("the halves of the window chose different counters for it, and it is not exact: which counters are its flows "
                "is not identified")
    if idn.cum_ratio is not None and idn.cum_ratio > CUM_RATIO:
        return (f"it does not reproduce the level: the running total of what it misses spreads {idn.cum_ratio:.2f} times "
                "as wide as the level")
    if idn.p_null is not None and idn.p_null > P_NULL:
        return (f"the level moved in time against the same counters is balanced as well in {idn.p_null:.0%} of the shifts "
                f"(best R² {max(idn.null_r2):.2f}): a coincidence the search finds by chance")
    return ""


def accepted(found: list, counters: list, barred: dict, masks: dict, provenance: dict, left_out: dict, same,
             pinned: set | frozenset = frozenset()) -> tuple[list, dict, set, dict]:
    """The balances accepted as stocks', each level's identification, the levels balanced by
    construction, and what was recorded of each refused balance (by level key). ``pinned``: the
    levels whose balance the operator declared (``sd.pins``), tested rather than chosen."""
    solvers: dict[tuple, LeastSquares] = {}

    def solver(level, pool: list, steps: list[int]) -> LeastSquares:
        key = (tuple(steps), tuple(c.key for c in pool), tuple(level.blocks or ()))
        if key not in solvers:
            solvers[key] = LeastSquares(columns(level, pool, steps))
        return solvers[key]

    out, identified, built, refused = [], {}, set(), {}
    for s, terms, r2, exact in found:
        if constructed(s, terms, provenance):
            if label := no_place(s):
                left_out[s.key] = (f"a count of reporters split by {label}, balanced by its own turnover: exact by construction, so "
                                   f"no evidence, and {label} is what happened to what they reported, not a place they are held")
                continue
            built.add(s.key)
            out.append((s, terms, r2, exact))
            continue
        pool = [c for c in counters if c.key not in barred.get(s.key, ())]
        declared = bool(s.traffic and s.traffic[0] == "backlog" and all(c.traffic and c.traffic[1] == s.traffic[1] for c, _ in terms))
        idn = identify(s, terms, r2, exact, pool, masks[s.key], solver, same, declared=declared, pinned=s.key in pinned,
                       clocks=two_clocks(s, terms))
        if why := gate(idn):
            shown = " ".join(f"{'+' if sg > 0 else '−'}{c.key}" for c, sg in terms)
            left_out[s.key] = f"{NET_FLOW} on evidence that holds ({shown} fits at R² {r2:.2f}, but {why})"
            refused[s.key] = {"terms": [{"series": c.key, "sign": sg} for c, sg in terms], "r2": round(r2, 4),
                              "exact": round(exact, 4), "why": why, **idn.record()}
            continue
        identified[s.key] = idn
        out.append((s, idn.terms, idn.r2, idn.exact))
    return out, identified, built, refused


def stock_trust(s, exact: float | None, identified: dict, by_construction: bool, passage) -> dict:
    """The trust record of a conservation stock (``sd.stocktrust``)."""
    if by_construction:
        return stocktrust.by_construction()
    if passage is not None:
        return stocktrust.passage(passage) if passage.measured else stocktrust.unmeasured()
    if s.key in identified:
        return stocktrust.conservation(identified[s.key], exact or 0.0)
    return stocktrust.unmeasured("found as a step between two others (sd.hops): judged on the counters, not on a balance of its own")

