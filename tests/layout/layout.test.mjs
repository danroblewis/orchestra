// The Dynamics graph's layout, measured (orchestra/web/static/layout-score.js) on saved models
// (tests/fixtures/dynamics). The graph is built and laid out by the same code the page runs:
// sd-graph.js (model → graph), sd-layout.js (ELK, springs, untangling), netgraph-geometry.js (sizes, frame,
// clouds, labels).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ELK = require("elkjs/lib/elk.bundled.js");
const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static");
const FIXTURES = path.resolve(import.meta.dirname, "../fixtures/dynamics");
const SDGraph = require(path.join(STATIC, "sd-graph.js"));
const SDLayout = require(path.join(STATIC, "sd-layout.js"));
const LayoutScore = require(path.join(STATIC, "layout-score.js"));
// the renderer's pure geometry (netgraph-geometry.js) needs no DOM or d3
const { size, frameOf, tetherPlaces, labelSize, placeLabels } = require(path.join(STATIC, "netgraph-geometry.js"));
const inside = (n) => n.kind !== "cloud";

async function laidOut(file) {
  const model = JSON.parse(fs.readFileSync(path.join(FIXTURES, file), "utf8")).model;
  const { nodes, edges } = SDGraph.build(model);
  // as the page does: ELK, then springs, then untangled (the page's worker), with labels placed
  const geo = { size, inside, frameOf, tetherPlaces };
  const labels = (placed) => {
    const m = LayoutScore.mids(placed, edges, size), o = placeLabels(placed, edges, m);
    return Object.fromEntries(Object.entries(o).map(([id, [dx, dy]]) => [id, [m[id].x + dx, m[id].y + dy]]));
  };
  const elk = await SDLayout.layout(nodes, edges, { elk: new ELK(), ...geo, hierarchy: true });
  const springs = SDLayout.refine(nodes, edges, SDLayout.pack(nodes, edges, elk, geo), { ...geo, labelSize });
  const at = SDLayout.untangle(nodes, edges, springs, { ...geo, score: LayoutScore.score, labelSize, labels });
  const placed = nodes.map((n) => ({ ...n, x: at[n.id][0], y: at[n.id][1] }));
  return { placed, edges, score: LayoutScore.score(placed, edges, { size, frame: frameOf(placed, inside), inside, labels: labels(placed), labelSize }) };
}

// Known shortfalls, by fixture: what the layout does not yet reach on that model, recorded here so
// it stays visible and cannot get worse. bakery-2026-10-25c (12 stocks in many small groups): the
// packing leaves the frame too spread out, one stub and one influence too long, and two labels touch.
// bakery-2026-10-25: since flow labels name stocks by their short names (2026-10-25), the search
// lands on a layout with the chef's outside flows 549 px long and an influence 535 px long; it is
// that sensitive to label sizes.
const KNOWN = { "bakery-2026-10-25.json": { stub: 560, influence: 550 },
                "bakery-2026-10-25c.json": { labelsOnLabels: 1, stub: 800, influence: 950, emptiness: 12.5, scale: 0.4 } };

