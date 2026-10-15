"""The causal graph behind a project, and the feedback loops found in it.

Input: the declared stocks (what the project holds; each names the events that fill it and
the events that drain it, and the agents that consume it with the sign of that effect) and
the org (every agent's wake rules and the events its actions cause, Orchestra's own
bindings included). Flows are never declared: an agent woken by an arrival at one stock
whose actions fill another is a conversion between them. Output: the cycles of that signed
graph through at least one stock and one agent, each with its polarity and a signature.
Expected loops (the model's `loops/`) are matched by membership; a cycle no expectation
names is reported for the Supervisor; an expectation no cycle matches is a hypothesis."""

from __future__ import annotations

import hashlib
from typing import Any

MAX_CYCLES = 400
MAX_LEN = 14
SEARCH_BUDGET = 40000


# who moves tickets out of each state; a declared "ticket_transition:FROM>TO" fits an agent's
# plain "ticket_transition:TO" only when that agent owns the (FROM, TO) transition
TRANSITION_OWNER = {("OPEN", "IN_PROGRESS"): "orchestra", ("REJECTED", "IN_PROGRESS"): "orchestra", ("BLOCKED", "OPEN"): "coordinator", ("IN_PROGRESS", "OPEN"): "orchestra",
                    ("READY_FOR_REVIEW", "IN_REVIEW"): "orchestra", ("IN_REVIEW", "READY_FOR_REVIEW"): "orchestra", ("IN_PROGRESS", "READY_FOR_REVIEW"): "worker", ("IN_PROGRESS", "BLOCKED"): "worker",
                    ("IN_REVIEW", "APPROVED"): "reviewer", ("IN_REVIEW", "REJECTED"): "reviewer", ("APPROVED", "MERGING"): "merge_gate", ("MERGING", "DONE"): "merge_gate", ("MERGING", "REJECTED"): "merge_gate",
                    ("MERGING", "APPROVED"): "merge_gate", ("OPEN", "CANCELLED"): "coordinator", ("BLOCKED", "CANCELLED"): "coordinator"}


LOOP_SLACK = 2          # a declared loop may be detected with up to this many members beyond the ones it names


def _split(ev: str) -> tuple[str, str]:
    t, _, suffix = ev.partition(":")
    return t, suffix


def plain(ev: str) -> str:
    """'ticket_transition:IN_REVIEW>REJECTED' → 'ticket_transition:REJECTED', the form the log counts."""
    t, suffix = _split(ev)
    return f"{t}:{suffix.split('>')[-1]}" if ">" in suffix else ev


def event_fits(declared: str, emitted: str, agent: str | None = None) -> bool:
    """A stock's inflow/outflow or an agent's wake rule against an emitted event type: the
    types match and either side's suffix is empty or they are equal. A declared transition
    with a source state ('ticket_transition:IN_REVIEW>REJECTED') fits an emitter's plain
    'ticket_transition:REJECTED' only when that emitter owns the transition."""
    dt, ds = _split(declared)
    et, es = _split(emitted)
    if dt != et:
        return False
    if ">" in ds:
        frm, to = ds.split(">", 1)
        if es and es != to:
            return False
        return agent is None or TRANSITION_OWNER.get((frm, to)) == agent or agent not in set(TRANSITION_OWNER.values())
    return not ds or not es or ds == es


