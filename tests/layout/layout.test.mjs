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
  const springs = SDLayout.refine(nodes, edges, await SDLayout.layout(nodes, edges, { elk: new ELK(), ...geo, hierarchy: true }), { ...geo, labelSize });
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

  test(`${file}: lines are short and do not run through nodes`, async () => {
    const { score } = await laidOut(file);
    console.log(file, JSON.stringify({ crossings: score.crossings, all: score.allCrossings, through: score.through.length, labelsOnNodes: score.labelsOnNodes.length, labelsOnLabels: score.labelsOnLabels, flow: score.flowLength,
      stub: score.stubLength, influence: score.influenceLength, nearest: score.nearest, emptiness: score.emptiness }));
    // on bakery-2026-10-25 the force layout this replaced had 9 lines behind boxes, labels on boxes,
    // influences up to 1187 px; this pipeline: no line behind a box, no label covered, no flows
    // crossing (8 crossings among the dashed influences). These hold it there.
    assert.equal(score.crossings, 0, "flows cross");
    assert.ok(score.through.length <= 1, `${score.through.length} lines behind boxes: ${JSON.stringify(score.through)}`);
    assert.ok(score.labelsOnNodes.length <= 1, `labels on boxes: ${JSON.stringify(score.labelsOnNodes)}`);
    assert.equal(score.labelsOnLabels, 0, "labels on labels");
    assert.ok(score.allCrossings <= 10, `${score.allCrossings} lines cross`);
    assert.ok(score.flowLength.max <= 160, `a flow ${score.flowLength.max} px long`);
    assert.ok(score.stubLength.max <= 320, `a flow from or to outside ${score.stubLength.max} px long`);
    assert.ok(score.influenceLength.max <= 600, `an influence ${score.influenceLength.max} px long`);
    assert.ok(score.nearest.max <= 450, `a node ${score.nearest.max} px from the nearest thing it is connected to: ${JSON.stringify(score.nearest.worst)}`);
    assert.ok(score.emptiness <= 5.0, `the system's frame is ${score.emptiness}× the area of what is in it`);
  });
}
