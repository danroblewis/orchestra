// The Dynamics graph's layout, measured (orchestra/web/static/layout-score.js) on saved models
// (tests/fixtures/dynamics). The graph is built and laid out by the same code the page runs:
// sd-graph.js (model → graph), sd-layout.js (ELK, springs, untangling), netgraph.js (sizes, frame,
// clouds, labels).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ELK = require("elkjs/lib/elk.bundled.js");
const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static");
const FIXTURES = path.resolve(import.meta.dirname, "../fixtures/dynamics");
const SDGraph = require(path.join(STATIC, "sd-graph.js"));
const SDLayout = require(path.join(STATIC, "sd-layout.js"));
const LayoutScore = require(path.join(STATIC, "layout-score.js"));
// netgraph.js is a browser script (a global const); its pure parts need no DOM or d3
const ctx = {};
vm.runInNewContext(fs.readFileSync(path.join(STATIC, "netgraph.js"), "utf8") + "\nthis.NetGraph = NetGraph;", ctx);
const { size, frameOf, tetherPlaces, labelSize, placeLabels } = ctx.NetGraph;
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

for (const file of fs.readdirSync(FIXTURES).filter((f) => f.endsWith(".json"))) {
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
    assert.equal(score.labelsOnLabels, 0, "labels on labels");
    // and not by spreading out until it is unreadable
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of placed) { const z = size(n), hw = (z.r || z.w / 2) + 40, hh = (z.r || z.h / 2) + 40; x0 = Math.min(x0, n.x - hw); x1 = Math.max(x1, n.x + hw); y0 = Math.min(y0, n.y - hh); y1 = Math.max(y1, n.y + hh); }
    const scale = Math.min(1, 1300 / (x1 - x0), 600 / (y1 - y0));
    assert.ok(scale >= 0.45, `fitted to the view, the drawing is ${scale.toFixed(2)} of full size`);
    assert.ok(score.flowLength.max <= 300, `a flow ${score.flowLength.max} px long`);
    assert.ok(score.stubLength.max <= 500, `a flow from or to outside ${score.stubLength.max} px long`);
    assert.ok(score.influenceLength.max <= 500, `an influence ${score.influenceLength.max} px long`);
    assert.ok(score.emptiness <= 5.5, `the system's frame is ${score.emptiness}× the area of what is in it`);
  });
}
