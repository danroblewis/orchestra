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
  const ROOM = 7;

  // Refine a layout (ELK's) by springs: every flow, influence and cloud is a spring toward a
  // sensible length, and a node moves in inverse proportion to how connected it is, so a node with
  // one connection comes in to it while busy stocks hold the structure. Nodes push apart only
  // where they overlap, and a stock keeps ``ROOM`` px more room per flow so its flows can be seen.
  // A stock with flows from or to outside is drawn toward the nearest side of the frame, so its
  // clouds' stubs are short. Returns new positions; clouds placed by the cloud rule.
  // A flow with a label is given room for it (``labelSize``): its rest length is at least the
  // label's width, so the words fit beside the line instead of on a box.
  function refine(nodes, edges, at, { size, inside = (n) => n.kind !== "cloud", frameOf, tetherPlaces, iterations = 300, gap = 70, outwardK = 0.06, influenceGap = 40, labelSize = null }) {
    const P = new Map(nodes.filter((n) => at[n.id] && inside(n)).map((n) => [n.id, { n, x: at[n.id][0], y: at[n.id][1] }]));
    const half = (n) => { const s = size(n); return s.r ? [s.r, s.r] : [s.w / 2, s.h / 2]; };
    const byEdge = new Map(edges.filter((e) => !e.toEdge).map((e) => [e.id, e]));
    const springs = [], degree = new Map([...P.keys()].map((id) => [id, 0]));
    const spring = (a, b, extra) => { if (a !== b && P.has(a) && P.has(b)) { springs.push([a, b, extra]); degree.set(a, degree.get(a) + 1); degree.set(b, degree.get(b) + 1); } };
    for (const e of byEdge.values()) { const ls = labelSize && labelSize(e); spring(e.source, e.target, Math.max(gap, ls ? ls.w * 0.8 + 16 : 0)); }
    for (const e of edges.filter((x) => x.toEdge)) { const f = byEdge.get(e.toEdge); if (f) for (const end of [f.source, f.target]) spring(e.source, end, gap + influenceGap); }
    const outward = new Set(nodes.filter((n) => n.kind === "cloud" && n.tether).map((n) => n.tether));
    const room = (id) => 14 + ROOM * (degree.get(id) || 0);
    const ids = [...P.keys()];
    for (let it = 0; it < iterations; it++) {
      const t = 1 - it / iterations, k = 0.08 * t + 0.01;
      for (const [a, b, extra] of springs) {              // springs: toward the touching distance plus a gap
        const A = P.get(a), B = P.get(b), dx = B.x - A.x, dy = B.y - A.y, d = Math.hypot(dx, dy) || 1;
        const [ha, va] = half(A.n), [hb, vb] = half(B.n);
        const touch = Math.abs(dx) / d * (ha + hb) + Math.abs(dy) / d * (va + vb);
        const pull = (d - (touch + extra)) * k;
        if (pull <= 0) continue;                           // never pushes: overlap removal does that
        const wa = 1 / (1 + degree.get(a)), wb = 1 / (1 + degree.get(b)), w = wa + wb;
        A.x += dx / d * pull * wa / w; A.y += dy / d * pull * wa / w;
        B.x -= dx / d * pull * wb / w; B.y -= dy / d * pull * wb / w;
      }
      const b = frameOf ? frameOf([...P.values()].map((p) => ({ ...p.n, x: p.x, y: p.y })), inside) : null;
      if (b) for (const id of outward) {                   // toward the nearest side of the frame
        const p = P.get(id); if (!p) continue;
        const [h, v] = half(p.n);
        const [d, dx, dy] = [[p.x - h - (b.x0 + 34), -1, 0], [(b.x1 - 34) - (p.x + h), 1, 0], [p.y - v - (b.y0 + 46), 0, -1], [(b.y1 - 34) - (p.y + v), 0, 1]].sort((u, w) => u[0] - w[0])[0];
        if (d > 4) { p.x += dx * d * outwardK * t; p.y += dy * d * outwardK * t; }
      }
      for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {   // overlaps, with room
        const A = P.get(ids[i]), B = P.get(ids[j]), [ha, va] = half(A.n), [hb, vb] = half(B.n);
        const r = (room(ids[i]) + room(ids[j])) / 2;
        const ox = ha + hb + r - Math.abs(B.x - A.x), oy = va + vb + r - Math.abs(B.y - A.y);
        if (ox <= 0 || oy <= 0) continue;
        const wa = degree.get(ids[i]) <= degree.get(ids[j]) ? 0.6 : 0.4;        // the less connected one moves more
        if (ox < oy) { const s = Math.sign(B.x - A.x) || 1; A.x -= s * ox * wa; B.x += s * ox * (1 - wa); }
        else { const s = Math.sign(B.y - A.y) || 1; A.y -= s * oy * wa; B.y += s * oy * (1 - wa); }
      }
    }
    const out = { ...at };
    for (const [id, p] of P) out[id] = [p.x, p.y];
    if (frameOf && tetherPlaces) {
      const placed = nodes.map((n) => (P.has(n.id) ? { ...n, x: out[n.id][0], y: out[n.id][1] } : { ...n, x: undefined, y: undefined }));
      Object.assign(out, tetherPlaces(placed, frameOf(placed, inside)));
    }
    return out;
  }

  // Untangle a layout by local search: try moving each node a step in eight directions, and
  // swapping two nodes of a kind (stock and stock, auxiliary and auxiliary); keep a change only
  // when it lowers the cost, which counts most what reads worst (a line hidden behind a box,
  // flows crossing, nodes overlapping), then any crossing, then length and spread. ``score`` is
  // LayoutScore.score. Clouds are placed by the cloud rule after every change.
  const COST = (s) => 40 * s.through.length + 25 * s.crossings + 8 * s.allCrossings + 300 * s.overlaps.length
    + 40 * (s.labelsOnNodes ? s.labelsOnNodes.length : 0) + 25 * (s.labelsOnLabels || 0)
    + 0.02 * s.nearest.max + 0.02 * s.influenceLength.median + 2 * (s.emptiness || 0);
  // ``labels(placed)``, when given, places the edge labels ({edge id: [x, y]}) so words covered by
  // boxes or other words count too (``labelSize`` sizes them)
  function untangle(nodes, edges, at, { size, score, inside = (n) => n.kind !== "cloud", frameOf, tetherPlaces, labels = null, labelSize = null, passes = 4, steps = [60, 120] }) {
    const ids = nodes.filter((n) => inside(n) && at[n.id]).map((n) => n.id), byId = new Map(nodes.map((n) => [n.id, n]));
    let cur = { ...at };
    const evaluate = (pos) => {
      const placed = nodes.map((n) => (inside(n) ? { ...n, x: pos[n.id][0], y: pos[n.id][1] } : { ...n, x: undefined, y: undefined }));
      const frame = frameOf(placed, inside), clouds = tetherPlaces(placed, frame);
      for (const n of placed) if (clouds[n.id]) [n.x, n.y] = clouds[n.id];
      return { cost: COST(score(placed, edges, { size, frame, inside, labels: labels ? labels(placed) : null, labelSize })), clouds };
    };
    let best = evaluate(cur);
    // only nodes in a problem are moved: the ends of a line through a box or crossing another, a box
    // under a label and the ends of the label's line (``tangled`` from the score)
    const tangledNow = (pos) => {
      const placed = nodes.map((n) => (inside(n) ? { ...n, x: pos[n.id][0], y: pos[n.id][1] } : { ...n, x: undefined, y: undefined }));
      const frame = frameOf(placed, inside), clouds = tetherPlaces(placed, frame);
      for (const n of placed) if (clouds[n.id]) [n.x, n.y] = clouds[n.id];
      return new Set(score(placed, edges, { size, frame, inside, labels: labels ? labels(placed) : null, labelSize }).tangled || ids);
    };
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
    for (let pass = 0; pass < passes; pass++) {
      let improved = false;
      const busy = tangledNow(cur), movable = ids.filter((id) => busy.has(id));
      if (!movable.length) break;
      for (const id of movable) {
        for (const step of steps) for (const [dx, dy] of dirs) {
          const next = { ...cur, [id]: [cur[id][0] + dx * step, cur[id][1] + dy * step] }, r = evaluate(next);
          if (r.cost < best.cost - 1e-6) { cur = next; best = r; improved = true; }
        }
      }
      for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
        if (!busy.has(ids[i]) && !busy.has(ids[j])) continue;
        const a = byId.get(ids[i]), b = byId.get(ids[j]);
        if (!!a.sid !== !!b.sid) continue;                            // stocks with stocks, auxiliaries with auxiliaries
        const next = { ...cur, [ids[i]]: cur[ids[j]], [ids[j]]: cur[ids[i]] }, r = evaluate(next);
        if (r.cost < best.cost - 1e-6) { cur = next; best = r; improved = true; }
      }
      if (!improved) break;
    }
    return { ...cur, ...best.clouds };
  }

  return { layout, refine, untangle, OPTIONS, COST };
});
