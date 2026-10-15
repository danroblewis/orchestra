"""Questions an agent asks the model before placing an agent: what an agent, a stock, an
event or a loop is connected to, and what a new agent with given bindings would close.
Everything here reads the detector's graph; nothing is written."""

from __future__ import annotations

from typing import Any

from . import foundrygraph as fg


def _name(i: str) -> str:
    return i.split(":", 1)[1] if i.startswith("agent:") else i


def _nodes_of(model: dict, key: str) -> list[str]:
    for lp in model["loops"]:
        k = lp.get("key") if isinstance(lp, dict) else getattr(lp, "key", None)
        if k == key:
            return list(lp.get("nodes", []) if isinstance(lp, dict) else getattr(lp, "nodes", []) or [])
    return []


def _loops_through(det: dict, ident: str) -> list[dict]:
    out = []
    for d in det["declared"]:
        c = d.get("cycle")
        if c and ident in c["nodes"]:
            out.append({"key": d["key"], "status": "observed" if c["observed"] else "closable", "path": [_name(n) for n in c["nodes"]], "polarity": c["polarity"]})
    return out


def _unconsumed(model: dict, agents: dict, system: dict | None = None) -> list[dict]:
    """Outflow events no agent wakes on, Orchestra's own processes counted: a departure nobody notices."""
    wakes = [w for a in agents.values() for w in (a.wake_on or [])] + [w for n, b in (system or {}).items() if n != "probes" for w in b.get("wake_on", ())]
    out = []
    for st in model["stocks"]:
        for ev in st.outflows:
            if not any(fg.event_fits(w, ev) or fg.event_fits(ev, w) for w in wakes):
                out.append({"stock": st.key, "event": ev})
    return out


