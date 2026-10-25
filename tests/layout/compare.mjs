// Score ELK, and ELK refined by springs, on every fixture (not a test). Argument: refine options as JSON.
import fs from "node:fs"; import path from "node:path"; import vm from "node:vm"; import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const ELK = require("elkjs/lib/elk.bundled.js");
const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static"), FIX = path.resolve(import.meta.dirname, "../fixtures/dynamics");
const SDGraph = require(path.join(STATIC, "sd-graph.js")), SDLayout = require(path.join(STATIC, "sd-layout.js")), LayoutScore = require(path.join(STATIC, "layout-score.js"));
const ctx = {}; vm.runInNewContext(fs.readFileSync(path.join(STATIC, "netgraph.js"), "utf8") + "\nthis.NetGraph = NetGraph;", ctx);
const { size, frameOf, tetherPlaces } = ctx.NetGraph, inside = (n) => n.kind !== "cloud";
const extra = JSON.parse(process.argv[2] || "{}");
for (const file of fs.readdirSync(FIX).filter((f) => f.endsWith(".json"))) {
  const { nodes, edges } = SDGraph.build(JSON.parse(fs.readFileSync(path.join(FIX, file), "utf8")).model);
  const runs = { elk: () => SDLayout.layout(nodes, edges, { elk: new ELK(), size, inside, frameOf, tetherPlaces, hierarchy: true }),
                 "elk+refine": async () => SDLayout.refine(nodes, edges, await SDLayout.layout(nodes, edges, { elk: new ELK(), size, inside, frameOf, tetherPlaces, hierarchy: true }), { size, inside, frameOf, tetherPlaces, labelSize: ctx.NetGraph.labelSize, ...extra }),
                 "+untangle": async () => { const geo = { size, inside, frameOf, tetherPlaces };
                   const r = SDLayout.refine(nodes, edges, await SDLayout.layout(nodes, edges, { elk: new ELK(), ...geo, hierarchy: true }), { ...geo, labelSize: ctx.NetGraph.labelSize });
                   const t0 = Date.now(), u = SDLayout.untangle(nodes, edges, r, { ...geo, score: LayoutScore.score, labelSize: ctx.NetGraph.labelSize, ...(JSON.parse(process.argv[4] || "{}")),
                     labels: (placed) => { const m = LayoutScore.mids(placed, edges, size), o = ctx.NetGraph.placeLabels(placed, edges, m); return Object.fromEntries(Object.entries(o).map(([id, [dx, dy]]) => [id, [m[id].x + dx, m[id].y + dy]])); } }); console.log("   untangle ms", Date.now() - t0); return u; } };
  for (const [name, run] of Object.entries(runs)) {
    const at = await run();
    const placed = nodes.map((n) => ({ ...n, x: at[n.id][0], y: at[n.id][1] }));
    const mids = LayoutScore.mids(placed, edges, size), off = ctx.NetGraph.placeLabels(placed, edges, mids);
    const labels = Object.fromEntries(Object.entries(off).map(([id, [dx, dy]]) => [id, [mids[id].x + dx, mids[id].y + dy]]));
    const s = LayoutScore.score(placed, edges, { size, frame: frameOf(placed, inside), inside, labels, labelSize: ctx.NetGraph.labelSize });
    console.log(name.padEnd(11), JSON.stringify({ ov: s.overlaps.length, x: s.crossings, thr: s.through.length, flow: s.flowLength, stub: s.stubLength.max, inf: s.influenceLength, near: s.nearest.max, nearMed: s.nearest.median, empty: s.emptiness, ins: s.cloudsInside.length, xall: s.allCrossings, lblNode: s.labelsOnNodes.length, lblLbl: s.labelsOnLabels, cost: Math.round(SDLayout.COST(s)) }));
    if (process.argv[3]) console.log("   worst", JSON.stringify(s.nearest.worst), "labels on nodes", JSON.stringify(s.labelsOnNodes.map((id) => [id.slice(0, 70), (edges.find((e) => e.id === id) || {}).label || (edges.find((e) => e.id === id) || {}).sign])));
  }
}
