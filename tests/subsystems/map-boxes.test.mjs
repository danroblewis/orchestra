// Subsystems on the Machines page's event map, and partitions a page extension offers
// (orchestra/web/static/subsystem-boxes.js applyMap, subsystem-offers.js, netgraph-geometry.js
// separateBoxes; docs/proposals/subsystems.md B10, B13, B15, step 3): a box around each group's
// machines, event types inside a box or between, hand-offs crossing with the pair's count, spanning
// and unassigned machines outside every box, ghosts of gathered members, an offered partition listed
// after the API's, drawn, and stored nowhere. Run: node --test tests/subsystems/map-boxes.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static");
const Boxes = require(path.join(STATIC, "subsystem-boxes.js"));
const Offers = require(path.join(STATIC, "subsystem-offers.js"));
const Focus = require(path.join(STATIC, "focus.js"));
const NetGeometry = require(path.join(STATIC, "netgraph-geometry.js"));

// planner, writer (team a) -> reviewer, shipper (team b); helper in both; the host in none
const API = {
  machines: [
    { id: "planner", name: "planner", publishes: [{ type: "plan.made" }], subscribes: [] },
    { id: "writer", name: "writer", publishes: [{ type: "draft.written" }], subscribes: ["plan.made"] },
    { id: "reviewer", name: "reviewer", publishes: [{ type: "review.passed" }], subscribes: ["draft.written"] },
    { id: "shipper", name: "shipper", publishes: [{ type: "item.shipped" }], subscribes: ["review.passed"] },
    { id: "helper", name: "helper", publishes: [], subscribes: ["plan.made"] },
    { id: "orchestra-host", name: "orchestra-host", publishes: [], subscribes: [] }],
  types: ["draft.written", "item.shipped", "plan.made", "review.passed"],
  handoffs: [{ from: "planner", via: "plan.made", to: "writer", count: 3 }, { from: "writer", via: "draft.written", to: "reviewer", count: 3 },
             { from: "reviewer", via: "review.passed", to: "shipper", count: 3 }],
};
// as web/machine_subsystems.py reports it (/api/machines subsystems)
const GROUP = { label: "group", source: "announced", by: "group",
  groups: [{ value: "a", machines: ["planner", "writer"], events: [] }, { value: "b", machines: ["reviewer", "shipper"], events: ["item.shipped", "review.passed"] }],
  unassigned: { machines: ["orchestra-host"], events: ["plan.made"] }, between: [{ type: "draft.written", groups: ["a", "b"] }],
  crossing: [{ between: ["a", "b"], handoffs: [{ from: "writer", via: "draft.written", to: "reviewer", count: 3 }], count: 1, subjects: 3 }],
  spanning: [{ machine: "helper", groups: ["a", "b"] }], joined: 2, crossed: 1, crossed_simulated: 0 };
const DECLARED = { label: "declared", source: "declared", by: "hypotheses",
  groups: [{ value: "line", name: "the line", declared: "line", provenance: { author: "owner", via: "plugin", source: "supervisor" }, machines: ["planner"], events: [],
             ghosts: { machines: ["nobody"] } }],
  unassigned: { machines: [], events: [] }, between: [], crossing: [], spanning: [], joined: 0, crossed: 0, crossed_simulated: 0 };
const SUBS = { default: "group", partitions: [GROUP, DECLARED] };

// the map's nodes and edges as machines.html hands them to NetGraph ("with event types")
const NODES = [...API.machines.map((m) => ({ id: "m:" + m.id, kind: "circle", label: m.id, mid: m.id, machine: true, anchor: [0.2, 0.2] })),
  ...API.types.map((t) => ({ id: "ev:" + t, kind: "box", label: t })), { id: "ch:queue", kind: "box", label: "queue" }];
const EDGES = [["m:planner", "ev:plan.made"], ["ev:plan.made", "m:writer"], ["ev:plan.made", "m:helper"], ["m:writer", "ev:draft.written"],
  ["ev:draft.written", "m:reviewer"], ["m:reviewer", "ev:review.passed"], ["ev:review.passed", "m:shipper"], ["m:shipper", "ev:item.shipped"],
  ["m:writer", "m:reviewer"], ["m:planner", "m:writer"]].map(([source, target]) => ({ id: source + ">" + target, source, target }));