def inspect(model: dict, agents: dict, det: dict, *, agent: str | None = None, stock: str | None = None,
            loop: str | None = None, event: str | None = None, system: dict | None = None) -> dict[str, Any]:
    g = det["graph"]
    edges = g["edges"]
    stocks = {s.key: s for s in model["stocks"]}
    convs = fg.conversions(g, {}, model["stocks"])
    if agent:
        if f"agent:{agent}" not in g["nodes"]:
            return {"error": f"no agent {agent!r}; agents: {sorted(_name(n) for n in g['nodes'] if n.startswith('agent:'))}"}
        a, ia = agents.get(agent), f"agent:{agent}"
        woken = [{"stock": e["src"], "event": e["via"]} for e in edges if e["kind"] == "wakes" and e["dst"] == ia]
        fills = [{"stock": e["dst"], "event": e["via"]} for e in edges if e["kind"] == "fills" and e["src"] == ia]
        drains = [{"stock": e["dst"], "event": e["via"]} for e in edges if e["kind"] == "drains" and e["src"] == ia]
        reads = [e["src"] for e in edges if e["kind"] == "reads" and e["dst"] == ia]
        triggers = [{"agent": _name(e["dst"]), "event": e["via"]} for e in edges if e["kind"] in ("triggers", "departs") and e["src"] == ia and e["dst"].startswith("agent:")]
        valves = [c for c in convs if c["agent"] == agent and not c["coflow"]]
        wake_on = list(getattr(a, "wake_on", []) or []) if a else []
        emits = list(getattr(a, "emits", []) or []) if a else []
        blind = [w for w in wake_on if not any(fg.event_fits(i, w) or fg.event_fits(w, i) for s in stocks.values() for i in [*s.inflows, *s.outflows])]
        unseen = [e for e in emits if not any(fg.event_fits(i, e, agent) for s in stocks.values() for i in [*s.inflows, *s.outflows])]
        openings = [{"loop": d["key"], "fix": lk["fix"]} for d in det["declared"] if not d["detected"] for lk in (d.get("gaps") or {}).get("missing_links", []) if agent in lk["fix"]]
        lines = [f"{agent} wakes on {', '.join(wake_on) or 'nothing'}" + (f": arrivals at {', '.join(sorted({w['stock'] for w in woken}))}" if woken else " (no stock carries those events)"),
                 f"{agent} emits {', '.join(emits) or 'nothing'}" + (f": fills {', '.join(sorted({x['stock'] for x in fills}))}" if fills else "") + (f"; drains {', '.join(sorted({x['stock'] for x in drains}))}" if drains else ""),
                 "valve on " + ", ".join(f"{c['src']} → {c['dst']} ({c['via']})" for c in valves) if valves else f"{agent} converts nothing: no event of its drains one stock and fills another"]
        lp = _loops_through(det, ia)
        lines.append("on loops " + ", ".join(f"{l['key']} ({l['status']})" for l in lp) if lp else f"{agent} is on no expected loop")
        for o in openings:
            lines.append(f"would close {o['loop']}: {o['fix']}")
        return {"agent": agent, "wake_on": wake_on, "woken_by": woken, "emits": emits, "fills": fills, "drains": drains, "reads": reads, "triggers": triggers,
                "valve_on": valves, "loops": lp, "would_close": openings, "wake_on_no_stock_carries": blind, "emits_no_stock_carries": unseen, "lines": lines}
    if stock:
        st = stocks.get(stock)
        if st is None:
            return {"error": f"no stock {stock!r}; stocks: {sorted(stocks)}"}
        by_in: dict[str, list[str]] = {ev: [] for ev in st.inflows}
        by_out: dict[str, list[str]] = {ev: [] for ev in st.outflows}
        for e in edges:
            if e["dst"] != stock or not e["src"].startswith("agent:"):
                continue
            tgt = by_in if e["kind"] == "fills" else by_out if e["kind"] == "drains" else None
            if tgt is None:
                continue
            key = next((ev for ev in tgt if fg.event_fits(ev, e["via"]) or fg.event_fits(e["via"], ev) or ev == e["via"]), e["via"])
            tgt.setdefault(key, []).append(_name(e["src"]))
        wakes = sorted({_name(e["dst"]) for e in edges if e["kind"] == "wakes" and e["src"] == stock})
        readers = sorted({_name(e["dst"]) for e in edges if e["kind"] == "reads" and e["src"] == stock})
        unconsumed = [u["event"] for u in _unconsumed(model, agents, system) if u["stock"] == stock]
        into = [c for c in convs if c["dst"] == stock and not c["coflow"]]
        outof = [c for c in convs if c["src"] == stock and not c["coflow"]]
        gaps = []
        for d in det["declared"]:
            if d["detected"] or stock not in _nodes_of(model, d["key"]):
                continue
            gp = d.get("gaps") or {}
            fixes = [lk["fix"] for lk in gp.get("missing_links", [])] + [f"{m} does not exist in this org" for m in gp.get("missing_members", [])]
            gaps.append({"loop": d["key"], "fix": "; ".join(fixes) or "not closed"})
        lines = [f"{stock} ({st.unit}): {st.description}",
                 "filled by " + ("; ".join(f"{ev} ← {', '.join(sorted(set(ags))) or 'nobody'}" for ev, ags in by_in.items()) or "nothing"),
                 "drained by " + ("; ".join(f"{ev} → {', '.join(sorted(set(ags))) or 'nobody'}" for ev, ags in by_out.items()) or "nothing"),
                 f"an arrival wakes {', '.join(wakes) or 'nobody'}" + (f"; read by {', '.join(readers)}" if readers else "")]
        if unconsumed:
            lines.append(f"departures nobody wakes on: {', '.join(unconsumed)} (an agent with wake_on=[that event] would see them)")
        for c in into:
            lines.append(f"comes from {c['src']} through {c['agent']} ({c['via']})")
        for c in outof:
            lines.append(f"goes to {c['dst']} through {c['agent']} ({c['via']})")
        for gp in gaps:
            lines.append(f"open loop {gp['loop']}: {gp['fix']}")
        return {"stock": stock, "unit": st.unit, "description": st.description, "hidden": st.hidden, "inflows": by_in, "outflows": by_out, "woken_on_arrival": wakes, "readers": readers,
                "unconsumed_outflows": unconsumed, "flows_in": into, "flows_out": outof, "loops": _loops_through(det, stock), "open_loops": gaps, "lines": lines}
    if event:
        fits = lambda x, y, n=None: fg.event_fits(x, y, n) or fg.event_fits(y, x, n)
        # the graph carries Orchestra's own processes too (the loop, the gate), so emitters and wakers come from its edges first
        emitters = sorted({_name(e["src"]) for e in edges if e["kind"] in ("fills", "drains") and e["src"].startswith("agent:") and e["via"] and fits(event, e["via"])}
                          | {n for n, a in agents.items() if any(fits(event, e, n) for e in (a.emits or []))})
        wakers = sorted({_name(e["dst"]) for e in edges if e["kind"] in ("wakes", "inspects", "triggers", "departs") and e["via"] and fits(event, e["via"])}
                        | {n for n, a in agents.items() if any(fits(w, event) for w in (a.wake_on or []))})
        fills = sorted(s.key for s in stocks.values() if any(fg.event_fits(i, event) or fg.event_fits(event, i) for i in s.inflows))
        drains = sorted(s.key for s in stocks.values() if any(fg.event_fits(o, event) or fg.event_fits(event, o) for o in s.outflows))
        lines = [f"{event}: emitted by {', '.join(emitters) or 'nobody'}; wakes {', '.join(wakers) or 'nobody'}; fills {', '.join(fills) or 'no stock'}; drains {', '.join(drains) or 'no stock'}"]
        if not emitters:
            lines.append("nothing emits it: an agent that wakes on it would never run")
        if not fills and not drains:
            lines.append("no stock carries it: emitting it moves nothing on the map until a stock lists it as an inflow or outflow")
        return {"event": event, "emitted_by": emitters, "wakes": wakers, "fills": fills, "drains": drains, "lines": lines}
    if loop:
        d = next((d for d in det["declared"] if d["key"] == loop), None)
        if d is None:
            return {"error": f"no loop {loop!r}; loops: {[x['key'] for x in det['declared']]}"}
        c = d.get("cycle")
        status = "observed" if c and c["observed"] else "closable, not yet seen in the log" if c else "hypothesis: not closed in this org"
        lines = [f"{loop}: {status}" + (f"; path {' → '.join(_name(n) for n in c['nodes'])}; polarity {c['polarity'] or 'none'} ({c['basis']})" if c else "")]
        for lk in (d.get("gaps") or {}).get("missing_links", []):
            lines.append(f"to close it: {lk['fix']}")
        for m in (d.get("gaps") or {}).get("missing_members", []):
            lines.append(f"{m} does not exist in this org")
        return {"loop": loop, "detected": d["detected"], "status": status, "cycle": c, "gaps": d.get("gaps"), "lines": lines}
    # the overview: where an agent could go
    unattached = sorted(n for n, a in agents.items() if not getattr(a, "builtin", False) and not any(e["src"] == f"agent:{n}" and e["kind"] in ("fills", "drains") or e["dst"] == f"agent:{n}" and e["kind"] in ("wakes", "reads") for e in edges))
    open_loops = [{"loop": d["key"], "fixes": [lk["fix"] for lk in (d.get("gaps") or {}).get("missing_links", [])], "missing": (d.get("gaps") or {}).get("missing_members", [])} for d in det["declared"] if not d["detected"]]
    unconsumed = _unconsumed(model, agents, system)
    flows = [f"{c['src']} → {c['dst']} through {c['agent']} ({c['via']})" for c in convs if not c["coflow"]]
    lines = ["flows: " + ("; ".join(flows) or "none"),
             "open loops: " + ("; ".join(f"{o['loop']} ({'; '.join(o['fixes']) or 'members missing: ' + ', '.join(o['missing'])})" for o in open_loops) or "none"),
             "departures nobody wakes on: " + ("; ".join(f"{u['event']} from {u['stock']}" for u in unconsumed) or "none"),
             "agents on no flow: " + (", ".join(unattached) or "none"),
             "ask inspect_model with agent=, stock=, event= or loop= for one of these; what_if_agent to try a binding before creating it"]
    return {"flows": [c for c in convs if not c["coflow"]], "open_loops": open_loops, "unconsumed_outflows": unconsumed, "unattached_agents": unattached, "lines": lines}