def _agents_from(agents: dict, system: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, ag in agents.items():
        out[name] = {"wake_on": list(getattr(ag, "wake_on", []) or []), "emits": list(getattr(ag, "emits", []) or []), "builtin": bool(getattr(ag, "builtin", False)), "team": getattr(ag, "team", None)}
    for name, b in (system or {}).items():
        if name == "probes":
            continue
        out.setdefault(name, {"wake_on": list(b.get("wake_on", ())), "emits": list(b.get("emits", ())), "builtin": True, "team": None, "system": True})
    return out


def build(stocks: list, agents: dict, system: dict | None = None) -> dict[str, Any]:
    """Nodes: stock keys and ``agent:<name>``. Signed edges:

    - fills: an agent emits an event that is a stock's inflow (+)
    - drains: an agent emits an event that is a stock's outflow (−)
    - wakes: an agent wakes on an event that is a stock's inflow (the arrival) or, when no
      stock has it as an inflow, a stock's outflow (the departure); both + (more events, more
      activity; the drain link already carries the −)
    - triggers: an agent emits an event another agent wakes on and no stock carries (+)
    - departs: an agent emits an event that drains a stock and another agent wakes on it (−):
      the departure reaches the agent through whoever caused it, not through the level
    - reads: a stock names the agent as a consumer, with the declared effect sign
    """
    ags = _agents_from(agents, system)
    nodes: dict[str, dict] = {s.key: {"id": s.key, "kind": "stock", "name": s.name, "hidden": bool(getattr(s, "hidden", False))} for s in stocks}
    for name, a in ags.items():
        nodes[f"agent:{name}"] = {"id": f"agent:{name}", "kind": "agent", "name": name, "builtin": a["builtin"], "team": a["team"]}
    edges: list[dict] = []
    carries: list[dict] = []
    seen: set[tuple] = set()
    touched: dict[str, set[str]] = {}          # agent -> stocks whose departures wake it

    def add(src: str, dst: str, sign: str, kind: str, via: str) -> None:
        k = (src, dst, sign, kind, via)
        if k in seen:
            return
        seen.add(k)
        edges.append({"src": src, "dst": dst, "sign": sign, "kind": kind, "via": via})

    for name, a in ags.items():
        aid = f"agent:{name}"
        for ev in a["emits"]:
            for s in stocks:
                hit_in = next((i for i in s.inflows if event_fits(i, ev, name)), None)
                if hit_in:
                    add(aid, s.key, "+", "fills", hit_in if ">" in hit_in else ev)
                hit_out = next((o for o in s.outflows if event_fits(o, ev, name)), None)
                if hit_out:
                    add(aid, s.key, "-", "drains", hit_out if ">" in hit_out else ev)
                    if getattr(s, "hidden", False):
                        # every agent whose verdict drains the hidden stock inspects it: its discovery rate rises with the level
                        # (Ford & Sterman's p_detect × defects); nothing is woken by a stock nobody can see
                        add(s.key, aid, "+", "inspects", hit_out if ">" in hit_out else ev)
                hit_carry = next((o for o in getattr(s, "carried_by", []) or [] if event_fits(o, ev, name)), None)
                if hit_carry:
                    carries.append({"src": aid, "dst": s.key, "via": hit_carry if ">" in hit_carry else ev, "to": (getattr(s, "carried_to", None) or {}).get(hit_carry)})   # not a link of the causal graph: the stock keeps its level
        for w in a["wake_on"]:
            fills = [s for s in stocks if any(event_fits(i, w) or event_fits(w, i) for i in s.inflows)]
            if fills:
                for s in fills:
                    if getattr(s, "hidden", False):
                        continue                          # a stock nobody can see wakes nobody; its inspectors are linked by their drains
                    add(s.key, aid, "+", "wakes", w)
            else:
                # a departure wakes the agent through the agent that caused it, not through the
                # stock's level: a trigger from the draining agent, signed − because the event
                # lowered a stock (build fails → the manager acts)
                for s in stocks:
                    if any(event_fits(o, w) or event_fits(w, o) for o in s.outflows):
                        for other, b in ags.items():
                            if other != name and any(event_fits(o, w, other) for o in s.outflows if any(event_fits(o, e, other) for e in b["emits"])):
                                add(f"agent:{other}", aid, "-", "departs", w)
                        touched.setdefault(aid, set()).add(s.key)
    # an agent whose action wakes another agent directly, by an event no stock carries
    for name, a in ags.items():
        for ev in a["emits"]:
            if any(event_fits(i, ev, name) for s in stocks for i in s.inflows) or any(event_fits(o, ev, name) for s in stocks for o in s.outflows):
                continue                      # carried by a stock: a fill, or a departure handled above
            for other, b in ags.items():
                if other != name and any(event_fits(w, ev) for w in b["wake_on"]):
                    add(f"agent:{name}", f"agent:{other}", "+", "triggers", ev)
    for s in stocks:
        for c in getattr(s, "consumers", []) or []:
            name, effect = (c, "+") if isinstance(c, str) else (c.get("agent"), c.get("effect", "+"))
            if f"agent:{name}" in nodes:
                add(s.key, f"agent:{name}", effect, "reads", "")
    for aid, sts in touched.items():
        nodes[aid]["touches"] = sorted(sts)
    return {"nodes": nodes, "edges": edges, "carries": carries}


def elementary_cycles(g: dict, max_cycles: int = MAX_CYCLES, max_len: int = MAX_LEN) -> list[list[str]]:
    """Simple cycles through at least one stock and one agent, shortest first, bounded."""
    adj: dict[str, list[str]] = {}
    for e in g["edges"]:
        adj.setdefault(e["src"], []).append(e["dst"])
    order = sorted(g["nodes"])
    index = {n: i for i, n in enumerate(order)}
    found: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    budget = [SEARCH_BUDGET]

    def dfs(start: str, node: str, path: list[str], on_path: set[str]) -> None:
        budget[0] -= 1
        if budget[0] <= 0 or len(found) >= max_cycles or len(path) > max_len:
            return
        for nxt in adj.get(node, []):
            if nxt == start:
                kinds = {g["nodes"][n]["kind"] for n in path}
                acts_on_stock = "stock" in kinds or any(g["nodes"][n].get("touches") for n in path)
                if acts_on_stock and "agent" in kinds:
                    key = tuple(path)
                    if key not in seen:
                        seen.add(key)
                        found.append(list(path))
            elif index.get(nxt, -1) > index[start] and nxt not in on_path:
                path.append(nxt)
                on_path.add(nxt)
                dfs(start, nxt, path, on_path)
                path.pop()
                on_path.discard(nxt)

    for s in order:
        dfs(s, s, [s], {s})
    found.sort(key=len)
    return found


def _signs(g: dict, weights: dict[str, int] | None = None) -> dict[tuple[str, str], str]:
    """The sign between two nodes: +, −, or ? when parallel mechanisms disagree. A sign is
    structural; when a pair carries both a + and a − mechanism the link is indeterminate
    from structure, and ``dominant`` says which the window's event counts favour."""
    by_pair: dict[tuple[str, str], list[dict]] = {}
    for e in g["edges"]:
        by_pair.setdefault((e["src"], e["dst"]), []).append(e)
    out: dict[tuple[str, str], str] = {}
    for k, es in by_pair.items():
        signs = {e["sign"] for e in es}
        out[k] = signs.pop() if len(signs) == 1 else "?"
    return out


def dominant(g: dict, pair: tuple[str, str], weights: dict[str, int] | None = None) -> str | None:
    """For an indeterminate link, the sign the window's events favour, if any."""
    w = weights or {}
    es = [e for e in g["edges"] if (e["src"], e["dst"]) == pair and e["via"]]
    weighted = [(w.get(plain(e["via"]), 0), e["sign"]) for e in es]
    if not weighted or max(n for n, _ in weighted) == 0:
        return None
    return max(weighted, key=lambda t: t[0])[1]


def material(g: dict, cycle: list[str], hidden: set[str] | None = None) -> str | None:
    """Judged on the path: every stock on the cycle is filled by the agent before it and
    drained by the agent after it, by different agents. "material circuit" when the event
    that drains each stock is the event that fills the next (the same thing moves on);
    "co-flow" when the stocks are carried by different events (a defect inside a change);
    None otherwise. Either way the circuit is a stock-flow chain, not a causal loop."""
    stocks_on = [n for n in cycle if not n.startswith("agent:")]
    if len(stocks_on) < 2:
        return None                                           # one stock and its agents is a controller, not a circuit of material
    n = len(cycle)
    same_event, chain = True, True
    for i, node in enumerate(cycle):
        if node.startswith("agent:"):
            continue
        prev, nxt = cycle[i - 1], cycle[(i + 1) % n]
        if prev == nxt:
            return None                                   # one agent filling and draining one stock is a controller, not a circuit
        fills = [e for e in g["edges"] if e["kind"] == "fills" and e["src"] == prev and e["dst"] == node]
        drains = [e for e in g["edges"] if e["kind"] == "drains" and e["src"] == nxt and e["dst"] == node] + [c for c in g.get("carries", []) if c["src"] == nxt and c["dst"] == node]   # a carrying link moves the thing on too
        if not (fills and drains):
            chain = False                                 # a stock read or merely woken from: not a stock-flow chain here
            continue
        # the draining event must fill the stock after the next agent for the same thing to move on
        after = cycle[(i + 2) % n]
        carried = any(e["kind"] == "fills" and e["src"] == nxt and e["dst"] == after and any(plain(d["via"]) == plain(e["via"]) for d in drains) for e in g["edges"])
        if not carried:
            same_event = False
    on_hidden = any(s in (hidden or set()) for s in stocks_on)
    if chain and same_event:
        return "material circuit"
    if chain and on_hidden:
        return "co-flow"                                      # a defect rides inside a change through the hidden stock
    if hidden and not on_hidden and discovery_closed(g, cycle, hidden):
        return "discovery"                                    # closed by an event that drains the hidden stock: balancing through it, which the graph cannot sign
    return None                                               # otherwise the links are signed


def discovery_closed(g: dict, cycle: list[str], hidden: set[str]) -> bool:
    """Is a link of the cycle an event that drains the hidden stock (a discovery), carried by
    an agent into the next node? Such a cycle is the found defect's circuit (a ticket filed
    for what the base check or the build turned up), a co-flow of the change, not a causal
    loop; the hidden stock itself is off the path because nothing is woken by its inflow."""
    discovery = {plain(e["via"]) for e in g["edges"] if e["kind"] == "drains" and e["dst"] in hidden and e.get("via")}
    links = set(zip(cycle, cycle[1:] + cycle[:1]))
    return any((e["src"], e["dst"]) in links and e["src"].startswith("agent:") and e.get("via") and plain(e["via"]) in discovery and e["kind"] in ("wakes", "inspects", "triggers", "departs", "fills")
               for e in g["edges"])


def polarity(g: dict, cycle: list[str], weights: dict[str, int] | None = None, hidden: set[str] | None = None) -> tuple[str | None, str]:
    """(polarity, basis). A conserved material circuit has no causal polarity (Sterman: a
    circuit of conserved material is not a causal loop) and is reported as such. Otherwise
    the product of the link signs: B when negative, R when positive, ? when any link is
    indeterminate from structure (the basis then names the sign the window favours)."""
    kind = material(g, cycle, hidden)
    if kind == "discovery":
        return None, "closes through a discovery, so its balancing runs through undiscovered rework, which the graph cannot see: no polarity is claimed"
    if kind:
        return None, kind
    signs = _signs(g, weights)
    pairs = list(zip(cycle, cycle[1:] + cycle[:1]))
    if any(signs.get(p, "+") == "?" for p in pairs):
        notes = []
        for p in pairs:
            if signs.get(p, "+") != "?":
                continue
            es = [e for e in g["edges"] if (e["src"], e["dst"]) == p and e["via"]]
            w = weights or {}
            seen = [f"{e['via']} ({e['sign']}, {w.get(plain(e['via']), 0)} seen)" for e in es]
            notes.append(f"{p[0].replace('agent:', '')}→{p[1].replace('agent:', '')}: " + ", ".join(seen))
        dom = {p: dominant(g, p, weights) for p in pairs if signs.get(p, "+") == "?"}
        if all(dom.values()) and len(cycle) > 2:                  # the window decides on a longer loop: the mechanism seen most carries the link's sign; a pair is its drain's
            resolved = {**{p: signs.get(p, "+") for p in pairs}, **dom}
            neg = sum(1 for p in pairs if resolved[p] == "-")
            return ("B" if neg % 2 else "R"), "link signs, with " + "; ".join(notes) + " resolved by the window's dominant mechanism"
        return "?", "indeterminate: mechanisms disagree on " + "; ".join(notes)
    neg = sum(1 for p in pairs if signs.get(p, "+") == "-")
    # a negative that comes only from a departure (an event that drained a stock elsewhere and woke
    # the next agent) is not a causal link on this path: the balancing lives in the stock's pair
    # with the agent that drained it, so the cycle is closed but its polarity is not structural
    only_departs = neg > 0 and all(any(e["kind"] == "departs" for e in g["edges"] if (e["src"], e["dst"]) == p) for p in pairs if signs.get(p, "+") == "-")
    if only_departs:
        drained = sorted({f"{e['dst']} ↔ {e['src'].replace('agent:', '')}" for p in pairs for e in g["edges"] if (e["src"], e["dst"]) == p and e["kind"] == "departs" for e2 in [e]})
        return "?", "closed; the balancing is in the first-order pair of the drained stock and its agent, not on this path"
    return ("B" if neg % 2 else "R"), "link signs"


def signature(cycle: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(cycle)).encode()).hexdigest()[:10]


