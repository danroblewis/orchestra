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
    "elk.aspectRatio": "2.1",          // the diagram's view is about twice as wide as tall
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
      Object.assign(at, tetherPlaces(placed, frameOf(placed, inside), edges));
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
      Object.assign(out, tetherPlaces(placed, frameOf(placed, inside), edges));
    }
    return out;
  }

  // The groups of a graph: what is connected inside the system (by flows between its nodes, and
  // by influences). [[node id]], biggest first.
  function groupsOf(nodes, edges, inside = (n) => n.kind !== "cloud") {
    const ids = nodes.filter(inside).map((n) => n.id), parent = new Map(ids.map((id) => [id, id]));
    const find = (x) => { while (parent.get(x) !== x) x = parent.get(x); return x; };
    const join = (a, b) => { if (parent.has(a) && parent.has(b)) parent.set(find(a), find(b)); };
    const flowById = new Map(edges.filter((e) => !e.toEdge).map((e) => [e.id, e]));
    for (const e of flowById.values()) join(e.source, e.target);
    for (const e of edges.filter((x) => x.toEdge)) { const f = flowById.get(e.toEdge); if (f) { join(e.source, f.source); join(e.source, f.target); } }
    return [...ids.reduce((m, id) => m.set(find(id), [...(m.get(find(id)) || []), id]), new Map()).values()].sort((a, b) => b.length - a.length);
  }

  // Pack the groups side by side in rows to fill a view of ``aspect`` (width / height), each keeping
  // its own internal layout, so no group sits among another's lines and the drawing fits a wide view.
  function pack(nodes, edges, at, { size, inside = (n) => n.kind !== "cloud", aspect = 2.1, gap = 90, frameOf, tetherPlaces }) {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const boxes = groupsOf(nodes, edges, inside).map((g) => {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const id of g) { const z = size(byId.get(id)), hw = z.r || z.w / 2, hh = z.r || z.h / 2, [x, y] = at[id]; x0 = Math.min(x0, x - hw); x1 = Math.max(x1, x + hw); y0 = Math.min(y0, y - hh); y1 = Math.max(y1, y + hh); }
      return { g, x0, y0, w: x1 - x0, h: y1 - y0 };
    }).sort((a, b) => b.h - a.h);
    const area = boxes.reduce((a, b) => a + (b.w + gap) * (b.h + gap), 0);
    const width = Math.max(Math.sqrt(area * aspect), ...boxes.map((b) => b.w));
    const out = { ...at };
    let x = 0, y = 0, rowH = 0;
    for (const b of boxes) {
      if (x > 0 && x + b.w > width) { x = 0; y += rowH + gap; rowH = 0; }
      for (const id of b.g) out[id] = [at[id][0] - b.x0 + x, at[id][1] - b.y0 + y];
      x += b.w + gap; rowH = Math.max(rowH, b.h);
    }
    if (frameOf && tetherPlaces) {
      const placed = nodes.map((n) => (inside(n) ? { ...n, x: out[n.id][0], y: out[n.id][1] } : { ...n, x: undefined, y: undefined }));
      Object.assign(out, tetherPlaces(placed, frameOf(placed, inside), edges));
    }
    return out;
  }

  // Untangle a layout by local search: try moving each node a step in eight directions, and
  // swapping two nodes of a kind (stock and stock, auxiliary and auxiliary); keep a change only
  // when it lowers the cost, which counts most what reads worst (a line hidden behind a box,
  // flows crossing, nodes overlapping), then any crossing, then length and spread. ``score`` is
  // LayoutScore.score. Clouds are placed by the cloud rule after every change.
  // any two lines that cross (a flow, a dashed influence, a cloud's stub) cost as much as a line
  // behind a box: a crossing is allowed only when every way around it costs more in length and spread
  const COST = (s) => 40 * s.through.length + 30 * s.crossings + 30 * s.allCrossings + 5000 * s.overlaps.length   // overlapping boxes: never worth it
    + 40 * (s.labelsOnNodes ? s.labelsOnNodes.length : 0) + 25 * (s.labelsOnLabels || 0)
    + 0.02 * s.nearest.max + 0.02 * s.influenceLength.median + 2 * (s.emptiness || 0)
    + 150 * Math.max(0, 1 - (s.scale ?? 1));   // shrunk to fit the view: smaller words, so worth about five crossings at half size
  // ``labels(placed)``, when given, places the edge labels ({edge id: [x, y]}) so words covered by
  // boxes or other words count too (``labelSize`` sizes them)
  // ``fixed``: node ids that stay where they are (the viewer's placements)
  function untangle(nodes, edges, at, { size, score, inside = (n) => n.kind !== "cloud", frameOf, tetherPlaces, labels = null, labelSize = null, passes = 4, steps = [60, 120], groupSteps = [120, 240, 400], view = [1300, 600], fixed = [] }) {
    const hold = new Set(fixed);
    const ids = nodes.filter((n) => inside(n) && at[n.id] && !hold.has(n.id)).map((n) => n.id), byId = new Map(nodes.map((n) => [n.id, n]));
    let cur = { ...at };
    const evaluate = (pos) => {
      const placed = nodes.map((n) => (inside(n) ? { ...n, x: pos[n.id][0], y: pos[n.id][1] } : { ...n, x: undefined, y: undefined }));
      const frame = frameOf(placed, inside), clouds = tetherPlaces(placed, frame, edges);
      for (const n of placed) if (clouds[n.id]) [n.x, n.y] = clouds[n.id];
      const sc = score(placed, edges, { size, frame, inside, labels: labels ? labels(placed) : null, labelSize });
      // how big the drawing is when fitted to the view (1: full size; less: shrunk)
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const n of placed) { const z = size(n), hw = (z.r || z.w / 2) + 40, hh = (z.r || z.h / 2) + 40; x0 = Math.min(x0, n.x - hw); x1 = Math.max(x1, n.x + hw); y0 = Math.min(y0, n.y - hh); y1 = Math.max(y1, n.y + hh); }
      sc.scale = Math.min(1, view[0] / (x1 - x0), view[1] / (y1 - y0));
      return { cost: COST(sc), clouds };
    };
    let best = evaluate(cur);
    // only nodes in a problem are moved: the ends of a line through a box or crossing another, a box
    // under a label and the ends of the label's line (``tangled`` from the score)
    const tangledNow = (pos) => {
      const placed = nodes.map((n) => (inside(n) ? { ...n, x: pos[n.id][0], y: pos[n.id][1] } : { ...n, x: undefined, y: undefined }));
      const frame = frameOf(placed, inside), clouds = tetherPlaces(placed, frame, edges);
      for (const n of placed) if (clouds[n.id]) [n.x, n.y] = clouds[n.id];
      return new Set(score(placed, edges, { size, frame, inside, labels: labels ? labels(placed) : null, labelSize }).tangled || ids);
    };
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
    // groups move as a whole too, so a group can step out of another's way instead of sitting among its lines
    const groups = groupsOf(nodes, edges, inside).filter((g) => !g.some((id) => hold.has(id)));   // a group with a held node stays
    const shift = (pos, members, dx, dy) => { const next = { ...pos }; for (const id of members) next[id] = [pos[id][0] + dx, pos[id][1] + dy]; return next; };
    const centre = (pos, members) => [members.reduce((a, id) => a + pos[id][0], 0) / members.length, members.reduce((a, id) => a + pos[id][1], 0) / members.length];
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
      for (const g of groups) {                                  // a whole group, by bigger steps
        if (!g.some((id) => busy.has(id))) continue;
        for (const step of groupSteps) for (const [dx, dy] of dirs) {
          const next = shift(cur, g, dx * step, dy * step), r = evaluate(next);
          if (r.cost < best.cost - 1e-6) { cur = next; best = r; improved = true; }
        }
      }
      // a jump for an auxiliary: next to the middle of each flow it influences, all round it
      const mid = (pos, f) => { const a = pos[f.source] || null, b = pos[f.target] || null; return a && b ? [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] : a || b; };
      const flows = new Map(edges.filter((e) => !e.toEdge).map((e) => [e.id, e]));
      for (const id of ids.filter((x) => busy.has(x) && !byId.get(x).sid)) {
        for (const inf of edges.filter((e) => e.toEdge && e.source === id)) {
          const f = flows.get(inf.toEdge), m = f && mid(cur, f); if (!m) continue;
          for (const [dx, dy] of dirs) for (const r of [110, 170]) {
            const next = { ...cur, [id]: [m[0] + dx * r * 1.4, m[1] + dy * r * 0.8] }, res = evaluate(next);
            if (res.cost < best.cost - 1e-6) { cur = next; best = res; improved = true; }
          }
        }
      }
      // a jump: a group in a problem tried just beside each other group (left, right, above, below
      // its box), so it can get out from between another group's lines
      const half = (id) => { const z = size(byId.get(id)); return z.r ? [z.r, z.r] : [z.w / 2, z.h / 2]; };
      const bbox = (pos, members) => members.reduce((b, id) => { const [hw, hh] = half(id), [x, y] = pos[id];
        return [Math.min(b[0], x - hw), Math.min(b[1], y - hh), Math.max(b[2], x + hw), Math.max(b[3], y + hh)]; }, [Infinity, Infinity, -Infinity, -Infinity]);
      for (const g of groups) {
        if (!g.some((id) => busy.has(id))) continue;
        for (const other of groups) {
          if (other === g) continue;
          const [x0, y0, x1, y1] = bbox(cur, other), [gx0, gy0, gx1, gy1] = bbox(cur, g), gw = gx1 - gx0, gh = gy1 - gy0, cx = (gx0 + gx1) / 2, cy = (gy0 + gy1) / 2;
          for (const [tx, ty] of [[x0 - 60 - gw / 2, (y0 + y1) / 2], [x1 + 60 + gw / 2, (y0 + y1) / 2], [(x0 + x1) / 2, y0 - 60 - gh / 2], [(x0 + x1) / 2, y1 + 60 + gh / 2]]) {
            const next = shift(cur, g, tx - cx, ty - cy), r = evaluate(next);
            if (r.cost < best.cost - 1e-6) { cur = next; best = r; improved = true; }
          }
        }
      }
      for (let i = 0; i < groups.length; i++) for (let j = i + 1; j < groups.length; j++) {   // two groups trade places
        const a = groups[i], b = groups[j];
        if (!a.concat(b).some((id) => busy.has(id))) continue;
        const [ax, ay] = centre(cur, a), [bx, by] = centre(cur, b);
        const next = shift(shift(cur, a, bx - ax, by - ay), b, ax - bx, ay - by), r = evaluate(next);
        if (r.cost < best.cost - 1e-6) { cur = next; best = r; improved = true; }
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

  return { layout, pack, refine, untangle, groupsOf, OPTIONS, COST };
});
