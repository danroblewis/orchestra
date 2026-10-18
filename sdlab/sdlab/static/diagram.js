// Stock and flow diagrams, shared by the editor (app.js) and the ladder page (ladder.js).
//
//   geometry   center, clip, shorten: a stock is a box; arrows start and end on its edge
//   svg        el, text, arrowHead, cloud: the marks every diagram is made of
//   layout     columns: related stocks in columns from upstream to downstream, ordered within a
//              column so related stocks sit side by side (the editor's Arrange uses it);
//              layout: whole positions for a small model, the same every time for the same model
//   draw       a read-only diagram: stocks as boxes (dashed when nobody measures them), flows as
//              thick arrows (clouds for outside), links from the stocks an equation reads (dashed),
//              effects (dashed, labelled) and co-flows (dotted, "uses"), each coloured by a class
(function (root) {
  "use strict";
  const BOX = { w: 150, h: 64 };
  const SVGNS = "http://www.w3.org/2000/svg";

  const center = (s, box = BOX) => ({ x: s.x + box.w / 2, y: s.y + box.h / 2 });
  function clip(s, toward, box = BOX) {
    const c = center(s, box), dx = toward.x - c.x, dy = toward.y - c.y;
    if (!dx && !dy) return c;
    const k = Math.min(dx ? (box.w / 2) / Math.abs(dx) : Infinity, dy ? (box.h / 2) / Math.abs(dy) : Infinity);
    return { x: c.x + dx * k, y: c.y + dy * k };
  }
  function shorten(p, toward, d) {
    const dx = toward.x - p.x, dy = toward.y - p.y, L = Math.hypot(dx, dy) || 1;
    return { x: p.x + dx / L * d, y: p.y + dy / L * d };
  }
  function el(tag, attrs, parent) {
    const e = root.document.createElementNS(SVGNS, tag);
    for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(parent, x, y, str, attrs) { const t = el("text", { x, y, ...attrs }, parent); t.textContent = str; return t; }
  function arrowHead(parent, from, to, col, size) {
    const dx = to.x - from.x, dy = to.y - from.y, L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L;
    const bx = to.x - ux * size, by = to.y - uy * size, w = size * 0.55;
    return el("polygon", { points: `${to.x},${to.y} ${bx - uy * w},${by + ux * w} ${bx + uy * w},${by - ux * w}`, fill: col }, parent);
  }
  function cloud(parent, p, attrs) {
    const g = el("g", { class: "cloud", fill: "var(--canvas)", stroke: "var(--muted)", "stroke-width": 1.3, ...attrs }, parent);
    el("circle", { cx: p.x - 7, cy: p.y + 2, r: 8 }, g);
    el("circle", { cx: p.x + 7, cy: p.y + 2, r: 8 }, g);
    el("circle", { cx: p.x, cy: p.y - 5, r: 8 }, g);
    return g;
  }

  // ---------- layout ----------
  // One connected group of stocks in columns: the longest chain of flows leading to a stock decides
  // its column (cycles are cut), then a few sweeps order each column by its neighbours' places.
  // inn / out: Map id -> [ids]. Returns the columns, each a list of ids top to bottom.
  function columns(group, inn, out, nameOf) {
    const col = new Map(), onPath = new Set();
    const visit = (a) => {
      if (col.has(a)) return col.get(a);
      if (onPath.has(a)) return 0;
      onPath.add(a);
      const c = Math.max(0, ...inn.get(a).filter((b) => !onPath.has(b)).map((b) => visit(b) + 1));
      onPath.delete(a); col.set(a, c);
      return c;
    };
    group.forEach(visit);
    const ncol = Math.max(...group.map((a) => col.get(a))) + 1;
    const cols = Array.from({ length: ncol }, () => []);
    group.forEach((a) => cols[col.get(a)].push(a));
    cols.forEach((c) => c.sort((a, b) => nameOf(a).localeCompare(nameOf(b))));
    const pos = new Map();
    cols.forEach((c) => c.forEach((a, i) => pos.set(a, i)));
    for (let sweep = 0; sweep < 8; sweep++) {
      const order = sweep % 2 ? [...cols.keys()].reverse() : [...cols.keys()];
      order.forEach((ci) => {
        const nb = (a) => { const one = (sweep % 2 ? out.get(a) : inn.get(a)).filter((b) => pos.has(b)); return one.length ? one : [...out.get(a), ...inn.get(a)].filter((b) => pos.has(b)); };
        const key = (a) => { const n = nb(a); return n.length ? n.reduce((s, b) => s + pos.get(b), 0) / n.length : pos.get(a); };
        cols[ci].sort((a, b) => key(a) - key(b));
        cols[ci].forEach((a, i) => pos.set(a, i));
      });
    }
    return cols;
  }

  // Which stocks are related: a flow between them, or a flow's equation, effect or co-flow reading one.
  function relations(ids, flows) {
    const set = new Set(ids), pairs = [], seen = new Set();
    const add = (a, b) => { const k = `${a}>${b}`; if (a && b && a !== b && set.has(a) && set.has(b) && !seen.has(k)) { seen.add(k); pairs.push([a, b]); } };
    flows.forEach((f) => {
      add(f.from, f.to);
      const end = f.to || f.from;
      const r = f.rate || {};
      [r.stock, ...(r.terms || []).map((t) => t.stock), ...(f.effects || []).map((e) => e.stock), ...(f.uses || []).map((u) => u.stock)]
        .forEach((x) => { if (x !== f.from && x !== f.to) add(x, end); });
    });
    return pairs;
  }

  // Positions {id: {x, y}} for a small model: connected groups in columns (wrapped after maxCols
  // columns into bands below), then the stocks related to nothing in a row. Same model, same places.
  function layout(stockIds, flows, opts = {}) {
    const box = opts.box || BOX, COLW = opts.colw || box.w + 150, ROWH = opts.rowh || box.h + 90, maxCols = opts.maxCols || Infinity;
    const ids = [...stockIds];
    const out = new Map(ids.map((i) => [i, []])), inn = new Map(ids.map((i) => [i, []]));
    relations(ids, flows).forEach(([a, b]) => { out.get(a).push(b); inn.get(b).push(a); });
    const comp = new Map(); let nc = 0;
    ids.forEach((id) => {
      if (comp.has(id)) return;
      const stack = [id]; comp.set(id, nc);
      while (stack.length) { const a = stack.pop(); [...out.get(a), ...inn.get(a)].forEach((b) => { if (!comp.has(b)) { comp.set(b, nc); stack.push(b); } }); }
      nc++;
    });
    const groups = Array.from({ length: nc }, () => []);
    ids.forEach((id) => groups[comp.get(id)].push(id));
    const connected = groups.filter((g) => g.length > 1).sort((a, b) => b.length - a.length), alone = groups.filter((g) => g.length === 1).map((g) => g[0]);
    const pos = {}, nameOf = (a) => String(a);
    let y = 0;
    connected.forEach((g) => {
      const cols = columns(g, inn, out, nameOf);
      for (let start = 0; start < cols.length; start += maxCols) {
        const band = cols.slice(start, start + maxCols), tall = Math.max(...band.map((c) => c.length));
        band.forEach((c, ci) => c.forEach((a, i) => { pos[a] = { x: ci * COLW, y: Math.round(y + (i + (tall - c.length) / 2) * ROWH) }; }));
        y += tall * ROWH + 20;
      }
    });
    alone.sort().forEach((a, i) => { pos[a] = { x: (i % Math.max(1, Math.min(maxCols, 4))) * COLW, y: y + Math.floor(i / Math.max(1, Math.min(maxCols, 4))) * ROWH }; });
    return pos;
  }

  // ---------- read-only drawing ----------
  // Where a flow's outside end sits: inflows above-left of their stock, outflows below-right, each
  // further one of the same kind turned a little more, so several never sit on each other.
  function cloudSpots(flows, pos, box) {
    const n = {}, spots = new Map();
    flows.forEach((f) => {
      if (f.from && f.to) return;
      const sid = f.to || f.from, s = pos[sid]; if (!s) return;
      const kind = f.to ? "in" : "out", k = (n[sid + kind] = (n[sid + kind] || 0) + 1) - 1;
      const base = kind === "in" ? 215 : 35, step = [0, 38, -38, 76][k % 4];
      const ang = (base + step) * Math.PI / 180, c = center(s, box), r = box.w / 2 + 64;
      spots.set(f, { x: c.x + Math.cos(ang) * r, y: c.y + Math.sin(ang) * r });
    });
    return spots;
  }
  function flowEnds(f, pos, spots, box, offset) {
    const A = f.from && pos[f.from], B = f.to && pos[f.to];
    const a0 = A ? center(A, box) : spots.get(f), b0 = B ? center(B, box) : spots.get(f);
    let a = A ? clip(A, b0, box) : { ...a0 }, b = B ? clip(B, a0, box) : { ...b0 };
    if (!A) a = shorten(a, b, 15);
    if (!B) b = shorten(b, a, 15);
    if (offset) {
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1, ox = -dy / L * offset, oy = dx / L * offset;
      a = { x: a.x + ox, y: a.y + oy }; b = { x: b.x + ox, y: b.y + oy };
    }
    return { a, b };
  }
  // the box around everything a diagram of these flows draws, for one viewBox shared by several diagrams
  function bounds(pos, flows, box = BOX, pad = 50) {
    const spots = cloudSpots(flows, pos, box), xs = [], ys = [];
    Object.values(pos).forEach((p) => { xs.push(p.x, p.x + box.w); ys.push(p.y, p.y + box.h); });
    spots.forEach((p) => { xs.push(p.x - 20, p.x + 20); ys.push(p.y - 20, p.y + 20); });
    if (!xs.length) return { x: 0, y: 0, w: 300, h: 150 };
    const x0 = Math.min(...xs) - pad, y0 = Math.min(...ys) - pad - 10;
    return { x: x0, y: y0, w: Math.max(...xs) + pad - x0, h: Math.max(...ys) + pad - y0 };
  }

  // D: {stocks: [{id, name, sub?, dashed?, cls?, title?}], flows: [{from, to, label, label2?, cls,
  // dashed?, reads: [{stock, label?, dash?, cls?}], title?}]}; pos: {id: {x, y}}; colours come from
  // opts.color(cls). Flows between the same two stocks are drawn side by side.
  function draw(svg, D, pos, opts = {}) {
    const box = opts.box || BOX, color = opts.color || (() => "var(--fg)");
    svg.innerHTML = "";
    const vb = opts.viewBox || bounds(pos, D.flows, box);
    svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
    const flows = D.flows.filter((f) => (!f.from || pos[f.from]) && (!f.to || pos[f.to]) && (f.from || f.to));
    const spots = cloudSpots(flows, pos, box);
    // flows between the same pair of stocks (either way) are spread apart
    const pairN = {}, pairI = new Map();
    flows.forEach((f) => { if (f.from && f.to) { const k = [f.from, f.to].sort().join("|"); pairI.set(f, pairN[k] = (pairN[k] || 0) + 1); } });
    const offsetOf = (f) => {
      if (!f.from || !f.to) return 0;
      const k = [f.from, f.to].sort().join("|"), n = pairN[k], i = pairI.get(f) - 1;
      const sign = f.from < f.to ? 1 : -1;                      // the same side for both directions
      return n === 1 ? 0 : sign * (i - (n - 1) / 2) * 16;
    };
    const gLinks = el("g", {}, svg), gFlows = el("g", {}, svg), gStocks = el("g", {}, svg), gLabels = el("g", {}, svg);
    const geo = new Map(flows.map((f) => [f, flowEnds(f, pos, spots, box, offsetOf(f))]));

    flows.forEach((f) => {
      (f.reads || []).forEach((r, k) => {
        const src = pos[r.stock]; if (!src) return;
        const { a, b } = geo.get(f), mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const c = center(src, box), start = clip(src, mid, box);
        const dx = mid.x - c.x, dy = mid.y - c.y, L = Math.hypot(dx, dy) || 1;
        const bend = 40 * (k % 2 ? -1 : 1) * (1 + Math.floor(k / 2) * 0.7);
        const ctl = { x: (start.x + mid.x) / 2 + dy / L * bend, y: (start.y + mid.y) / 2 - dx / L * bend };
        const end = shorten(mid, ctl, 8), col = r.cls ? color(r.cls) : "var(--muted)";
        el("path", { d: `M${start.x} ${start.y} Q${ctl.x} ${ctl.y} ${end.x} ${end.y}`, fill: "none", stroke: col, "stroke-width": r.label ? 1.6 : 1.3, "stroke-dasharray": r.dash || "3 4" }, gLinks);
        arrowHead(gLinks, ctl, end, col, 6);
        if (r.label) text(gLinks, ctl.x, ctl.y - 3, r.label, { "text-anchor": "middle", "font-size": 11, fill: col, "font-weight": 600 });
      });
    });

    flows.forEach((f) => {
      const { a, b } = geo.get(f), col = color(f.cls);
      const g = el("g", { class: `dflow ${f.cls || ""}` }, gFlows);
      if (f.title) el("title", {}, g).textContent = f.title;
      const tip = shorten(b, a, 10);
      el("path", { d: `M${a.x} ${a.y} L${tip.x} ${tip.y}`, stroke: col, "stroke-width": f.thin ? 1.8 : 3.2, fill: "none", "stroke-dasharray": f.dashed ? "7 5" : null }, g);
      el("path", { d: `M${a.x} ${a.y} L${b.x} ${b.y}`, stroke: "transparent", "stroke-width": 14, fill: "none" }, g);
      arrowHead(g, a, b, col, 12);
      if (!f.from || !f.to) cloud(gFlows, spots.get(f));
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1;
      // the label sits beside the arrow, on the side its offset pushed it to (above when level)
      let nx = -dy / L, ny = dx / L;
      if (ny > 0 || (Math.abs(ny) < 1e-6 && nx < 0)) { nx = -nx; ny = -ny; }
      if (offsetOf(f) < 0) { nx = -nx; ny = -ny; }
      const lines = [f.label, f.label2].filter(Boolean);
      const w = Math.max(...lines.map((s) => s.length * 6.6), 10) + 10, h = lines.length * 14 + 4;
      const dist = Math.abs(nx) * (w / 2) + Math.abs(ny) * (h / 2) + 6;
      const lx = mid.x + nx * dist, ly = mid.y + ny * dist;
      const lg = el("g", { class: `dlabel ${f.cls || ""}` }, gLabels);
      if (f.title) el("title", {}, lg).textContent = f.title;
      el("rect", { x: lx - w / 2, y: ly - h / 2, width: w, height: h, rx: 3, fill: "var(--canvas)", opacity: 0.9 }, lg);
      lines.forEach((s, i) => text(lg, lx, ly - h / 2 + 13 + i * 14, s, { "text-anchor": "middle", "font-size": i ? 11.5 : 12, "font-weight": i ? 600 : 500, fill: i ? col : "var(--fg)", "font-family": i ? "var(--mono)" : null }));
    });

    D.stocks.forEach((s) => {
      const p = pos[s.id]; if (!p) return;
      const g = el("g", { class: `dstock ${s.cls || ""}`, transform: `translate(${p.x} ${p.y})` }, gStocks);
      if (s.title) el("title", {}, g).textContent = s.title;
      el("rect", { width: box.w, height: box.h, rx: s.dashed ? 8 : 3, fill: "var(--canvas)", stroke: s.cls ? color(s.cls) : "var(--fg)", "stroke-width": 1.6, "stroke-dasharray": s.dashed ? "6 4" : null }, g);
      text(g, box.w / 2, s.sub ? box.h / 2 - 3 : box.h / 2 + 5, s.name || s.id, { "text-anchor": "middle", "font-size": 14, "font-weight": 600, fill: "var(--fg)" });
      if (s.sub) text(g, box.w / 2, box.h / 2 + 13, s.sub, { "text-anchor": "middle", "font-size": 10.5, fill: s.cls ? color(s.cls) : "var(--muted)" });
    });
    return vb;
  }

  const api = { BOX, center, clip, shorten, el, text, arrowHead, cloud, columns, relations, layout, bounds, draw };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SDDiagram = api;
})(typeof window !== "undefined" ? window : globalThis);