def members(cycle: list[str], g: dict | None = None) -> set[str]:
    out = {n.split(":", 1)[1] if n.startswith("agent:") else n for n in cycle}
    if g:
        for n in cycle:
            out.update(g["nodes"].get(n, {}).get("touches", []))
    return out


def detect(stocks: list, agents: dict, expected: list | None = None, system: dict | None = None, weights: dict[str, int] | None = None, evidence: dict[str, int] | None = None) -> dict[str, Any]:
    """The loops in the project. ``expected`` are the model's loop declarations (anything with
    ``key``, ``nodes`` and ``polarity``); each is matched to the shortest cycle whose members
    cover its nodes. ``weights`` are event counts by type (and type:filter) over the window,
    used to sign parallel links by their dominant mechanism."""
    g = build(stocks, agents, system)
    stock_keys = {s.key for s in stocks}
    hidden_keys = {s.key for s in stocks if getattr(s, "hidden", False)}
    # short cycles first, in passes of growing length, so the pairs and the small loops are never pushed out by the
    # budget that bounds the long ones
    cycles, seen_sigs = [], set()
    for max_len in (4, 6, 8, 10, MAX_LEN):
        for c in elementary_cycles(g, max_len=max_len):
            if signature(c) not in seen_sigs:
                cycles.append(c)
                seen_sigs.add(signature(c))
        # each pass has its own budget: a crowded short pass never hides the long loops (the discovery
        # loop runs eleven nodes once every stock that drains the hidden stock inspects it)
    sg = _signs(g, weights)
    ev = evidence or {}
    infos = []
    for c in cycles:
        pol, basis = polarity(g, c, weights, {s.key for s in stocks if getattr(s, "hidden", False)})
        # observed: every agent→stock link on the cycle has been seen in the log (the agent
        # caused that event in the window); a cycle closable by declaration alone is not
        # observed: on every step of the cycle, at least one of its mechanisms was seen in the
        # window: an agent's event attributed to it, or a wake/trigger whose event occurred
        evidence: dict[str, int] = {}
        step_seen = []
        for a, b in zip(c, c[1:] + c[:1]):
            es = [e for e in g["edges"] if e["src"] == a and e["dst"] == b]
            hits = []
            for e in es:
                if e["kind"] in ("fills", "drains") and e["via"]:
                    n = ev.get(f"{a.split(':', 1)[1]}|{plain(e['via'])}", 0) or ev.get(f"orchestra|{e['via']}", 0)   # the step happened when Orchestra made the transition (a block when the worker stopped): the circuit ran (round 32)
                elif e["kind"] in ("wakes", "inspects", "triggers", "departs") and e["via"]:
                    n = (weights or {}).get(plain(e["via"]), 0)
                else:
                    n = sum(v for k, v in ev.items() if k.startswith(b.split(":", 1)[1] + "|")) if e["kind"] == "reads" and b.startswith("agent:") else 0
                evidence[f"{a}>{b}|{e['via'] or e['kind']}"] = n
                hits.append(n)
            step_seen.append(any(n > 0 for n in hits))
        if len(c) == 2 and pol == "?":
            ag_, st_ = (c[0], c[1]) if c[0].startswith("agent:") else (c[1], c[0])
            if weights and dominant(g, (ag_, st_), weights) == "+":
                pol, basis = "?", f"{ag_.replace('agent:', '')} filled {st_} more than it drained it in the window: not acting as its controller (round 31)"
            else:
                pol, basis = "B", "first-order: the drain controls the stock; a wake on arrival carries no sign"
        infos.append({"nodes": c, "members": sorted(members(c, g)), "polarity": pol, "basis": basis, "signature": signature(c), "length": len(c),
                      "pair": len(c) == 2,          # one stock and the agent that fills or drains it: every stock has these
                      "observed": bool(step_seen) and all(step_seen) and not any(n in hidden_keys for n in c),   # a stock nobody can see cannot make a cycle observed "evidence": evidence,
                      "edges": [{"src": a, "dst": b, "sign": None if basis in ("material circuit", "co-flow") else sg.get((a, b), "+")} for a, b in zip(c, c[1:] + c[:1])]})
    declared, used = [], set()
    for lp in expected or []:
        want = set(lp.get("nodes", []) if isinstance(lp, dict) else (lp.nodes or []))
        sig = getattr(lp, "signature", None) if not isinstance(lp, dict) else lp.get("signature")
        pol = getattr(lp, "polarity", None) if not isinstance(lp, dict) else lp.get("polarity")
        key = getattr(lp, "key", None) if not isinstance(lp, dict) else lp.get("key")
        best = next((ci for ci in infos if ci["signature"] == sig), None) if sig else None
        if best is None and want:
            want_stocks = {w for w in want if w in stock_keys}
            cands = [ci for ci in infos if want <= set(ci["members"]) and want_stocks <= set(ci["nodes"]) and len(ci["nodes"]) <= len(want) + LOOP_SLACK]   # the loop's own structure: every declared stock on its path, not merely touched
            as_nodes = lambda ci: sum(1 for w in want if w in ci["nodes"] or f"agent:{w}" in ci["nodes"])   # declared members present on the path, not merely touched
            best = max(cands, key=lambda ci: (as_nodes(ci), -ci["length"])) if cands else None
        if best:
            used.add(best["signature"])
        declared.append({"key": key, "detected": best is not None, "cycle": best, "claimed_polarity": pol,
                         "polarity_agrees": (best["polarity"] == pol) if best and pol and best["polarity"] in ("B", "R") else None})
    for d, lp in zip(declared, expected or []):
        if not d["detected"]:
            d["gaps"] = gaps(g, (lp.get("nodes", []) if isinstance(lp, dict) else (lp.nodes or [])), stocks)
    unnamed, seen_members, uncounted = [], set(), []
    for ci in infos:
        key = tuple(ci["members"])
        if ci["signature"] in used or ci["pair"] or key in seen_members:
            continue
        seen_members.add(key)
        # a cycle nobody declared is a path through agent nodes, not a causal loop: no polarity is claimed for it;
        # only short cycles the log has seen are worth a Supervisor's naming, the rest are counted
        if ci["length"] <= 6 and ci["observed"]:
            unnamed.append({**ci, "polarity": None, "basis": "path (polarity is only computed for declared loops and first-order pairs)"})
        else:
            uncounted.append(ci["signature"])
    # first-order pairs: a stock and an agent that drains it (the balancing structure); agent-only pairs are triggers, not loops
    pairs = [ci for ci in infos if ci["pair"] and any(not n.startswith("agent:") for n in ci["nodes"])
             and any(e["kind"] == "drains" and {e["src"], e["dst"]} == set(ci["nodes"]) for e in g["edges"])]
    return {"graph": g, "cycles": infos, "declared": declared, "unnamed": unnamed, "pairs": pairs, "unlisted": len(uncounted)}


