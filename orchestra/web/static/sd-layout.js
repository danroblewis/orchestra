// The Dynamics graph's layout, by ELK's layered algorithm (elkjs): what is inside the system is
// laid out in layers along its flows (material moves left to right), with as few crossings as it
// can find; then the clouds go just outside the frame, beside their stocks (NetGeometry.tetherPlaces, netgraph-geometry.js).
//
// What ELK sees: every node inside the system at its drawn size, every flow between two of them,
// and, for each auxiliary, a link to the stock its influence's flow runs into, so an auxiliary is
// placed beside the flows it drives instead of wherever it lands. Influences from stocks are left
// out of the layering (they would fight the flows' direction); clouds are placed afterwards.
//
// A loop of flows is the one thing layers draw badly (a line and one flow back from its end to its
// start, as long as the line), so the untangling also starts from the loops drawn as rings and
// keeps whichever start ends cheaper (``untangle``).
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
    const links = linksOf(nodes, edges, isIn);
    const kids = ins.map((n) => ({ id: n.id, width: dims.get(n.id)[0], height: dims.get(n.id)[1] }));
    const at = {};
    if (hierarchy) {
      // the system as a box of its own, the clouds outside it, and the flows across its edge laid
      // out with the rest: a stock fed from outside lands at the side its cloud is on
      const outs = nodes.filter((n) => !inside(n)), cut = [];
      for (const e of byEdge.values()) if (!isIn.has(e.source) || !isIn.has(e.target)) cut.push({ id: "c" + cut.length, sources: [e.source], targets: [e.target] });
      // with subsystems' boxes (subsystem-boxes.js: a node's ``box``), each box a compound node inside
      // the system holding its members and the flows between them; the unassigned beside the boxes
      const boxOf = new Map(ins.filter((n) => n.box != null).map((n) => [n.id, String(n.box)]));
      const sameBox = (l) => boxOf.has(l.sources[0]) && boxOf.get(l.sources[0]) === boxOf.get(l.targets[0]);
      const boxes = [...new Set(boxOf.values())].map((v) => ({ id: "__box:" + v,
        layoutOptions: { "elk.padding": `[top=${BOX_ROOM + 22},left=${BOX_ROOM},bottom=${BOX_ROOM + 14},right=${BOX_ROOM}]` },
        children: kids.filter((k) => boxOf.get(k.id) === v), edges: links.filter((l) => sameBox(l) && boxOf.get(l.sources[0]) === v) }));
      const system = { id: "__system", layoutOptions: { "elk.padding": `[top=${PAD + 12},left=${PAD},bottom=${PAD},right=${PAD}]` },
        children: [...boxes, ...kids.filter((k) => !boxOf.has(k.id))], edges: links.filter((l) => !sameBox(l)) };
      const res = await elk.layout({ id: "root", layoutOptions: { ...OPTIONS, "elk.hierarchyHandling": "INCLUDE_CHILDREN", ...options },
        children: [system, ...outs.map((n) => { const s = size(n), d = s.r ? 2 * s.r : s.w; return { id: n.id, width: d, height: d }; })],
        edges: cut });
      const walk = (c, ox, oy) => { if (c.children && c.children.length) { for (const k of c.children) walk(k, ox + c.x, oy + c.y); return; }
        if (!c.id.startsWith("__")) at[c.id] = [ox + c.x + c.width / 2, oy + c.y + c.height / 2]; };
      for (const c of res.children) walk(c, 0, 0);
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
  // What ELK lays out: every flow between two nodes inside the system (``isIn``), and a link from
  // each auxiliary to the stock its influence's flow runs into. [{id, sources: [a], targets: [b]}]
  function linksOf(nodes, edges, isIn) {
    const byEdge = new Map(edges.filter((e) => !e.toEdge).map((e) => [e.id, e])), byId = new Map(nodes.map((n) => [n.id, n]));
    const links = [], seen = new Set();
    const link = (a, b, id) => { const k = a + ">" + b; if (a === b || seen.has(k) || !isIn.has(a) || !isIn.has(b)) return; seen.add(k); links.push({ id, sources: [a], targets: [b] }); };
    for (const e of byEdge.values()) link(e.source, e.target, "f" + links.length);
    for (const e of edges.filter((x) => x.toEdge)) {
      const src = byId.get(e.source), f = byEdge.get(e.toEdge);
      if (!src || src.kind === "cloud" || src.sid || !f) continue;          // auxiliaries only
      link(e.source, isIn.has(f.target) ? f.target : f.source, "i" + links.length);
    }
    return links;
  }

  // The loops of the flows: their strongly connected parts of three nodes or more, each with its
  // longest cycle in the flows' order ([{members, cycle}]). A model has a few nodes, so the cycle
  // is found by trying every path (within a budget).
  function loopsOf(links) {
    const out = new Map();
    for (const l of links) out.set(l.sources[0], [...(out.get(l.sources[0]) || []), l.targets[0]]);
    const index = new Map(), low = new Map(), on = new Set(), stack = [], parts = [];
    const visit = (v) => {                                     // Tarjan's
      index.set(v, index.size); low.set(v, index.get(v)); stack.push(v); on.add(v);
      for (const w of out.get(v) || []) {
        if (!index.has(w)) { visit(w); low.set(v, Math.min(low.get(v), low.get(w))); }
        else if (on.has(w)) low.set(v, Math.min(low.get(v), index.get(w)));
      }
      if (low.get(v) === index.get(v)) { const part = []; let w; do { w = stack.pop(); on.delete(w); part.push(w); } while (w !== v); parts.push(part); }
    };
    for (const l of links) for (const v of [l.sources[0], l.targets[0]]) if (!index.has(v)) visit(v);
    return parts.filter((p) => p.length >= 3).map((part) => {
      const mine = new Set(part);
      let cycle = [], budget = 100000;
      const walk = (path, seen) => {
        if (--budget < 0) return;
        for (const w of (out.get(path[path.length - 1]) || []).filter((x) => mine.has(x))) {
          if (w === path[0]) { if (path.length > cycle.length) cycle = [...path]; }
          else if (!seen.has(w) && w > path[0]) { seen.add(w); path.push(w); walk(path, seen); path.pop(); seen.delete(w); }
        }
      };
      for (const v of part) walk([v], new Set([v]));
      return { members: part, cycle };
    });
  }

  // The loops drawn as rings: each loop's longest cycle on an ellipse twice as wide as tall, in its
  // order, clockwise from where material enters it on the left, its outline as long as the cycle's
  // nodes and a gap between each; the loop's other members inside the ring between their
  // neighbours, and what hangs off the loop alone (a place it fills, an auxiliary that drives it)
  // just outside, beside what it hangs off. Centred where the loop was. Returns new positions, or
  // null when there is no loop.
  const RING_GAP = 90;
  const TURNS = [0, 0.25, 0.5, 0.75];
  function rings(nodes, edges, at, { size, inside = (n) => n.kind !== "cloud", turn = 0 }) {
    const isIn = new Set(nodes.filter((n) => inside(n) && at[n.id]).map((n) => n.id)), byId = new Map(nodes.map((n) => [n.id, n]));
    const links = linksOf(nodes, edges, isIn), loops = loopsOf(links.filter((l) => l.id[0] === "f"));
    if (!loops.length) return null;
    const dims = (id) => { const z = size(byId.get(id)); return z.r ? [2 * z.r, 2 * z.r] : [z.w, z.h]; };
    const box = (id) => (byId.get(id).box == null ? null : String(byId.get(id).box));
    const nbr = new Map();
    for (const l of links) for (const [a, b] of [[l.sources[0], l.targets[0]], [l.targets[0], l.sources[0]]]) nbr.set(a, new Set([...(nbr.get(a) || []), b]));
    const out = { ...at };
    for (const { members, cycle } of loops) {
      const R = new Set(members);
      for (const v of members) for (const w of nbr.get(v) || []) if (!R.has(w) && box(w) === box(v) && [...nbr.get(w)].every((x) => R.has(x))) R.add(w);
      const ids = [...R], [cx, cy] = centreOf(at, ids);
      // where material enters: the member of the cycle with most flows into it from outside the loop
      const entering = (v) => edges.filter((e) => !e.toEdge && e.target === v && !R.has(e.source)).length;
      const first = (cycle.indexOf([...cycle].sort((a, b) => entering(b) - entering(a))[0]) + Math.round(turn * cycle.length)) % cycle.length;
      const outline = cycle.reduce((a, id) => a + (dims(id)[0] + dims(id)[1]) / 2 + RING_GAP, 0);
      const ry = outline / (Math.PI * 3.1), rx = ry * 2.1;
      const start = new Map();
      cycle.forEach((id, i) => { const t = Math.PI - 2 * Math.PI * (i - first) / cycle.length; start.set(id, [cx + rx * Math.cos(t), cy - ry * Math.sin(t)]); });
      for (let pass = 0; pass < 3; pass++) for (const id of ids) if (!cycle.includes(id)) {
        const ps = [...(nbr.get(id) || [])].map((w) => start.get(w)).filter(Boolean); if (!ps.length) continue;
        const m = [ps.reduce((a, p) => a + p[0], 0) / ps.length, ps.reduce((a, p) => a + p[1], 0) / ps.length], dx = m[0] - cx, dy = m[1] - cy, d = Math.hypot(dx, dy) || 1;
        start.set(id, ps.length > 1 ? [cx + dx * 0.55, cy + dy * 0.55] : [m[0] + dx / d * (dims(id)[0] / 2 + 100), m[1] + dy / d * (dims(id)[1] / 2 + 80)]);
      }
      for (const [id, p] of start) out[id] = p;
    }
    return out;
  }
  const centreOf = (pos, ids) => [ids.reduce((a, id) => a + pos[id][0], 0) / ids.length, ids.reduce((a, id) => a + pos[id][1], 0) / ids.length];

  const ROOM = 7;
  // the room ELK keeps inside a box around its members (its tags and title included)
  const BOX_ROOM = 30;

  // Subsystems' boxes kept apart (``boxesOf``: NetGeometry.boxesOf, a hull per box): two boxes that
  // overlap (with ``gap``) are pushed apart as wholes, and a node of no box (or of another) inside a
  // box is pushed out of it. ``half(n)``: a node's half width and height. Moves the positions ``P``
  // ({id: {n, x, y}}) in place; true when it moved one.
  function separate(P, boxesOf, half, gap = 40) {
    const placed = [...P.values()].map((p) => ({ ...p.n, x: p.x, y: p.y }));
    const hulls = Object.entries(boxesOf(placed));
    if (!hulls.length) return false;
    let moved = false;
    const shift = (ids, dx, dy) => { for (const id of ids) { const p = P.get(id); if (p) { p.x += dx; p.y += dy; } } };
    for (let i = 0; i < hulls.length; i++) for (let j = i + 1; j < hulls.length; j++) {
      const [, A] = hulls[i], [, B] = hulls[j];
      const ox = Math.min(A.x1, B.x1) - Math.max(A.x0, B.x0) + gap, oy = Math.min(A.y1, B.y1) - Math.max(A.y0, B.y0) + gap;
      if (ox <= 0 || oy <= 0) continue;
      moved = true;
      if (ox < oy) { const s = Math.sign((B.x0 + B.x1) - (A.x0 + A.x1)) || 1; shift(A.members, -s * ox / 2, 0); shift(B.members, s * ox / 2, 0); }
      else { const s = Math.sign((B.y0 + B.y1) - (A.y0 + A.y1)) || 1; shift(A.members, 0, -s * oy / 2); shift(B.members, 0, s * oy / 2); }
    }
    for (const p of P.values()) {
      const [hw, hh] = half(p.n);
      for (const [v, H] of hulls) {
        if (p.n.box != null && String(p.n.box) === v) continue;
        const r = { x0: p.x - hw - gap / 2, x1: p.x + hw + gap / 2, y0: p.y - hh - gap / 2, y1: p.y + hh + gap / 2 };
        if (!(r.x0 < H.x1 && H.x0 < r.x1 && r.y0 < H.y1 && H.y0 < r.y1)) continue;
        const opts = [[H.x0 - r.x1, 0], [H.x1 - r.x0, 0], [0, H.y0 - r.y1], [0, H.y1 - r.y0]].sort((a, b) => Math.abs(a[0] + a[1]) - Math.abs(b[0] + b[1]));
        p.x += opts[0][0]; p.y += opts[0][1]; moved = true;
      }
    }
    return moved;
  }

  // Refine a layout (ELK's) by springs: every flow, influence and cloud is a spring toward a
  // sensible length, and a node moves in inverse proportion to how connected it is, so a node with
  // one connection comes in to it while busy stocks hold the structure. Nodes push apart only
  // where they overlap, and a stock keeps ``ROOM`` px more room per flow so its flows can be seen.
  // A stock with flows from or to outside is drawn toward the nearest side of the frame, so its
  // clouds' stubs are short. Returns new positions; clouds placed by the cloud rule.
  // A flow with a label is given room for it (``labelSize``): its rest length is at least the
  // label's width, so the words fit beside the line instead of on a box.
  function refine(nodes, edges, at, { size, inside = (n) => n.kind !== "cloud", frameOf, tetherPlaces, boxesOf = null, iterations = 300, gap = 70, outwardK = 0.06, influenceGap = 40, labelSize = null }) {
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
    const boxes = !!boxesOf && [...P.values()].some((p) => p.n.box != null);
    for (let it = 0; it < iterations; it++) {
      if (boxes) separate(P, boxesOf, half);
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
      // (the frame of the nodes alone: a frame around subsystems' boxes would draw a stock ever outward)
      const b = frameOf ? frameOf([...P.values()].map((p) => ({ ...p.n, x: p.x, y: p.y, box: undefined })), inside) : null;
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
    // subsystems' boxes: apart, and nothing of another box or of none inside one
    if (boxes) for (let k = 0; k < 200 && separate(P, boxesOf, half); k++);
    const out = { ...at };
    for (const [id, p] of P) out[id] = [p.x, p.y];
    if (frameOf && tetherPlaces) {
      const placed = nodes.map((n) => (P.has(n.id) ? { ...n, x: out[n.id][0], y: out[n.id][1] } : { ...n, x: undefined, y: undefined }));
      Object.assign(out, tetherPlaces(placed, frameOf(placed, inside), edges));
    }
    return out;
  }

  // The groups of a graph: what is connected inside the system (by flows between its nodes, and
  // by influences). [[node id]], biggest first. An influence from a subsystem's box into another
  // box's flow joins no boxes (each box is a whole of its own); ``loose``: no influence from a
  // stock joins either, so the parts the flows make are groups of their own.
  function groupsOf(nodes, edges, inside = (n) => n.kind !== "cloud", loose = false) {
    const ids = nodes.filter(inside).map((n) => n.id), parent = new Map(ids.map((id) => [id, id]));
    const find = (x) => { while (parent.get(x) !== x) x = parent.get(x); return x; };
    const join = (a, b) => { if (parent.has(a) && parent.has(b)) parent.set(find(a), find(b)); };
    const flowById = new Map(edges.filter((e) => !e.toEdge).map((e) => [e.id, e]));
    for (const e of flowById.values()) join(e.source, e.target);
    const stock = new Set(nodes.filter((n) => n.sid).map((n) => n.id)), boxOf = new Map(nodes.filter((n) => n.box != null).map((n) => [n.id, String(n.box)]));
    const across = (e, f) => boxOf.has(e.source) && [f.source, f.target].some((x) => boxOf.has(x) && boxOf.get(x) !== boxOf.get(e.source));
    for (const e of edges.filter((x) => x.toEdge)) {
      const f = flowById.get(e.toEdge);
      if (f && !across(e, f) && !(loose && stock.has(e.source))) { join(e.source, f.source); join(e.source, f.target); }
    }
    // a subsystem's box moves as one: its members are of one group, connected or not
    const first = new Map();
    for (const n of nodes) if (n.box != null && parent.has(n.id)) { const k = String(n.box); if (first.has(k)) join(n.id, first.get(k)); else first.set(k, n.id); }
    return [...ids.reduce((m, id) => m.set(find(id), [...(m.get(find(id)) || []), id]), new Map()).values()].sort((a, b) => b.length - a.length);
  }

  // Pack the groups side by side in rows to fill a view of ``aspect`` (width / height), each keeping
  // its own internal layout, so no group sits among another's lines and the drawing fits a wide view.
  // ``loose``: the groups as groupsOf counts them loosely (the parts the flows make)
  function pack(nodes, edges, at, { size, inside = (n) => n.kind !== "cloud", aspect = 2.1, gap = 90, frameOf, tetherPlaces, loose = false }) {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const boxes = groupsOf(nodes, edges, inside, loose).map((g) => {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const id of g) { const z = size(byId.get(id)), hw = z.r || z.w / 2, hh = z.r || z.h / 2, [x, y] = at[id]; x0 = Math.min(x0, x - hw); x1 = Math.max(x1, x + hw); y0 = Math.min(y0, y - hh); y1 = Math.max(y1, y + hh); }
      return { g, x0, y0, w: x1 - x0, h: y1 - y0 };
    }).sort((a, b) => b.h - a.h);
    const area = boxes.reduce((a, b) => a + (b.w + gap) * (b.h + gap), 0);
    // rows ``width`` wide: the places, and how wide and tall they are
    const rows = (width) => {
      const out = { ...at };
      let x = 0, y = 0, rowH = 0, W = 0;
      for (const b of boxes) {
        if (x > 0 && x + b.w > width) { x = 0; y += rowH + gap; rowH = 0; }
        for (const id of b.g) out[id] = [at[id][0] - b.x0 + x, at[id][1] - b.y0 + y];
        x += b.w + gap; rowH = Math.max(rowH, b.h); W = Math.max(W, x - gap);
      }
      return { out, W, H: y + rowH };
    };
    // the width by area, unless another row break fits the view larger (a few groups of unlike
    // sizes can fill it better than their area says), with the clouds' room around
    const fit = (r) => Math.min(aspect / (r.W + 160), 1 / (r.H + 160));
    let best = rows(Math.max(Math.sqrt(area * aspect), ...boxes.map((b) => b.w)));
    for (let k = 0, w = 0; k < boxes.length; k++) { w += boxes[k].w + (k ? gap : 0); const r = rows(w + 1); if (fit(r) > fit(best) * 1.02) best = r; }
    const out = best.out;
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
    + 5000 * (s.boxOverlaps ? s.boxOverlaps.length : 0)   // a subsystem's box over another, or over a node not its own: never either
    + 40 * (s.labelsOnNodes ? s.labelsOnNodes.length : 0) + 25 * (s.labelsOnLabels || 0)
    + 0.02 * s.nearest.max + 0.02 * s.influenceLength.median + 2 * (s.emptiness || 0)
    + 150 * Math.max(0, 1 - (s.scale ?? 1))   // shrunk to fit the view: smaller words, so worth about five crossings at half size
    // a line longer than reads as joining two things (a flow past 280 px, a stub or an influence
    // past 460): 20 px more worth a point, so a crossing's worth of length is 600 px
    + 0.05 * (Math.max(0, s.flowLength.max - 280) + Math.max(0, s.stubLength.max - 460) + Math.max(0, s.influenceLength.max - 460));
  // ``labels(placed)``, when given, places the edge labels ({edge id: [x, y]}) so words covered by
  // boxes or other words count too (``labelSize`` sizes them)
  // ``fixed``: node ids that stay where they are (the viewer's placements)
  //
  // Where it starts from matters (a local search keeps the shape it is given), so it starts from
  // more than one place and keeps the cheapest end (``settle``): the layout as given and, when the
  // flows make loops, the loops drawn as rings. With subsystems' boxes, each box is settled on its
  // own first and the boxes then packed side by side to fit the view, so a box keeps the shape its
  // own flows give it; without boxes, the parts the flows make (an influence from a stock joins
  // none) are tried that way too, against the parts as they were placed together. The viewer's
  // placements (``fixed``) are untangled around, from where they are.
  function untangle(nodes, edges, at, opts) {
    const { inside = (n) => n.kind !== "cloud", boxesOf = null, fixed = [] } = opts;
    if (fixed.length) return search(nodes, edges, at, opts).at;
    const boxed = !!boxesOf && nodes.some((n) => inside(n) && n.box != null);
    const parts = boxed ? [...new Set(nodes.filter((n) => inside(n) && n.box != null).map((n) => String(n.box)))].map((v) => nodes.filter((n) => inside(n) && n.box != null && String(n.box) === v).map((n) => n.id))
      : groupsOf(nodes, edges, inside, true);
    if (!boxed && parts.length < 2) return settle(nodes, edges, at, opts).at;
    const tries = [search(nodes, edges, apart(nodes, edges, at, parts, opts, !boxed), { ...opts, loose: !boxed })];
    if (!boxed) tries.unshift(search(nodes, edges, at, opts));
    return tries.reduce((a, b) => (b.cost < a.cost - 1e-6 ? b : a)).at;
  }
  // the cheapest end of the search from ``at`` and from the loops drawn as rings (``rings``, each
  // of a few turns, then packed and sprung as a layout is): {at, cost}
  function settle(nodes, edges, at, opts) {
    const { size, inside = (n) => n.kind !== "cloud", frameOf, tetherPlaces, boxesOf = null, labelSize = null } = opts, geo = { size, inside, frameOf, tetherPlaces, boxesOf };
    const tries = [search(nodes, edges, at, opts)];
    for (const turn of TURNS) { const r = rings(nodes, edges, at, { ...geo, turn }); if (!r) break; tries.push(search(nodes, edges, refine(nodes, edges, pack(nodes, edges, r, geo), { ...geo, labelSize }), opts)); }
    return tries.reduce((a, b) => (b.cost < a.cost - 1e-6 ? b : a));
  }
  // ``parts`` ([[id]]: boxes, or the parts the flows make) each settled on its own (its members,
  // their clouds, the flows and influences among them), kept where it was, then packed (``loose``:
  // as groupsOf counts loosely)
  function apart(nodes, edges, at, parts, opts, loose) {
    const { inside = (n) => n.kind !== "cloud", size, frameOf, tetherPlaces } = opts;
    const cur = { ...at };
    for (const part of parts) {
      const mine = new Set(part);
      const sub = nodes.filter((n) => mine.has(n.id) || (!inside(n) && n.tether && mine.has(n.tether))).map((n) => ({ ...n, box: undefined }));
      const has = new Set(sub.map((n) => n.id)), flows = edges.filter((e) => !e.toEdge && has.has(e.source) && has.has(e.target)), fid = new Set(flows.map((e) => e.id));
      const subEdges = [...flows, ...edges.filter((e) => e.toEdge && has.has(e.source) && fid.has(e.toEdge))];
      const r = settle(sub, subEdges, Object.fromEntries(sub.filter((n) => cur[n.id]).map((n) => [n.id, cur[n.id]])), { ...opts, boxesOf: null }).at;
      const c0 = centreOf(cur, part), c1 = centreOf(r, part);
      for (const id of part) cur[id] = [r[id][0] - c1[0] + c0[0], r[id][1] - c1[1] + c0[1]];
    }
    return pack(nodes, edges, cur, { size, inside, frameOf, tetherPlaces, loose });
  }
  // the local search from ``at``: {at, cost}. ``loose``: groups move as groupsOf counts them loosely
  function search(nodes, edges, at, { size, score, inside = (n) => n.kind !== "cloud", frameOf, tetherPlaces, boxesOf = null, labels = null, labelSize = null, passes = 4, steps = [60, 120], groupSteps = [120, 240, 400], view = [1300, 600], fixed = [], loose = false }) {
    const hold = new Set(fixed);
    const ids = nodes.filter((n) => inside(n) && at[n.id] && !hold.has(n.id)).map((n) => n.id), byId = new Map(nodes.map((n) => [n.id, n]));
    let cur = { ...at };
    const evaluate = (pos) => {
      const placed = nodes.map((n) => (inside(n) ? { ...n, x: pos[n.id][0], y: pos[n.id][1] } : { ...n, x: undefined, y: undefined }));
      const frame = frameOf(placed, inside), clouds = tetherPlaces(placed, frame, edges);
      for (const n of placed) if (clouds[n.id]) [n.x, n.y] = clouds[n.id];
      const sc = score(placed, edges, { size, frame, inside, labels: labels ? labels(placed) : null, labelSize, boxes: boxesOf ? boxesOf(placed) : null });
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
      return new Set(score(placed, edges, { size, frame, inside, labels: labels ? labels(placed) : null, labelSize, boxes: boxesOf ? boxesOf(placed) : null }).tangled || ids);
    };
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
    const joined = new Map(), inId = new Set(ids);
    for (const e of edges.filter((x) => !x.toEdge && inId.has(x.source) && byId.has(x.target) && inside(byId.get(x.target))))
      for (const [a, b] of [[e.source, e.target], [e.target, e.source]]) joined.set(a, new Set([...(joined.get(a) || []), b]));
    // groups move as a whole too, so a group can step out of another's way instead of sitting among its lines
    const groups = groupsOf(nodes, edges, inside, loose).filter((g) => !g.some((id) => hold.has(id)));   // a group with a held node stays
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
      // a jump for a node: just beside each node a flow joins it to, all round it
      const half = (id) => { const z = size(byId.get(id)); return z.r ? [z.r, z.r] : [z.w / 2, z.h / 2]; };
      for (const id of ids.filter((x) => busy.has(x))) for (const o of joined.get(id) || []) {
        const [ow, oh] = half(o), [w, h] = half(id);
        for (const [dx, dy] of dirs) for (const g of [70, 140]) {
          const next = { ...cur, [id]: [cur[o][0] + dx * (ow + w + g), cur[o][1] + dy * (oh + h + g)] }, r = evaluate(next);
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
      // a jump: a group with an influence into another group's flow, its source beside the flow's
      // middle, all round it, so the influence is short
      for (const g of groups) {
        const own = new Set(g);
        for (const inf of edges.filter((e) => e.toEdge && own.has(e.source))) {
          const f = flows.get(inf.toEdge), m = f && !own.has(f.source) && !own.has(f.target) && mid(cur, f); if (!m) continue;
          for (const [dx, dy] of dirs) for (const r of [180, 280]) {
            const next = shift(cur, g, m[0] + dx * r * 1.4 - cur[inf.source][0], m[1] + dy * r * 0.8 - cur[inf.source][1]), res = evaluate(next);
            if (res.cost < best.cost - 1e-6) { cur = next; best = res; improved = true; }
          }
        }
      }
      // a jump: a group in a problem tried just beside each other group (left, right, above, below
      // its box), so it can get out from between another group's lines
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
    return { at: { ...cur, ...best.clouds }, cost: best.cost };
  }

  return { layout, pack, refine, untangle, rings, OPTIONS };
});
