"""Whether a level's balance is identified: the evidence that its counters are its flows, measured.

R² on a level's changes does not identify a balance. A balance is chosen from thousands of signed
pairs of counters and local moves, so among dozens of busy counters some always explain a per cent
or two of any level's changes by chance (a GC count, CPU seconds, the scrapes of ``/metrics``), and
a proxy that moves with the true flow step by step (requests for the messages they produce) fits as
well as the flow while drifting from it. Four measurements tell them apart, each computed here for
every balance a level is accepted on (``Identification``), and recorded with the stock:

- **Units.** How many observations the balance is judged on: steps, or for a slow level the
  stretches between its writes (``sd.resolution.units``). A balance needs ``UNITS_PER_TERM`` of
  them per counter it uses, and at least ``MIN_UNITS`` (a level that changed twice in an hour,
  balanced by two counters on its two stretches, fits at R² 1.000 whatever the counters are).
- **Held out.** The balance is searched again on each half of the window alone, and each half's
  choice is scored on the other half (``held_out_r2``: the worse of the two). A counter of the
  balance is kept only when the search on each half (that saw the level move and the counter count)
  chose it again, or a counter of the same events; a counter only the whole window chose is a
  coincidence of that window (``dropped``). An exact balance (``FLAG_EXACT`` of its units) is its
  own proof and keeps every counter: a coincidence is not exact for an hour.
- **The level reproduced.** The balance's residual summed over time, against the level's own spread
  (``cum_ratio``: the standard deviation of the running sum of what the balance misses, over that
  of the level). A true balance's misses are timing (one exporter scraped a moment after another)
  and cancel; a proxy's accumulate, so its running total drifts from the level however high its R².
  This is the cointegration of the level with its flows' running totals, which is what a model run
  from the balance needs.
- **The shift null.** The level's changes moved in time against the counters, circularly by
  ``NULL_SHIFTS`` offsets, and balanced again by the same search over the same counters: the share
  of those (counting the real one) that fit at least as well is ``p_null``. It prices the search's
  size honestly: with many counters to choose from, chance alone fits well, and the null shows how
  well."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import pstdev

from .balance import MIN_EVENTS, LeastSquares, balance, balance_of, columns, fit_of
from .resolution import pick, units

MIN_UNITS = 12           # a balance is judged on at least this many units (steps, or stretches between a slow level's writes)
UNITS_PER_TERM = 6       # ... and this many per counter it uses
NULL_SHIFTS = 9          # circular shifts of the level against the counters in the null
ALIKE = 0.9              # two counters whose changes correlate this well on a half are one choice there (requests and the messages they produce)
FLAG_EXACT = 0.97        # the share of units a balance explains exactly to keep every counter without the halves' vote (as sd.discover)


@dataclass
class Identification:
    terms: list                                     # the balance, after the halves' vote
    r2: float
    exact: float
    units: int
    held_out_r2: float | None = None
    halves_r2: float | None = None                  # the balance itself on each half (the worse): an exact balance's held-out evidence
    exact_moved: float = 0.0                        # the share of the units the level or a counter moved in that it explains exactly
    moved: int = 0                                  # ... and how many such units there were
    halves: list = field(default_factory=list)      # per half: the counters its own search chose
    dropped: list = field(default_factory=list)     # counters only the whole window chose
    stable: bool | None = None                      # both halves chose the same counters (or counters of the same events)
    cum_ratio: float | None = None
    cum_steady: float | None = None                 # ... less a steady unmeasured flow (the residual's mean)
    p_null: float | None = None
    null_r2: list = field(default_factory=list)
    why: str = ""                                   # why it is not identified (empty: it is)
    declared: bool = False                          # the source declared the balance (a channel and its traffic): no search to price

    @property
    def is_exact(self) -> bool:
        """Exact in ``FLAG_EXACT`` of the units anything moved in, on ``MIN_EVENTS`` of them at least:
        a coincidence is not exact for an hour, so the balance is its own proof."""
        return self.exact_moved >= FLAG_EXACT and self.moved >= MIN_EVENTS

    def record(self) -> dict:
        return {"units": self.units, "held_out_r2": _round(self.held_out_r2), "halves_r2": _round(self.halves_r2),
                "exact_moved": _round(self.exact_moved), "stable": self.stable,
                "cum_residual_ratio": _round(self.cum_ratio), "cum_residual_steady": _round(self.cum_steady), "p_null": _round(self.p_null), "null_shifts": len(self.null_r2),
                **({"declared": True} if self.declared else {}),
                "null_r2_max": _round(max(self.null_r2)) if self.null_r2 else None,
                "halves": [[f"{'+' if sg > 0 else '-'}{c.key}" for c, sg in h] for h in self.halves],
                **({"dropped": [f"{'+' if sg > 0 else '-'}{c.key}" for c, sg in self.dropped]} if self.dropped else {})}


def _round(x: float | None) -> float | None:
    return None if x is None or not math.isfinite(x) else round(x, 4)


def needed_units(terms: int, exact: bool) -> int:
    """The units a balance of this many counters must be judged on: ``UNITS_PER_TERM`` per counter
    and ``MIN_UNITS`` at least; an exact balance (each change matched to the event) is evidence on
    fewer, two per counter and ``MIN_EVENTS`` at least (a queue a few minutes into an era)."""
    if exact:
        return max(MIN_EVENTS, 2 * max(1, terms))
    return max(MIN_UNITS, UNITS_PER_TERM * max(1, terms))


def unit_count(level, steps: list[int]) -> int:
    return len(units(level.blocks, steps))


def exact_moved(level, terms: list, steps: list[int]) -> tuple[float, int]:
    """The share of the units in which the level or a counter moved that the balance explains
    exactly (within half an event), and how many such units there were: steps in which nothing
    moved prove nothing, and a rare counter beside a quiet level would otherwise be exact by default."""
    moved = hit = 0
    for u in units(level.blocks, steps):
        y = pick(level, u)
        xs = [sign * pick(c, u) for c, sign in terms]
        if abs(y) > 1e-9 or any(abs(x) > 1e-9 for x in xs):
            moved += 1
            hit += abs(y - sum(xs)) <= 0.5
    return (hit / moved if moved else 0.0), moved


def cum_ratio(level, terms: list, steps: list[int], steady: bool = False) -> float:
    """The running total of what the balance misses, over the level's own spread (standard
    deviations). ``steady``: less the steady part of what it misses (its mean per unit), which is a
    flow no counter measures at a constant rate (a supplier nobody counts), not a misfit."""
    us = units(level.blocks, steps)
    if len(us) < 2:
        return math.inf
    resid, lv = [], []
    for u in us:
        resid.append(pick(level, u) - sum(sign * pick(c, u) for c, sign in terms))
        last = u if isinstance(u, int) else u.steps[-1]
        lv.append(level.values[last + 1])
    mean = sum(resid) / len(resid) if steady else 0.0
    acc, run = 0.0, []
    for r in resid:
        acc += r - mean
        run.append(acc)
    spread = pstdev(lv)
    return pstdev(run) / spread if spread > 0 else math.inf


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def _chosen(c, sign: int, picked: list, steps: list[int], same) -> bool:
    """Whether a half's search chose the counter, or one of the same events, with the same sign."""
    for k, sg in picked:
        if sg != sign:
            continue
        if k is c or same(c, k):
            return True
        if _corr([c.deltas[i] for i in steps], [k.deltas[i] for i in steps]) >= ALIKE:
            return True
    return False