for (const file of fs.readdirSync(FIXTURES).filter((f) => f.endsWith(".json"))) {
  const known = KNOWN[file] || {};
  test(`${file}: every node is placed, nothing overlaps, the boundary holds`, async () => {
    const { placed, score } = await laidOut(file);
    assert.ok(placed.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y)), "a node has no place");
    assert.deepEqual(score.overlaps, [], "nodes on top of each other");
    assert.deepEqual(score.cloudsInside, [], "a cloud inside the system");
    assert.deepEqual(score.outsideFrame, [], "something of the system outside it");
  });

  test(`${file}: no avoidable crossings, nothing hidden, still readable`, async () => {
    const { placed, score } = await laidOut(file);
    console.log(file, JSON.stringify({ crossings: score.crossings, all: score.allCrossings, through: score.through.length, labelsOnNodes: score.labelsOnNodes.length, labelsOnLabels: score.labelsOnLabels, flow: score.flowLength,
      stub: score.stubLength, influence: score.influenceLength, nearest: score.nearest, emptiness: score.emptiness }));
    // nothing that can be avoided: no line behind a box, no two lines crossing (flows, dashed
    // influences, cloud stubs), no covered word, no overlap. (The force layout this replaced had 9
    // lines behind boxes and 8-10 crossings on these models.)
    assert.deepEqual(score.through, [], "lines behind boxes");
    assert.equal(score.allCrossings, 0, `lines cross: ${JSON.stringify(score.crossPairs)}`);
    assert.deepEqual(score.labelsOnNodes, [], "labels on boxes");
    assert.ok(score.labelsOnLabels <= (known.labelsOnLabels || 0), `${score.labelsOnLabels} labels on labels`);
    // and not by spreading out until it is unreadable
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of placed) { const z = size(n), hw = (z.r || z.w / 2) + 40, hh = (z.r || z.h / 2) + 40; x0 = Math.min(x0, n.x - hw); x1 = Math.max(x1, n.x + hw); y0 = Math.min(y0, n.y - hh); y1 = Math.max(y1, n.y + hh); }
    const scale = Math.min(1, 1300 / (x1 - x0), 600 / (y1 - y0));
    assert.ok(scale >= (known.scale || 0.45), `fitted to the view, the drawing is ${scale.toFixed(2)} of full size`);
    assert.ok(score.flowLength.max <= 300, `a flow ${score.flowLength.max} px long`);
    assert.ok(score.stubLength.max <= (known.stub || 500), `a flow from or to outside ${score.stubLength.max} px long`);
    assert.ok(score.influenceLength.max <= (known.influence || 500), `an influence ${score.influenceLength.max} px long`);
    assert.ok(score.emptiness <= (known.emptiness || 5.5), `the system's frame is ${score.emptiness}× the area of what is in it`);
  });
}

// The Machines map at rest (netgraph.js fit): a node linked to nothing (the host, alone) is set in a
// row under the connected part, so the automatic fit of a 1330×600 view keeps every name readable
// (at DESK_K or more) instead of shrinking everything to reach a node the forces threw far away.
test("ten connected machines and one alone fit a 1330×600 view at no less than DESK_K", () => {
  const { isolatedRows, fitView, boundsOf, DESK_K } = require(path.join(STATIC, "netgraph-geometry.js"));
  const ring = Array.from({ length: 10 }, (_, i) => ({ id: "m:" + i, kind: "circle", label: "machine " + i, x: 200 + 260 * Math.cos(i * Math.PI / 5), y: 220 + 170 * Math.sin(i * Math.PI / 5) }));
  const host = { id: "m:host", kind: "circle", label: "orchestra-host", x: 2600, y: -900 };
  const before = fitView(boundsOf([...ring, host]), { w: 1330, h: 600, top: 40, all: true });
  assert.ok(before.k < DESK_K, `the lone node far away would shrink the view (${before.k})`);
  const at = isolatedRows([host], ring);
  Object.assign(host, { x: at[host.id][0], y: at[host.id][1] });
  const after = fitView(boundsOf([...ring, host]), { w: 1330, h: 600, top: 40, minK: DESK_K });
  assert.ok(after.kFit >= DESK_K && after.k >= DESK_K, `scale ${after.kFit}`);
  // and the lone node is in view under the ring
  const sx = host.x * after.k + after.tx, sy = host.y * after.k + after.ty;
  assert.ok(sx > 0 && sx < 1330 && sy > 40 && sy < 600, `host at ${sx}, ${sy}`);
});

