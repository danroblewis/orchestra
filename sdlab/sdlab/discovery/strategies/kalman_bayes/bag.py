"""A block-subsampling ensemble of the discovery (Ensemble-SINDy / stability selection style): the
whole discovery run again on contiguous blocks of the run, each flow's inclusion probability (the
share of blocks whose model has it), and the structure of the flows kept in most blocks.

A block is one contiguous stretch of FRACTION of the reports (continuity of the levels is kept, so the
discovery sees an ordinary shorter run); the blocks' starts are spread evenly from the first report
to the last start that fits. The injections and measured inputs are cut to the block, the eras kept.
"""

from __future__ import annotations

import copy
import time

import numpy as np

FRACTION = 0.7        # each block holds this share of the reports (stability selection's half, more for dynamics)
BLOCKS = 8            # blocks tried (fewer when the time does not allow; none below MIN_BLOCKS)
MIN_BLOCKS = 4
KEEP = 0.5            # a flow is kept when more than this share of the blocks has it


def readers(f: dict) -> tuple:
    out = set()
    for r in [g["rate"] for g in f["byTime"]] if f.get("byTime") else [f.get("rate") or {}]:
        out |= {r.get("stock")} | {x.get("stock") for x in r.get("terms") or []}
    return tuple(sorted(s for s in out if s))


def key(f: dict) -> tuple:
    """What a flow is, numbers aside: its ends, the stocks its rate reads, its co-flows and effects
    (an outside inflow in pieces is the same flow wherever its pieces fall)."""
    return (f.get("from"), f.get("to"), readers(f), tuple(sorted(u.get("stock") or "" for u in f.get("uses") or [])),
            tuple(sorted(e.get("stock") or "" for e in f.get("effects") or [])))


def label(k: tuple) -> str:
    a, b, rd, us, ef = k
    s = f"{a or 'outside'}->{b or 'outside'}"
    if rd:
        s += f" reads {','.join(rd)}"
    if us:
        s += f" uses {','.join(us)}"
    if ef:
        s += f" effects {','.join(ef)}"
    return s


def block(run: dict, opts: dict, i0: int, i1: int) -> tuple[dict, dict]:
    """The run and opts cut to reports i0..i1-1."""
    t = list(run["t"])[i0:i1]
    lv = {k: list(v)[i0:i1] for k, v in run["levels"].items()}
    o = dict(opts)
    if opts.get("injections"):
        o["injections"] = [j for j in opts["injections"] if t[0] < float(j["t"]) <= t[-1]] or None
    if opts.get("inputs"):
        n = len(run["t"])
        o["inputs"] = {k: (list(v)[i0:i1] if len(v) == n else list(v)) for k, v in opts["inputs"].items()}
    return {**run, "t": t, "levels": lv}, o


def starts(n: int, m: int, count: int) -> list[int]:
    return sorted({int(round(x)) for x in np.linspace(0, n - m, count)})


def ensemble(discover, stocks: list[dict], run: dict, opts: dict, each: float, until: float) -> list[list[dict]]:
    """The discovery's flows on each block (as many blocks as finish before `until`; each given `each`
    seconds at most by `discover(stocks, run, opts, seconds)`, which returns None when it cannot)."""
    n = len(run["t"])
    m = int(round(FRACTION * n))
    out = []
    if m < 12:
        return out
    for i0 in starts(n, m, BLOCKS):
        left = until - time.monotonic()
        if left < min(each, 5.0):
            break
        r, o = block(run, opts, i0, i0 + m)
        got = discover(stocks, r, o, min(each, left))
        if got is not None:
            out.append(got.get("flows") or [])
    return out


def inclusion(full: list[dict], members: list[list[dict]]) -> dict[tuple, float]:
    """Each flow's share of the blocks whose model has it (the full run's flows and any other)."""
    keys = list(dict.fromkeys([key(f) for f in full] + [key(f) for fl in members for f in fl]))
    return {k: sum(any(key(f) == k for f in fl) for fl in members) / len(members) for k in keys}


def bagged(full: list[dict], members: list[list[dict]], inc: dict[tuple, float]) -> tuple[list[dict], list, list]:
    """The full run's flows kept in most blocks, and the flows most blocks have that it lacks (taken
    from the first block that has them; only plain rates, not pieces or eras cut to a block)."""
    have = {key(f) for f in full}
    kept = [copy.deepcopy(f) for f in full if inc.get(key(f), 0.0) > KEEP]
    dropped = [label(key(f)) for f in full if inc.get(key(f), 0.0) <= KEEP]
    added = []
    for k, p in inc.items():
        if k in have or p <= KEEP:
            continue
        f = next(f for fl in members for f in fl if key(f) == k)
        if f.get("inflow") or f.get("byTime"):
            continue
        kept.append(copy.deepcopy(f))
        added.append(label(k))
    return kept, dropped, added
