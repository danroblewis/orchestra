// Subsystems drawn as boxes in the Dynamics diagram (orchestra/web/static/subsystem-boxes.js;
// docs/proposals/subsystems.md B10–B14): a box per group, crossing flows between boxes with each
// pair's count, the unassigned and the machines in two groups outside every box, a focus on a box
// cutting to it with stubs, the default on at open. Run: node --test tests/subsystems/subsystems.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static");
const Boxes = require(path.join(STATIC, "subsystem-boxes.js"));
const SDGraph = require(path.join(STATIC, "sd-graph.js"));
const Focus = require(path.join(STATIC, "focus.js"));
const NetGeometry = require(path.join(STATIC, "netgraph-geometry.js"));

// two workflows (delivery: a1, a2; hotfix: b1, b2) and a stock no workflow label names (disk)
const stock = (id, labels) => ({ id, name: id, series: { name: "items_" + id, labels }, evidence: {}, tags: labels.workflow ? [`workflow=${labels.workflow}`] : [] });
const flow = (id, from, to, extra = {}) => ({ id, from, to, counter: { name: "moves_total", labels: { from: from || "<start>", to: to || "<end>" } },
  current: { form: "constant", params: { c: 0.1 }, quality: { events: 20 }, origin: "fitted" }, machines: [], evidence: {}, ...extra });
const MODEL = {
  stocks: [stock("a1", { workflow: "delivery", step: "write" }), stock("a2", { workflow: "delivery", step: "review" }),
           stock("b1", { workflow: "hotfix", step: "write" }), stock("b2", { workflow: "hotfix", step: "review" }), stock("disk", {})],
  flows: [flow("in_a1", null, "a1"), flow("a1_a2", "a1", "a2"), flow("a2_b1", "a2", "b1"), flow("sim", "b2", "a1", { evidence: { simulated: true } }),
          flow("b1_b2", "b1", "b2"), flow("b2_out", "b2", null), flow("disk_a1", "disk", "a1")],
  machines: [{ id: "planner", name: "planner", attributed: [] }, { id: "worker", name: "worker", attributed: [] }],
};
// as sd/subsystems.py reports it (model.subsystems)
const WF = { label: "workflow",
  groups: [{ value: "delivery", stocks: ["a1", "a2"], flows: ["in_a1", "a1_a2"], machines: ["planner"] },
           { value: "hotfix", stocks: ["b1", "b2"], flows: ["b1_b2", "b2_out"], machines: [] }],
  unassigned: { stocks: ["disk"], flows: ["disk_a1"], machines: [] },
  crossing: [{ between: ["delivery", "hotfix"], flows: ["a2_b1", "sim"], count: 1, simulated: 1, simulated_flows: ["sim"] }],
  spanning: [{ machine: "worker", groups: ["delivery", "hotfix"] }], joined: 2, crossed: 1, crossed_simulated: 1 };
const STEP = { label: "step", groups: [{ value: "review", stocks: ["a2", "b2"], flows: [], machines: [] }, { value: "write", stocks: ["a1", "b1"], flows: [], machines: [] }],
  unassigned: { stocks: ["disk"], flows: [], machines: [] }, crossing: [{ between: ["review", "write"], flows: ["a1_a2", "a2_b1", "b1_b2"], count: 3, simulated: 0, simulated_flows: [] }],
  spanning: [], joined: 0, crossed: 3, crossed_simulated: 0 };
const SUBS = { default: "workflow", partitions: [STEP, WF] };

const drawn = () => { const g = SDGraph.build(MODEL); return Boxes.apply(g.nodes, g.edges, Boxes.choose(SUBS, null)); };

test("the page opens with the default partition on; the control lists it first, each named with its boxes and crossings, then off", () => {
  assert.equal(Boxes.choose(SUBS, null).label, "workflow", "nothing chosen: the default");
  assert.equal(Boxes.choose(SUBS, "step").label, "step");
  assert.equal(Boxes.choose(SUBS, "off"), null);
  assert.equal(Boxes.choose(SUBS, "gone").label, "workflow", "a label no longer reported: the default");
  assert.equal(Boxes.choose({ default: null, partitions: [] }, null), null, "no partition: no boxes");
  assert.deepEqual(Boxes.choices(SUBS).map((c) => c.text), ["workflow · 2 boxes · 1 crossing (1 simulated)", "step · 2 boxes · 3 crossing", "off"]);
  assert.deepEqual(Boxes.choices(SUBS).map((c) => c.value), ["workflow", "step", "off"], "only what the API reports, and off");
});

