"""Which candidates a round probes, and what it carries from the rounds and discoveries before it:
inference as a loop that improves under its budget, as the equations do.

Each candidate has an **ident** that is the same in every round (family, view, statistic,
grouping: ``ident``). A round reads the last discovery's verdicts (``feedback.py``) and its own
memory (the last round's ``probed``, ``demoted`` and ``lifted``), and sorts every candidate:

- **kept**: one discovery made a stock or a fitted flow is not probed again; its last probe is
  carried (``known``) and ranked as it was.
- **demoted**: one discovery left out as "an input, not a stock" or "no counters balance it" is
  not probed again and loses ``rank.DEMOTE`` of its score, until the source's held history
  (``held.py``) grows by ``HELD_GROWTH`` of what it was or the window the round serves widens by
  ``WIDER``: then it is probed again, first (and a later discovery's refutation demotes it anew).
- **proposed**: a finer split of a split that became a stock (one more grouping label,
  ``views.finer``), probed before the others never probed.
- **never probed**: probed best first by their score before any probe (``rank.score``, the store's
  labels included), within what is left of the round's ``infer_requests`` and of the store's daily
  cap (``headroom``), each priced by the batched reads it adds (``plan.probe_parts``); those that
  do not fit are **queued**: left out this round, saying so, and first in line the next.
- **probed before** (no verdict): probed again with what is left after those, oldest first; else
  their last probe is carried.

The round records what it probed, kept, demoted and queued (``Inference.round``), and each
candidate's fate and why (``Inference.explored``): the Instruments page's source row and drawer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import Source
from .batch import Part
from .plan import probe_parts, requests_for
from .views import Definition

HELD_GROWTH = 0.5            # of the held history at a demotion: grown by this much, the demoted candidate is probed again
WIDER = 1.05                 # ... or the window a round serves this many times the one it was demoted under
KEPT = ("stock", "flow")
CARRIED = ("series", "moves", "apart", "min", "over")   # what a round remembers of a probe


def ident(d: Definition) -> str:
    """A candidate's identity across rounds (its ``id`` is the round's own)."""
    return "|".join([d.family, d.view, d.stat or "", ",".join(sorted(d.group_by))])


def headroom(source: Source) -> int | None:
    """Requests the round may still make: what is left of its budget and of the store's daily cap
    (every bucket up to the store's); None when neither is bounded."""
    left = None
    b = getattr(source, "budget", None)
    if b is not None and b.requests is not None:
        left = b.requests - b.used
    lim = getattr(source, "limiter", None)
    while lim is not None:
        if lim.per_day:
            day = lim.per_day - lim.today()
            left = day if left is None else min(left, day)
        lim = lim.parent
    return None if left is None else max(0, left)


def finer(verdicts: dict[str, dict]) -> dict[str, list[tuple[list[str], str]]]:
    """Family -> the groupings of its candidates that became stocks, each with why: the splits
    whose finer splits (one more grouping label) are proposed next (``views.views``)."""
    out: dict[str, list[tuple[list[str], str]]] = {}
    for k, v in sorted(verdicts.items()):
        fam, view, _, by = k.split("|")
        if v["fate"] == "stock" and view in ("sum_by", "count", "rollup"):
            out.setdefault(fam, []).append((by.split(",") if by else [], f"a finer split of {fam} by ({by or 'nothing'}), which became a stock"))
    return out


@dataclass
class Plan:
    probe: list[Definition] = field(default_factory=list)          # probed this round, in the order chosen
    carried: dict[str, dict] = field(default_factory=dict)         # id -> an earlier round's probe, not probed again
    demoted: dict[str, str] = field(default_factory=dict)          # id -> why (rank's penalty)
    queued: list[Definition] = field(default_factory=list)         # never probed, and over the budget
    fates: dict[str, tuple[str, str]] = field(default_factory=dict)   # id -> (fate, why)
    budget: int | None = None                                      # requests the probes could spend
    cost: int = 0                                                  # ... and what those chosen were priced at
    demotions: dict[str, dict] = field(default_factory=dict)       # ident -> {why, at, held, serves}: for the next round
    lifted: dict[str, float] = field(default_factory=dict)         # ident -> the discovery whose refutation was lifted


def _grew(rec: dict, held_s: float, serves: float) -> str:
    """Why a demotion lapses, or "": the held history grew by ``HELD_GROWTH``, or the window widened."""
    was = float(rec.get("held") or 0.0)
    if (held_s > was * (1 + HELD_GROWTH)) if was else held_s > 0:
        return f"the held history grew from {was / 3600:.1f} h to {held_s / 3600:.1f} h"
    if serves > float(rec.get("serves") or 0.0) * WIDER:
        return f"the window widened from {float(rec.get('serves') or 0) / 3600:.1f} h to {serves / 3600:.1f} h"
    return ""


def plan(source: Source, cands: list[Definition], verdicts: dict[str, dict], memory, held_s: float, serves: float,
         allot: int | None, prior, start: float, end: float) -> Plan:
    """The round's plan (see the module's docstring). ``memory``: the last round under the same
    settings (``Inference``) or None; ``allot``: the requests its probes may spend (None: no
    bound); ``prior(d)``: a candidate's score before any probe."""
    probed = dict(getattr(memory, "probed", None) or {})
    out = Plan(budget=allot, demotions=dict(getattr(memory, "demoted", None) or {}), lifted=dict(getattr(memory, "lifted", None) or {}))
    urgent, fresh, again = [], [], []
    for d in cands:
        if d.pin:
            continue
        k, v = ident(d), verdicts.get(ident(d))
        mem = probed.get(k)
        if v and v["fate"] in KEPT:
            out.demotions.pop(k, None)
            if mem:
                out.carried[d.id] = {x: mem[x] for x in CARRIED if x in mem}
                out.fates[d.id] = ("kept", f"{v['why']}: kept, not probed again")
            else:
                urgent.append((d, f"{v['why']}; no earlier probe of it is kept: probed"))
            continue
        rec = out.demotions.get(k)
        if v and v["fate"] == "refuted" and rec is None and v["at"] > out.lifted.get(k, float("-inf")):
            rec = out.demotions[k] = {"why": v["why"], "at": v["at"], "held": held_s, "serves": serves}
        if rec is not None:
            if why := _grew(rec, held_s, serves):
                out.lifted[k] = rec["at"]
                del out.demotions[k]
                urgent.append((d, f"demoted ({rec['why']}); probed again: {why}"))
                continue
            out.demoted[d.id] = rec["why"]
            if mem:
                out.carried[d.id] = {x: mem[x] for x in CARRIED if x in mem}
            out.fates[d.id] = ("demoted", (f"{rec['why']}: demoted, not probed again until the held history grows by "
                                          f"{HELD_GROWTH:.0%} or the window widens"))
            continue
        (again if mem else fresh).append(d)
    fresh.sort(key=lambda d: (not d.proposed, -prior(d), d.id))
    again.sort(key=lambda d: (float((probed.get(ident(d)) or {}).get("at") or 0.0), -prior(d), d.id))
    order = [(d, why) for d, why in urgent]
    order += [(d, d.proposed or f"never probed (score {prior(d):.2f} before a probe)") for d in fresh]
    order += [(d, f"probed at {_when(probed.get(ident(d)))}; probed again") for d in again]
    parts: dict[tuple, Part] = {}
    alone = 0
    for d, why in order:
        need = probe_parts(d, start, end)
        if allot is not None:
            new = {k: p for k, p in (need or []) if k not in parts}
            cost = requests_for(source, {**parts, **new}, alone + (need is None)) if new or need is None else out.cost
            if cost > allot:
                if (mem := probed.get(ident(d))) is not None:
                    out.carried[d.id] = {x: mem[x] for x in CARRIED if x in mem}
                    out.fates[d.id] = ("known", f"probed at {_when(mem)}; not probed again this round (its budget): that probe stands")
                else:
                    out.queued.append(d)
                    out.fates[d.id] = ("queued", (f"queued: not probed this round, its {allot} requests spent on better candidates "
                                                 f"(score {prior(d):.2f} before a probe)"))
                continue
            out.cost = cost
        for k, p in need or []:
            if k in parts:
                parts[k].series = max(parts[k].series, p.series)
            else:
                parts[k] = p
        alone += need is None
        out.demoted.pop(d.id, None)
        out.carried.pop(d.id, None)
        out.probe.append(d)
        out.fates[d.id] = ("probed", why)
    return out


def _when(mem: dict | None) -> str:
    at = float((mem or {}).get("at") or 0.0)
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at)) if at else "an earlier round"


def summary(p: Plan, cands: list[Definition]) -> tuple[dict, list[dict]]:
    """What the round did (``Inference.round``), and each candidate's fate and why (``explored``)."""
    count = lambda f: sum(1 for x, _ in p.fates.values() if x == f)
    rec = {"probed": count("probed"), "kept": count("kept"), "demoted": count("demoted"), "queued": count("queued"),
           "known": count("known"), "proposed": sum(1 for d in p.probe if d.proposed), "budget": p.budget, "priced": p.cost}
    chosen = {d.id for d in p.probe}
    rows = [{"candidate": ident(d), "name": d.name, "family": d.family, "view": d.view, "group_by": list(d.group_by),
             "fate": p.fates[d.id][0], "why": p.fates[d.id][1]}
            for d in p.probe + [d for d in cands if d.id in p.fates and d.id not in chosen]]       # the probed in the order chosen
    return rec, rows
