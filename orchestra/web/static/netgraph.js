// One network renderer for every graph in the UI (the Machines page's event map, the Dynamics
// page's stock-and-flow model): a d3 force layout with
//   nodes   circle (a machine: initial inside, name beneath, optional halo), box (an event type, a
//           stock: lines of text, optional decoration), valve (a flow: a small dot with a label),
//           cloud (outside: a source or a sink);
//   edges   solid or dashed, coloured, with an arrow, an optional label and sign, and optional
//           moving dashes whose speed follows a rate; an edge may end on another edge
//           (``toEdge``), drawn to its middle: an influence on a flow;
//   loops   elementary cycles of a directed graph, listed and clickable: clicking one highlights
//           its nodes and edges and fades the rest;
// plus drag, zoom and pan, and hover to isolate a neighbourhood.
//
// Layout: a node keeps its place. Positions persist across redraws, reloads and new structures
// (every node ever placed is remembered, so one that leaves and comes back returns where it was).
// The forces run only to place nodes: all of them the first time; when the structure changes, only
// the new ones (each starts by its neighbours) while every known node is held still; and all of
// them again on "tidy" (around the ones the viewer placed) or "reset" (from scratch). Dragging
// moves just that node, which then stays where it was dropped (double-click lets the forces place it
// again). Weak gravity keeps nodes from drifting off; a node with an ``anchor`` ([fx, fy], fractions
// of the view) is pulled toward that spot.
//
// With a ``boundary``, a node outside it that is ``tether``ed to one inside (a source or sink
// cloud and its stock) is not placed by the forces: it sits just outside the frame, on the side
// nearest its node, level with it, and follows it when it moves (until the viewer drags it). A
// node inside marked ``edgeward`` (a stock with flows from or to outside) is drawn gently toward
// the nearest side of the frame, so those crossings stay short.
const NetGraph = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const POS_KEY = (k) => `orchestra.netgraph.${k}`;

  // ---- geometry ----
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

  // ---- the frame and the clouds (pure: the renderer and the layout tests share them) ----
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

  // ---- edge labels (pure, shared with the layout tests) ----
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

  // ---- elementary cycles (small graphs): each cycle once, as a list of node ids ----
  function cycles(nodeIds, edges, { max = 40, maxLen = 14 } = {}) {
    const adj = new Map(nodeIds.map((id) => [id, []]));
    edges.forEach((e) => { if (adj.has(e.source) && adj.has(e.target)) adj.get(e.source).push(e.target); });
    const order = new Map(nodeIds.map((id, i) => [id, i])), out = [];
    for (const start of nodeIds) {
      const s = order.get(start), stack = [start], onPath = new Set([start]);
      const go = (v) => {
        if (out.length >= max) return;
        for (const w of adj.get(v)) {
          if (w === start) { out.push([...stack]); continue; }
          if (order.get(w) < s || onPath.has(w) || stack.length >= maxLen) continue;
          stack.push(w); onPath.add(w); go(w); stack.pop(); onPath.delete(w);
        }
      };
      go(start);
    }
    return out;
  }

  // ---- the renderer ----
  // ``boundary``: {inside: node => bool, label}: a frame around the nodes inside (the system),
  // with every other node kept outside it, so what crosses the frame is visibly what crosses the
  // system's boundary (its sources, sinks and outside conditions).
  // ``layout``: an async function (nodes, edges) -> {id: [x, y]} that places a whole graph (ELK on
  // the Dynamics page); used for the first layout, tidy and reset instead of the forces.
  // ``polish``: an optional async function (nodes, edges, at) -> {id: [x, y]} run after it (in a
  // worker), whose result the nodes glide to unless the viewer has moved something meanwhile.
  function create(container, { key, height = 600, isolateHops = 1, onClick, tip, boundary, layout, polish } = {}) {
    container.innerHTML = "";
    const svgEl = document.createElementNS(NS, "svg");
    svgEl.setAttribute("class", "netgraph");
    container.appendChild(svgEl);
    const W = () => container.clientWidth || 1000, H = height;
    const svg = d3.select(svgEl).attr("viewBox", `0 0 ${W()} ${H}`).style("height", H + "px");
    const defs = svg.append("defs");
    defs.html(`<linearGradient id="ng-halo" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="60" y2="60"><stop offset="0" stop-color="#60a5fa"/><stop offset=".5" stop-color="#c084fc"/><stop offset="1" stop-color="#22c55e"/></linearGradient>`);
    const root = svg.append("g"), gFrame = root.append("g"), gEdges = root.append("g"), gLabels = root.append("g"), gNodes = root.append("g");
    const frameRect = gFrame.append("rect").attr("class", "ng-frame").attr("rx", 18).style("display", "none");
    const frameLabel = gFrame.append("text").attr("class", "ng-frame-label").style("display", "none");
    // the frame: the box around the inside nodes, padded
    function frameBox() { return boundary ? frameOf(NODES, boundary.inside) : null; }
    // a force that pushes outside nodes out of the frame, to its nearest side
    function keepOutside(alpha) {
      const b = frameBox(); if (!b) return;
      for (const n of NODES) {
        if (boundary.inside(n) || n.fx != null || (n.tether && !n.pin)) continue;   // held, placed by the viewer, or placed by its tether
        const r = (size(n).r || 14) + 6;
        if (n.x > b.x0 - r && n.x < b.x1 + r && n.y > b.y0 - r && n.y < b.y1 + r) {
          const d = [[n.x - (b.x0 - r), -1, 0], [(b.x1 + r) - n.x, 1, 0], [n.y - (b.y0 - r), 0, -1], [(b.y1 + r) - n.y, 0, 1]].sort((a, c) => a[0] - c[0])[0];
          // a hard rule, not a nudge: put it just outside the nearest side
          n.x += d[1] * d[0]; n.y += d[2] * d[0]; n.vx = 0; n.vy = 0;
        }
      }
    }
    // a tethered node's place: just outside the frame, on the side nearest the node it belongs to,
    // level with it (several on one side of one node sit side by side)
    function placeTethered() {
      const at = tetherPlaces(NODES, frameBox(), RAW_EDGES);
      for (const n of NODES) if (at[n.id]) { [n.x, n.y] = at[n.id]; n.vx = n.vy = 0; }
    }
    // a force drawing ``edgeward`` nodes toward the nearest side of the frame (nothing for a node
    // already at it, so the frame does not grow)
    function towardEdge(alpha) {
      const b = frameBox(); if (!b) return;
      for (const n of NODES) {
        if (!n.edgeward || n.fx != null) continue;
        const s = size(n), hw = s.r || s.w / 2, hh = s.r || s.h / 2;
        const [d, dx, dy] = [[n.x - hw - (b.x0 + PAD), -1, 0], [(b.x1 - PAD) - (n.x + hw), 1, 0], [n.y - hh - (b.y0 + PAD + 12), 0, -1], [(b.y1 - PAD) - (n.y + hh), 0, 1]]
          .sort((a, c) => a[0] - c[0])[0];
        if (d > 6) { n.vx += dx * d * 0.04 * alpha; n.vy += dy * d * 0.04 * alpha; }
      }
    }
    let userZoomed = false;
    const zoom = d3.zoom().scaleExtent([0.2, 4]).filter((ev) => ev.type === "wheel" || !ev.target.closest(".ng-node"))
      .on("zoom", (ev) => { root.attr("transform", ev.transform); if (ev.sourceEvent) userZoomed = true; });
    svg.call(zoom).on("dblclick.zoom", null);
    // fit everything in view: after a new layout settles (unless the viewer has zoomed), and on demand
    function fit(animate = true) {
      if (!NODES.length || NODES.some((n) => n.x === undefined)) return;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const n of NODES) { const s = size(n), hw = (s.r || s.w / 2) + 40, hh = (s.r || s.h / 2) + 40; x0 = Math.min(x0, n.x - hw); x1 = Math.max(x1, n.x + hw); y0 = Math.min(y0, n.y - hh); y1 = Math.max(y1, n.y + hh); }
      const fb = frameBox();
      if (fb) { x0 = Math.min(x0, fb.x0 - 16); x1 = Math.max(x1, fb.x1 + 16); y0 = Math.min(y0, fb.y0 - 16); y1 = Math.max(y1, fb.y1 + 16); }
      const w = W(), k = Math.min(w / (x1 - x0), H / (y1 - y0), 1.4);
      const t = d3.zoomIdentity.translate(w / 2 - k * (x0 + x1) / 2, H / 2 - k * (y0 + y1) / 2).scale(k);
      (animate ? svg.transition().duration(400) : svg).call(zoom.transform, t);
    }
    const fitBtn = document.createElement("button");
    fitBtn.className = "ctl ng-fit"; fitBtn.textContent = "fit"; fitBtn.title = "fit the whole graph in view";
    fitBtn.onclick = () => { userZoomed = false; fit(); };
    container.style.position = "relative"; container.appendChild(fitBtn);
    const ctl = (text, title, right, fn) => { const b = document.createElement("button"); b.className = "ctl ng-fit"; b.textContent = text; b.title = title; b.style.right = right + "px"; b.onclick = fn; container.appendChild(b); };
    ctl("tidy", "lay the graph out again around the nodes you placed", 52, () => tidy(false));
    ctl("reset", "forget every position, including the ones you placed, and lay it out from scratch", 104, () => tidy(true));
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(POS_KEY(key)) || "{}"); } catch (e) {}
    const markers = new Set();
    const marker = (col, start = false) => {
      const id = "ng-arr-" + (start ? "s-" : "") + col.replace(/[^a-z0-9]/gi, "");
      if (!markers.has(id)) { markers.add(id); defs.append("marker").attr("id", id).attr("viewBox", "0 -4 8 8").attr("refX", 8).attr("refY", 0).attr("markerUnits", "userSpaceOnUse").attr("markerWidth", 10).attr("markerHeight", 10).attr("orient", start ? "auto-start-reverse" : "auto").append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", col); }
      return `url(#${id})`;
    };
    let sim = null, NODES = [], EDGES = [], ALLEDGES = [], sig = null, pinned = null;
    const tipEl = () => { let t = document.getElementById("ng-tip"); if (!t) { t = document.createElement("div"); t.id = "ng-tip"; t.className = "ng-tip"; document.body.appendChild(t); } return t; };
    const showTip = (html, ev) => { if (!html) return; const t = tipEl(); t.innerHTML = html; t.style.display = "block"; moveTip(ev); };
    const moveTip = (ev) => { const t = tipEl(), r = t.getBoundingClientRect(); t.style.left = Math.min(innerWidth - r.width - 8, ev.clientX + 14) + "px"; t.style.top = Math.min(innerHeight - r.height - 8, ev.clientY + 14) + "px"; };
    const hideTip = () => { tipEl().style.display = "none"; };

    // remember every node's place, including nodes not drawn now (the most recent 500)
    function save() {
      for (const n of NODES) {
        if (n.x === undefined || !isFinite(n.x)) continue;
        delete saved[n.id]; saved[n.id] = [Math.round(n.x), Math.round(n.y), n.pin ? 1 : 0];
      }
      const ids = Object.keys(saved);
      for (const id of ids.slice(0, Math.max(0, ids.length - 500))) delete saved[id];
      try { localStorage.setItem(POS_KEY(key), JSON.stringify(saved)); } catch (e) {}
    }
    function path(e) {
      if (e.toEdge) return linkPath(e);
      const s = e.source, t = e.target;
      if (s === t) return `M${s.x},${s.y - 20} C${s.x + 50},${s.y - 70} ${s.x + 70},${s.y - 20} ${s.x + 20},${s.y}`;
      const dx = t.x - s.x, dy = t.y - s.y, d = Math.hypot(dx, dy) || 1, bend = e.bend ?? 22;
      const mx = (s.x + t.x) / 2 - dy / d * bend, my = (s.y + t.y) / 2 + dx / d * bend;
      const a = edgePoint(s, mx, my, e.both ? 3 : 1), b = edgePoint(t, mx, my, 3);
      e._mid = { x: (a.x + 2 * mx + b.x) / 4, y: (a.y + 2 * my + b.y) / 4 };
      return `M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}`;
    }
    // a link into another edge (an influence on a flow): from its node to the middle of that edge
    function linkPath(e) {
      const s = e.source, m = e.toEdge._mid;
      if (!m || s.x === undefined) return "";
      const dx = m.x - s.x, dy = m.y - s.y, d = Math.hypot(dx, dy) || 1, bend = e.bend ?? 30;
      const cx = (s.x + m.x) / 2 - dy / d * bend, cy = (s.y + m.y) / 2 + dx / d * bend;
      const a = edgePoint(s, cx, cy, 1), L = Math.hypot(m.x - cx, m.y - cy) || 1;
      const bx = m.x - (m.x - cx) / L * 7, by = m.y - (m.y - cy) / L * 7;   // stop just short of the line
      e._mid = { x: (a.x + 2 * cx + bx) / 4, y: (a.y + 2 * cy + by) / 4 };
      return `M${a.x},${a.y} Q${cx},${cy} ${bx},${by}`;
    }
    function drawNode(g, n) {
      const s = size(n);
      g.selectAll("*").remove();
      if (n.halo) g.append("circle").attr("class", "ng-halo").attr("r", (s.r || Math.max(s.w, s.h) / 2) + 7);
      if (n.kind === "circle") {
        g.append("circle").attr("r", s.r).attr("fill", n.color || "#94a3b8").attr("stroke", n.stroke || "var(--border2)").attr("stroke-width", n.strokeWidth || 1.5);
        g.append("text").attr("class", "ng-initial").attr("text-anchor", "middle").attr("dy", 5).text((n.label || "?")[0].toUpperCase());
        g.append("text").attr("class", "ng-name").attr("text-anchor", "middle").attr("dy", s.r + 13).text(n.label);
        if (n.sub) g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("dy", s.r + 25).text(n.sub);
      } else if (n.kind === "valve") {
        g.append("circle").attr("class", "ng-grab").attr("r", 14);
        g.append("circle").attr("r", s.r).attr("fill", n.color || "#94a3b8").attr("stroke", "var(--panel)").attr("stroke-width", 2);
      } else if (n.kind === "cloud") {
        g.append("circle").attr("class", "ng-grab").attr("r", 18);          // an outline alone is too thin to grab
        g.append("path").attr("class", "ng-cloud").attr("transform", "scale(.8)").attr("d", "M-10,6 a6,6 0 0 1 0,-12 a8,8 0 0 1 14,-3 a6,6 0 0 1 8,9 a5,5 0 0 1 -4,6 Z");
      } else {
        g.append("rect").attr("class", "ng-box").attr("x", -s.w / 2).attr("y", -s.h / 2).attr("width", s.w).attr("height", s.h).attr("rx", n.rx ?? 5)
          .attr("stroke", n.color || "#6b5313").attr("fill", n.fill || "#0b0e14").attr("stroke-dasharray", n.dashed ? "6 4" : null);
        if (n.decorate) n.decorate(g, n, s);
        const lines = n.lines || [n.label], top = -s.h / 2 + 15;
        g.append("text").attr("class", "ng-boxtext").attr("text-anchor", "middle").attr("fill", n.textColor || "var(--text)")
          .selectAll("tspan").data(lines).join("tspan").attr("x", 0).attr("y", (l, i) => top + i * 14).text((l) => l);
        if (n.sub) g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", top + lines.length * 14).text(n.sub);
      }
    }

    function render(nodes, edges) {
      const newSig = JSON.stringify([nodes.map((n) => n.id + n.kind), edges.map((e) => e.id)]);
      const old = new Map(NODES.map((n) => [n.id, n]));
      // a node keeps its place across redraws and structures; one the viewer dropped is marked so
      NODES = nodes.map((n) => {
        const o = old.get(n.id), sv = saved[n.id];
        // a tethered node (a cloud) is never pinned: it always sits by the node it belongs to
        const p = o && o.x !== undefined ? [o.x, o.y] : sv, pin = !n.tether && (o ? !!o.pin : !!(sv && sv[2]));
        return { ...n, x: p ? p[0] : undefined, y: p ? p[1] : undefined, pin, fx: null, fy: null, _new: !p };
      });
      const byId = new Map(NODES.map((n) => [n.id, n]));
      placeNew(edges, byId);
      EDGES = edges.filter((e) => !e.toEdge && byId.has(e.source) && byId.has(e.target)).map((e) => ({ ...e, source: byId.get(e.source), target: byId.get(e.target) }));
      // links that end on another edge (``toEdge``: its id), drawn to that edge's middle; for
      // hovering they touch both of its ends
      const edgeById = new Map(EDGES.map((e) => [e.id, e]));
      const LINKS = edges.filter((e) => e.toEdge && byId.has(e.source) && edgeById.has(e.toEdge))
        .map((e) => { const t = edgeById.get(e.toEdge); return { ...e, source: byId.get(e.source), toEdge: t, target: t.target }; });
      const ALL = [...EDGES, ...LINKS];
      ALLEDGES = ALL;
      const structural = newSig !== sig;
      sig = newSig;
      const edgeSel = gEdges.selectAll("g.ng-edge").data(ALL, (e) => e.id).join("g").attr("class", (e) => `ng-edge ${e.cls || ""}`).attr("data-id", (e) => e.id);
      edgeSel.each(function (e) {
        const g = d3.select(this); g.selectAll("*").remove();
        const col = e.color || "#4b5563";
        // ``both``: one line for two nodes linked both ways, an arrowhead at each end
        g.append("path").attr("class", "ng-line").attr("stroke", col).attr("stroke-width", e.width || 1.6).attr("stroke-dasharray", e.dashed ? "5 4" : null).attr("marker-end", e.arrow === false ? null : marker(col))
          .attr("marker-start", e.both ? marker(col, true) : null);
        g.append("path").attr("class", "ng-hit");
        if (e.rate) g.append("path").attr("class", "ng-flowdash").style("animation-duration", `${Math.max(0.25, Math.min(6, 8 / Math.sqrt(e.rate))).toFixed(2)}s`);
        g.on("mouseenter", (ev) => showTip(tip && tip(e, "edge"), ev)).on("mousemove", moveTip).on("mouseleave", hideTip)
          .on("click", (ev) => { hideTip(); onClick && onClick(e, "edge"); });
      });
      const labelSel = gLabels.selectAll("g.ng-label").data(ALL.filter((e) => e.label || e.sign), (e) => e.id).join("g").attr("class", "ng-label").attr("data-id", (e) => e.id);
      labelSel.each(function (e) {
        const g = d3.select(this); g.selectAll("*").remove();
        if (e.sign) g.append("text").attr("class", "ng-sign").attr("text-anchor", "middle").attr("fill", e.color || "var(--muted)").text(e.sign);
        if (e.label) { const t = g.append("text").attr("class", "ng-elabel").attr("text-anchor", "middle"); (Array.isArray(e.label) ? e.label : [e.label]).forEach((l, i) => t.append("tspan").attr("x", 0).attr("dy", i ? 12 : 0).attr("fill", i ? (e.color || "var(--muted)") : null).text(l)); }
      });
      const nodeSel = gNodes.selectAll("g.ng-node").data(NODES, (n) => n.id).join("g").attr("class", (n) => `ng-node ng-${n.kind} ${n.cls || ""}`).attr("data-id", (n) => n.id);
      nodeSel.each(function (n) { drawNode(d3.select(this), n); });
      nodeSel.on("mouseenter", (ev, n) => { isolate(n.id); showTip(tip && tip(n, "node"), ev); }).on("mousemove", moveTip)
        .on("mouseleave", () => { isolate(null); hideTip(); }).on("click", (ev, n) => { hideTip(); onClick && onClick(n, "node"); })
        // dragging moves this node alone (nothing else is pushed around), and it stays where it is dropped
        .call(d3.drag().on("start", () => { if (sim) sim.stop(); if (settling) { settling = null; for (const n of NODES) { n.fx = n.fy = null; n._new = false; } } })
          .on("start.place", () => { placing++; })                 // a layout in progress gives way to the viewer
          .on("drag", (ev, d) => { d.x = ev.x; d.y = ev.y; tick(); }).on("end", (ev, d) => { d.pin = !d.tether; tick(); save(); relabel(); }))   // a cloud goes back beside its stock
        .on("dblclick", (ev, d) => { ev.stopPropagation(); d.pin = false; settle(new Set([d.id]), 0.3, false); });   // let the forces place it again
      // parallel edges (several flows between the same two nodes) spread apart
      const par = new Map();
      for (const e of EDGES) { const k = e.source.id + ">" + e.target.id; par.set(k, [...(par.get(k) || []), e]); }
      for (const group of par.values()) group.forEach((e, k) => { e.bend = (e.bend ?? 22) + (k - (group.length - 1) / 2) * 44; });
      // a layout still settling carries on (with any new nodes added to it); otherwise only the
      // new nodes move, or nothing does
      RAW_EDGES = edges;
      const fresh = NODES.filter((n) => n._new);
      if (layout && fresh.length === NODES.length && !settling) placeAll(false);
      else if (settling) settle(new Set([...settling.movable].filter((id) => byId.has(id)).concat(fresh.map((n) => n.id))), Math.max(0.5, sim ? sim.alpha() : 0.5), true);
      else if (fresh.length === NODES.length) settle(new Set(NODES.map((n) => n.id)), 1, true);
      else if (fresh.length) settle(new Set(fresh.map((n) => n.id)), 0.5, true);
      else { tick(); relabel(); }                                // nothing new: nothing moves
      // the first drawing fits the view (a layout still settling fits when it is done)
      if (!drawnOnce) { drawnOnce = true; if (!settling) requestAnimationFrame(() => fit(false)); }
      if (pinned) highlight(pinned.nodes, pinned.edges);
    }
    // a new node starts by the nodes it is linked to (or at its anchor, or the middle)
    function placeNew(edges, byId) {
      const w = W();
      for (const n of NODES.filter((x) => x._new)) {
        const nb = edges.flatMap((e) => (e.source === n.id ? [e.target] : e.target === n.id ? [e.source] : []))
          .map((id) => byId.get(id)).filter((m) => m && !m._new);
        const [x, y] = nb.length ? [nb.reduce((a, m) => a + m.x, 0) / nb.length, nb.reduce((a, m) => a + m.y, 0) / nb.length]
          : n.anchor ? [n.anchor[0] * w, n.anchor[1] * H] : [w / 2, H / 2];
        n.x = x + (Math.random() - 0.5) * 80; n.y = y + (Math.random() - 0.5) * 80;
      }
    }
    // run the forces on ``movable`` nodes only; every other node, and every node the viewer placed,
    // is held where it is
    let settling = null, drawnOnce = false, RAW_EDGES = [], placing = 0;
    // place every node with ``layout`` (keeping the viewer's placements unless ``all``), then fit
    // Reset (``all``) and the first layout: the whole layout (``layout``, then ``polish``) is worked
    // out in the background, and the nodes glide once, to where it ends. Tidy (``fromHere``): only
    // ``polish``, from where the nodes are now (the viewer's placements held), then one glide.
    const plain = (n) => Object.fromEntries(Object.entries(n).filter(([, v]) => typeof v !== "function"));
    async function placeAll(all, fromHere = false) {
      const ticket = ++placing;
      if (sim) sim.stop();
      settling = null;
      const first = NODES.every((n) => n._new);
      let at = Object.fromEntries(NODES.filter((n) => n.x !== undefined).map((n) => [n.id, [n.x, n.y]]));
      if (!fromHere) {
        try { at = await layout(NODES, RAW_EDGES); } catch (e) { console.error("layout failed; using the forces", e); settle(new Set(NODES.map((n) => n.id)), 1, true); return; }
        if (ticket !== placing) return;                          // a newer layout was asked for
      }
      if (polish) {
        const fixed = all ? [] : NODES.filter((n) => n.pin).map((n) => n.id);
        try { at = await polish(NODES.map(plain), RAW_EDGES.map(plain), at, fixed); } catch (e) { console.error("polish failed", e); }
        if (ticket !== placing) return;                          // the viewer dragged, or asked again
      }
      await glide(at, all, first ? 0 : 650);                     // the first layout appears at once, finished
    }
    // move the nodes to ``at`` (the viewer's placements stay, unless ``all``), over ``ms``, then
    // place the labels and fit the view
    function glide(at, all, ms) {
      const moving = NODES.filter((n) => at[n.id] && (all || !n.pin)).map((n) => ({ n, x0: n.x ?? at[n.id][0], y0: n.y ?? at[n.id][1], x1: at[n.id][0], y1: at[n.id][1] }));
      for (const m of moving) { m.n._new = false; m.n.fx = m.n.fy = null; }
      return new Promise((resolve) => {
        const t0 = performance.now(), ticket = placing;
        const frame = (t) => {
          const k = ms ? Math.min(1, (t - t0) / ms) : 1, e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
          if (ticket !== placing) return resolve();
          for (const m of moving) { m.n.x = m.x0 + (m.x1 - m.x0) * e; m.n.y = m.y0 + (m.y1 - m.y0) * e; }
          tick();
          if (k < 1) return requestAnimationFrame(frame);
          save(); relabel(); if (!userZoomed) fit(); resolve();
        };
        ms ? requestAnimationFrame(frame) : frame(t0 + 1);
      });
    }
    // labels: placed where they cover no box and no other label (placeLabels), whenever the graph rests
    let LABEL_AT = {};
    function relabel() {
      const mids = Object.fromEntries(ALLEDGES.filter((e) => e._mid).map((e) => [e.id, e._mid]));
      LABEL_AT = placeLabels(NODES, ALLEDGES, mids);
      tick();
    }
    function settle(movable, alpha, refit) {
      if (sim) sim.stop();
      settling = { movable, refit };
      for (const n of NODES) { const hold = n.pin || !movable.has(n.id); n.fx = hold ? n.x : null; n.fy = hold ? n.y : null; }
      const w = W(), ax = (n) => (n.anchor ? n.anchor[0] * w : w / 2), ay = (n) => (n.anchor ? n.anchor[1] * H : H / 2);
      sim = d3.forceSimulation(NODES)
        .force("link", d3.forceLink(EDGES).id((d) => d.id).distance((e) => e.distance || 110).strength((e) => e.strength ?? 0.6))
        .force("charge", d3.forceManyBody().strength((n) => n.charge ?? -480))
        .force("x", d3.forceX(ax).strength((n) => (n.anchor ? 0.15 : 0.04)))     // weak gravity; anchored nodes pulled to their spot
        .force("y", d3.forceY(ay).strength((n) => (n.anchor ? 0.15 : 0.04)))
        .force("collide", d3.forceCollide((n) => { const s = size(n); return (s.r || Math.max(s.w, s.h) / 2) + 24; }))
        .force("boundary", boundary ? keepOutside : null)
        .force("edge", boundary ? towardEdge : null)
        .alpha(alpha);
      sim.on("tick", tick).on("end", () => { settling = null; for (const n of NODES) { n.fx = n.fy = null; n._new = false; } save(); relabel(); if (refit && !userZoomed) fit(); });
      tick();
    }
    // lay it out again: around the viewer's placements, or (``reset``) from nothing
    function tidy(reset) {
      if (!NODES.length) return;
      if (layout) {                                              // the layout engine, not the forces
        if (reset) for (const n of NODES) { n.pin = false; delete saved[n.id]; }
        userZoomed = false;
        placeAll(reset, !reset);                                 // tidy: from where the nodes are
        return;
      }
      if (reset) {
        for (const n of NODES) { n.pin = false; n._new = true; delete saved[n.id]; }
        placeNew(ALLEDGES.filter((e) => !e.toEdge).map((e) => ({ source: e.source.id, target: e.target.id })), new Map(NODES.map((n) => [n.id, n])));
      }
      userZoomed = false;
      settle(new Set(NODES.map((n) => n.id)), 1, true);
    }
    function tick() {
      if (boundary) placeTethered();
      const b = frameBox();
      frameRect.style("display", b ? null : "none"); frameLabel.style("display", b ? null : "none");
      if (b) {
        frameRect.attr("x", b.x0).attr("y", b.y0).attr("width", b.x1 - b.x0).attr("height", b.y1 - b.y0);
        frameLabel.attr("x", b.x0 + 14).attr("y", b.y0 + 16).text(boundary.label || "the system");
      }
      const sel = gEdges.selectAll("g.ng-edge");
      for (const links of [false, true]) {       // edges first: links aim at their middles
        sel.filter((e) => !!e.toEdge === links).each(function (e) {
          if (e.source.x === undefined) return;
          const d = path(e);
          d3.select(this).selectAll("path").attr("d", d);
        });
      }
      // a label's box is centred where placeLabels put it; text sits from its top (first baseline 11 px down)
      gLabels.selectAll("g.ng-label").attr("transform", (e) => {
        if (!e._mid) return null;
        const [dx, dy] = LABEL_AT[e.id] || [0, 0], s = labelSize(e) || { h: 16 };
        return `translate(${e._mid.x + dx},${e._mid.y + dy - s.h / 2 + (e.label ? 11 : 13)})`;
      });
      gNodes.selectAll("g.ng-node").attr("transform", (n) => (n.x === undefined ? null : `translate(${n.x},${n.y})`));
    }
    // hover: a node, its edges and their far ends; with two hops, also what those reach (a
    // machine, its event types, and the machines on the other side of them)
    function isolate(id) {
      if (pinned) return;
      const ns = gNodes.selectAll("g.ng-node"), es = gEdges.selectAll("g.ng-edge"), ls = gLabels.selectAll("g.ng-label");
      // an edge with a ``hoverColor`` shows it while its neighbourhood is isolated, and goes back after
      const paint = (lit) => es.each(function (e) {
        if (!e.hoverColor) return;
        const col = lit && lit.has(e.id) ? e.hoverColor : e.color || "#4b5563";
        d3.select(this).select(".ng-line").attr("stroke", col).attr("marker-end", e.arrow === false ? null : marker(col)).attr("marker-start", e.both ? marker(col, true) : null).classed("ng-hover", !!(lit && lit.has(e.id)));
      });
      if (!id) { ns.classed("ng-dim", false); es.classed("ng-dim", false); ls.classed("ng-dim", false); paint(null); return; }
      const keep = new Set([id]), lit = new Set();
      let frontier = [id];
      for (let h = 0; h < isolateHops; h++) {
        const next = [];
        ALLEDGES.forEach((e) => {
          const ends = e.toEdge ? [e.source.id, e.toEdge.source.id, e.toEdge.target.id] : [e.source.id, e.target.id];
          if (!ends.some((x) => frontier.includes(x))) return;
          lit.add(e.id); if (e.toEdge) lit.add(e.toEdge.id);
          for (const b of ends) if (!keep.has(b)) { keep.add(b); next.push(b); }
        });
        frontier = next.filter((x) => (NODES.find((n) => n.id === x) || {}).hop);
      }
      ns.classed("ng-dim", (n) => !keep.has(n.id)); es.classed("ng-dim", (e) => !lit.has(e.id)); ls.classed("ng-dim", (e) => !lit.has(e.id));
      paint(lit);
    }
    // a loop or any set: these nodes and edges in gold, everything else faded
    function highlight(nodeIds, edgeIds) {
      pinned = nodeIds ? { nodes: nodeIds, edges: edgeIds } : null;
      const ns = gNodes.selectAll("g.ng-node"), es = gEdges.selectAll("g.ng-edge"), ls = gLabels.selectAll("g.ng-label");
      const N = new Set(nodeIds || []), E = new Set(edgeIds || []);
      ns.classed("ng-dim", (n) => !!nodeIds && !N.has(n.id)).classed("ng-hl", (n) => N.has(n.id));
      es.classed("ng-dim", (e) => !!nodeIds && !E.has(e.id)).classed("ng-hl", (e) => E.has(e.id));
      ls.classed("ng-dim", (e) => !!nodeIds && !E.has(e.id));
    }
    // redraw the decorations of the given nodes (live data) without touching the layout
    function refreshNodes(update) {
      gNodes.selectAll("g.ng-node").each(function (n) { const u = update(n); if (u) { Object.assign(n, u); drawNode(d3.select(this), n); } });
    }
    function setRates(rateOf) {
      gEdges.selectAll("g.ng-edge").each(function (e) {
        const r = rateOf(e), g = d3.select(this); g.selectAll(".ng-flowdash").remove();
        if (r && r > 0.01) g.append("path").attr("class", "ng-flowdash").attr("d", g.select(".ng-line").attr("d")).style("animation-duration", `${Math.max(0.25, Math.min(6, 8 / Math.sqrt(r))).toFixed(2)}s`);
      });
    }
    return { render, highlight, refreshNodes, setRates, fit, tidy, edgesBetween: (ids) => EDGES.filter((e) => ids.includes(e.source.id) && ids.includes(e.target.id)) };
  }

  // a clickable list of loops under a graph: clicking one highlights it; clicking it again clears
  function loopList(el, graph, loops) {
    let active = null;
    el.innerHTML = loops.length ? loops.map((l, i) => `<div class="ng-loop" data-i="${i}">${l.html}</div>`).join("") : "";
    el.querySelectorAll(".ng-loop").forEach((row) => row.addEventListener("click", () => {
      const i = +row.dataset.i;
      el.querySelectorAll(".ng-loop").forEach((r) => r.classList.remove("on"));
      if (active === i) { active = null; graph.highlight(null); return; }
      active = i; row.classList.add("on"); graph.highlight(loops[i].nodes, loops[i].edges);
    }));
  }

  return { create, cycles, loopList, size, frameOf, tetherPlaces, labelSize, placeLabels };
})();