test("a box around each group's machines; event types inside a box only when the API placed them there", () => {
  const r = Boxes.applyMap(NODES, EDGES, GROUP), box = (id) => r.nodes.find((n) => n.id === id).box;
  assert.deepEqual(r.boxes, ["a", "b"]);
  assert.equal(box("m:planner"), "a"); assert.equal(box("m:writer"), "a"); assert.equal(box("m:reviewer"), "b"); assert.equal(box("m:shipper"), "b");
  assert.equal(box("ev:review.passed"), "b", "every machine on it is in b");
  assert.equal(box("ev:draft.written"), undefined, "between the boxes");
  assert.equal(box("ev:plan.made"), undefined, "a machine on it is in two groups: outside every box");
  assert.equal(box("m:helper"), undefined, "in two groups: outside every box");
  assert.equal(box("m:orchestra-host"), undefined, "in none: outside every box");
  assert.equal(box("ch:queue"), undefined, "a channel is in no box");
  assert.deepEqual(r.outside.spanning, [{ machine: "helper", groups: ["a", "b"] }]);
  // a boxed node is pulled to its box's spot, not the announced group's ring anchor
  assert.equal(r.nodes.find((n) => n.id === "m:planner").anchor, undefined);
  const spots = Boxes.anchors(GROUP);
  assert.deepEqual(Object.keys(spots), ["a", "b"]); assert.notDeepEqual(spots.a, spots.b);
});

test("a hand-off between two boxes is drawn across, and each pair's count written between them", () => {
  const r = Boxes.applyMap(NODES, EDGES, GROUP), edge = (id) => r.edges.find((e) => e.id === id);
  assert.deepEqual(edge("m:writer>m:reviewer").cross, ["a", "b"]);
  assert.match(edge("m:writer>m:reviewer").cls, /ng-box-cross/);
  assert.equal(edge("m:planner>m:writer").cross, undefined, "inside one box");
  assert.deepEqual(r.pairs.map((p) => [p.between, p.text, p.short]), [[["a", "b"], "1 hand-off between a and b · 3 subjects", "1 hand-off"]]);
  assert.deepEqual(Boxes.choices(SUBS).map((c) => c.text), ["group · 2 boxes · 4 machines · 1 crossing", "declared · 1 box · 1 machine", "off"]);
  // a group no machine acts only in is a box too, counted, with its line inside
  const one = { ...GROUP, groups: [GROUP.groups[0], { value: "c", machines: [], events: [] }], spanning: [{ machine: "helper", groups: ["a", "c"] }] };
  assert.equal(Boxes.nameOf(one), "group · 2 boxes · 2 machines · 1 crossing");
  const e = Boxes.applyMap(NODES, EDGES, one);
  assert.deepEqual(e.boxes, ["a", "c"], "every group drawn");
  const line = e.nodes.find((n) => n.box === "c");
  assert.equal(line.id, "sub-empty:c"); assert.deepEqual(line.lines, ["no machine acts only here"]); assert.ok(line.inert, "it opens nothing");
  assert.deepEqual(line.subEmpty.acting, ["helper"]);
  assert.equal(Boxes.emptyHint(one, "c"), "no machine acts only here: helper acts here and elsewhere, outside every box");
  assert.match(Boxes.hintOf(one, "c"), /helper acts here and elsewhere/, "named on hover over its title");
  assert.equal(e.nodes.find((n) => n.id === "m:helper").box, undefined, "the machine acting there stays outside");
});

test("a declared subsystem titles its box by its name, says who named it, and draws a gathered machine not on the map as a ghost", () => {
  const r = Boxes.applyMap(NODES, EDGES, DECLARED);
  assert.equal(Boxes.titles(DECLARED)("line"), "the line");
  assert.equal(Boxes.namedBy(DECLARED.groups[0]), "named by the owner (quoted), per supervisor");
  assert.match(Boxes.hintOf(DECLARED, "line"), /named by .* · 1 member no longer here, drawn as ghosts/);
  const ghost = r.nodes.find((n) => n.id === "sub-ghost:m:nobody");
  assert.ok(ghost && ghost.box === "line" && ghost.subGhost, "a ghost in its box");
  assert.deepEqual(Boxes.offers(DECLARED).map((o) => o.title), ["the line"], "the box's focus chip is titled by the name");
  // a label's value a declared subsystem names: the raw value is said on hover only
  const named = { ...GROUP, groups: [{ ...GROUP.groups[0], name: "the writers", declared: "writers", provenance: { author: "owner", via: "page" } }, GROUP.groups[1]] };
  assert.equal(Boxes.titles(named)("a"), "the writers");
  assert.equal(Boxes.hintOf(named, "a"), "named by you · group = a");
  assert.equal(Boxes.pairText(named.crossing[0], Boxes.titles(named)), "1 hand-off between the writers and b · 3 subjects");
});

