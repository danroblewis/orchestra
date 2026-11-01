// The network renderer's pure geometry (netgraph.js draws with it): node sizes and outlines, the
// frame around the system and where its clouds sit, and where edge labels go. No DOM and no d3, so
// the layout worker (layout-worker.js) and the layout tests (tests/layout) use the same code the
// page draws with.
const NetGeometry = (() => {
  // a node's drawn size: a radius, or a box's width and height
  function size(n) {
    if (n.kind === "circle") return { r: n.r || 22 };
    if (n.kind === "valve") return { r: 7 };
    if (n.kind === "cloud") return { r: 11 };
    const lines = n.lines || [n.label];
    const w = n.w || Math.max(80, Math.max(...lines.map((l) => String(l).length)) * 7 + 22);
    const h = n.h || 14 + lines.length * 14 + (n.sub ? 14 : 0);
    return { w, h };
  }
  // where a line from (x, y) toward node n meets its outline
  function edgePoint(n, x, y, pad = 2) {
    const dx = x - n.x, dy = y - n.y, d = Math.hypot(dx, dy) || 1, s = size(n);
    if (s.r) return { x: n.x + dx / d * (s.r + pad), y: n.y + dy / d * (s.r + pad) };
    const hw = s.w / 2 + pad, hh = s.h / 2 + pad, k = Math.min(hw / Math.abs(dx || 1e-9), hh / Math.abs(dy || 1e-9));
    return { x: n.x + dx * k, y: n.y + dy * k };
  }

  // the frame and the clouds
  const PAD = 34, GAP = 34;
  // the box around the nodes ``inside`` the system, padded
  function frameOf(nodes, inside) {
    const ins = nodes.filter((n) => inside(n) && n.x !== undefined);
    if (!ins.length) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of ins) { const s = size(n), hw = s.r || s.w / 2, hh = s.r || s.h / 2; x0 = Math.min(x0, n.x - hw); x1 = Math.max(x1, n.x + hw); y0 = Math.min(y0, n.y - hh); y1 = Math.max(y1, n.y + hh); }
    return { x0: x0 - PAD, y0: y0 - PAD - 12, x1: x1 + PAD, y1: y1 + PAD };
  }
  // where each tethered node goes: just outside the frame, level with the node it belongs to, on
  // the side whose stub crosses the fewest lines and boxes (with ``edges``; nearest side first among
  // equals, so with no edges it is simply the nearest side); several on one side of one node sit
  // side by side, and clouds along a side never sit on each other. {id: [x, y]}
  const segCross = (p1, p2, p3, p4) => {
    const d = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    const d1 = d(p3, p4, p1), d2 = d(p3, p4, p2), d3 = d(p1, p2, p3), d4 = d(p1, p2, p4);
    return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0)) && d1 && d2 && d3 && d4;
  };
  const segBox = (p, q, b) => { for (let i = 1; i < 16; i++) { const x = p[0] + (q[0] - p[0]) * i / 16, y = p[1] + (q[1] - p[1]) * i / 16; if (x > b[0] && x < b[2] && y > b[1] && y < b[3]) return true; } return false; };
  function tetherPlaces(nodes, b, edges = null) {
    const byId = new Map(nodes.map((n) => [n.id, n])), count = new Map(), out = {};
    if (!b) return out;
    const spot = (s, side, i) => {
      const off = (i % 2 ? 1 : -1) * Math.ceil(i / 2) * 38;              // 0, -38, +38, -76…
      return side === "t" ? [s.x + off, b.y0 - GAP] : side === "b" ? [s.x + off, b.y1 + GAP] : side === "l" ? [b.x0 - GAP, s.y + off] : [b.x1 + GAP, s.y + off];
    };
    // the lines a stub must not cross: flows between placed nodes inside, and influences into them
    const placedIn = (id) => { const n = byId.get(id); return n && n.x !== undefined && !n.tether; };
    const lines = [];
    if (edges) {
      const mid = {};
      for (const e of edges) if (!e.toEdge && placedIn(e.source) && placedIn(e.target)) {
        const a = byId.get(e.source), c = byId.get(e.target); lines.push({ e, p: [a.x, a.y], q: [c.x, c.y] }); mid[e.id] = [(a.x + c.x) / 2, (a.y + c.y) / 2];
      }
      for (const e of edges) if (e.toEdge && placedIn(e.source) && mid[e.toEdge]) { const a = byId.get(e.source); lines.push({ e, p: [a.x, a.y], q: mid[e.toEdge] }); }
    }
    const boxes = nodes.filter((n) => n.x !== undefined && !n.tether).map((n) => { const z = size(n), hw = z.r || z.w / 2, hh = z.r || z.h / 2; return { n, b: [n.x - hw, n.y - hh, n.x + hw, n.y + hh] }; });
    for (const n of nodes) {
      const s = n.tether && byId.get(n.tether);
      if (!s || s.x === undefined) continue;
      const near = [[s.x - b.x0, "l"], [b.x1 - s.x, "r"], [s.y - b.y0, "t"], [b.y1 - s.y, "b"]].sort((u, v) => u[0] - v[0]);
      let side = near[0][1];
      if (edges) {
        let best = Infinity;
        for (const [dist, sd] of near) {
          const q = spot(s, sd, 0), p = [s.x, s.y];
          let crossings = lines.filter((l) => l.e.source !== s.id && l.e.target !== s.id && segCross(p, q, l.p, l.q)).length;
          // and the influences that point at this stub's middle, from where they start
          const stub = edges.find((e) => !e.toEdge && ((e.source === n.id && e.target === s.id) || (e.source === s.id && e.target === n.id)));
          if (stub) {
            const m = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
            for (const inf of edges.filter((e) => e.toEdge === stub.id && placedIn(e.source))) {
              const a = byId.get(inf.source), from = [a.x, a.y];
              crossings += lines.filter((l) => l.e.source !== inf.source && l.e.target !== inf.source && l.e.source !== s.id && l.e.target !== s.id && segCross(from, m, l.p, l.q)).length;
            }
          }
          const through = boxes.filter((x) => x.n !== s && segBox(p, q, x.b)).length;
          const cost = 300 * crossings + 1000 * through + dist;   // a crossing is worth 300 px of longer stub, no more
          if (cost < best) { best = cost; side = sd; }
        }
      }
      const k = `${s.id}|${side}`, i = count.get(k) || 0;
      count.set(k, i + 1);
      out[n.id] = spot(s, side, i);
      out[n.id].side = side;
    }
    // clouds on one side never sit on each other: spread them along it, at least SPREAD apart
    const SPREAD = 38;
    for (const side of ["t", "b", "l", "r"]) {
      const along = side === "t" || side === "b" ? 0 : 1;
      const row = Object.values(out).filter((p) => p.side === side).sort((p, q) => p[along] - q[along]);
      for (let i = 1; i < row.length; i++) row[i][along] = Math.max(row[i][along], row[i - 1][along] + SPREAD);
    }
    return out;
  }

  // a label's box, from its text (10.5 px type: about 5.9 px a character, 12 px a line), centred on
  // its anchor; a sign alone (+, −) is a small box
  function labelSize(e) {
    const lines = e.label ? (Array.isArray(e.label) ? e.label : [e.label]).filter(Boolean) : [];
    if (!lines.length) return e.sign ? { w: 12, h: 16 } : null;
    return { w: Math.max(...lines.map((l) => String(l).length)) * 5.9 + 6, h: lines.length * 12 + 4 };
  }
  const OFFSETS = [[0, 0]];
  for (const r of [16, 30, 46, 64, 84, 106]) for (const [ux, uy] of [[0, -1], [0, 1], [-1, 0], [1, 0], [-1, -1], [1, -1], [-1, 1], [1, 1]]) OFFSETS.push([ux * r * (ux && uy ? 0.8 : 1) * (ux ? 1.6 : 1), uy * r * (ux && uy ? 0.8 : 1)]);
  // where each label goes: the nearest spot to its line's middle (``mids``: {edge id: {x, y}})
  // where it covers no node and no label already placed; if there is none, where it covers least.
  // Longer labels are placed first. {edge id: [dx, dy]}
  function placeLabels(nodes, edges, mids) {
    const boxes = nodes.filter((n) => n.x !== undefined).map((n) => { const s = size(n), hw = (s.r || s.w / 2) + 2, hh = (s.r || s.h / 2) + 2; return [n.x - hw, n.y - hh, n.x + hw, n.y + hh]; });
    const area = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
    const out = {}, placed = [];
    const todo = edges.filter((e) => mids[e.id] && labelSize(e)).sort((a, b) => labelSize(b).w - labelSize(a).w);
    for (const e of todo) {
      const m = mids[e.id], s = labelSize(e);
      let best = null;
      for (const [dx, dy] of OFFSETS) {
        const b = [m.x + dx - s.w / 2, m.y + dy - s.h / 2, m.x + dx + s.w / 2, m.y + dy + s.h / 2];
        const cost = boxes.reduce((a, x) => a + area(b, x), 0) + placed.reduce((a, x) => a + 2 * area(b, x), 0);
        if (!best || cost < best.cost - 1e-9) best = { cost, dx, dy, b };
        if (cost === 0) break;
      }
      out[e.id] = [best.dx, best.dy];
      placed.push(best.b);
    }
    return out;
  }

  return { size, edgePoint, frameOf, tetherPlaces, labelSize, placeLabels, PAD, GAP };
})();
if (typeof module === "object" && module.exports) module.exports = NetGeometry;
