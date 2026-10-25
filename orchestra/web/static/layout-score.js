// How good a drawn graph's layout is, as numbers: used by the layout tests (tests/layout) and
// available in the browser (LayoutScore.score) to measure what is on screen.
//
// Input: nodes with x, y (centres) and their sizes (NetGraph.size), and edges as NetGraph takes
// them (source, target, or toEdge for an influence into a flow's middle). Edges are measured as
// straight lines between the nodes' outlines; the renderer bends them a little.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.LayoutScore = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const box = (n, size, pad = 0) => { const s = size(n), hw = (s.r || s.w / 2) + pad, hh = (s.r || s.h / 2) + pad; return { x0: n.x - hw, x1: n.x + hw, y0: n.y - hh, y1: n.y + hh }; };
  const overlap = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  // where the line from a's centre toward (x, y) leaves a's outline
  function exit(n, size, x, y) {
    const dx = x - n.x, dy = y - n.y, s = size(n);
    if (!dx && !dy) return { x: n.x, y: n.y };
    if (s.r) { const d = Math.hypot(dx, dy); return { x: n.x + dx / d * s.r, y: n.y + dy / d * s.r }; }
    const k = Math.min((s.w / 2) / Math.abs(dx || 1e-9), (s.h / 2) / Math.abs(dy || 1e-9), 1);
    return { x: n.x + dx * k, y: n.y + dy * k };
  }
  const cross = (p1, p2, p3, p4) => {
    const d = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
    const d1 = d(p3, p4, p1), d2 = d(p3, p4, p2), d3 = d(p1, p2, p3), d4 = d(p1, p2, p4);
    return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0)) && d1 && d2 && d3 && d4;
  };
  // does the segment p→q pass through box b
  function through(p, q, b) {
    const steps = 24;
    for (let i = 1; i < steps; i++) {
      const x = p.x + (q.x - p.x) * i / steps, y = p.y + (q.y - p.y) * i / steps;
      if (x > b.x0 && x < b.x1 && y > b.y0 && y < b.y1) return true;
    }
    return false;
  }
  const median = (xs) => { if (!xs.length) return 0; const s = [...xs].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };

  // ``frame``: the system's box ({x0, y0, x1, y1}) when there is one
  function score(nodes, edges, { size, frame = null, inside = (n) => n.kind !== "cloud" } = {}) {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const flows = edges.filter((e) => !e.toEdge && byId.has(e.source) && byId.has(e.target)).map((e) => {
      const a = byId.get(e.source), b = byId.get(e.target), p = exit(a, size, b.x, b.y), q = exit(b, size, a.x, a.y);
      return { e, a, b, p, q, len: Math.hypot(q.x - p.x, q.y - p.y), mid: { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 },
               outside: a.kind === "cloud" || b.kind === "cloud" };
    });
    const flowById = new Map(flows.map((f) => [f.e.id, f]));
    const links = edges.filter((e) => e.toEdge && byId.has(e.source) && flowById.has(e.toEdge)).map((e) => {
      const a = byId.get(e.source), m = flowById.get(e.toEdge).mid, p = exit(a, size, m.x, m.y);
      return { e, a, p, q: m, len: Math.hypot(m.x - p.x, m.y - p.y) };
    });
    const out = { nodes: nodes.length, flows: flows.length, influences: links.length };
    // nodes on top of each other (10 px apart at least)
    out.overlaps = [];
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++)
      if (overlap(box(nodes[i], size, 5), box(nodes[j], size, 5))) out.overlaps.push([nodes[i].id, nodes[j].id]);
    // flows that cross each other (not at a shared end)
    out.crossings = 0;
    for (let i = 0; i < flows.length; i++) for (let j = i + 1; j < flows.length; j++) {
      const f = flows[i], g = flows[j];
      if ([f.a, f.b].some((n) => n === g.a || n === g.b)) continue;
      if (cross(f.p, f.q, g.p, g.q)) out.crossings++;
    }
    // flows and influences drawn through a node that is not one of their ends
    out.through = [];
    for (const f of [...flows, ...links]) for (const n of nodes) {
      if (n === f.a || n === f.b || (f.e.toEdge && (n === flowById.get(f.e.toEdge).a || n === flowById.get(f.e.toEdge).b))) continue;
      if (through(f.p, f.q, box(n, size, -3))) out.through.push([f.e.id, n.id]);
    }
    const inner = flows.filter((f) => !f.outside), stubs = flows.filter((f) => f.outside);
    out.flowLength = { max: Math.round(Math.max(0, ...inner.map((f) => f.len))), median: Math.round(median(inner.map((f) => f.len))) };
    out.stubLength = { max: Math.round(Math.max(0, ...stubs.map((f) => f.len))), median: Math.round(median(stubs.map((f) => f.len))) };
    out.influenceLength = { max: Math.round(Math.max(0, ...links.map((f) => f.len))), median: Math.round(median(links.map((f) => f.len))) };
    out.longest = [...inner, ...stubs, ...links].sort((a, b) => b.len - a.len).slice(0, 3).map((f) => [f.e.id, Math.round(f.len)]);
    if (frame) {
      out.cloudsInside = nodes.filter((n) => !inside(n) && overlap(box(n, size), frame)).map((n) => n.id);
      out.outsideFrame = nodes.filter((n) => inside(n) && !overlap(box(n, size), frame)).map((n) => n.id);
      const area = nodes.filter(inside).reduce((a, n) => { const b = box(n, size); return a + (b.x1 - b.x0) * (b.y1 - b.y0); }, 0);
      out.emptiness = +(((frame.x1 - frame.x0) * (frame.y1 - frame.y0)) / Math.max(1, area)).toFixed(2);   // frame area per node area
    }
    return out;
  }
  return { score };
});