test("the phone list's sections: a heading per group, then between subsystems, then outside every subsystem", () => {
  const s = Boxes.sections(GROUP);
  assert.deepEqual(s.groups.map((g) => [g.title, g.machines]), [["a", ["planner", "writer"]], ["b", ["reviewer", "shipper"]]]);
  assert.deepEqual(s.between.map((c) => c.text), ["1 hand-off between a and b · 3 subjects"]);
  assert.deepEqual(s.outside.machines, ["orchestra-host"]);
  assert.deepEqual(s.outside.spanning, [{ machine: "helper", groups: ["a", "b"] }]);
  assert.deepEqual(s.groups.map((g) => g.acting), [["helper"], ["helper"]], "who acts in each group and elsewhere, for an empty group's heading");
  assert.ok(s.groups.every((g) => !g.empty), "both hold machines");
  // a group no machine acts only in keeps its heading, saying so and who acts there
  const e = Boxes.sections({ ...GROUP, groups: [...GROUP.groups, { value: "c", machines: [], events: [] }], spanning: [{ machine: "helper", groups: ["a", "c"] }] },
    { name: (id) => id.toUpperCase() });
  assert.deepEqual(e.groups.map((g) => [g.title, !!g.empty]), [["a", false], ["b", false], ["c", true]], "a heading per group, the empty one too");
  assert.equal(e.groups[2].line, "no machine acts only here: HELPER acts here and elsewhere, outside every box");
});

test("boxes kept whole on a force-laid map: overlapping boxes pushed apart, a node not its own pushed out", () => {
  const nodes = [{ id: "m:a1", kind: "circle", label: "a1", box: "a", x: 0, y: 0 }, { id: "m:a2", kind: "circle", label: "a2", box: "a", x: 60, y: 0 },
    { id: "m:b1", kind: "circle", label: "b1", box: "b", x: 80, y: 10 }, { id: "m:x", kind: "circle", label: "x", x: 30, y: 0 }];
  for (let i = 0; i < 200 && NetGeometry.separateBoxes(nodes); i++);
  const hulls = NetGeometry.boxesOf(nodes), A = hulls.a, B = hulls.b;
  assert.ok(A.x1 <= B.x0 || B.x1 <= A.x0 || A.y1 <= B.y0 || B.y1 <= A.y0, "no box over another");
  const x = nodes.find((n) => n.id === "m:x"), s = NetGeometry.size(x);
  for (const H of [A, B]) assert.ok(!(x.x - s.r < H.x1 && H.x0 < x.x + s.r && x.y - s.r < H.y1 && H.y0 < x.y + s.r), "a node of no box is outside every box");
});

// a browser's globals, watched: an offer must be kept in memory only
function browser() {
  const touched = [], events = [];
  const watch = (name) => new Proxy({}, { get: (_, k) => { touched.push(`${name}.${String(k)}`); return () => null; } });
  globalThis.localStorage = watch("localStorage"); globalThis.sessionStorage = watch("sessionStorage"); globalThis.indexedDB = watch("indexedDB");
  globalThis.fetch = (...a) => { touched.push("fetch"); return Promise.resolve(); };
  globalThis.XMLHttpRequest = function () { touched.push("XMLHttpRequest"); };
  globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
  globalThis.document = { dispatchEvent: (e) => events.push(e.type) };
  return { touched, events, done: () => { for (const k of ["localStorage", "sessionStorage", "indexedDB", "fetch", "XMLHttpRequest", "CustomEvent", "document"]) delete globalThis[k]; } };
}