def what_if(model: dict, agents: dict, system: dict, name: str, wake_on: list[str], emits: list[str], team: str | None = None) -> dict[str, Any]:
    """What a new agent with these bindings would do to the model: the loops it would close,
    the flows it would be the valve on, the departures it would start consuming, and the
    bindings that would do nothing. Nothing is saved; the result carries the create_agent call."""
    from .org import AgentDef
    before = fg.detect(model["stocks"], agents, model["loops"], system=system)
    trial = dict(agents)
    trial[name] = AgentDef(name=name, roles=[], team=team, kind="ad_hoc", session="ephemeral", wake_on=list(wake_on), emits=list(emits))
    after = fg.detect(model["stocks"], trial, model["loops"], system=system)
    was = {d["key"]: d["detected"] for d in before["declared"]}
    closes = [d["key"] for d in after["declared"] if d["detected"] and not was.get(d["key"])]
    still_open = [{"loop": d["key"], "fixes": [lk["fix"] for lk in (d.get("gaps") or {}).get("missing_links", [])]} for d in after["declared"] if not d["detected"]]
    me = inspect(model, trial, after, agent=name, system=system)
    consumed_before = {(u["stock"], u["event"]) for u in _unconsumed(model, agents, system)}
    consumed_after = {(u["stock"], u["event"]) for u in _unconsumed(model, trial, system)}
    now_consumed = sorted(consumed_before - consumed_after)
    new_cycles = len(after["cycles"]) - len(before["cycles"])
    lines = [f"{name} would close {', '.join(closes)}" if closes else f"{name} would close no expected loop as bound"]
    lines += me["lines"][:4]
    if now_consumed:
        lines.append("would start consuming " + ", ".join(f"{ev} leaving {st}" for st, ev in now_consumed))
    if me["wake_on_no_stock_carries"]:
        lines.append(f"wake_on {', '.join(me['wake_on_no_stock_carries'])}: no stock carries these, so the wake sits on no flow")
    if me["emits_no_stock_carries"]:
        lines.append(f"emits {', '.join(me['emits_no_stock_carries'])}: no stock lists these as an inflow or outflow; add the stock (or its inflow) or the work stays invisible")
    for o in still_open:
        if o["fixes"]:
            lines.append(f"{o['loop']} would still be open: {o['fixes'][0]}")
    return {"name": name, "would_close": closes, "still_open": still_open, "valve_on": me["valve_on"], "loops": me["loops"], "woken_by": me["woken_by"], "fills": me["fills"], "drains": me["drains"],
            "would_consume": [{"stock": st, "event": ev} for st, ev in now_consumed], "new_cycles": new_cycles, "wake_on_no_stock_carries": me["wake_on_no_stock_carries"], "emits_no_stock_carries": me["emits_no_stock_carries"],
            "create_agent": {"name": name, "roles": ["<role>"], "team": team or "<team>", "kind": "ad_hoc", "session": "ephemeral", "wake_on": list(wake_on), "emits": list(emits)}, "lines": lines}
