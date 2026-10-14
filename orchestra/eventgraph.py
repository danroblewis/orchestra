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

MAX_CYCLES = 300         # reported (the UI groups them by member set)
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
        if not ag.builtin:
            for grp in effective_tools(ag, roles, teams):
                for e in TOOL_CAUSES.get(grp, ()):
                    t, f = _split(e)
                    g.edge(me, _ev(g, t, f), "may_emit", filter=f)
            if "escalate" in effective_tools(ag, roles, teams) and "supervisor" in agents:
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
        if e["kind"] in ("emits", "may_emit", "observed", "wakes", "messages") and e["from"] in adj and e["to"] in adj:
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
