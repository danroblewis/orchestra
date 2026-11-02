// The Machines page's event map (orchestra/web/static/machine-graph.js): a listener edge is observed
// only through a hand-off, an announced listener that received none stays a declared listener, and
// communication (and its cycles) is made of observed hand-offs only.
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const MachineGraph = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/machine-graph.js"));
const Loops = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/loops.js"));

const machine = (id, publishes, subscribes) => ({ id, publishes: publishes.map((type) => ({ type, count: 5, day: 5 })), subscribes });
// A publishes T; B and C listen for T; B replies with U, which A listens for
const machines = [machine("A", ["T"], ["U"]), machine("B", ["U"], ["T"]), machine("C", [], ["T"])];
const AtoB = { from: "A", via: "T", to: "B", count: 3, day: 3 };
const BtoA = { from: "B", via: "U", to: "A", count: 2, day: 2 };
const view = (handoffs) => MachineGraph.graph({ machines, handoffs }, { showAll: true });
const edge = (g, a, b) => g.links.find((l) => l.source === a && l.target === b);
const cycles = (g) => { const ch = MachineGraph.chains(g.links).filter((c) => c.observed);
  return Loops.analyse(g.nodes.filter((n) => n.machine).map((n) => n.id), ch, { exchanges: true }); };

test("a listener edge is observed only when a hand-off through the type reached that machine", () => {
  const g = view([AtoB]);
  const b = edge(g, "ev:T", "m:B"), c = edge(g, "ev:T", "m:C");
  assert.equal(b.declaredListener, false); assert.equal(b.observed, 3); assert.equal(b.inferred, false);
  assert.equal(c.declaredListener, true, "C announced T, nothing was handed to it: a declared listener");
  assert.equal(c.observed, 0);
  assert.equal(edge(g, "ev:U", "m:A").declaredListener, true, "B never replied");
});

test("machine → machine chains through a declared listener are drawn but are not communication", () => {
  const ch = MachineGraph.chains(view([AtoB]).links);
  const of = (a, b) => ch.find((c) => c.source === "m:" + a && c.target === "m:" + b);
  assert.equal(of("A", "B").observed, true);
  assert.equal(of("A", "C").observed, false);
  assert.equal(of("B", "A").observed, false);
});

test("a hand-off through the same type from another publisher does not make this one's chain observed", () => {
  const ms = [...machines, machine("D", ["T"], [])];
  const ch = MachineGraph.chains(MachineGraph.graph({ machines: ms, handoffs: [{ from: "D", via: "T", to: "C", count: 1, day: 1 }] }, { showAll: true }).links);
  assert.equal(ch.find((c) => c.source === "m:D" && c.target === "m:C").observed, true);
  assert.equal(ch.find((c) => c.source === "m:A" && c.target === "m:C").observed, false, "C's offers came from D, not A");
});

test("the cycle A → B → A counts only once B's reply was observed", () => {
  assert.equal(cycles(view([AtoB])).exchanges.length, 0);
  assert.equal(cycles(view([])).exchanges.length, 0, "announcements alone make no cycle");
  const r = cycles(view([AtoB, BtoA]));
  assert.equal(r.exchanges.length, 1);
  assert.deepEqual([...r.exchanges[0].nodes].sort(), ["m:A", "m:B"]);
});

test("a hand-off through a type the receiver never announced is an inferred, observed edge", () => {
  const g = view([{ from: "B", via: "U", to: "C", count: 1, day: 1 }]);
  const l = edge(g, "ev:U", "m:C");
  assert.equal(l.inferred, true); assert.equal(l.declaredListener, false);
  assert.equal(MachineGraph.chains(g.links).find((c) => c.source === "m:B" && c.target === "m:C").observed, true);
});

test("event types are grouped only with types their listeners received the same way", () => {
  // A publishes T and T2, B listens for both, a hand-off came through T only: two boxes, not one
  const ms = [machine("A", ["T", "T2"], []), machine("B", [], ["T", "T2"])];
  const g = MachineGraph.graph({ machines: ms, handoffs: [{ from: "A", via: "T", to: "B", count: 1, day: 1 }] }, { showAll: true });
  assert.ok(edge(g, "ev:T", "m:B") && edge(g, "ev:T2", "m:B"));
  assert.equal(edge(g, "ev:T2", "m:B").declaredListener, true);
});

// A hub and three roles alike, as a planner offers work (the owner, 2026-11-01: "most of the agents
// look like they both publish and subscribe to the same events"): H publishes x.made, which every
// role listens for, and listens for x.done, which every role publishes; H also publishes and listens
// for h.closed (its own bookkeeping). P, a person, acts next after R1's x.done and publishes p.opened,
// which Q listens for.
const hubbed = () => {
  const ms = [machine("H", ["x.made", "h.closed"], ["x.done", "h.closed"]), machine("R1", ["x.done"], ["x.made"]),
              machine("R2", ["x.done"], ["x.made"]), machine("R3", [], ["x.made"]), machine("P", ["p.opened"], []), machine("Q", [], ["p.opened"])];
  const intended = [{ machine: "R3", kind: "publishes", type: "x.done" }];     // R3 declared, never yet seen to publish
  const handoffs = [{ from: "H", via: "x.made", to: "R1", count: 2, day: 2 }, { from: "R1", via: "x.done", to: "P", count: 2, day: 2 },
                    { from: "P", via: "p.opened", to: "Q", count: 2, day: 2 }, { from: "R1", via: "x.done", to: "H", count: 1, day: 1 },
                    { from: "H", via: "x.made", to: "R2", count: 1, day: 1 }];
  const relays = [{ from: "R1", via: "x.done", through: "H", through_via: "x.made", to: "R2", count: 1, day: 1 },
                  { from: "Q", via: null, through: "H", through_via: "x.made", to: "R2", count: 1, day: 1 },
                  { from: "P", via: "p.opened", through: "Q", through_via: "q.done", to: "R1", count: 1, day: 1 }];
  return { d: { machines: ms, handoffs, relays }, intended };
};

