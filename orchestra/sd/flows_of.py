"""The counters that fill and drain one given level: discovery's balance search, asked about one level.

Discovery searches every level's balance at once (``sd.discover``). An operator translating
another store often knows the level (a queue's depth, a pool's open connections, a volume's used
bytes) and not which of the store's counters move it. ``flows_of`` answers that for one level and
a pool of candidate counters the caller read (``orchestra.sources``), with discovery's own code
and gates and nothing of its own:

- **units:** only counters in the level's unit are terms (``sd.units``); the others are listed;
- **the search:** ``sd.balance`` on the steps every series is live in (``sd.live``), and on the
  stretches between a slow counter's writes when that fits where steps do not (``sd.coarse``);
- **the evidence:** ``sd.identify`` (enough units, the halves' vote and held-out fit, the level
  reproduced, the shift null) and ``sd.accept.gate``, which says whether discovery would accept it.

Two things are added for a question about one level:

- **Alternatives.** The best balance without each of its counters in turn, so a copy of a flow in
  another store, or a second balance, is seen beside the first (only those that fit at
  ``SHOWN_R2`` or are accepted).
- **One side.** A level drained (or filled) steadily by a flow no counter measures (sessions that
  end unseen) has no ±1 balance: its inflow alone fits worse than nothing. With no balance, the
  counters whose changes correlate with the level's (``SIDE_CORR``) are listed as its sides, a
  weaker evidence: an inflow (positive) or an outflow (negative) beside an unmeasured residual.
- **Bursts.** A level that one unmeasured flow moves in a few large steps (a log's retention
  deleting whole segments, a dead-letter queue purged at six) is balanced by nothing over the
  window: its measured inflow alone makes the error worse at the burst. When no balance fits, the
  search is run again without the units in which the level moved by more than ``BURST`` times its
  usual change, and the bursts are reported as a flow no counter measures (a residual)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from statistics import median

from .accept import MIN_R2, gate
from .balance import MIN_EVENTS, LeastSquares, balance, columns, explained_share, fit_of
from .coarse import coarse
from .discover import lagged_flow, same_flow
from .identify import FLAG_EXACT, identify, timing_limited, two_clocks
from .live import arrived, balance_steps
from .resolution import pick, units
from .series import Declared, Series, sample, series_key
from .units import WORDS, unit_of

BURST = 5.0             # a unit the level moved by this many times its median absolute change is a burst
MAX_BURSTS = 0.15       # ... and bursts are at most this share of the units (more is how the level moves)
ALTERNATIVES = 3        # balances reported beside the best one, at most
SHOWN_R2 = 0.5          # a balance not accepted is reported only when it fits at least this well
SIDE_CORR = 0.3         # with no balance, a counter whose changes correlate this well with the level's is one side of it


@dataclass
class Balance:
    terms: list[tuple[str, int]]            # series key and sign, +1 inflow, −1 outflow
    r2: float
    exact: float
    accepted: bool                          # discovery's gates pass (sd.accept.gate)
    why: str                                # ... or why not
    evidence: dict                          # sd.identify's record: units, held-out R², running residual, shift null
    on: str                                 # "steps", or the stretches between which counter's writes
    shares: dict[str, float] = field(default_factory=dict)   # each counter's share of the level's variance
    level_change: float = 0.0               # the level's change over the units judged
    counted: dict[str, float] = field(default_factory=dict)  # each counter's count over those units
    residual: float = 0.0                   # what the balance leaves unexplained over them: an unmeasured net flow
    bursts: dict | None = None              # the bursts left out (bursts mode): {"units", "direction", "total"}

    def record(self) -> dict:
        return {"terms": [{"series": k, "sign": s} for k, s in self.terms], "r2": round(self.r2, 4),
                "exact": round(self.exact, 4), "accepted": self.accepted, "why": self.why, "on": self.on,
                "shares": {k: round(v, 4) for k, v in self.shares.items()}, "level_change": self.level_change,
                "counted": self.counted, "residual": self.residual, "evidence": self.evidence,
                **({"bursts": self.bursts} if self.bursts else {})}


@dataclass
class Found:
    level: str
    unit: str
    balances: list[Balance] = field(default_factory=list)   # the best first
    other_units: dict[str, str] = field(default_factory=dict)  # counters not searched: their unit
    still: list[str] = field(default_factory=list)          # counters that did not move in the window
    sides: list[tuple[str, float]] = field(default_factory=list)  # with no balance: counters whose changes move with the level's (correlation)
    why: str = ""                                           # why nothing could be searched


def name_unit(name: str, labels: dict[str, str], declared: str | None = None) -> str:
    """``sd.units.unit_of``, and when that finds no unit word, a name word that begins or ends with
    one (``bytesin``, ``rxbytes``: exporters that glue the unit to the direction)."""
    got = unit_of(name, labels, declared)
    if got != "count" or labels.get("unit") or declared:
        return got
    words = [w for w in name.lower().replace(":", "_").split("_") if w]
    for w in reversed(words):
        for u, norm in WORDS.items():
            if len(u) >= 4 and w != u and (w.startswith(u) or w.endswith(u)):
                return norm
    return got


def _fits(level, r2: float, exact: float, terms: list | None = None, steps: list[int] | None = None) -> bool:
    """A balance a level may be a stock on (as ``sd.discover``'s): ``MIN_R2``, or, judged on a slow
    counter's writes, misses that are timing; a level of two values only when exact."""
    good = r2 >= MIN_R2 or (terms is not None and steps is not None and two_clocks(level, terms)
                            and timing_limited(level, terms, steps, r2))
    return good and (exact >= FLAG_EXACT or len({v for _, v in level.points}) > 2)


def _solver_cache():
    solvers: dict[tuple, LeastSquares] = {}

    def solver(level, pool: list, steps: list[int]) -> LeastSquares:
        key = (tuple(steps), tuple(c.key for c in pool), tuple(level.blocks or ()))
        if key not in solvers:
            solvers[key] = LeastSquares(columns(level, pool, steps))
        return solvers[key]
    return solver


def _fresh(level: Series) -> Series:
    view = replace(level, blocks=level.blocks)
    view.__dict__.pop("_deltas", None)
    return view


def _search(level: Series, pool: list[Series], steps: list[int], start: float, step: float, n: int) -> Balance | None:
    """The best balance of ``level`` among ``pool`` over ``steps``, with its evidence."""
    if not pool:
        return None
    level = _fresh(level)
    solvers: dict = {}
    got = balance(level, pool, None, steps)
    terms, r2, exact = coarse(level, pool, steps, got, _fits, solvers, ())
    if not terms:
        return None
    mine = arrived(steps, [level, *(c for c, _ in terms)], start, step)
    if mine != steps:
        steps = mine
        r2, exact = fit_of(level, terms, steps)
    idn = identify(level, terms, r2, exact, pool, steps, _solver_cache(), lambda a, b: same_flow(a, b, n) or lagged_flow(a, b),
                   clocks=two_clocks(level, terms))
    why = gate(idn)
    if why and not idn.why and not idn.dropped and idn.r2 < MIN_R2:
        why = f"it fits at R² {idn.r2:.2f}, under the {MIN_R2} a stock's balance needs"
    if not why and not _fits(level, idn.r2, idn.exact, idn.terms, steps):
        why = f"it fits at R² {idn.r2:.2f}, under the {MIN_R2} a stock's balance needs"
    final = idn.terms or terms
    slow = [c for c, _ in final if c.blocks] if level.blocks is not None else []
    on = f"the stretches between the writes of {min(slow, key=lambda c: len(c.blocks)).key}" if slow else "steps"
    us = units(level.blocks, steps)
    lv = sum(pick(level, u) for u in us)
    counted = {c.key: sum(pick(c, u) for u in us) for c, _ in final}
    resid = lv - sum(sg * counted[c.key] for c, sg in final)
    shares = {c.key: explained_share(level, final, c, steps) for c, _ in final}
    return Balance([(c.key, sg) for c, sg in final], idn.r2, idn.exact, not why, why, idn.record(), on, shares,
                   _num(lv), {k: _num(v) for k, v in counted.items()}, _num(resid))


def _num(x: float) -> float:
    return round(x, 3) if abs(x) < 1e6 else float(f"{x:.6g}")


def sides(level: Series, pool: list[Series], steps: list[int]) -> list[tuple[str, float]]:
    """The counters whose changes over ``steps`` correlate with the level's by ``SIDE_CORR`` or
    more either way, the strongest first (at most ``ALTERNATIVES``)."""
    y = [level.deltas[i] for i in steps]
    out = []
    for c in pool:
        r = _corr(y, [c.deltas[i] for i in steps])
        if abs(r) >= SIDE_CORR:
            out.append((c.key, round(r, 3)))
    return sorted(out, key=lambda x: -abs(x[1]))[:ALTERNATIVES]


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 3:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((x - ma) * (z - mb) for x, z in zip(a, b)) / (va * vb) ** 0.5


def bursts(level: Series, steps: list[int]) -> tuple[list[int], dict] | None:
    """The steps in which the level moved by more than ``BURST`` times its median absolute change,
    when they are few (``MAX_BURSTS``) and the level moved in at least ``MIN_EVENTS`` others; and
    what they were. None when there are none."""
    d = [(i, level.deltas[i]) for i in steps]
    moved = [abs(v) for _, v in d if v]
    if len(moved) < MIN_EVENTS:
        return None
    usual = median(moved)
    big = [(i, v) for i, v in d if abs(v) > BURST * usual]
    if not big or len(big) > MAX_BURSTS * len(d):
        return None
    falls = sum(1 for _, v in big if v < 0)
    direction = "falls" if falls > len(big) / 2 else "rises" if falls < len(big) / 2 else "both"
    return [i for i, _ in big], {"units": len(big), "direction": direction, "total": _num(sum(v for _, v in big)),
                                 "usual_change": _num(usual)}


def flows_of(level: tuple[str, dict, list], counters: list[tuple[str, dict, list]], start: float, step: float, n: int,
             kinds: dict[str, Declared] | None = None, declared_units: dict[str, str] | None = None,
             alternatives: int = ALTERNATIVES) -> Found:
    """The balances of ``level`` (name, labels, points) among ``counters`` (each name, labels,
    points) on the grid of ``n`` steps from ``start``: the best first, then up to ``alternatives``
    found without each of its counters in turn, each with discovery's evidence and verdict.
    ``kinds`` says what a series is (by ``series_key``: a level, a counter, and whether its first
    sample is a baseline); ``declared_units`` a unit its source declared (by key)."""
    kinds = dict(kinds or {})
    lkey = series_key(level[0], level[1])
    kinds[lkey] = replace(kinds.get(lkey) or Declared("level"), kind="level")
    for name, labels, _ in counters:
        k = series_key(name, labels)
        kinds.setdefault(k, Declared("counter", baseline=not name.endswith("_total")))
    series = sample([level, *counters], start, step, n, kinds)
    lv = next((s for s in series if s.key == lkey), None)
    units_ = declared_units or {}
    unit = name_unit(level[0], level[1], units_.get(lkey))
    out = Found(lkey, unit)
    if lv is None:
        out.why = "the level has no points in the window"
        return out
    pool = []
    for s in series:
        if s is lv:
            continue
        if not any(s.deltas):
            out.still.append(s.key)
            continue
        u = name_unit(s.name, s.labels, units_.get(s.key))
        if u != unit:
            out.other_units[s.key] = u
            continue
        pool.append(s)
    steps = balance_steps(lv, pool)
    moved = sum(1 for i in steps if lv.deltas[i])
    if moved < MIN_EVENTS:
        out.why = f"the level changed in {moved} step{'s' if moved != 1 else ''} of the window: fewer than {MIN_EVENTS}, too few to tell a balance from coincidence"
        return out
    if not pool:
        out.why = f"no counter in the level's unit ({unit}) moved in the window"
        return out
    best = _search(lv, pool, steps, start, step, n)
    calm = steps
    if (best is None or not best.accepted) and (b := bursts(lv, steps)) is not None:
        trial = [i for i in steps if i not in set(b[0])]
        got = _search(lv, pool, trial, start, step, n)
        if got is not None and (best is None or got.accepted or got.r2 > best.r2):
            got.bursts, best, calm = b[1], got, trial
    if best is None or (not best.accepted and best.r2 < SHOWN_R2):
        out.sides = sides(lv, pool, steps)
        if best is None:
            out.why = "no counters balance it: none explains a share of the level's changes"
        else:
            shown = " ".join(f"{'+' if sg > 0 else '−'}{k}" for k, sg in best.terms)
            out.why = f"no counters balance it: the best ({shown}) fits at R² {best.r2:.2f}"
        return out
    out.balances.append(best)
    seen = {tuple(sorted(best.terms))}
    for key, _ in best.terms:
        if len(out.balances) > alternatives:
            break
        got = _search(lv, [c for c in pool if c.key != key], calm, start, step, n)
        if got is None or tuple(sorted(got.terms)) in seen or not (got.accepted or got.r2 >= SHOWN_R2):
            continue
        got.bursts = best.bursts
        seen.add(tuple(sorted(got.terms)))
        out.balances.append(got)
    return out