BUILTIN_EVENT_PREFIXES = ("ticket_", "gate_", "staging_", "pipeline_", "session_", "turn_", "agent_", "milestone_", "capacity_", "pickup_", "loop_", "probe_", "context_", "role_", "team_", "note_")


def _declarable(evs: list[str], for_custom: bool) -> list[str]:
    """Events a custom agent may be told to emit: never Orchestra's own (invariant 4)."""
    return [e for e in evs if not (for_custom and e.split(":")[0].startswith(BUILTIN_EVENT_PREFIXES))]


def gaps(g: dict, nodes: list[str], stocks: list) -> dict[str, Any]:
    """Why an expected loop is not closed: members missing from the graph, and consecutive
    members with no link between them, each with the binding that would close it."""
    ids = [n if n in g["nodes"] else f"agent:{n}" for n in nodes]
    stock_by = {s.key: s for s in stocks}
    missing = [n for n, i in zip(nodes, ids) if i not in g["nodes"]]
    links = {(e["src"], e["dst"]) for e in g["edges"]}
    broken = []
    for (a, ia), (b, ib) in zip(list(zip(nodes, ids)), list(zip(nodes[1:] + nodes[:1], ids[1:] + ids[:1]))):
        if ia not in g["nodes"] or ib not in g["nodes"] or (ia, ib) in links:
            continue
        if not ia.startswith("agent:") and not ib.startswith("agent:"):
            # two stocks in a row: some agent woken by (or reading) the first and filling the second closes the step
            via_agent = any((ia, m) in links and (m, ib) in links for m in g["nodes"] if m.startswith("agent:"))
            if via_agent:
                continue
        if ia.startswith("agent:") and not ib.startswith("agent:"):
            st = stock_by.get(b)
            custom = not g["nodes"][ia].get("builtin")
            ok = _declarable(st.inflows, custom) if st else []
            fix = (f"{a} must emit an event that fills {b}" + (f" (one of: {', '.join(ok)})" if ok else f"; {b} is filled only by Orchestra's own events, so declare a custom inflow on {b} (a team's emits) and have {a} emit it"))
        elif not ia.startswith("agent:") and ib.startswith("agent:"):
            st = stock_by.get(a)
            fix = (f"{a} → {b} is Orchestra's own pickup or wiring; no binding of a project agent closes it" if g["nodes"][ib].get("builtin")
                   else f"{b} must wake on an event that fills {a}" + (f" (one of: {', '.join(st.inflows)})" if st and st.inflows else "") + f", or {a} must list {b} as a consumer")   # Orchestra's processes are never advice
        elif ia.startswith("agent:"):
            fix = f"{a} must emit an event {b} wakes on"
        else:
            st_b = stock_by.get(b)
            woken = sorted(e["dst"].split(":", 1)[1] for e in g["edges"] if e["kind"] == "wakes" and e["src"] == ia)
            custom = [n for n in woken if not g["nodes"].get(f"agent:{n}", {}).get("builtin")]
            woken = custom                       # only the project's own agents are ever told to change; Orchestra's processes are never advice
            wants = f" (one of: {', '.join(st_b.inflows)})" if st_b and st_b.inflows else ""
            ok = _declarable(st_b.inflows, True) if st_b else []
            wants = f" (one of: {', '.join(ok)})" if ok else (f"; {b} is filled only by Orchestra's own events, so declare a custom inflow on {b} first" if st_b and st_b.inflows else "")
            if woken:
                fix = (f"{', '.join(woken)} {'is' if len(woken) == 1 else 'are'} woken by {a}'s inflow but emit{'s' if len(woken) == 1 else ''} nothing that fills {b}{wants}: "
                       f"declare the event on the team first (update_team emits=[...]), then update_agent emits=[...], and tell the agent in its role prompt to call emit_event when it has done the work")
            else:
                fix = f"no agent converts {a} into {b}: create an agent woken by {a}'s inflow that emits {b}'s inflow{wants}"
        broken.append({"from": a, "to": b, "fix": fix})
    return {"missing_members": missing, "missing_links": broken}



