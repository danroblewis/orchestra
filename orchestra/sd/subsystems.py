"""Subsystems (docs/proposals/subsystems.md): partitions of the one model's stocks, flows and
machines by a label its series already carry, derived on read and display only, as candidate
marks are. A partition never splits the model: every part stays in it, and nothing here changes a
stock, a flow, an equation or a hypothesis.

- **The labels.** Every label a stock's series carries (its own series, or the level discovery
  keeps for a hidden one, ``evidence["level"]``), except who wrote it (``NOT_IDENTITY``:
  instrument, machine, source, project, instance) and Orchestra's own flags (``simulated``,
  ``draft``): a series' writer is never a subsystem (AGENTS.md rule 7). A label with fewer than
  two values among the stocks partitions nothing and is left out. No label's name is known here
  (rule 1).
- **A stock** is in the group of its label's value; one whose series carries no such label is
  unassigned, drawn outside every box.
- **A flow** is inside a group when both its ends are in it, or one is and the other is outside
  the system; it **crosses** when its ends are in two groups; it touches the unassigned
  otherwise. Each flow counts once (a co-flow, ``<flow>@<writer>``, is a flow of its own). The
  separation measure is the count of crossing flows per pair of groups; a flow fitted from a
  simulated series (``evidence["simulated"]``) is counted apart (``simulated``), never in it, so a
  placeholder neither joins two subsystems nor keeps them apart. Draft series are never in a model.
- **A machine** is placed only by the flows it is a hypothesis for (``sd.attribute``): in the one
  group their ends in a group are all in (a flow to an unassigned stock places it by its other
  end), spanning when they are in several, unassigned when it has none. Never by a label on a
  series.
- **The default** partition is the one that keeps the most flows between two stocks inside a
  group, then crosses the fewest, assigns the most stocks and has the fewest groups: what the
  data separates best, never a label chosen by name."""

from __future__ import annotations

from .discover import NOT_IDENTITY

LEFT = NOT_IDENTITY | {"simulated", "draft"}


def labels_of(stock) -> dict[str, str]:
    """The labels a stock's series carries that may partition it."""
    if stock.series is not None:
        labels = stock.series.labels or {}
    else:
        level = (stock.evidence or {}).get("level")
        labels = (level.get("labels") or {}) if isinstance(level, dict) else {}
    return {k: str(v) for k, v in labels.items() if k not in LEFT}


def _hypotheses(model) -> dict[str, list[str]]:
    """flow id -> the machines it is a hypothesis for (``evidence["machines"]``; for a version saved
    before 2026-10-27, the machines' ``attributed``)."""
    out: dict[str, list[str]] = {}
    for f in model.flows:
        assoc = (f.evidence or {}).get("machines")
        if isinstance(assoc, dict):
            out[f.id] = [h["machine"] for h in assoc.get("hypotheses") or [] if h.get("machine")]
    old = {f.id for f in model.flows if f.id not in out}
    for m in model.machines:
        for fid in m.attributed:
            if fid in old:
                out.setdefault(fid, []).append(m.id)
    return out


def partition(model, label: str) -> dict | None:
    """The model's parts by ``label``'s value; None when it has fewer than two values."""
    group: dict[str, str] = {}
    for s in model.stocks:
        if (v := labels_of(s).get(label)) is not None:
            group[s.id] = v
    values = sorted(set(group.values()))
    if len(values) < 2:
        return None
    groups = {v: {"value": v, "stocks": [], "flows": [], "machines": []} for v in values}
    unassigned = {"stocks": [s.id for s in model.stocks if s.id not in group], "flows": [], "machines": []}
    for s in model.stocks:
        if s.id in group:
            groups[group[s.id]]["stocks"].append(s.id)
    crossing: dict[tuple[str, str], dict] = {}
    flow_groups: dict[str, set[str]] = {}
    joined = 0
    for f in model.flows:
        ends = [None if e is None else group.get(e, "") for e in (f.src, f.dst)]   # None: outside; "": unassigned
        inner = {e for e in ends if e}
        if "" in ends:
            unassigned["flows"].append(f.id)
            flow_groups[f.id] = inner
        elif len(inner) == 1:
            g = inner.pop()
            groups[g]["flows"].append(f.id)
            flow_groups[f.id] = {g}
            if None not in ends and not (f.evidence or {}).get("simulated"):
                joined += 1
        else:
            pair = tuple(sorted(inner))
            c = crossing.setdefault(pair, {"between": list(pair), "flows": [], "count": 0, "simulated": 0})
            c["flows"].append(f.id)
            c["simulated" if (f.evidence or {}).get("simulated") else "count"] += 1
            flow_groups[f.id] = set(pair)
    spanning = []
    hyps = _hypotheses(model)
    for m in model.machines:
        gs = sorted({g for fid, ms in hyps.items() if m.id in ms for g in flow_groups.get(fid, ())})
        if len(gs) == 1:
            groups[gs[0]]["machines"].append(m.id)
        elif gs:
            spanning.append({"machine": m.id, "groups": gs})
        else:
            unassigned["machines"].append(m.id)
    cross = sorted(crossing.values(), key=lambda c: (-c["count"], c["between"]))
    return {"label": label, "groups": list(groups.values()), "unassigned": unassigned, "crossing": cross,
            "spanning": spanning, "joined": joined, "crossed": sum(c["count"] for c in cross),
            "crossed_simulated": sum(c["simulated"] for c in cross)}


def subsystems(model) -> dict:
    """Every partition the model's series carry a label for, the default first:
    ``{"default": label or None, "partitions": [...]}``."""
    labels = sorted({k for s in model.stocks for k in labels_of(s)})
    parts = [p for k in labels if (p := partition(model, k)) is not None]
    parts.sort(key=lambda p: (-p["joined"], p["crossed"], len(p["unassigned"]["stocks"]), len(p["groups"]), p["label"]))
    return {"default": parts[0]["label"] if parts else None, "partitions": parts}