test("a box per group: each stock in its group's box, the unassigned stock and the clouds in none", () => {
  const r = drawn(), box = (id) => r.nodes.find((n) => n.id === id).box;
  assert.deepEqual(r.boxes, ["delivery", "hotfix"]);
  assert.equal(box("s:a1"), "delivery"); assert.equal(box("s:a2"), "delivery");
  assert.equal(box("s:b1"), "hotfix"); assert.equal(box("s:b2"), "hotfix");
  assert.equal(box("s:disk"), undefined, "unassigned: outside every box, inside the frame");
  for (const n of r.nodes.filter((x) => x.kind === "cloud")) assert.equal(n.box, undefined, `${n.id}: a cloud is the environment, never in a box`);
  assert.deepEqual(r.outside.stocks, ["disk"]);
});

test("crossing flows are drawn box to box, the simulated dashed, the pair's count written between", () => {
  const r = drawn(), byFid = (fid) => r.edges.find((e) => e.fid === fid);
  assert.deepEqual(byFid("a2_b1").cross, ["delivery", "hotfix"]);
  assert.deepEqual(byFid("sim").cross, ["hotfix", "delivery"], "in its own direction");
  assert.ok(byFid("sim").dash && !byFid("a2_b1").dash, "a simulated crossing is dashed");
  assert.ok(byFid("a2_b1").label.includes("delivery → hotfix"), "its ends named by their boxes");
  assert.equal(byFid("a1_a2").cross, undefined, "inside a box: not crossing");
  assert.equal(byFid("disk_a1").cross, undefined, "touching the unassigned: not crossing");
  assert.deepEqual(r.pairs.map((p) => p.text), ["1 flow between delivery and hotfix · 1 simulated"]);
});

test("machines in two subsystems are outside every box, said so", () => {
  const r = drawn();
  assert.deepEqual(r.outside.machines, [{ machine: "worker", groups: ["delivery", "hotfix"] }]);
  assert.equal(Boxes.spanText(r.outside.machines[0]), "in two subsystems (delivery, hotfix): outside the boxes");
  const s = Boxes.sections(WF);
  assert.deepEqual(s.groups.map((g) => [g.value, g.machines]), [["delivery", ["planner"]], ["hotfix", []]], "a machine in one group is listed with it");
  assert.deepEqual(s.outside.spanning.map((x) => x.machine), ["worker"]);
  assert.deepEqual(s.between.map((b) => b.text), ["1 flow between delivery and hotfix · 1 simulated"]);
  assert.deepEqual(s.outside.stocks, ["disk"]);
});

test("the partition label's tag is left off parts inside their box and kept on the unassigned (B14)", () => {
  const g = SDGraph.build(MODEL), r = Boxes.apply(g.nodes, g.edges, WF);
  const tags = (id) => ((r.nodes.find((n) => n.id === id).tags) || []).map((t) => t.text);
  assert.ok(((g.nodes.find((n) => n.id === "s:a1").tags) || []).some((t) => t.text === "workflow=delivery"), "drawn without boxes");
  assert.ok(!tags("s:a1").includes("workflow=delivery"), "said once, by the box's title");
  const byStep = Boxes.apply(g.nodes, g.edges, STEP);
  assert.ok(((byStep.nodes.find((n) => n.id === "s:a1").tags) || []).some((t) => t.text === "workflow=delivery"), "another label's tag stays");
});

test("an auxiliary is in a box only when every rate that reads it is inside that box", () => {
  const nodes = [{ id: "s:a1", sid: "a1", kind: "box" }, { id: "s:a2", sid: "a2", kind: "box" }, { id: "s:b1", sid: "b1", kind: "box" },
    { id: "i:load", input: "load", kind: "box" }, { id: "i:cpu", input: "cpu", kind: "box" }];
  const edges = [{ id: "f1", source: "s:a1", target: "s:a2", fid: "a1_a2", flowPart: true }, { id: "f2", source: "s:a2", target: "s:b1", fid: "a2_b1", flowPart: true },
    { id: "i1", source: "i:load", toEdge: "f1" }, { id: "i2", source: "i:cpu", toEdge: "f1" }, { id: "i3", source: "i:cpu", toEdge: "f2" }];
  const r = Boxes.apply(nodes, edges, WF), box = (id) => r.nodes.find((n) => n.id === id).box;
  assert.equal(box("i:load"), "delivery");
  assert.equal(box("i:cpu"), undefined, "read by a crossing flow too: outside every box");
});