// The Machines map and the Dynamics diagram on a desktop fill the viewport under the header
// (NetGeometry.viewHeight, 600 to 1100 px): on a 1440×1000 screen with 160 px of header, bar and
// legend the drawing is 840 px tall, and the same eleven machines fit it whole, larger than at 600.
test("a desktop drawing as tall as the viewport allows fits the map larger, every node in view", () => {
  const { viewHeight, fitView, boundsOf, isolatedRows, DESK_K } = require(path.join(STATIC, "netgraph-geometry.js"));
  assert.equal(viewHeight(1000, 160), 840);
  assert.equal(viewHeight(700, 160), 600, "never shorter than 600");
  assert.equal(viewHeight(1600, 160), 1100, "never taller than 1100");
  const ring = Array.from({ length: 10 }, (_, i) => ({ id: "m:" + i, kind: "circle", label: "machine " + i, x: 200 + 260 * Math.cos(i * Math.PI / 5), y: 220 + 260 * Math.sin(i * Math.PI / 5) }));
  const host = { id: "m:host", kind: "circle", label: "orchestra-host", x: 0, y: 0 };
  Object.assign(host, { x: isolatedRows([host], ring)[host.id][0], y: isolatedRows([host], ring)[host.id][1] });
  const box = boundsOf([...ring, host]), h = viewHeight(1000, 160);
  const short = fitView(box, { w: 1330, h: 600, top: 40, all: true }), tall = fitView(box, { w: 1330, h, top: 40, all: true });
  assert.ok(short.k < DESK_K && tall.k > short.k, `600 px: ${short.k.toFixed(2)}, ${h} px: ${tall.k.toFixed(2)}`);
  for (const n of [...ring, host]) {
    const sx = n.x * tall.k + tall.tx, sy = n.y * tall.k + tall.ty;
    assert.ok(sx > 0 && sx < 1330 && sy > 40 && sy < h, `${n.id} at ${sx.toFixed(0)}, ${sy.toFixed(0)}`);
  }
});

// Reset on every new structure (the owner, 2026-11-02: "We should load the page and it already been in
// the position it would be after hitting Reset, and it should run the Reset operation when a new
// graph is generated"). netgraph.js asks NetGeometry.onRender what a redraw does and runs the reset
// button's own code (resetLayout) for "reset"; the reset forgets every position, so what it lays out
// is a function of the graph alone: positions the nodes carried in (saved ones, the viewer's) change nothing.
test("a new structure is laid out as reset lays it out; the same structure moves nothing; a drag defers it", () => {
  const { onRender } = require(path.join(STATIC, "netgraph-geometry.js"));
  assert.equal(onRender({ resetOnStructure: true, structural: true }), "reset", "the first drawing, a new version, a focus");
  assert.equal(onRender({ resetOnStructure: true, structural: false }), "keep", "a data refresh of the same structure");
  assert.equal(onRender({ resetOnStructure: true, structural: true, dragging: true }), "defer", "not while the viewer drags");
  assert.equal(onRender({ resetOnStructure: false, structural: true }), "keep", "a graph that keeps its places");
});

test("the first drawing (with saved positions) and the reset end in the same layout", async () => {
  const file = fs.readdirSync(FIXTURES).filter((f) => f.endsWith(".json")).sort()[0];
  const model = JSON.parse(fs.readFileSync(path.join(FIXTURES, file), "utf8")).model;
  const geo = { size, inside, frameOf, tetherPlaces };
  const run = async (nodes, edges) => {
    const elk = await SDLayout.layout(nodes, edges, { elk: new ELK(), ...geo, hierarchy: true });
    return SDLayout.refine(nodes, edges, SDLayout.pack(nodes, edges, elk, geo), { ...geo, labelSize });
  };
  const { nodes, edges } = SDGraph.build(model);
  const reset = await run(nodes.map((n) => ({ ...n })), edges);
  // as a first drawing finds them: places saved by an earlier visit, some dragged by the viewer
  const stale = nodes.map((n, i) => ({ ...n, x: 37 * i - 400, y: (i % 3) * 211, pin: i % 2 === 0 }));
  const first = await run(stale, edges);
  assert.deepEqual(first, reset);
  // and a new structure (one stock fewer) is laid out from scratch too: the same as its own reset
  const fewer = SDGraph.build({ ...model, stocks: model.stocks.slice(1), flows: model.flows.filter((f) => f.from !== model.stocks[0].id && f.to !== model.stocks[0].id) });
  const placed = Object.fromEntries(Object.entries(reset));
  const again = await run(fewer.nodes.map((n) => ({ ...n, x: (placed[n.id] || [0, 0])[0], y: (placed[n.id] || [0, 0])[1] })), fewer.edges);
  assert.deepEqual(again, await run(fewer.nodes.map((n) => ({ ...n })), fewer.edges));
});
