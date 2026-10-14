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


def _split(ev: str) -> tuple[str, str]:
    t, _, suffix = ev.partition(":")
    return t, suffix


def event_fits(declared: str, emitted: str) -> bool:
    """A stock's inflow/outflow or an agent's wake rule against an emitted event type: the
    types match and either side's suffix is empty or they are equal."""
    dt, ds = _split(declared)
    et, es = _split(emitted)
    return dt == et and (not ds or not es or ds == es)


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
    - wakes: an agent wakes on an event that is a stock's inflow (the arrival, +) or, when
      no stock has it as an inflow, a stock's outflow (the departure, −)
    - triggers: an agent emits an event another agent wakes on and no stock carries (+)
    - reads: a stock names the agent as a consumer, with the declared effect sign
    """
    ags = _agents_from(agents, system)
    nodes: dict[str, dict] = {s.key: {"id": s.key, "kind": "stock", "name": s.name, "hidden": bool(getattr(s, "hidden", False))} for s in stocks}
    for name, a in ags.items():
        nodes[f"agent:{name}"] = {"id": f"agent:{name}", "kind": "agent", "name": name, "builtin": a["builtin"], "team": a["team"]}
    edges: list[dict] = []
    seen: set[tuple] = set()

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
                if any(event_fits(i, ev) for i in s.inflows):
                    add(aid, s.key, "+", "fills", ev)
                if any(event_fits(o, ev) for o in s.outflows):
                    add(aid, s.key, "-", "drains", ev)
        for w in a["wake_on"]:
            fills = [s for s in stocks if any(event_fits(i, w) or event_fits(w, i) for i in s.inflows)]
            if fills:
                for s in fills:
                    add(s.key, aid, "+", "wakes", w)
            else:
                for s in stocks:
                    if any(event_fits(o, w) or event_fits(w, o) for o in s.outflows):
                        add(s.key, aid, "-", "wakes", w)
    # an agent whose action wakes another agent directly, by an event no stock carries
    for name, a in ags.items():
        for ev in a["emits"]:
            if any(event_fits(i, ev) for s in stocks for i in s.inflows):
                continue
            for other, b in ags.items():
                if other != name and any(event_fits(w, ev) for w in b["wake_on"]):
                    add(f"agent:{name}", f"agent:{other}", "+", "triggers", ev)
    for s in stocks:
        for c in getattr(s, "consumers", []) or []:
            name, effect = (c, "+") if isinstance(c, str) else (c.get("agent"), c.get("effect", "+"))
            if f"agent:{name}" in nodes:
                add(s.key, f"agent:{name}", effect, "reads", "")
    return {"nodes": nodes, "edges": edges}


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
                if "stock" in kinds and "agent" in kinds:
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


def _signs(g: dict) -> dict[tuple[str, str], str]:
    """The sign between two nodes. An agent that both fills a stock and emits an event that
    drains it is counted as filling it: the drain is its own failure mode (a deploy that
    fails), not a control link. Otherwise a − link wins over a +."""
    fills = {(e["src"], e["dst"]) for e in g["edges"] if e["kind"] == "fills"}
    out: dict[tuple[str, str], str] = {}
    for e in g["edges"]:
        k = (e["src"], e["dst"])
        if k in fills:
            out[k] = "+"
        else:
            out[k] = "-" if e["sign"] == "-" or out.get(k) == "-" else "+"
    return out


def polarity(g: dict, cycle: list[str]) -> str:
    """B when the product of the link signs is negative, R when positive."""
    signs = _signs(g)
    neg = sum(1 for a, b in zip(cycle, cycle[1:] + cycle[:1]) if signs.get((a, b), "+") == "-")
    return "B" if neg % 2 else "R"


def signature(cycle: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(cycle)).encode()).hexdigest()[:10]


def members(cycle: list[str]) -> set[str]:
    return {n.split(":", 1)[1] if n.startswith("agent:") else n for n in cycle}


def detect(stocks: list, agents: dict, expected: list | None = None, system: dict | None = None) -> dict[str, Any]:
    """The loops in the project. ``expected`` are the model's loop declarations (anything with
    ``key``, ``nodes`` and ``polarity``); each is matched to the shortest cycle whose members
    cover its nodes."""
    g = build(stocks, agents, system)
    cycles = elementary_cycles(g)
    sg = _signs(g)
    infos = [{"nodes": c, "members": sorted(members(c)), "polarity": polarity(g, c), "signature": signature(c), "length": len(c),
              "pair": len(c) == 2,          # one stock and the agent that fills or drains it: every stock has these
              "edges": [{"src": a, "dst": b, "sign": sg.get((a, b), "+")} for a, b in zip(c, c[1:] + c[:1])]} for c in cycles]
    declared, used = [], set()
    for lp in expected or []:
        want = set(getattr(lp, "nodes", None) or lp.get("nodes", []))
        sig = getattr(lp, "signature", None) if not isinstance(lp, dict) else lp.get("signature")
        pol = getattr(lp, "polarity", None) if not isinstance(lp, dict) else lp.get("polarity")
        key = getattr(lp, "key", None) if not isinstance(lp, dict) else lp.get("key")
        best = next((ci for ci in infos if ci["signature"] == sig), None) if sig else None
        if best is None and want:
            cands = [ci for ci in infos if want <= set(ci["members"])]
            best = min(cands, key=lambda ci: ci["length"]) if cands else None
        if best:
            used.add(best["signature"])
        declared.append({"key": key, "detected": best is not None, "cycle": best, "claimed_polarity": pol, "polarity_agrees": (best["polarity"] == pol) if best and pol else None})
    for d, lp in zip(declared, expected or []):
        if not d["detected"]:
            d["gaps"] = gaps(g, getattr(lp, "nodes", None) or lp.get("nodes", []), stocks)
    unnamed = [ci for ci in infos if ci["signature"] not in used and not ci["pair"]]
    pairs = [ci for ci in infos if ci["pair"]]
    return {"graph": g, "cycles": infos, "declared": declared, "unnamed": unnamed, "pairs": pairs}


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
        if ia.startswith("agent:") and not ib.startswith("agent:"):
            st = stock_by.get(b)
            fix = f"{a} must emit an event that fills {b}" + (f" (one of: {', '.join(st.inflows)})" if st and st.inflows else f"; declare an inflow event on {b} and have {a} emit it")
        elif not ia.startswith("agent:") and ib.startswith("agent:"):
            st = stock_by.get(a)
            fix = f"{b} must wake on an event that fills {a}" + (f" (one of: {', '.join(st.inflows)})" if st and st.inflows else "") + f", or {a} must list {b} as a consumer"
        elif ia.startswith("agent:"):
            fix = f"{a} must emit an event {b} wakes on"
        else:
            st_b = stock_by.get(b)
            woken = sorted(e["dst"].split(":", 1)[1] for e in g["edges"] if e["kind"] == "wakes" and e["src"] == ia)
            custom = [n for n in woken if not g["nodes"].get(f"agent:{n}", {}).get("builtin")]
            woken = custom or woken              # the project's own agent is the one to change
            wants = f" (one of: {', '.join(st_b.inflows)})" if st_b and st_b.inflows else ""
            if woken:
                fix = f"{', '.join(woken)} {'is' if len(woken) == 1 else 'are'} woken by {a}'s inflow but emit{'s' if len(woken) == 1 else ''} nothing that fills {b}{wants}: add that event to the agent's emits (and to its team's emits if it is custom)"
            else:
                fix = f"no agent converts {a} into {b}: create an agent woken by {a}'s inflow that emits {b}'s inflow{wants}"
        broken.append({"from": a, "to": b, "fix": fix})
    return {"missing_members": missing, "missing_links": broken}

