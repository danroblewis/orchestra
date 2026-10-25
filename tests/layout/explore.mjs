// Try layout options on the fixtures and print their scores (not a test).
import fs from "node:fs"; import path from "node:path"; import vm from "node:vm"; import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const ELK = require("elkjs/lib/elk.bundled.js");
const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static"), FIX = path.resolve(import.meta.dirname, "../fixtures/dynamics");
const SDGraph = require(path.join(STATIC, "sd-graph.js")), SDLayout = require(path.join(STATIC, "sd-layout.js")), LayoutScore = require(path.join(STATIC, "layout-score.js"));
const ctx = {}; vm.runInNewContext(fs.readFileSync(path.join(STATIC, "netgraph.js"), "utf8") + "\nthis.NetGraph = NetGraph;", ctx);
const { size, frameOf, tetherPlaces } = ctx.NetGraph, inside = (n) => n.kind !== "cloud";
const variants = JSON.parse(process.argv[2] || "{}"), hier = process.argv[3] === "hier";
for (const file of fs.readdirSync(FIX).filter((f) => f.endsWith(".json"))) {
  const { nodes, edges } = SDGraph.build(JSON.parse(fs.readFileSync(path.join(FIX, file), "utf8")).model);
  for (const [name, options] of Object.entries({ base: {}, ...variants })) {
    const at = await SDLayout.layout(nodes, edges, { elk: new ELK(), size, inside, frameOf, tetherPlaces, options, hierarchy: hier });
    const placed = nodes.map((n) => ({ ...n, x: at[n.id][0], y: at[n.id][1] }));
    const s = LayoutScore.score(placed, edges, { size, frame: frameOf(placed, inside), inside });
    console.log(name.padEnd(14), JSON.stringify({ ov: s.overlaps.length, x: s.crossings, thr: s.through.length, flow: s.flowLength, stub: s.stubLength.max, inf: s.influenceLength, empty: s.emptiness }));
  }
}