test("an offered partition is listed after the API's, drawn on both pages, and stored nowhere", () => {
  const b = browser();
  try {
    const Orchestra = {};
    Offers.install(Orchestra);
    // the Workflows plugin's shape: one group per definition, machines by id, stocks by their series
    Orchestra.subsystems.offer({ title: "workflows", groups: [
      { title: "drafting", machines: ["planner", "writer"], events: ["plan.made"], stocks: [{ name: "pile_items", labels: { workflow: "drafting", step: "write" } }], flows: [] },
      { title: "shipping", machines: ["reviewer", "shipper"], stocks: ["s2"], flows: [] }] });
    assert.deepEqual(b.events, ["orchestra:subsystems"], "the pages are told, so they redraw");
    assert.deepEqual(Orchestra.subsystems.offers().map((o) => o.title), ["workflows"]);
    assert.equal(Orchestra.subsystems.offers()[0].groups[0].stocks[0], Focus.keyOf({ name: "pile_items", labels: { workflow: "drafting", step: "write" } }), "keyed as a focus keys a series");
    // the event map
    const P = Offers.eventMap(Orchestra.subsystems.offers()[0], API);
    assert.deepEqual(P.groups.map((g) => [g.value, g.machines]), [["drafting", ["planner", "writer"]], ["shipping", ["reviewer", "shipper"]]]);
    assert.equal(P.source, "offered");
    assert.deepEqual(P.crossing.map((c) => [c.between, c.count, c.subjects]), [[["drafting", "shipping"], 1, 3]]);
    assert.deepEqual(P.between, [{ type: "draft.written", groups: ["drafting", "shipping"] }]);
    assert.ok(P.groups[1].events.includes("review.passed") && P.unassigned.events.includes("plan.made"), "helper, in no group, listens for plan.made");
    const cs = Boxes.choices(SUBS, [P]);
    assert.deepEqual(cs.map((c) => c.value), ["group", "declared", "workflows", "off"], "after the API's partitions, before off");
    assert.match(cs[2].text, /offered$/);
    assert.equal(Boxes.choose(SUBS, "workflows", [P]).label, "workflows");
    const r = Boxes.applyMap(NODES, EDGES, P);
    assert.deepEqual(r.boxes, ["drafting", "shipping"], "drawn");
    // the Dynamics diagram
    const model = { stocks: [{ id: "s1", series: { name: "pile_items", labels: { workflow: "drafting", step: "write" } } }, { id: "s2", series: { name: "x", labels: {} } }, { id: "s3", series: null }],
      flows: [{ id: "f12", from: "s1", to: "s2", machines: [{ machine: "writer" }], evidence: {} }, { id: "fin", from: null, to: "s1", machines: [{ machine: "planner" }], evidence: {} }],
      machines: [{ id: "writer", name: "writer" }, { id: "planner", name: "planner" }, { id: "idle", name: "idle" }] };
    const D = Offers.dynamics(Orchestra.subsystems.offers()[0], model);
    assert.deepEqual(D.groups.map((g) => [g.value, g.stocks, g.flows]), [["drafting", ["s1"], ["fin"]], ["shipping", ["s2"], []]]);
    assert.deepEqual(D.crossing.map((c) => [c.between, c.flows, c.count]), [[["drafting", "shipping"], ["f12"], 1]]);
    assert.deepEqual(D.unassigned.stocks, ["s3"]);
    assert.deepEqual(D.unassigned.machines, ["idle"]);
    Orchestra.subsystems.offer({ title: "workflows", groups: Orchestra.subsystems.offers()[0].groups });   // the same again: no redraw
    assert.equal(b.events.length, 1);
    Orchestra.subsystems.withdraw("workflows");
    assert.deepEqual(Orchestra.subsystems.offers(), []);
    assert.deepEqual(b.touched, [], "no storage, no request: display only, stored nowhere");
  } finally { b.done(); }
});