test("a machine exchanging types both ways with two or more others is a hub; those types are its protocol", () => {
  const { d, intended } = hubbed(), p = MachineGraph.protocol(d, intended);
  assert.deepEqual([...p.hubs.keys()], ["H"]);
  assert.deepEqual([...p.hubs.get("H")].sort(), ["R1", "R2", "R3"], "R3 is a member by its declaration");
  assert.equal(p.is("H", "x.made", "R1"), true);
  assert.equal(p.is("R2", "x.done", "H"), true);
  assert.equal(p.is("H", "h.closed", "H"), true, "the hub's own bookkeeping");
  assert.equal(p.is("R1", "x.done", "P"), false, "a role handing work to a person is no protocol");
  assert.equal(p.is("P", "p.opened", "Q"), false);
  assert.deepEqual(p.families, ["h.*", "x.*"]);
  assert.deepEqual(p.folds.map((f) => [f.member, f.types.join(",")]).sort(), [["R1", "x.done,x.made"], ["R2", "x.done,x.made"], ["R3", "x.done,x.made"]]);
});

test("two machines alone exchanging both ways are no hub: a request and its reply stay drawn", () => {
  const p = MachineGraph.protocol({ machines });
  assert.equal(p.hubs.size, 0);
  assert.equal(p.is("A", "T", "B"), false);
});

test("the map's chains: the protocol is marked, the hub's own loop is never drawn, a hand-off between roles and people is", () => {
  const { d, intended } = hubbed();
  const g = MachineGraph.graph(d, { intended: intended.map((e) => ({ ...e, observed: false })), showAll: true });
  const ch = MachineGraph.chains(g.links), of = (a, b) => ch.find((c) => c.source === "m:" + a && c.target === "m:" + b);
  assert.equal(of("H", "R1").protocol, true);
  assert.equal(of("R1", "H").protocol, true);
  assert.equal(of("H", "H"), undefined, "H publishing and listening for h.closed is no edge to itself");
  assert.equal(of("R1", "P").protocol, false);
  assert.equal(of("R1", "P").observed, true);
  assert.equal(of("P", "Q").protocol, false);
});

test("work handed through a hub's protocol is a hand-off from the one to the other, through the hub", () => {
  const { d, intended } = hubbed(), p = MachineGraph.protocol(d, intended);
  const r = MachineGraph.relays(d, p);
  assert.deepEqual(r.map((x) => [x.source, x.target, x.through]), [["m:R1", "m:R2", "H"], ["m:Q", "m:R2", "H"]],
    "a relay through a machine that is no hub, or not over its protocol, is not one");
});

test("a machine that publishes a type and listens for it has no edge to itself without a hand-off to itself", () => {
  const ms = [machine("S", ["s.step"], ["s.step"])];
  const g = MachineGraph.graph({ machines: ms, handoffs: [] }, { showAll: true });
  assert.equal(MachineGraph.chains(g.links).length, 0, "announced only: no edge to itself");
});

test("roles that pass the hub's own type to each other are its members, not hubs, and what they hand on stays drawn", () => {
  // the task loop: the floor publishes x.made under the role that finished, so W and V exchange it too
  const ms = [machine("C", ["x.made"], ["x.done"]), machine("W", ["x.made", "x.done"], ["x.made"]), machine("V", ["x.made", "x.done"], ["x.made"]), machine("G", ["x.done"], ["x.made"])];
  const p = MachineGraph.protocol({ machines: ms });
  assert.deepEqual([...p.hubs.keys()], ["C"]);
  assert.equal(p.is("W", "x.made", "V"), false, "W hands work to V");
  assert.equal(p.is("C", "x.made", "W"), true);
});

test("the server's hubs, when served, are the page's: one answer for the page and the Supervisor (web/hubs.py)", () => {
  const MG = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/machine-graph.js"));
  const d = { machines: [{ id: "p", publishes: [{ type: "x.made" }], subscribes: ["x.done"] }, { id: "a", publishes: [{ type: "x.done" }], subscribes: ["x.made"] },
    { id: "b", publishes: [{ type: "x.done" }], subscribes: ["x.made"] }] };
  assert.deepEqual([...MG.protocol(d).hubs.keys()], ["p"]);
  assert.deepEqual([...MG.protocol({ ...d, hubs: [] }).hubs.keys()], [], "none served: none drawn");
});
