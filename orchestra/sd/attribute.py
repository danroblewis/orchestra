"""Which machines may be associated with each flow: hypotheses with their evidence, never a label
and never a declaration (AGENTS.md rules 2, 6 and 7).

System dynamics has no machines. A machine does actual work (a program, an AI agent, a person) and
is known by its events on the bus; how its work relates to the model's flows is unknown, and
inferring it is what Orchestra is for. A machine may be associated with no flow, one or several,
and several machines with one flow. A flow's counter is a measurement of the system: who wrote it
(an instrument, or the ``machine`` label of a series) says nothing about which machine's work it
reflects, so it is never read for this; nor does any configuration or plugin say it.

Each hypothesis is recorded in ``flow.evidence["machines"]`` (``hypotheses``, best first, each with
its evidence and a ``confidence`` between 0 and 1), from one of:

- **its own events**: the flow's counter is itself one machine's event count
  (``orchestra_events_total`` of one type and source);
- **events on the bus**: a machine whose own events, counted per (type, source) in
  ``orchestra_events_total``, match the counter's increments over the window. The events of one
  type from one machine (its instances summed) are compared with the counter step by step, at the
  same step or one step either way (two clocks, two writes). They match when their increments are
  equal in at least ``EQUAL_STEPS`` of the steps either moved in (confidence: that share), or
  correlate at least ``MIN_CORR`` with totals within ``RATIO`` of each other (confidence: the
  correlation times the smaller ratio of the totals). Every machine that matches is a hypothesis.

A counter of traffic on another system's bus (``orchestra.sources.traffic``) carries the
producer or consumer its definition names in its ``machine`` label; that is a label (or, with
``[sources.producers]``, a declaration), so it is not read here either.

A flow with no hypothesis says so: no machine associated yet. That is a question about the system,
not an answer. None of this changes a flow's equation or the model's stocks and flows. Its limits:
a match is a correlation in time, not a cause; two machines reacting to the same events both match;
and discovery itself may not tell apart two similar flows between the same stocks, so a
hypothesis may belong to a flow's twin. Orchestra's own event types (``orchestra.*``:
announcements, the host's and the launcher's) are never candidates."""

from __future__ import annotations

import math

from .series import EVENT_COUNTER, Series, writer_of

EQUAL_STEPS = 0.9        # increments equal in this share of the steps both were live
MIN_CORR = 0.9           # ... or correlated at least this well
RATIO = 2.0              # ... with totals within this factor of each other
MIN_MOVES = 3            # a counter that moved in fewer steps than this cannot be matched to anyone's events
LAGS = (0, -1, 1)        # the event count compared at the same step, a step before and a step after
UNSET = "no machine associated yet"
MAX_HYPOTHESES = 5


def _nonzero(s: Series) -> dict[int, float]:
    """The steps the series moved in, and by how much (worked out once per series)."""
    cached = s.__dict__.get("_moved")
    if cached is None or cached[0] is not s.values:
        cached = (s.values, {i: d for i, d in enumerate(s.deltas) if d})
        s.__dict__["_moved"] = cached
    return cached[1]


def match(counter: Series, events: Series) -> dict | None:
    """How well ``events`` (one machine's events of one type) explain the counter's increments, or
    None when they do not. Worked on the steps either moved in: a long window is mostly quiet."""
    n = min(len(counter.deltas), len(events.deltas))
    xc, xe = _nonzero(counter), _nonzero(events)
    tc, te = sum(xc.values()), sum(xe.values())
    if len(xc) < MIN_MOVES or tc <= 0 or te <= 0 or not (1 / (2 * RATIO) <= te / tc <= 2 * RATIO):
        return None                                   # nowhere near: neither test below could pass
    live = set(range(n) if counter.live is None else counter.live)
    if events.live is not None:
        live &= set(events.live)
    best = None
    for lag in LAGS:
        valid = {i for i in live if 0 <= i + lag < n}
        if not valid:
            continue
        x = {i: v for i, v in xc.items() if i in valid}
        y = {j - lag: v for j, v in xe.items() if j - lag in valid}
        tx, ty, k = sum(x.values()), sum(y.values()), len(valid)
        if len(x) < MIN_MOVES or tx <= 0 or ty <= 0:
            continue
        moved = x.keys() | y.keys()
        same = sum(1 for i in moved if abs(x.get(i, 0.0) - y.get(i, 0.0)) < 1e-9)
        equal_moving = same / len(moved)
        sxy = sum(v * y[i] for i, v in x.items() if i in y) - tx * ty / k
        sxx = sum(v * v for v in x.values()) - tx * tx / k
        syy = sum(v * v for v in y.values()) - ty * ty / k
        corr = sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0
        ratio = ty / tx
        if equal_moving >= EQUAL_STEPS:
            confidence = equal_moving
        elif corr >= MIN_CORR and 1 / RATIO <= ratio <= RATIO:
            confidence = corr * min(ratio, 1 / ratio)
        else:
            continue
        if best is None or confidence > best["confidence"]:
            best = {"confidence": round(confidence, 4), "equal_steps": round((k - len(moved) + same) / k, 4), "equal_steps_moving": round(equal_moving, 4),
                    "corr": round(corr, 4), "lag_steps": lag, "counts": {"flow": round(tx, 3), "events": round(ty, 3)}, "steps": k}
    return best


def candidates(series: list[Series]) -> list[Series]:
    """Each machine's event counts, one per (type, machine): what a flow may be explained by."""
    return [s for s in series if s.name == EVENT_COUNTER and s.counter and writer_of(s) is not None
            and not (s.labels.get("type") or "").startswith("orchestra.")]


def associate(counter: Series | None, events: list[Series]) -> dict:
    """The machines that may be associated with the flow ``counter`` measures, best first, and
    why: ``flow.evidence["machines"]``."""
    if counter is None:
        return {"hypotheses": [], "why": f"{UNSET}: no counter measures it, so no machine's events can be compared with it"}
    if counter.name == EVENT_COUNTER and (who := writer_of(counter)):
        return {"hypotheses": [{"machine": who, "origin": "inferred", "by": "its own events", "confidence": 1.0,
                                "events": {"type": counter.labels.get("type"), "source": who},
                                "why": f"its counter counts {who}'s own events of type {counter.labels.get('type')}"}]}
    best: dict[str, dict] = {}
    for e in events:
        if e is counter or (m := match(counter, e)) is None:
            continue
        who = writer_of(e)
        if who not in best or m["confidence"] > best[who]["confidence"]:
            best[who] = {"machine": who, "origin": "inferred", "by": "events on the bus",
                         "events": {"type": e.labels.get("type"), "source": who}, **m,
                         "why": (f"{who}'s {e.labels.get('type')} events match its increments: equal in "
                                 f"{round(100 * m['equal_steps_moving'])}% of the steps either moved, correlation {m['corr']:.2f}")}
    found = sorted(best.values(), key=lambda h: (-h["confidence"], h["machine"]))[:MAX_HYPOTHESES]
    if found:
        return {"hypotheses": found}
    return {"hypotheses": [], "why": f"{UNSET}: no machine's events on the bus match its counter"}