test("the map opens with boxes on by the API's default, every group a box even when every machine is outside; the note says why", () => {
  const WF = { label: "workflow", source: "labels", groups: [{ value: "delivery_sail", machines: [], events: [] }, { value: "pr_watch", machines: [], events: [] }],
    unassigned: { machines: ["orchestra-host"], events: [] }, between: [], crossing: [], joined: 0, crossed: 0, crossed_simulated: 0,
    spanning: ["a", "b", "c", "d", "e", "f"].map((m) => ({ machine: m, groups: ["delivery_sail", "pr_watch"] })) };
  const PLACE = { label: "place", source: "labels", groups: [{ value: "held", machines: [], events: [] }, { value: "waiting", machines: ["a", "b", "c", "d", "e"], events: [] }],
    unassigned: { machines: [], events: [] }, between: [], crossing: [], spanning: [], joined: 0, crossed: 0, crossed_simulated: 0 };
  const subs = { default: "workflow", partitions: [WF, PLACE] };
  const P = Boxes.choose(subs, null);
  assert.equal(P.label, "workflow", "on, by the partition the Dynamics page opens on: never a state such as place chosen instead");
  assert.equal(Boxes.outsideNote(P), "6 machines act in both workflows (delivery_sail, pr_watch): outside every box, so no box holds a machine (a machine belongs to one subsystem only)");
  assert.equal(Boxes.outsideNote(GROUP), "1 machine acts in both groups (a, b): outside every box (a machine belongs to one subsystem only)");
  assert.equal(Boxes.outsideNote(DECLARED), "", "nothing outside to explain");
  assert.deepEqual(Boxes.choices(subs).map((x) => x.text), ["workflow · 2 boxes · 0 machines", "place · 2 boxes · 5 machines", "off"], "the same boxes as the Dynamics page, with how many machines they hold");
  // both boxes drawn side by side, each with its line; the six machines outside them
  const nodes = ["a", "b", "c", "d", "e", "f"].map((m) => ({ id: "m:" + m, kind: "circle", label: m, mid: m, machine: true }));
  const r = Boxes.applyMap(nodes, [], P);
  assert.deepEqual(r.boxes, ["delivery_sail", "pr_watch"]);
  assert.deepEqual(r.nodes.filter((n) => n.subEmpty).map((n) => [n.box, n.subEmpty.acting.length]), [["delivery_sail", 6], ["pr_watch", 6]]);
  assert.ok(r.nodes.filter((n) => n.machine).every((n) => n.box == null), "every machine outside");
  const spots = Boxes.anchors(P);
  assert.equal(spots.delivery_sail[1], spots.pr_watch[1], "beside each other, in one row");
  assert.ok(spots.delivery_sail[0] < spots.pr_watch[0]);
  const four = Boxes.anchors({ groups: ["p", "q", "r", "s"].map((value) => ({ value })) });
  assert.equal(new Set(Object.values(four).map((a) => a[1])).size, 2, "four boxes in two rows");
  assert.equal(Boxes.choose(subs, "place").label, "place", "the owner can choose another");
  assert.equal(Boxes.choose(subs, "off"), null, "or turn them off");
});

test("a focus on an empty box draws it with its line and the machines acting there as stubs joined to it", () => {
  const P = { ...GROUP, groups: [...GROUP.groups, { value: "c", machines: [], events: [] }], spanning: [{ machine: "helper", groups: ["a", "c"] }] };
  const r = Boxes.applyMap(NODES, EDGES, P);
  const offer = Boxes.offers(P).find((o) => o.title === "c"), F = Focus.normal({ title: "c", ...offer.get() });
  const fc = Boxes.focusEmpty(Focus.eventMap(r.nodes, r.edges, F), P, "c", r.nodes);
  assert.ok(fc.nodes.some((n) => n.id === "sub-empty:c"), "the box, with its line");
  const stub = fc.nodes.find((n) => n.stub);
  assert.equal(stub.of, "m:helper"); assert.ok(fc.edges.some((e) => e.source === stub.id && e.target === "sub-empty:c"));
  assert.deepEqual(fc.outside, ["helper"]);
  assert.ok(!fc.nodes.some((n) => n.machine), "no machine inside the focus");
  // any other focus is left as Focus.eventMap cut it
  const Fa = Focus.normal({ title: "a", ...Boxes.offers(P)[0].get() }), cut = Focus.eventMap(r.nodes, r.edges, Fa);
  assert.equal(Boxes.focusEmpty(cut, P, "a", r.nodes), cut);
  assert.ok(!cut.nodes.some((n) => n.subEmpty), "another box's line is not in a focus");
});
