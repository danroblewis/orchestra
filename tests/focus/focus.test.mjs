// A focus (orchestra/web/static/focus.js): a sub-graph of the one system shown on its own, what
// crosses its edge drawn to named grey stubs; and the browser's Orchestra.focus (set, clear, offer,
// the hash). Run: node --test tests/focus/focus.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static");
const Focus = require(path.join(STATIC, "focus.js"));
const SDGraph = require(path.join(STATIC, "sd-graph.js"));

// the event map as machines.html hands it to the renderer (machines only): eleven machines, a..k
const IDS = "abcdefghijk".split("");
const machines = IDS.map((id) => ({ id: "m:" + id, kind: "circle", label: id, mid: id, machine: true }));
const link = (a, b) => ({ id: `m:${a}>m:${b}`, source: "m:" + a, target: "m:" + b });
const mapEdges = [link("a", "b"), link("b", "c"), link("c", "a"), link("d", "a"), link("d", "b"), link("c", "e"), link("f", "g"), link("h", "i"), link("j", "k")];

test("a focus of 3 of 11 machines draws those 3, the edges among them, and a stub for each machine handing work in or out", () => {
  const f = Focus.normal({ title: "loop", machines: ["a", "b", "c"] });
  const r = Focus.eventMap(machines, mapEdges, f);
  const drawn = r.nodes.filter((n) => n.machine).map((n) => n.id).sort();
  assert.deepEqual(drawn, ["m:a", "m:b", "m:c"]);
  assert.equal(r.inside, 3); assert.equal(r.total, 11);
  const stubs = r.nodes.filter((n) => n.stub);
  assert.deepEqual(stubs.map((s) => s.id).sort(), ["out:m:d", "out:m:e"], "d hands work in, e takes it out; f, g, h, i, j, k touch nothing inside");
  assert.deepEqual(stubs.map((s) => s.label).sort(), ["d", "e"], "a stub is named");
  assert.ok(stubs.every((s) => s.kind === "cloud" && s.outside));
  const d = stubs.find((s) => s.id === "out:m:d"), e = stubs.find((s) => s.id === "out:m:e");
  assert.ok(d.anchor[0] < 0.5 && e.anchor[0] > 0.5, "handing in at the left edge, taking out at the right");
  assert.deepEqual(r.edges.map((x) => `${x.source}>${x.target}`).sort(),
    ["m:a>m:b", "m:b>m:c", "m:c>m:a", "m:c>out:m:e", "out:m:d>m:a", "out:m:d>m:b"]);
  assert.deepEqual(r.outside.sort(), ["d", "e"]);
});

test("with event types drawn, a type between the focus and a machine outside stays, and the machine is a stub; a type not named is left out", () => {
  const nodes = [...machines, { id: "ev:offer.made", kind: "box", label: "offer.made" }, { id: "ev:audit.done", kind: "box", label: "audit.done" }];
  const edges = [{ id: "m:a>ev:offer.made", source: "m:a", target: "ev:offer.made" }, { id: "ev:offer.made>m:h", source: "ev:offer.made", target: "m:h" },
    { id: "m:b>ev:audit.done", source: "m:b", target: "ev:audit.done" }, { id: "ev:audit.done>m:k", source: "ev:audit.done", target: "m:k" }];
  const all = Focus.eventMap(nodes, edges, Focus.normal({ title: "t", machines: ["a", "b"] }));
  assert.ok(all.nodes.some((n) => n.id === "ev:offer.made") && all.nodes.some((n) => n.id === "ev:audit.done"));
  assert.ok(all.edges.some((x) => x.source === "ev:offer.made" && x.target === "out:m:h"));
  const some = Focus.eventMap(nodes, edges, Focus.normal({ title: "t", machines: ["a", "b"], events: ["offer.made"] }));
  assert.ok(some.nodes.some((n) => n.id === "ev:offer.made") && !some.nodes.some((n) => n.id === "ev:audit.done"));
  assert.ok(!some.nodes.some((n) => n.id === "out:m:k"), "nothing of the type left out reaches k");
});

test("a focus of 2 stocks keeps them, the flow between them, and every flow crossing to another stock as a named stub beside the stock inside", () => {
  const model = JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, "../fixtures/dynamics/bakery-2026-10-25.json"), "utf8")).model;
  const g = SDGraph.build(model);
  // one by its series key (as a plugin names it), one by its id
  const f = Focus.normal({ title: "the line", stocks: ['bakery_orders_waiting{machine="board"}', "bakery_orders_baking"] });
  const ids = Focus.resolve(model, f);
  assert.deepEqual([...ids.stocks].sort(), ["bakery_orders_baking", "bakery_orders_waiting"]);
  const r = Focus.dynamics(g.nodes, g.edges, ids, {});
  const inside = new Set(["s:bakery_orders_waiting", "s:bakery_orders_baking"]);
  assert.deepEqual(r.nodes.filter((n) => n.sid).map((n) => n.id).sort(), [...inside].sort(), "no other stock is drawn");
  assert.equal(r.inside, 2); assert.equal(r.total, g.nodes.filter((n) => n.sid).length);
  const byId = new Map(g.nodes.map((n) => [n.id, n])), cut = new Map(r.edges.map((e) => [e.id, e])), drawn = new Map(r.nodes.map((n) => [n.id, n]));
  let crossing = 0;
  for (const e of g.edges.filter((x) => x.flowPart)) {
    const a = inside.has(e.source), b = inside.has(e.target);
    if (a && b) { assert.equal(cut.get(e.id), e, `${e.id} drawn as it is`); continue; }
    if (!a && !b) { assert.ok(!cut.has(e.id), `${e.id} touches nothing inside`); continue; }
    const other = a ? e.target : e.source, x = cut.get(e.id);
    assert.ok(x, `${e.id} crosses the focus and is drawn`);
    if (!byId.get(other).sid) { assert.equal(a ? x.target : x.source, other, "a cloud or a place stays as it is"); continue; }
    crossing++;
    const s = drawn.get(a ? x.target : x.source);
    assert.ok(s && s.stub && s.kind === "cloud", `${e.id} ends at a stub`);
    assert.equal(s.tether, a ? e.source : e.target, "beside the stock inside");
    assert.equal(s.label, byId.get(other).label, "named for the stock outside");
  }
  assert.ok(crossing >= 2, `${crossing} flows cross to stocks outside`);
  assert.ok(r.outside.length >= 2);
});

