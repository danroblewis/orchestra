// The Dynamics graph's layout, by ELK's layered algorithm (elkjs): what is inside the system is
// laid out in layers along its flows (material moves left to right), with as few crossings as it
// can find; then the clouds go just outside the frame, beside their stocks (NetGraph.tetherPlaces).
//
// What ELK sees: every node inside the system at its drawn size, every flow between two of them,
// and, for each auxiliary, a link to the stock its influence's flow runs into, so an auxiliary is
// placed beside the flows it drives instead of wherever it lands. Influences from stocks are left
// out of the layering (they would fight the flows' direction); clouds are placed afterwards.
//
// Shared by the browser (global SDLayout, with the global ELK) and the layout tests (Node, elkjs).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SDLayout = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const OPTIONS = {
    "elk.algorithm": "layered",
    "elk.direction": "RIGHT",
    "elk.edgeRouting": "POLYLINE",
    "elk.spacing.nodeNode": "46",
    "elk.layered.spacing.nodeNodeBetweenLayers": "120",
    "elk.spacing.componentComponent": "70",
    "elk.separateConnectedComponents": "true",
    "elk.aspectRatio": "1.6",
    "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
    "elk.layered.crossingMinimization.semiInteractive": "false",
  };

  // {id: [x, y]} (centres) for every node: ``inside(n)`` nodes by ELK, tethered ones beside them
  const PAD = 34;
  async function layout(nodes, edges, { elk, size, inside = (n) => n.kind !== "cloud", frameOf, tetherPlaces, options = {}, hierarchy = false }) {
    const ins = nodes.filter(inside), isIn = new Set(ins.map((n) => n.id));
    const dims = new Map(ins.map((n) => { const s = size(n); return [n.id, s.r ? [2 * s.r, 2 * s.r] : [s.w, s.h]]; }));
    const byEdge = new Map(edges.filter((e) => !e.toEdge).map((e) => [e.id, e]));
    const links = [], seen = new Set();
    const link = (a, b, id) => { const k = a + ">" + b; if (a === b || seen.has(k) || !isIn.has(a) || !isIn.has(b)) return; seen.add(k); links.push({ id, sources: [a], targets: [b] }); };
    for (const e of byEdge.values()) link(e.source, e.target, "f" + links.length);
    for (const e of edges.filter((x) => x.toEdge)) {
      const src = nodes.find((n) => n.id === e.source), f = byEdge.get(e.toEdge);
      if (!src || src.kind === "cloud" || src.sid || !f) continue;          // auxiliaries only
      link(e.source, isIn.has(f.target) ? f.target : f.source, "i" + links.length);
    }
    const kids = ins.map((n) => ({ id: n.id, width: dims.get(n.id)[0], height: dims.get(n.id)[1] }));
    const at = {};
    if (hierarchy) {
      // the system as a box of its own, the clouds outside it, and the flows across its edge laid
      // out with the rest: a stock fed from outside lands at the side its cloud is on
      const outs = nodes.filter((n) => !inside(n)), cut = [];
      for (const e of byEdge.values()) if (!isIn.has(e.source) || !isIn.has(e.target)) cut.push({ id: "c" + cut.length, sources: [e.source], targets: [e.target] });
      const res = await elk.layout({ id: "root", layoutOptions: { ...OPTIONS, "elk.hierarchyHandling": "INCLUDE_CHILDREN", ...options },
        children: [{ id: "__system", layoutOptions: { "elk.padding": `[top=${PAD + 12},left=${PAD},bottom=${PAD},right=${PAD}]` }, children: kids, edges: links },
                   ...outs.map((n) => { const s = size(n), d = s.r ? 2 * s.r : s.w; return { id: n.id, width: d, height: d }; })],
        edges: cut });
      for (const c of res.children) {
        if (c.id === "__system") for (const k of c.children) at[k.id] = [c.x + k.x + k.width / 2, c.y + k.y + k.height / 2];
        else at[c.id] = [c.x + c.width / 2, c.y + c.height / 2];
      }
    } else {
      const res = await elk.layout({ id: "root", layoutOptions: { ...OPTIONS, ...options }, children: kids, edges: links });
      for (const c of res.children) at[c.id] = [c.x + c.width / 2, c.y + c.height / 2];
    }
    // the clouds by the renderer's own rule: just outside the frame, beside their stocks
    if (frameOf && tetherPlaces) {
      const placed = nodes.map((n) => (at[n.id] ? { ...n, x: at[n.id][0], y: at[n.id][1] } : { ...n, x: undefined, y: undefined }));
      Object.assign(at, tetherPlaces(placed, frameOf(placed, inside)));
    }
    return at;
  }
  return { layout, OPTIONS };
});
