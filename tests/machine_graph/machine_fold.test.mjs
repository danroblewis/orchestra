// The Machines page's folded machines (orchestra/web/static/machine-fold.js): announced only, or
// hidden by the owner, off the cards and the map with every line that names them; the map shows
// them again when asked; "Hide all of these" is one control naming them all.
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const MachineFold = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/machine-fold.js"));
const MachineGraph = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/machine-graph.js"));

const m = (id, extra = {}) => ({ id, publishes: [], subscribes: [], hidden: null, announced_only: false, ...extra });
const d = {
  machines: [m("orchestra-host", { bootstrap: true, announced_only: false }), m("worker", { publishes: [{ type: "T", count: 2, day: 2 }] }),
    m("person.u1", { announced_only: true, subscribes: ["T"] }), m("person.u2", { announced_only: true, hidden: { provenance: { via: "page" } } }),
    m("gate", { hidden: { provenance: { via: "page" } }, subscribes: ["T"] })],
  handoffs: [{ from: "worker", via: "T", to: "gate", count: 1, day: 1 }, { from: "worker", via: "T", to: "worker", count: 1, day: 1 }],
  relays: [{ from: "worker", via: "T", through: "gate", through_via: "U", to: "worker", count: 1, day: 1 }],
  counted: [{ machine: "gate", channel: "c", direction: "in" }], intended_edges: [{ from: "T", to: "person.u1", kind: "subscribes" }],
  hubs: [{ hub: "gate", members: ["worker"] }],
};

test("a machine is folded as hidden (which wins) or announced only; the host never", () => {
  const s = MachineFold.split(d.machines);
  assert.deepEqual(s.shown.map((x) => x.id), ["orchestra-host", "worker"]);
  assert.deepEqual(s.announced.map((x) => x.id), ["person.u1"]);
  assert.deepEqual(s.hidden.map((x) => x.id), ["person.u2", "gate"]);
  assert.equal(MachineFold.why({ id: "orchestra-host", bootstrap: true, hidden: {} }), null);
});

test("the map leaves folded machines out with every line that names them, unless asked", () => {
  const f = MachineFold.forMap(d, false);
  assert.deepEqual(f.machines.map((x) => x.id), ["orchestra-host", "worker"]);
  assert.deepEqual(f.handoffs.map((h) => h.to), ["worker"]);
  assert.deepEqual(f.relays, []); assert.deepEqual(f.counted, []); assert.deepEqual(f.intended_edges, []); assert.deepEqual(f.hubs, []);
  const g = MachineGraph.graph(f, { showAll: true });
  assert.ok(!g.nodes.some((n) => ["m:person.u1", "m:person.u2", "m:gate"].includes(n.id)));
  assert.ok(!g.links.some((l) => l.target === "m:gate" || l.target === "m:person.u1"));
  assert.equal(MachineFold.forMap(d, true), d, "shown on the map when asked");
  const back = { ...d, machines: d.machines.map((x) => (x.id === "person.u1" ? { ...x, announced_only: false } : x)) };
  assert.ok(MachineFold.forMap(back, false).machines.some((x) => x.id === "person.u1"), "it returns once it acts");
});

test("hide one, show one, hide all in one control", () => {
  assert.deepEqual(MachineFold.body("ignore", ["a"]), { control: "ignore", part: "machine", id: "a", page: "machines", from: "machine card" });
  assert.deepEqual(MachineFold.body("unignore", ["a"]).control, "unignore");
  const all = MachineFold.body("ignore", ["a", "b"]);
  assert.deepEqual(all.keys, ["a", "b"]); assert.equal(all.id, undefined); assert.equal(all.from, "announced only, never acted");
});