test("a focus names the stocks it leaves out, and draws a co-flow's stock as a stub beside its twin's (R3: commits on main dropped silently)", () => {
  const box = (sid) => ({ id: "s:" + sid, sid, kind: "box", label: sid.replace(/_/g, " ") });
  const nodes = [box("review"), box("sail"), box("commits_on_main"), box("other"), { id: "c:out:sail", kind: "cloud" }, { id: "c:in:commits_on_main", kind: "cloud" }];
  const edges = [{ id: "e1", source: "s:review", target: "s:sail", fid: "moves_review_sail", flowPart: true },
    { id: "e2", source: "s:sail", target: "c:out:sail", fid: "moves_sail_end", flowPart: true },
    { id: "e3", source: "c:in:commits_on_main", target: "s:commits_on_main", fid: "moves_sail_end@base", flowPart: true }];
  const r = Focus.dynamics(nodes, edges, { stocks: new Set(["review", "sail"]), flows: new Set() }, {});
  const stub = r.nodes.find((n) => n.stub && n.of === "s:commits_on_main");
  assert.ok(stub && stub.co && stub.tether === "s:sail", "the co-flow's stock is a stub beside sail");
  assert.ok(r.outside.includes("commits on main"));
  assert.deepEqual(r.left, ["other"], "a stock with no stub is named as left out");
});

test("a focus takes a series as {name, labels} and keys it itself", () => {
  const f = Focus.normal({ title: "t", stocks: [{ name: "workflow_pile_items", labels: { step: "write", project: "p", pile: "write.held" } }, "s2"] });
  assert.deepEqual(f.stocks, ['workflow_pile_items{pile="write.held",step="write"}', "s2"]);
});

// the browser's side: a page with a hash, and nothing else
function browser(hash = "") {
  const events = [];
  const g = { location: { pathname: "/machines", search: "", hash }, history: { replaceState(_, __, url) { g.location.hash = url.includes("#") ? url.slice(url.indexOf("#")) : ""; } },
    document: { dispatchEvent: (e) => events.push(e.detail) }, CustomEvent: class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } } };
  Object.assign(globalThis, g);
  const Orchestra = {};
  Focus.install(Orchestra);
  return { Orchestra, events, g };
}

test("set, clear, the hash; clear restores everything; an offer is a chip that sets and clears", () => {
  const { Orchestra, events, g } = browser("#worker");
  Orchestra.focus.set({ title: "delivery_sail", machines: ["a", "b", "c"], reason: "a workflow" });
  assert.equal(Orchestra.focus.current().title, "delivery_sail");
  assert.equal(g.location.hash, "#worker&focus=delivery_sail", "the machine opened stays in the address");
  assert.equal(Focus.hashId(g.location.hash), "worker");
  Orchestra.focus.clear();
  assert.equal(Orchestra.focus.current(), null);
  assert.equal(g.location.hash, "#worker");
  assert.equal(events.length, 2);
  // cleared, the map is drawn whole: the page draws what it computed, uncut
  const offer = { title: "loop", subtitle: "3 steps", get: () => ({ machines: ["a", "b", "c"] }) };
  Orchestra.focus.offer(offer);
  Orchestra.focus.offer(offer);                                    // again: still one
  assert.equal(Orchestra.focus.offers().length, 1);
  Orchestra.focus.toggle("loop");
  assert.deepEqual(Orchestra.focus.current().machines, ["a", "b", "c"]);
  Orchestra.focus.toggle("loop");
  assert.equal(Orchestra.focus.current(), null, "clicked again, it clears");
  Orchestra.focus.update("loop", { subtitle: "2 open" });
  assert.equal(Orchestra.focus.offers()[0].subtitle, "2 open");
});

test("a focus in the address is restored only when an extension offers that title again", () => {
  const { Orchestra } = browser("#focus=loop");
  assert.equal(Orchestra.focus.current(), null, "nothing until offered");
  Orchestra.focus.offer({ title: "other", get: () => ({ machines: ["x"] }) });
  assert.equal(Orchestra.focus.current(), null);
  Orchestra.focus.offer({ title: "loop", get: () => ({ machines: ["a"], stocks: ["k"] }) });
  assert.equal(Orchestra.focus.current().title, "loop");
  assert.deepEqual(Orchestra.focus.current().stocks, ["k"]);
  // offered again with a new subset (its data refreshed): the focus follows it
  Orchestra.focus.offer({ title: "loop", get: () => ({ machines: ["a", "b"] }) });
  assert.deepEqual(Orchestra.focus.current().machines, ["a", "b"]);
});
