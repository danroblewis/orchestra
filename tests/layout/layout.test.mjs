// The Dynamics graph's layout, measured (orchestra/web/static/layout-score.js) on saved models
// (tests/fixtures/dynamics). The graph is built and laid out by the same code the page runs:
// sd-graph.js (model → graph), sd-layout.js (ELK, then springs), netgraph.js (sizes, frame, clouds).
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
const { size, frameOf, tetherPlaces } = ctx.NetGraph;
const inside = (n) => n.kind !== "cloud";

async function laidOut(file) {
  const model = JSON.parse(fs.readFileSync(path.join(FIXTURES, file), "utf8")).model;
  const { nodes, edges } = SDGraph.build(model);
  const geo = { size, inside, frameOf, tetherPlaces };     // as the page does: ELK, then refined by springs
  const at = SDLayout.refine(nodes, edges, await SDLayout.layout(nodes, edges, { elk: new ELK(), ...geo, hierarchy: true }), geo);
  const placed = nodes.map((n) => ({ ...n, x: at[n.id][0], y: at[n.id][1] }));
  return { placed, edges, score: LayoutScore.score(placed, edges, { size, frame: frameOf(placed, inside), inside }) };
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
    console.log(file, JSON.stringify({ crossings: score.crossings, through: score.through.length, flow: score.flowLength,
      stub: score.stubLength, influence: score.influenceLength, nearest: score.nearest, emptiness: score.emptiness }));
    // on bakery-2026-10-25 the force layout this replaced measured: influences up to 1187 px (median
    // 545), 9 lines through nodes, a frame 8.0× the area of its nodes; ELK alone: flows up to 220 px,
    // 11 lines through nodes. These hold the layout to what it does now, so a change that makes it
    // worse fails.
    assert.ok(score.crossings <= 1, `${score.crossings} flows cross`);
    assert.ok(score.flowLength.max <= 140, `a flow ${score.flowLength.max} px long`);
    assert.ok(score.stubLength.max <= 320, `a flow from or to outside ${score.stubLength.max} px long`);
    assert.ok(score.influenceLength.max <= 400, `an influence ${score.influenceLength.max} px long`);
    assert.ok(score.influenceLength.median <= 270, `influences ${score.influenceLength.median} px long in the middle`);
    assert.ok(score.nearest.max <= 400, `a node ${score.nearest.max} px from the nearest thing it is connected to: ${JSON.stringify(score.nearest.worst)}`);
    assert.ok(score.through.length <= 4, `${score.through.length} lines through nodes: ${JSON.stringify(score.through)}`);
    assert.ok(score.emptiness <= 5.6, `the system's frame is ${score.emptiness}× the area of what is in it`);
  });
}
