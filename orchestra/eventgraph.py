"""The binding graph: who causes which events and who is woken by them, and the feedback
loops in it.

Nodes are agents (``agent:<name>``), system parts (``sys:orchestra``, ``sys:merge_gate``,
``sys:probes``), probes (``probe:<name>``), and events (``ev:<type>`` or
``ev:<type>:<filter>``). Edges run emitter → event → subscriber, plus direct agent → agent
edges for messages (a lead to its members, a member to its lead, the Supervisor to anyone),
which Orchestra delivers as wake-ups without an event. Observed edges come from the event
log: an agent that caused an event, a message that was actually sent.

Feedback loops are the elementary cycles of this graph (a cycle that visits no node twice).
A strongly connected component may hold several of them sharing nodes: those are the
subloops, and they are reported individually, with a stable signature so a loop can be
named once and recognised again."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .agents.roles import SYSTEM_BINDINGS
from .config import Project
from .org import AgentDef, TeamDef, all_agents, all_teams, effective_tools, teams_led_by
from .roles import all_roles

# What a tool group lets an agent cause. These are the loop's and the stores' events, raised
# when the agent calls the tool, so they are "may cause" edges on the declared graph.
TOOL_CAUSES = {
    "tickets": ("ticket_created", "ticket_updated", "note_added", "ticket_transition:CANCELLED", "ticket_transition:OPEN",
                "milestone_created", "milestone_closed"),
    "context": ("context_updated",), "capacity": ("capacity_changed",), "pipeline": ("pipeline_resumed", "staging_restarted"),
    "roles": ("role_created", "agent_created", "team_created", "agent_paused", "agent_resumed", "agent_reset"),
}

MAX_CYCLES = 300         # reported (grouped into loops by member set)
COUNTED = ("emits", "may_emit", "observed", "wakes", "messages")   # edges a loop may run along; "latent" never, "escalates" is the supervision loop
MAX_CYCLE_LEN = 12       # searched
SEARCH_CAP = 5000        # safety valve for a pathological graph


@dataclass
class Graph:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)

    def node(self, nid: str, kind: str, label: str | None = None, **extra: Any) -> None:
        self.nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label or nid, **extra})

    def edge(self, a: str, b: str, kind: str, **extra: Any) -> dict:
        for e in self.edges:
            if e["from"] == a and e["to"] == b and e["kind"] == kind and e.get("filter") == extra.get("filter"):
                return e
        e = {"from": a, "to": b, "kind": kind, **extra}
        self.edges.append(e)
        return e


def _split(w: str) -> tuple[str, str | None]:
    t, _, f = w.partition(":")
    return t, f or None


def _ev(g: Graph, t: str, f: str | None, custom: bool = False) -> str:
    nid = f"ev:{t}:{f}" if f else f"ev:{t}"
    g.node(nid, "event", f if (f and t == "ticket_transition") else (f"{t}:{f}" if f else t), type=t, filter=f, custom=custom)
    return nid


def build(project: Project, agents: dict[str, AgentDef] | None = None, teams: dict[str, TeamDef] | None = None,
          observed: dict | None = None) -> Graph:
    """The declared graph, with observed counts folded in when given
    (``observed = {"by": {agent: {type[:variant]: n}}, "messages": {(by, agent): n}}``)."""
    agents = agents if agents is not None else all_agents(project)
    teams = teams if teams is not None else all_teams(project)
    roles = all_roles(project)
    g = Graph()
    custom_types = {e for t in teams.values() for e in t.emits}
    for sid, sb in SYSTEM_BINDINGS.items():
        g.node("sys:" + sid, "system", sid.replace("_", " "), description=sb["description"])
        for e in sb["emits"]:
            t, f = _split(e)
            g.edge("sys:" + sid, _ev(g, t, f), "emits", filter=f)
        for w in sb["wake_on"]:
            t, f = _split(w)
            g.edge(_ev(g, t, f), "sys:" + sid, "wakes", filter=f, loop=True)
    for tm in teams.values():
        for pr in tm.probes or []:
            g.node("probe:" + pr["name"], "probe", pr["name"], team=tm.name)
            for e in ("probe_failed", "probe_recovered"):
                g.edge("probe:" + pr["name"], _ev(g, e, pr["name"]), "emits", filter=pr["name"])
    for ag in agents.values():
        g.node("agent:" + ag.name, "agent", ag.name, team=ag.team, builtin=ag.builtin, kind_of=ag.kind, resident=ag.resident)
    for ag in agents.values():
        me = "agent:" + ag.name
        for w in ag.wake_on:
            t, f = _split(w)
            g.edge(_ev(g, t, f, t in custom_types), me, "wakes", filter=f, loop=ag.builtin)
        for e in ag.emits:
            t, f = _split(e)
            g.edge(me, _ev(g, t, f), "emits", filter=f)
        if ag.team and ag.team in teams:
            for e in teams[ag.team].emits:
                g.edge(me, _ev(g, e, None, True), "may_emit", filter=None)
        # What its tools let it cause is latent until the log shows it happened: drawn faintly,
        # never counted as a loop. Escalation is a real edge to the Supervisor.
        tools = effective_tools(ag, roles, teams)
        for grp in tools:
            for e in TOOL_CAUSES.get(grp, ()):
                t, f = _split(e)
                if not any(x["from"] == me and x["to"] == (f"ev:{t}:{f}" if f else f"ev:{t}") for x in g.edges):
                    g.edge(me, _ev(g, t, f), "latent", filter=f)
        if "escalate" in tools and "supervisor" in agents and ag.name != "supervisor":
            g.edge(me, "agent:supervisor", "escalates")
        # messages: the tree the API enforces, drawn as direct edges. A lead briefs or notes
        # its members and they report to it; the loop starts built-in per-ticket agents, so
        # nobody messages those. The Supervisor can reach anyone, which is drawn only when it
        # happened (observed), and escalations are a reporting channel, not a loop.
        for tm in teams_led_by(teams, ag.name):
            for m in tm.agents:
                if m != ag.name and m in agents and not (agents[m].builtin and not agents[m].resident):
                    g.edge(me, "agent:" + m, "messages")
                    g.edge("agent:" + m, me, "messages")
            if tm.parent and tm.parent in teams and teams[tm.parent].lead in agents:
                g.edge(me, "agent:" + teams[tm.parent].lead, "messages")
    if observed:
        for who, types in (observed.get("by") or {}).items():
            if who not in agents:
                continue
            for key, n in types.items():
                t, f = _split(key)
                if t == "agent_messaged":
                    continue
                hits = [e for e in g.edges if e["from"] == "agent:" + who and e["to"] in (f"ev:{t}:{f}" if f else f"ev:{t}", f"ev:{t}")]
                if hits:
                    for e in hits:
                        e["seen"] = e.get("seen", 0) + n
                        if e["kind"] == "latent":
                            e["kind"] = "observed"            # the log proved the capability is used
                else:
                    g.edge("agent:" + who, _ev(g, t, f, t in custom_types), "observed", filter=f, seen=n)
        for (who, to), n in (observed.get("messages") or {}).items():
            if who in agents and to in agents:
                e = g.edge("agent:" + who, "agent:" + to, "messages")
                e["seen"] = e.get("seen", 0) + n
    return g


def elementary_cycles(g: Graph, max_cycles: int = MAX_CYCLES, max_len: int = MAX_CYCLE_LEN) -> list[list[str]]:
    """Simple cycles, each reported once starting from its smallest node id, shortest first.
    A feedback loop passes through at least one event: two agents messaging each other is
    a conversation, not a loop, and escalations to the Supervisor are reports. Bounded,
    because the graph is small and a wall of cycles would not be read anyway."""
    adj: dict[str, list[str]] = {n: [] for n in g.nodes}
    for e in g.edges:
        if e["kind"] in COUNTED and e["from"] in adj and e["to"] in adj:
            if e["to"] not in adj[e["from"]]:
                adj[e["from"]].append(e["to"])
    found: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for start in sorted(adj):
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        while stack and len(found) < SEARCH_CAP:
            node, path = stack.pop()
            for nxt in adj[node]:
                if nxt == start:
                    key = tuple(path)
                    if key not in seen and any(n.startswith("ev:") for n in path) and len([n for n in path if not n.startswith("ev:")]) >= 1:
                        seen.add(key)
                        found.append(list(path))
                elif nxt > start and nxt not in path and len(path) < max_len:
                    stack.append((nxt, path + [nxt]))
    found = [c for c in found if any(n.startswith("agent:") for n in c)]        # a loop with no agent in it is the loop's own bookkeeping
    found.sort(key=lambda c: (len(c), c))
    return found[:max_cycles]


def signature(cycle: list[str]) -> str:
    """Stable identity of a loop: its agent and system members, order-free."""
    members = sorted(n for n in cycle if not n.startswith("ev:"))
    return hashlib.sha256("|".join(members).encode()).hexdigest()[:12]


def describe(g: Graph, cycle: list[str]) -> dict:
    labels = [g.nodes[n]["label"] for n in cycle]
    agents = [g.nodes[n]["label"] for n in cycle if not n.startswith("ev:")]
    return {"signature": signature(cycle), "nodes": cycle, "labels": labels, "agents": agents,
            "self": len(agents) == 1, "length": len(cycle)}


# -- loops: the hierarchy ---------------------------------------------------------------------

CORE = "core"
CORE_NODES_CACHE: dict[int, set[str]] = {}


def loops(g: Graph) -> list[dict]:
    """Feedback loops as subgraphs, in two levels.

    The **core** is the loop baked into Orchestra: every cycle whose members are all built-in
    agents or system parts (worker, reviewer, merge gate, the loop itself). Its cycles are
    merged into one subgraph with branches: APPROVED or REJECTED out of the reviewer, DONE or
    REJECTED out of the gate.

    Every other loop is found with the core contracted to one node, so a custom loop reads
    "keeper → ticket_created → core → REJECTED → retrospective → keeper": one trip out and
    back. Cycles that differ only in which event carries them are variants of one loop,
    keyed by the agents in it. Loops that never touch the core stand on their own."""
    cycles = elementary_cycles(g)
    # The core is the per-ticket pipeline: the agents the loop starts per ticket and the
    # system parts. Resident built-ins (the Coordinator, the Pipeline Manager) plan around it
    # and get their own loops through it, like any custom agent.
    is_core_node = lambda n: n.startswith("sys:") or (n.startswith("agent:") and g.nodes[n].get("builtin") and not g.nodes[n].get("resident"))
    core_cycles = [c for c in cycles if all(is_core_node(n) for n in c if not n.startswith("ev:"))]
    core_nodes: set[str] = set().union(*[set(c) for c in core_cycles]) if core_cycles else set()
    CORE_NODES_CACHE[id(g)] = core_nodes
    out: list[dict] = []
    if core_cycles:
        out.append(_loop(g, "core", sorted(core_nodes), core_cycles, core=True))
    # contract the core and look again
    alias = {n: CORE for n in core_nodes}
    adj: dict[str, set[str]] = {}
    for e in g.edges:
        if e["kind"] not in COUNTED:
            continue
        a, b = alias.get(e["from"], e["from"]), alias.get(e["to"], e["to"])
        if a != b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set())
    found: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for start in sorted(adj):
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        while stack and len(found) < SEARCH_CAP:
            node, path = stack.pop()
            for nxt in sorted(adj.get(node, ())):
                if nxt == start:
                    key = tuple(path)
                    if key not in seen and any(n.startswith("ev:") or n == CORE for n in path) and any(n.startswith("agent:") for n in path):
                        seen.add(key)
                        found.append(list(path))
                elif nxt > start and nxt not in path and len(path) < MAX_CYCLE_LEN:
                    stack.append((nxt, path + [nxt]))
    groups: dict[str, list[list[str]]] = {}
    for c in found:
        key = "|".join(sorted(n for n in c if not n.startswith("ev:")))
        groups.setdefault(key, []).append(c)
    for key, cs in groups.items():
        cs.sort(key=len)
        agents = [n for n in key.split("|")]
        nodes = sorted(set().union(*[set(c) for c in cs]))
        out.append(_loop(g, "outer" if CORE in agents else "independent", nodes, cs, core=False))
    # A loop whose outer agents are covered by smaller loops is a composition of them, which
    # carries no information of its own; and a single agent woken by what it causes is a
    # one-shot, not feedback. Neither is reported.
    outer = [L for L in out if not L["core"]]
    keep = []
    for L in outer:
        mine = set(L["agents"]) - {"delivery loop (core)"}
        if len(mine) < 1 or (L["kind"] == "independent" and len(mine) < 2):
            continue
        parts = [set(M["agents"]) - {"delivery loop (core)"} for M in outer if M is not L and (set(M["agents"]) - {"delivery loop (core)"}) < mine]
        if parts and (any(a | b >= mine for i, a in enumerate(parts) for b in parts[i + 1:]) or any(mine <= a for a in parts)):
            continue
        keep.append(L)
    out = [L for L in out if L["core"]] + keep
    # supervision: every agent that can escalate, the Supervisor, and what it does in return.
    # One loop with a human in it, not a variant on every other loop.
    esc = sorted({e["from"] for e in g.edges if e["kind"] == "escalates"})
    if esc and "agent:supervisor" in g.nodes:
        sup_actions = sorted({g.nodes[e["to"]]["label"] for e in g.edges if e["from"] == "agent:supervisor" and e["to"].startswith("ev:") and e["kind"] != "latent"})
        members = sorted({g.nodes[n]["label"] for n in esc} | {"supervisor"})
        out.append({"kind": "supervision", "core": False, "signature": hashlib.sha256("|".join(members).encode()).hexdigest()[:12],
                    "agents": members, "nodes": esc + ["agent:supervisor"], "edges": [f"{n}>agent:supervisor" for n in esc],
                    "cycles": len(esc), "labels": [g.nodes[n]["label"] for n in esc] + ["supervisor"], "length": len(esc) + 1, "self": False,
                    "triggers": ["escalate_to_supervisor"], "actions": sup_actions, "paths": [], "composite": False})
    out.sort(key=lambda L: (not L["core"], L["kind"] == "supervision", L["kind"] == "independent", L["length"]))
    return out


def possible_loops(g: Graph) -> list[dict]:
    """The loops that would exist if every latent edge (a tool an agent has but has not been
    seen to use) fired. The ones not among the real loops are the design's intent that the
    log has not confirmed."""
    g2 = Graph(nodes=dict(g.nodes), edges=[{**e, "kind": "may_emit"} if e["kind"] == "latent" else dict(e) for e in g.edges])
    return loops(g2)


def _loop(g: Graph, kind: str, nodes: list[str], cycles: list[list[str]], core: bool) -> dict:
    label = lambda n: "delivery loop (core)" if n == CORE else g.nodes[n]["label"]
    agents = sorted({label(n) for n in nodes if not n.startswith("ev:")})
    shortest = min(cycles, key=len)
    edges = sorted({f"{c[i]}>{c[(i + 1) % len(c)]}" for c in cycles for i in range(len(c))})
    # The trip out and back, read from the agents' own bindings: a trigger is an event that
    # wakes a loop agent and is caused by someone in the loop (the core included); an action
    # is an event a loop agent causes that wakes someone in the loop.
    outer = {n for n in nodes if (n.startswith("agent:") or n.startswith("sys:")) and n != CORE}
    members = outer | (CORE_NODES_CACHE.get(id(g), set()) if CORE in nodes else set())
    causes = {}
    for e in g.edges:
        if e["kind"] in ("emits", "observed", "may_emit", "latent") and e["to"].startswith("ev:"):
            causes.setdefault(e["to"], set()).add(e["from"])
    wakes_of = {}
    for e in g.edges:
        if e["kind"] == "wakes":
            wakes_of.setdefault(e["from"], set()).add(e["to"])
    triggers = sorted({label(e["from"]) for e in g.edges if e["kind"] == "wakes" and e["to"] in outer and causes.get(e["from"], set()) & members}) if not core else []
    actions = sorted({label(e["to"]) for e in g.edges if e["kind"] in ("emits", "observed", "may_emit") and e["from"] in outer
                      and wakes_of.get(e["to"], set()) & members}) if not core else []
    return {"kind": kind, "core": core, "signature": hashlib.sha256("|".join(agents).encode()).hexdigest()[:12],
            "agents": agents, "nodes": nodes, "edges": edges, "cycles": len(cycles),
            "labels": [label(n) for n in shortest], "length": len(shortest), "self": len(agents) == 1,
            "triggers": triggers, "actions": actions, "paths": [[label(n) for n in c] for c in cycles[:12]]}