def _votes(level, c, steps: list[int]) -> bool:
    """Whether a half can say anything of a counter: the level moved, and the counter counted, in
    ``MIN_EVENTS`` of its steps there."""
    return sum(1 for i in steps if level.deltas[i]) >= MIN_EVENTS and sum(c.deltas[i] for i in steps) >= MIN_EVENTS


def identify(level, terms: list, r2: float, exact: float, pool: list, steps: list[int], solver, same=lambda a, b: False,
             shifts: int = NULL_SHIFTS, declared: bool = False) -> Identification:
    """The evidence for a level's balance (``terms``, found over ``steps`` among ``pool``), and the
    balance after the halves' vote. ``solver(level, pool, steps)`` is the counters' least squares
    over those steps (cached by the caller: it is the same for every level live in the same steps);
    ``same(a, b)``: two counters of the same events. ``declared``: the balance is the one its source
    declared (a channel's backlog and its own traffic, ``sd.discover.channel_balance``), not chosen
    by a search, so there is no choice for the halves to repeat or for the null to price: only its
    units and how it reproduces the level are measured."""
    n_units = unit_count(level, steps)
    got = Identification(list(terms), r2, exact, n_units, declared=declared)
    got.exact_moved, got.moved = exact_moved(level, terms, steps)
    if n_units < (need := needed_units(len(terms), got.is_exact)):
        got.why = (f"judged on {n_units} unit{'s' if n_units != 1 else ''} (steps, or stretches between its writes) for "
                   f"{len(terms)} counter{'s' if len(terms) != 1 else ''}: fewer than the {need} it takes to tell "
                   f"{'an exact' if got.is_exact else 'a'} balance from coincidence")
        return got
    if declared:
        got.cum_ratio = cum_ratio(level, terms, steps)
        got.cum_steady = cum_ratio(level, terms, steps, steady=True)
        return got
    h = len(steps) // 2
    halves = [steps[:h], steps[h:]]
    picks = []
    for half in halves:
        t, _, _ = balance(level, pool, solver(level, pool, half), half) if unit_count(level, half) >= MIN_UNITS else ([], 0.0, 0.0)
        picks.append(t)
    got.halves = picks
    held = []
    moved = [sum(1 for i in half if level.deltas[i]) >= MIN_EVENTS for half in halves]
    for (fit_on, test_on), t in zip(((halves[0], halves[1]), (halves[1], halves[0])), picks):
        # a half the level barely moved in can choose nothing and predict nothing: it says nothing
        if all(moved) and unit_count(level, fit_on) >= MIN_UNITS and unit_count(level, test_on) >= MIN_UNITS:
            held.append(fit_of(level, t, test_on)[0] if t else 0.0)
    got.held_out_r2 = min(held) if held else None
    if not got.is_exact:
        keep, dropped = [], []
        for c, sign in terms:
            voters = [(half, t) for half, t in zip(halves, picks) if _votes(level, c, half)]
            if all(_chosen(c, sign, t, half, same) for half, t in voters):
                keep.append((c, sign))
            else:
                dropped.append((c, sign))
        if dropped:
            got.terms, got.dropped = keep, dropped
            got.r2, got.exact = fit_of(level, keep, steps) if keep else (0.0, 0.0)
    got.stable = not got.dropped and all(
        len(t) == len(got.terms) and all(_chosen(c, sg, t, half, same) for c, sg in got.terms)
        for half, t in zip(halves, picks) if all(_votes(level, c, half) for c, _ in got.terms))
    got.cum_ratio = cum_ratio(level, got.terms, steps) if got.terms else None
    got.cum_steady = cum_ratio(level, got.terms, steps, steady=True) if got.terms else None
    own = [fit_of(level, got.terms, half)[0] for half in halves if got.terms and sum(1 for i in half if level.deltas[i]) >= MIN_EVENTS]
    got.halves_r2 = min(own) if own else None
    if got.dropped:
        got.exact_moved, got.moved = exact_moved(level, got.terms, steps)
    got.null_r2 = shift_null(level, pool, steps, solver, shifts)
    if got.null_r2:
        got.p_null = (1 + sum(1 for v in got.null_r2 if v >= r2 - 1e-9)) / (1 + len(got.null_r2))
    if not got.terms:
        got.why = "no counter of its balance was chosen again on both halves of the window: coincidences of the whole window"
    return got


def shift_null(level, pool: list, steps: list[int], solver, shifts: int) -> list[float]:
    """The R² of the best balance of the level's changes moved circularly in time against the
    counters (``shifts`` offsets, evenly spread, none closer than a tenth of the window to none):
    what the same search over the same counters finds when the level and the counters are unrelated."""
    us = units(level.blocks, steps)
    n = len(us)
    if n < 2 * MIN_UNITS or not pool:
        return []
    y = [pick(level, u) for u in us]
    xs = columns(level, pool, steps)
    ls: LeastSquares = solver(level, pool, steps)
    out = []
    for k in range(shifts):
        off = round(n * (0.1 + 0.8 * k / max(1, shifts - 1)))
        if off <= 0 or off >= n:
            continue
        ys = y[off:] + y[:off]
        _, r2, _ = balance_of(ys, xs, pool, ls)
        out.append(r2)
    return out
