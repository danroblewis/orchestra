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
  // the least scale an automatic fit draws a wide screen's graph at (names stay readable)
  const DESK_K = 0.85;
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
      // a focus's stub (focus.js) is named under or over itself on a top or bottom side: as wide as its name
      // (a cloud's name runs to its right: twice that, centred on it), counted only beside a stub
      out[n.id].w = !n.label ? 0 : n.stub ? String(n.label).length * 5.8 + 12 : 2 * (String(n.label).length * 5.8 + 20);
      out[n.id].stub = !!n.stub;
    }
    // clouds on one side never sit on each other: spread them along it, at least SPREAD apart (and a
    // stub's name clear of its neighbours')
    const SPREAD = 38;
    for (const side of ["t", "b", "l", "r"]) {
      const along = side === "t" || side === "b" ? 0 : 1;
      const row = Object.values(out).filter((p) => p.side === side).sort((p, q) => p[along] - q[along]);
      for (let i = 1; i < row.length; i++) row[i][along] = Math.max(row[i][along], row[i - 1][along] + (along || !(row[i - 1].stub || row[i].stub) ? SPREAD : Math.max(SPREAD, (row[i - 1].w + row[i].w) / 2)));
    }
    for (const p of Object.values(out)) { delete p.w; delete p.stub; }
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
  // ``obstacles``: more boxes no label should cover ([x0, y0, x1, y1]: a node's tags, the frame's title).
  // A node's tags stacked above (or below) it are covered by its box too
  function tagBoxes(n) {
    const s = size(n), hh = s.r || s.h / 2, out = [];
    (n.tags || []).filter((t) => !t.below).forEach((t, i) => { const w = String(t.text).length * 5.6 + 10, y = n.y - hh - 18 - i * 15; out.push([n.x - w / 2, y, n.x + w / 2, y + 13]); });
    (n.tags || []).filter((t) => t.below).forEach((t, i) => { const w = String(t.text).length * 5.6 + 10, y = n.y + hh + (s.r ? (n.sub ? 30 : 18) : 4) + i * 15; out.push([n.x - w / 2, y, n.x + w / 2, y + 13]); });
    return out;
  }
  function placeLabels(nodes, edges, mids, obstacles = []) {
    const boxes = [...nodes.filter((n) => n.x !== undefined).flatMap((n) => { const s = size(n), hw = (s.r || s.w / 2) + 2, hh = (s.r || s.h / 2) + 2; return [[n.x - hw, n.y - hh, n.x + hw, n.y + hh], ...tagBoxes(n)]; }), ...obstacles];
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

  // the nodes linked to nothing, set in rows directly under the rest (``rest``: the connected
  // nodes), as wide at most as the rest (or ``minRow`` nodes), so the fit that shows the connected
  // part shows them too: {id: [x, y]}
  function isolatedRows(lone, rest, gap = 130, minRow = 4) {
    if (!lone.length || !rest.length) return {};
    let x0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of rest) { const s = size(n), hw = s.r || s.w / 2, hh = s.r || s.h / 2; x0 = Math.min(x0, n.x - hw); x1 = Math.max(x1, n.x + hw); y1 = Math.max(y1, n.y + hh); }
    const per = Math.max(minRow, Math.floor((x1 - x0) / gap) + 1), cx = (x0 + x1) / 2, out = {};
    [...lone].sort((a, b) => String(a.label).localeCompare(String(b.label))).forEach((n, i) => {
      const row = Math.floor(i / per), inRow = Math.min(per, lone.length - row * per), j = i - row * per;
      out[n.id] = [cx + (j - (inRow - 1) / 2) * gap, y1 + 56 + row * 70];
    });
    return out;
  }
  // the transform that fits the box [x0, y0, x1, y1] in a view ``w`` wide and ``h`` high, under a band
  // ``top`` high, at no more than ``maxK``; an automatic fit (not ``all``) at no less than ``minK``,
  // centred: {k, tx, ty}
  function fitView([x0, y0, x1, y1], { w, h, top = 40, maxK = 1.4, minK = 0, all = false } = {}) {
    const room = h - top, kFit = Math.min(w / (x1 - x0), room / (y1 - y0), maxK), k = all ? kFit : Math.max(minK, kFit);
    return { k, kFit, tx: w / 2 - k * (x0 + x1) / 2, ty: top + room / 2 - k * (y0 + y1) / 2 };
  }
  // the box a set of nodes covers, with ``pad`` around each
  function boundsOf(nodes, pad = 40) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of nodes) { const s = size(n), hw = (s.r || s.w / 2) + pad, hh = (s.r || s.h / 2) + pad; x0 = Math.min(x0, n.x - hw); x1 = Math.max(x1, n.x + hw); y0 = Math.min(y0, n.y - hh); y1 = Math.max(y1, n.y + hh); }
    return [x0, y0, x1, y1];
  }

  // a desktop drawing's height: the viewport's, less what must stay on screen with it (the page's
  // header, the drawing's own bar and legend), at least ``min`` and at most ``max``
  const VIEW_MIN = 600, VIEW_MAX = 1100;
  function viewHeight(viewport, used, { min = VIEW_MIN, max = VIEW_MAX } = {}) {
    return Math.round(Math.max(min, Math.min(max, (viewport || 0) - (used || 0))));
  }

  // what a redraw does to the layout. With ``resetOnStructure`` (the owner, 2026-11-02: "load the page
  // and it already be in the position it would be after hitting Reset, and run the Reset operation
  // when a new graph is generated"), a drawing whose structure is new (the first, a new version, a
  // focus) is laid out exactly as the reset button lays it out: "reset"; while the viewer is
  // dragging a node, once the drag ends: "defer". Otherwise (the same structure, new data): "keep".
  function onRender({ resetOnStructure = false, structural = false, dragging = false } = {}) {
    if (!resetOnStructure || !structural) return "keep";
    return dragging ? "defer" : "reset";
  }

  return { size, edgePoint, onRender, frameOf, tetherPlaces, labelSize, placeLabels, tagBoxes, isolatedRows, fitView, boundsOf, viewHeight, PAD, GAP, DESK_K, VIEW_MIN, VIEW_MAX };
})();
if (typeof module === "object" && module.exports) module.exports = NetGeometry;
