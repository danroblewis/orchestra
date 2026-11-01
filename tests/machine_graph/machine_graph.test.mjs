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