test("a focus on a box (its title's offer) cuts the diagram to it, the box kept, what crosses its edge a grey stub named for its box", () => {
  const r = drawn(), o = Boxes.offers(WF).find((x) => x.title === "hotfix");
  assert.equal(o.row, false, "its chip is the box's title, not one more in the row");
  const f = Focus.normal({ ...o.get(), title: o.title });
  const cut = Focus.dynamics(r.nodes, r.edges, Focus.resolve(MODEL, f), { name: (n) => (n.box != null ? `${n.label} · in ${n.box}` : n.label) });
  const stocks = cut.nodes.filter((n) => n.sid);
  assert.deepEqual(stocks.map((n) => n.sid).sort(), ["b1", "b2"]);
  assert.ok(stocks.every((n) => n.box === "hotfix"), "the box is kept as the frame of what is shown");
  const stubs = cut.nodes.filter((n) => n.stub);
  assert.ok(stubs.length >= 1 && stubs.every((s) => s.box === undefined && /· in delivery$/.test(s.label)), `stubs say the box they lead to: ${stubs.map((s) => s.label)}`);
  assert.deepEqual(NetGeometry.boxesOf(cut.nodes.map((n, i) => ({ ...n, x: i * 300, y: 0 }))).hotfix.members.sort(), ["s:b1", "s:b2"]);
});

test("the hash carries boxes= beside focus= and a part's id; each partition keeps its own layout key", () => {
  assert.equal(Boxes.fromHash("#s:a1&boxes=step&focus=x"), "step");
  assert.equal(Boxes.fromHash("#s:a1"), null);
  assert.equal(Boxes.hashWith("off", "#s:a1&focus=x"), "#boxes=off&s:a1&focus=x");
  assert.equal(Focus.hashId("#boxes=step&focus=x"), "", "boxes= is not a part's id");
  assert.equal(Focus.hashWith("s:a1", "#boxes=step&focus=x"), "#s%3Aa1&boxes=step&focus=x");
  assert.equal(Boxes.layoutKey("dynamics.v2", WF), "dynamics.v2|boxes=workflow");
  assert.equal(Boxes.layoutKey("dynamics.v2", null), "dynamics.v2");
});

test("a box is the hull of its members and their tags, with room for its title; the frame holds every box", () => {
  const nodes = [{ id: "s:a", sid: "a", kind: "box", w: 180, h: 92, box: "x", x: 100, y: 100 }, { id: "s:b", sid: "b", kind: "box", w: 180, h: 92, box: "x", x: 400, y: 100 },
    { id: "c", kind: "cloud", box: "x", x: 900, y: 100 }];
  const b = NetGeometry.boxesOf(nodes).x;
  assert.deepEqual(b.members, ["s:a", "s:b"], "a cloud is never a member");
  assert.ok(b.x0 < 10 && b.x1 > 490 && b.y0 < 54 - NetGeometry.BOX_TITLE);
  const f = NetGeometry.frameOf(nodes, (n) => n.kind !== "cloud");
  assert.ok(f.x0 < b.x0 && f.y0 < b.y0 && f.x1 > b.x1 && f.y1 > b.y1);
});

test("a box's offer is the core's own: no chip in the row, toggled from the box's title, withdrawn with the boxes (its focus cleared)", () => {
  const g = { location: { pathname: "/dynamics", search: "", hash: "#boxes=workflow&focus=hotfix" }, history: { replaceState(_, __, url) { g.location.hash = url.includes("#") ? url.slice(url.indexOf("#")) : ""; } },
    document: { dispatchEvent: () => {} }, CustomEvent: class { constructor(t, o) { this.detail = o && o.detail; } } };
  Object.assign(globalThis, g);
  const Orchestra = {};
  Focus.install(Orchestra);
  for (const o of Boxes.offers(WF)) Orchestra.focus.offer(o);
  assert.equal(Orchestra.focus.current().title, "hotfix", "a link with focus=hotfix is restored once the box is offered");
  assert.deepEqual(Orchestra.focus.current().stocks, ["b1", "b2"]);
  assert.equal(g.location.hash, "#boxes=workflow&focus=hotfix", "boxes= stays beside focus=");
  const row = { isConnected: true, dataset: {}, innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
  Orchestra.focus.offer({ title: "a plugin's", get: () => ({}) });
  Orchestra.focus.mount(row, null);
  assert.ok(row.innerHTML.includes("a plugin&#39;s") || row.innerHTML.includes("a plugin's"), "a plugin's offer is a chip in the row");
  assert.ok(!row.innerHTML.includes('data-title="hotfix"') && !row.innerHTML.includes('data-title="delivery"'), "a box's offer is not");
  Orchestra.focus.toggle("delivery");
  assert.equal(Orchestra.focus.current().title, "delivery", "its title toggles it");
  Orchestra.focus.withdraw("delivery");
  assert.equal(Orchestra.focus.current(), null, "boxes turned off: the focus on a box goes with it");
  assert.ok(!Orchestra.focus.offers().some((o) => o.title === "delivery"));
});