def att_keys(att: dict, agent: str) -> set[str]:
    return {k.split("|", 1)[1] for k in att if k.startswith(agent + "|")}


def conversions(g: dict, attributed: dict[str, int] | None = None, stocks: list | None = None) -> list[dict]:
    """The flows: an agent that drains one stock and fills another by the same event moves
    the thing from one to the next; with the day's count attributed to that agent and the
    event a new agent on the same flow would wake on."""
    out, seen = [], set()
    att = attributed or {}
    additions = {s.key for s in (stocks or []) if getattr(s, "addition", False)}   # capability stocks are filled, not converted into
    hidden = {s.key for s in (stocks or []) if getattr(s, "hidden", False)}
    loss = {s.key for s in (stocks or []) if getattr(s, "loss", False)}
    row = {s.key: getattr(s, "row", None) for s in (stocks or [])}
    causes_of = {s.key: (["no_verdict", "lost", "conflict"] if getattr(s, "loss", False) else ["defect", "gate"] if any(e.get("kind") in ("known_rework", "pending_defects") for e in (getattr(s, "estimators", None) or [])) else None) for s in (stocks or [])}
    for e in [*g["edges"], *[{**c, "kind": "drains"} for c in g.get("carries", [])]]:
        if e["kind"] != "drains" or not e["src"].startswith("agent:"):
            continue
        for f in g["edges"]:
            if f["kind"] == "fills" and f["src"] == e["src"] and f["dst"] != e["dst"] and f["dst"] not in additions and e["dst"] not in additions and plain(f["via"]) == plain(e["via"]):
                if e.get("to") and f["dst"] != e["to"]:
                    continue                                          # a carrying event delivers to the stock the model names
                if (e["dst"] in hidden and f["dst"] in loss) or (f["dst"] in hidden and e["dst"] in loss):
                    continue                                          # a send-back with no verdict finds nothing: no defect leaves the hidden stock for a loss stock
                key = (e["dst"], f["dst"], e["src"])
                if key in seen:
                    continue
                seen.add(key)
                agent = e["src"].split(":", 1)[1]
                count = att.get(f"{agent}|{e['via']}") if e["via"] in att_keys(att, agent) else att.get(f"{agent}|{plain(e['via'])}")
                # a flow into a stock that splits send-backs by cause is counted by those causes; when the agent on the pipe moved none of
                # them and Orchestra did, the valve is the turn limit (a review turn that ended, a gate run that timed out)
                valve = agent
                cs = causes_of.get(f["dst"]) or causes_of.get(e["dst"])
                if cs:
                    by = lambda who: sum(att.get(f"{who}|{e['via']}|cause:{c}", att.get(f"{who}|{plain(e['via'])}|cause:{c}", 0)) for c in cs)
                    mine, orch = by(agent), by("orchestra")
                    if mine or orch or any(f"{agent}|{e['via']}|cause:" in k or f"{agent}|{plain(e['via'])}|cause:" in k for k in att):
                        count = mine
                        if not mine and orch and agent != "orchestra":
                            valve, count = "turn limit", orch
                elif agent != "orchestra" and not count:
                    orch = att.get(f"orchestra|{e['via']}") if ">" in (e["via"] or "") else None
                    if orch:
                        valve, count = "orchestra", orch                  # the transition happened and Orchestra made it (a block when the worker stopped without a report)
                out.append({"src": e["dst"], "dst": f["dst"], "agent": agent, "valve": valve, "via": plain(e["via"]), "via_full": e["via"], "count": count, "wake": e["via"] if ">" in (e["via"] or "") else f["via"],   # a new agent wakes on the form that leaves this stock (a fix pickup, not every start)
                            "coflow": e["dst"] in hidden or f["dst"] in hidden})       # a defect riding inside a change: drawn beside the change's pipe, never counted twice
    # one event moves one thing: where an agent's event converts along the product's own path (chain row to
    # chain row), the other conversions of that event are the same movement seen from a rework stock, not a second flow
    keep = []
    for c in out:
        same = [o for o in out if o["agent"] == c["agent"] and o["via_full"] == c["via_full"] and not o["coflow"]]   # the same event in the same declared form (OPEN>IN_PROGRESS and REJECTED>IN_PROGRESS are two flows)
        on_path = [o for o in same if row.get(o["src"]) == "chain" and row.get(o["dst"]) == "chain"]
        if c["coflow"] or not on_path or c in on_path:
            keep.append(c)
    out = keep
    return sorted(out, key=lambda c: (c["src"], c["dst"], c["agent"]))
