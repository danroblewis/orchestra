// One network renderer for every graph in the UI (the Machines page's event map, the Dynamics
// page's stock-and-flow model): a d3 force layout with
//   nodes   circle (a machine: initial inside, name beneath, optional halo), box (an event type, a
//           stock: lines of text, optional decoration), valve (a flow: a small dot with a label),
//           cloud (outside: a source or a sink);
//   edges   solid, dashed or double (``double``: two thin lines, for a count rather than events),
//           coloured, with an arrow, an optional label and sign, and optional
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
//
// The pure geometry (sizes, the frame and clouds, edge labels) is netgraph-geometry.js, loaded first.
const NetGraph = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const POS_KEY = (k) => `orchestra.netgraph.${k}`;
  const { size, edgePoint, frameOf, tetherPlaces, labelSize, placeLabels, isolatedRows, fitView, boundsOf, PAD, DESK_K } = NetGeometry;

  // ``boundary``: {inside: node => bool, label}: a frame around the nodes inside (the system),
  // with every other node kept outside it, so what crosses the frame is visibly what crosses the
  // system's boundary (its sources, sinks and outside conditions).
  // ``layout``: an async function (nodes, edges) -> {id: [x, y]} that places a whole graph (ELK on
  // the Dynamics page); used for the first layout, tidy and reset instead of the forces.
  // ``polish``: an optional async function (nodes, edges, at) -> {id: [x, y]} run after it (in a
  // worker), whose result the nodes glide to unless the viewer has moved something meanwhile.
  // ``narrow``: below this width (a phone) the automatic fit fits the whole drawing, and the drawing's
  // height follows the fitted content instead of a tall empty canvas; on a wider screen at no less than DESK_K, centred on the largest connected part. What that leaves out
  // of view is said at the right edge ("N more → · fit to see all"); the fit button fits everything,
  // at any scale.
  // ``isolatedRow``: nodes linked to nothing are set in a row under the rest after the first layout,
  // rather than wherever the forces threw them.
  // ``TOP``: the band at the top of the drawing the controls (reset, tidy, fit) sit in: a fit keeps
  // every node below it
  const NARROW = 600, TOP = 40, REVEAL_ALPHA = 0.1;
  function create(container, { key, height = 600, isolateHops = 1, onClick, tip, boundary, layout, polish, isolatedRow = false } = {}) {
    container.innerHTML = "";
    const svgEl = document.createElementNS(NS, "svg");
    svgEl.setAttribute("class", "netgraph");
    container.appendChild(svgEl);
    // the drawing is shown once it is laid out and fitted, never cut off or under the controls
    // first: with a layout engine when the layout lands; with the forces once they have mostly
    // settled (alpha below REVEAL_ALPHA), fitted then
    svgEl.style.visibility = "hidden"; setTimeout(() => { svgEl.style.visibility = ""; }, 10000);   // never hidden for good
    const reveal = () => { svgEl.style.visibility = ""; };
    const hidden = () => svgEl.style.visibility === "hidden";
    let H = height, Wd = container.clientWidth || 1000;
    const W = () => Wd;
    const svg = d3.select(svgEl).attr("viewBox", `0 0 ${W()} ${H}`).style("height", H + "px");
    // the drawing keeps the container's width (a panel opening beside it narrows it): the view is
    // refitted unless the viewer zoomed
    if (window.ResizeObserver) new ResizeObserver(() => { const w = container.clientWidth; if (!w || Math.abs(w - Wd) < 2) return;
      Wd = w; svg.attr("viewBox", `0 0 ${Wd} ${H}`); if (!userZoomed && NODES.length) refit(false); }).observe(container);
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
    // names and captions keep a readable size on screen however far the view is zoomed out (style.css
    // scales them by --ngs: 1 at full size, up to 1.6 below it)
    const textScale = (k) => svgEl.style.setProperty("--ngs", String(Math.min(1.6, Math.max(1, 1 / (k || 1)))));
    const zoom = d3.zoom().scaleExtent([0.2, 4]).filter((ev) => ev.type === "wheel" || !ev.target.closest(".ng-node"))
      .on("zoom", (ev) => { root.attr("transform", ev.transform); textScale(ev.transform.k); if (ev.sourceEvent) { userZoomed = true; hint(null); } });
    svg.call(zoom).on("dblclick.zoom", null);
    // what an automatic fit leaves out of view, said at the right edge: a press fits everything
    const hintEl = document.createElement("button");
    hintEl.className = "ctl ng-more"; hintEl.type = "button"; hintEl.style.display = "none";
    hintEl.onclick = () => { userZoomed = false; around = null; fit(true, null, 0, null, { all: true }); };
    // ``out``: the nodes left outside, each with where ("r", "b", or elsewhere); the arrow says which way they are
    function hint(out) {
      const n = out ? out.length : 0;
      hintEl.style.display = n ? "" : "none";
      if (!n) return;
      const arrow = out.every((o) => o.side === "r") ? " →" : out.every((o) => o.side === "b") ? " ↓" : "";
      hintEl.textContent = `${n} more${arrow} · fit to see all`; hintEl.title = `${n} node${n === 1 ? "" : "s"} outside the view at this scale`;
    }
    // the nodes a transform leaves outside the view, and on which side
    const outside = (k, tx, ty) => NODES.filter((n) => n.x !== undefined && n.kind !== "cloud").map((n) => { const x = n.x * k + tx, y = n.y * k + ty;
      return { n, side: x > W() ? "r" : y > H ? "b" : x < 0 || y < 0 ? "o" : null }; }).filter((o) => o.side);
    // the connected parts, largest first (by node count), over the drawn edges
    function largestPart() {
      const adj = new Map(NODES.map((n) => [n.id, []]));
      for (const e of EDGES) { if (adj.has(e.source.id) && adj.has(e.target.id)) { adj.get(e.source.id).push(e.target.id); adj.get(e.target.id).push(e.source.id); } }
      const seen = new Set(); let best = [];
      for (const n of NODES) { if (seen.has(n.id)) continue; const part = [], q = [n.id]; seen.add(n.id);
        while (q.length) { const a = q.pop(); part.push(a); for (const b of adj.get(a)) if (!seen.has(b)) { seen.add(b); q.push(b); } }
        if (part.length > best.length) best = part; }
      return new Set(best);
    }
    const bounds = (ns) => boundsOf(ns);
    // fit in view: after a new layout settles (unless the viewer has zoomed), and on demand.
    // ``only``: node ids to fit instead of all (a machine and its neighbours), at no less than ``minK``
    // and no more than 1; ``all``: everything, at whatever scale it takes (the fit button)
    let autoFitted = false;
    function fit(animate = true, only = null, minK = 0, center = null, { all = false } = {}) {
      const ns = only ? NODES.filter((n) => only.has(n.id)) : NODES;
      if (!ns.length || ns.some((n) => n.x === undefined)) return;
      // the nodes linked to nothing sit in rows directly under the rest, so the fit of the rest shows them
      if (!only && isolatedRow) rowIsolated();
      let [x0, y0, x1, y1] = bounds(ns);
      const fb = only ? null : frameBox();
      if (fb) { x0 = Math.min(x0, fb.x0 - 16); x1 = Math.max(x1, fb.x1 + 16); y0 = Math.min(y0, fb.y0 - 16); y1 = Math.max(y1, fb.y1 + 16); }
      const w = W(), narrow = w < NARROW;
      const apply = (k, tx, ty) => { (animate ? svg.transition().duration(400) : svg).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(k)); hint(only ? null : outside(k, tx, ty)); };
      if (narrow && !only) {                 // a phone: the whole drawing in view on first load, the canvas as tall as it
        // (never an empty frame with "N more → fit"); zoom in to read, the fit button fits it again
        const k = Math.min(w / (x1 - x0), 1.4, (height - TOP) / (y1 - y0));
        const h = Math.round(Math.min(Math.max(280, (y1 - y0) * k + TOP), height));
        if (h !== H) { H = h; svg.attr("viewBox", `0 0 ${w} ${H}`).style("height", H + "px"); }
        const tx = (x1 - x0) * k <= w ? w / 2 - k * (x0 + x1) / 2 : -k * x0;
        const ty = (y1 - y0) * k <= H - TOP ? TOP + (H - TOP) / 2 - k * (y0 + y1) / 2 : TOP - k * y0;
        apply(k, tx, ty);
        return;
      }
      const room = H - TOP, mid = TOP + room / 2;       // the drawing's height below the controls, and its middle
      const kFit = Math.min(w / (x1 - x0), room / (y1 - y0), 1.4);
      // the fit button shows everything at whatever scale; an automatic fit, every node at no less than DESK_K
      if (all || (!only && kFit >= DESK_K)) { const v = fitView([x0, y0, x1, y1], { w, h: H, top: TOP, all: true }); apply(v.k, v.tx, v.ty); return; }
      if (!only) {                           // too spread to read whole: the largest connected part, centred, the rest said
        const part = NODES.filter((n) => largestPart().has(n.id)), [a0, b0, a1, b1] = bounds(part.length ? part : NODES);
        const k = Math.max(DESK_K, Math.min(w / (a1 - a0), room / (b1 - b0), 1.4)) || DESK_K;
        apply(k, w / 2 - k * (a0 + a1) / 2, mid - k * (b0 + b1) / 2);
        return;
      }
      const k = Math.min(1, Math.max(minK, kFit));
      // too spread to fit at a readable size: the view centres on the ``center`` node, its neighbours around it
      const c = kFit < minK && center ? NODES.find((n) => n.id === center) : null;
      const [cx, cy] = c && c.x !== undefined ? [c.x, c.y] : [(x0 + x1) / 2, (y0 + y1) / 2];
      apply(k, w / 2 - k * cx, mid - k * cy);
    }
    // the nodes a hover lights: ``isolateHops`` links out, through nodes marked ``hop`` (event types)
    function neighbourhood(id) {
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
      return { keep, lit };
    }
    // fit a node and its neighbourhood as the hover lights it (a machine opened in a panel: its event
    // types and the machines on them), at no more than 1 so none is cut; kept as the view's fit until
    // fitAround(null), so a layout settling refits to it, not to all
    let around = null;
    function fitAround(id, minK = 0.6, animate = true) {
      around = id ? { id, minK } : null;
      if (userZoomed) return;
      if (!id) { fit(animate); return; }
      const near = neighbourhood(id).keep;
      if (near.size < 2) { fit(animate, null, 0, null, { all: true }); return; }   // linked to nothing: the whole map, all of it in view, is its context
      fit(animate, near, minK, id);
    }
    const refit = (animate = true) => (around ? fitAround(around.id, around.minK, animate) : fit(animate));
    const fitBtn = document.createElement("button");
    fitBtn.className = "ctl ng-fit"; fitBtn.textContent = "fit"; fitBtn.title = "fit the whole graph in view, at whatever scale it takes";
    fitBtn.onclick = () => { userZoomed = false; around = null; fit(true, null, 0, null, { all: true }); };
    container.style.position = "relative"; container.appendChild(fitBtn); container.appendChild(hintEl);
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
        if (n.label) g.append("text").attr("class", "ng-sub").attr("x", 16).attr("dy", 4).text(n.label);   // where it is: "the start", "the end", beside it (clear of the frame's title)
      } else {
        g.append("rect").attr("class", "ng-box").attr("x", -s.w / 2).attr("y", -s.h / 2).attr("width", s.w).attr("height", s.h).attr("rx", n.rx ?? 5)
          .attr("stroke", n.color || "#6b5313").attr("fill", n.fill || "#0b0e14").attr("stroke-dasharray", n.dashed ? "6 4" : null);
        if (n.decorate) n.decorate(g, n, s);
        // a caption above the name: what kind of thing it is (a stock's family)
        // a caption of up to two lines (``caption``: a string, or its lines), the name under it
        const caps = n.caption ? (Array.isArray(n.caption) ? n.caption : [n.caption]).slice(0, 2) : [];
        const lines = n.lines || [n.label], top = -s.h / 2 + (caps.length ? 18 + 10 * caps.length : 15);
        if (caps.length) g.append("text").attr("class", "ng-caption").attr("text-anchor", "middle").selectAll("tspan").data(caps).join("tspan").attr("x", 0).attr("y", (c, i) => -s.h / 2 + 13 + i * 10).text((c) => c);
        g.append("text").attr("class", "ng-boxtext" + (n.caption ? " ng-named" : "")).attr("text-anchor", "middle").attr("fill", n.textColor || "var(--text)")
          .selectAll("tspan").data(lines).join("tspan").attr("x", 0).attr("y", (l, i) => top + i * 14).text((l) => l);
        if (n.sub) g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", top + lines.length * 14).text(n.sub);
      }
      if (n.tags) drawTags(g, n, s);
      if (n.inert && n.why) g.append("title").text(`${(n.lines || [n.label]).join(" ")}: not a stock. ${n.why}`);
      // keyboard focus: a white ring outside a dark gap, shown only while focused (style.css)
      if (n.kind !== "cloud" && !n.inert) {
        if (s.r) { g.append("circle").attr("class", "ng-focusring gap").attr("r", s.r + 5); g.append("circle").attr("class", "ng-focusring ring").attr("r", s.r + 7); }
        else { g.append("rect").attr("class", "ng-focusring gap").attr("x", -s.w / 2 - 5).attr("y", -s.h / 2 - 5).attr("width", s.w + 10).attr("height", s.h + 10).attr("rx", 8);
               g.append("rect").attr("class", "ng-focusring ring").attr("x", -s.w / 2 - 7).attr("y", -s.h / 2 - 7).attr("width", s.w + 14).attr("height", s.h + 14).attr("rx", 9); }
      }
    }
    // ``tags``: small labelled boxes stacked above a node (or below, ``below: true``), each
    // {text, cls}: what the page wants said of it on the map ("heard", "+ new link")
    function drawTags(g, n, s) {
      const hh = s.r || s.h / 2, up = n.tags.filter((t) => !t.below), down = n.tags.filter((t) => t.below);
      const one = (t, y) => {
        const w = String(t.text).length * 5.6 + 10, tg = g.append("g").attr("class", "ng-tag " + (t.cls || "")).attr("transform", `translate(${-w / 2},${y})`);
        tg.append("rect").attr("width", w).attr("height", 13).attr("rx", 3);
        tg.append("text").attr("x", w / 2).attr("y", 9.5).attr("text-anchor", "middle").text(t.text);
      };
      up.forEach((t, i) => one(t, -hh - 18 - i * 15));
      down.forEach((t, i) => one(t, hh + (s.r ? (n.sub ? 30 : 18) : 4) + i * 15));      // under a circle's name; right under a box
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
      const edgeSel = gEdges.selectAll("g.ng-edge").data(ALL, (e) => e.id).join("g").attr("class", (e) => `ng-edge ${e.cls || ""}${e.warn ? " ng-warn" : ""}`).attr("data-id", (e) => e.id);
      edgeSel.each(function (e) {
        const g = d3.select(this); g.selectAll("*").remove();
        const col = e.color || "#4b5563";
        // ``both``: one line for two nodes linked both ways, an arrowhead at each end
        g.append("path").attr("class", "ng-line").attr("stroke", col).attr("stroke-width", e.width || 1.6).attr("stroke-dasharray", e.dash || (e.dashed ? "5 4" : null)).attr("marker-end", e.arrow === false ? null : marker(col))
          .attr("marker-start", e.both ? marker(col, true) : null);
        // a double line: the line drawn wide, and its middle drawn again in the background's colour
        if (e.double) { g.classed("ng-double", true); g.append("path").attr("class", "ng-gap"); }
        g.append("path").attr("class", "ng-hit");
        if (e.rate) g.append("path").attr("class", "ng-flowdash").style("animation-duration", `${Math.max(0.25, Math.min(6, 8 / Math.sqrt(e.rate))).toFixed(2)}s`);
        g.on("mouseenter", (ev) => { showTip(tip && tip(e, "edge"), ev); gLabels.selectAll("g.ng-label").filter((x) => x.id === e.id).classed("ng-lit", true); }).on("mousemove", moveTip)
          .on("mouseleave", () => { hideTip(); gLabels.selectAll("g.ng-label").filter((x) => x.id === e.id).classed("ng-lit", false); })
          .on("click", (ev) => { hideTip(); onClick && onClick(e, "edge"); });
      });
      // a label is part of its edge: hovering it shows the edge's tip, clicking it does what clicking the edge does
      const labelSel = gLabels.selectAll("g.ng-label").data(ALL.filter((e) => e.label || e.sign), (e) => e.id).join("g").attr("class", (e) => `${onClick ? "ng-label ng-clickable" : "ng-label"}${e.quiet ? " ng-quiet" : ""}${e.warn ? " ng-warn" : ""}`).attr("data-id", (e) => e.id)
        .on("mouseenter", (ev, e) => showTip(tip && tip(e, "edge"), ev)).on("mousemove", moveTip).on("mouseleave", hideTip)
        .on("click", (ev, e) => { hideTip(); onClick && onClick(e, "edge"); });
      // a flow's label is reachable from the keyboard: Enter or Space opens it as a click does
      // (out of the Tab order: the nodes come first; a label is reached from its node's panel, or by the pointer)
      if (onClick) labelSel.attr("tabindex", (e) => (e.label && e.fid ? -1 : null)).attr("role", (e) => (e.label && e.fid ? "button" : null))
        .attr("aria-label", (e) => (e.label ? `${(e.source.lines || [e.source.label]).join(" ")} → ${(e.target.lines || [e.target.label]).join(" ")}: ${(Array.isArray(e.label) ? e.label : [e.label]).filter(Boolean).join(", ")}` : null))
        .on("keydown", (ev, e) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onClick(e, "edge"); } })
        .on("focus", (ev, e) => { const m = e._mid; if (m) panTo(m.x, m.y); });
      labelSel.each(function (e) { drawLabel(d3.select(this), e); });
      // an ``inert`` node opens nothing: no tab stop, no button, the default cursor (its tooltip says what it is)
      const nodeSel = gNodes.selectAll("g.ng-node").data(NODES, (n) => n.id).join("g").attr("class", (n) => `ng-node ng-${n.kind} ${n.cls || ""}${n.inert ? " ng-inert" : ""}`).attr("data-id", (n) => n.id);
      // reachable from the keyboard: Tab to a node, Enter or Space opens it as a click does; a node
      // focused outside the view is brought into it
      if (onClick) nodeSel.attr("tabindex", (n) => (n.kind === "cloud" || n.inert ? null : 0)).attr("role", (n) => (n.kind === "cloud" || n.inert ? null : "button"))
        .attr("aria-label", (n) => [(n.lines || [n.label]).join(" "), n.caption, typeof n.sub === "string" ? n.sub.trim() : ""].filter(Boolean).join(", "))
        .on("keydown", (ev, n) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onClick(n, "node"); } })
        .on("focus", (ev, n) => { isolate(n.id); panTo(n.x, n.y); }).on("blur", () => isolate(null));
      // a node is drawn again only when what it shows changed (or it draws live data), so a refresh
      // every few seconds keeps what the viewer is pointing at
      nodeSel.each(function (n) { const sig = n.decorate ? null : drawSig(n); if (sig === null || this.__ngsig !== sig) { this.__ngsig = sig; drawNode(d3.select(this), n); } });
      nodeSel.on("mouseenter", (ev, n) => { HOVER = n.id; isolate(n.id); showTip(tip && tip(n, "node"), ev); }).on("mousemove", moveTip)
        .on("mouseleave", () => { HOVER = null; isolate(null); hideTip(); }).on("click", (ev, n) => { hideTip(); onClick && onClick(n, "node"); })
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
      // a layout settling carries on; it starts again only for new nodes (a redraw every few seconds
      // with nothing new must not keep it from ever settling, and the view from being fitted)
      else if (settling && !fresh.length && sim) {
        for (const n of NODES) { const hold = n.pin || !settling.movable.has(n.id); n.fx = hold ? n.x : null; n.fy = hold ? n.y : null; }
        sim.nodes(NODES); if (sim.force("link")) sim.force("link").links(EDGES); tick();
      }
      else if (settling) settle(new Set([...settling.movable].filter((id) => byId.has(id)).concat(fresh.map((n) => n.id))), Math.max(0.5, sim ? sim.alpha() : 0.5), true);
      else if (fresh.length === NODES.length) settle(new Set(NODES.map((n) => n.id)), 1, true);
      else if (fresh.length) settle(new Set(fresh.map((n) => n.id)), 0.5, true);
      else { tick(); relabel(); }                                // nothing new: nothing moves
      // the first drawing fits the view (a layout still settling fits when it is done)
      // (a whole new layout is shown when it is done: glide reveals it)
      if (!drawnOnce) { drawnOnce = true; const whole = layout && fresh.length === NODES.length;
        if (!settling && !whole) requestAnimationFrame(() => { refit(false); autoFitted = true; reveal(); }); else if (layout && !whole) reveal(); }
      if (pinned) highlight(pinned.nodes, pinned.edges);
      else if (focused) applyFocus();
      else if (HOVER && byId.has(HOVER)) isolate(HOVER);           // the pointer is still on a node: keep its neighbourhood lit
    }
    let HOVER = null;
    // what a node draws, as a string: unchanged, it is not drawn again
    const drawSig = (n) => JSON.stringify([n.kind, n.label, n.lines, n.sub, n.caption, n.color, n.stroke, n.strokeWidth, n.halo, n.tags, n.w, n.h, n.dashed, n.fill, n.textColor, n.rx]);
    // a label's text: the lines of its edge, the first in full, the rest a quiet aside when ``labelMuted``
    function drawLabel(g, e) {
      g.selectAll("*").remove();
      g.append("line").attr("class", "ng-leader");             // drawn when the label sits away from its line (tick)
      if (e.sign) g.append("text").attr("class", "ng-sign").attr("text-anchor", "middle").attr("fill", e.color || "var(--muted)").text(e.sign);
      if (e.label) { const t = g.append("text").attr("class", "ng-elabel").attr("text-anchor", "middle"); (Array.isArray(e.label) ? e.label : [e.label]).forEach((l, i) => t.append("tspan").attr("x", 0).attr("dy", i ? 12 : 0).attr("class", i && e.labelMuted ? "ng-muted" : null).attr("fill", i && !e.labelMuted ? (e.color || "var(--muted)") : null).text(l)); }
    }
    // bring a point (a focused node) into view when it is outside it
    function panTo(x, y) {
      if (x === undefined) return;
      const t = d3.zoomTransform(svgEl), sx = t.applyX(x), sy = t.applyY(y), m = 40;
      if (sx < m || sx > W() - m || sy < m || sy > H - m) svg.transition().duration(300).call(zoom.translateTo, x, y);
    }
    // a new node starts by the nodes it is linked to (or at its anchor, or the middle)
    function placeNew(edges, byId) {
      const w = W();
      for (const n of NODES.filter((x) => x._new)) {
        const nb = edges.flatMap((e) => (e.source === n.id ? [e.target] : e.target === n.id ? [e.source] : []))
          .map((id) => byId.get(id)).filter((m) => m && !m._new);
        const [x, y] = nb.length ? [nb.reduce((a, m) => a + m.x, 0) / nb.length, nb.reduce((a, m) => a + m.y, 0) / nb.length]
          : n.anchor ? [n.anchor[0] * w, n.anchor[1] * H] : [w / 2, H / 2];
        const [jx, jy] = jitter(n.id);                          // the same on every load: seeded by the node's id
        n.x = x + jx * 80; n.y = y + jy * 80;
      }
    }
    // two numbers in [-0.5, 0.5) from a node's id (FNV-1a): a new node's offset, never random
    function jitter(id) {
      let h = 2166136261; for (const ch of String(id)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; }
      return [(h & 0xffff) / 0x10000 - 0.5, ((h >>> 16) & 0xffff) / 0x10000 - 0.5];
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
      const gen = ++placing;
      if (sim) sim.stop();
      settling = null;
      const first = NODES.every((n) => n._new);
      let at = Object.fromEntries(NODES.filter((n) => n.x !== undefined).map((n) => [n.id, [n.x, n.y]]));
      if (!fromHere) {
        try { at = await layout(NODES, RAW_EDGES); } catch (e) { console.error("layout failed; using the forces", e); reveal(); settle(new Set(NODES.map((n) => n.id)), 1, true); return; }
        if (gen !== placing) return;                             // a newer layout was asked for
      }
      if (polish) {
        const fixed = all ? [] : NODES.filter((n) => n.pin).map((n) => n.id);
        try { at = await polish(NODES.map(plain), RAW_EDGES.map(plain), at, fixed); } catch (e) { console.error("polish failed", e); }
        if (gen !== placing) return;                             // the viewer dragged, or asked again
      }
      await glide(at, all, first ? 0 : 650);                     // the first layout appears at once, finished
    }
    // move the nodes to ``at`` (the viewer's placements stay, unless ``all``), over ``ms``, then
    // place the labels and fit the view
    function glide(at, all, ms) {
      const moving = NODES.filter((n) => at[n.id] && (all || !n.pin)).map((n) => ({ n, x0: n.x ?? at[n.id][0], y0: n.y ?? at[n.id][1], x1: at[n.id][0], y1: at[n.id][1] }));
      for (const m of moving) { m.n._new = false; m.n.fx = m.n.fy = null; }
      return new Promise((resolve) => {
        const t0 = performance.now(), gen = placing;
        const frame = (t) => {
          const k = ms ? Math.min(1, (t - t0) / ms) : 1, e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
          if (gen !== placing) return resolve();
          for (const m of moving) { m.n.x = m.x0 + (m.x1 - m.x0) * e; m.n.y = m.y0 + (m.y1 - m.y0) * e; }
          tick();
          if (k < 1) return requestAnimationFrame(frame);
          save(); relabel();
          if (!userZoomed && (!autoFitted || asked || outOfView())) { refit(ms > 0); autoFitted = true; }
          asked = false; reveal(); resolve();
        };
        ms ? requestAnimationFrame(frame) : frame(t0 + 1);
      });
    }
    // labels: placed where they cover no box and no other label (placeLabels), whenever the graph rests
    let LABEL_AT = {};
    function relabel() {
      const mids = Object.fromEntries(ALLEDGES.filter((e) => e._mid).map((e) => [e.id, e._mid]));
      const b = frameBox(), t = 6;
      const obstacles = b ? [[b.x0 + 10, b.y0 - 18, b.x0 + 14 + String(boundary.label || "the system").length * 6.6, b.y0 + 2],
        [b.x0 - t, b.y0 - t, b.x1 + t, b.y0 + t], [b.x0 - t, b.y1 - t, b.x1 + t, b.y1 + t], [b.x0 - t, b.y0, b.x0 + t, b.y1], [b.x1 - t, b.y0, b.x1 + t, b.y1]] : [];
      LABEL_AT = placeLabels(NODES, ALLEDGES, mids, obstacles);
      tick();
      crowd();
      // the Tab order is the layout's: top to bottom, left to right
      // (moving a focused node in the document drops its focus: it is given back)
      const had = document.activeElement && svgEl.contains(document.activeElement) ? document.activeElement : null;
      gNodes.selectAll("g.ng-node").sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (a.x ?? 0) - (b.x ?? 0));
      if (had && document.activeElement !== had && had.isConnected) try { had.focus({ preventScroll: true }); } catch (e) {}
    }
    // a label that still overlaps another (or a node's caption) where it was placed is hidden until
    // its edge is hovered or it is focused (style.css .ng-crowded): the widest first keep their place
    function crowd() {
      const taken = NODES.filter((n) => n.x !== undefined && n.kind !== "cloud").map((n) => { const s = size(n), hw = s.r ? Math.max(s.r, String(n.label || "").length * 3.2) : s.w / 2, hh = s.r ? s.r : s.h / 2;
        return [n.x - hw, n.y - hh, n.x + hw, n.y + hh + (s.r ? (n.sub ? 28 : 16) : 0)]; });
      const hit = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
      const crowded = new Set();
      for (const e of ALLEDGES.filter((x) => x._mid && x.label && labelSize(x)).sort((a, b) => labelSize(b).w - labelSize(a).w)) {
        const [dx, dy] = LABEL_AT[e.id] || [0, 0], z = labelSize(e), cx = e._mid.x + dx, cy = e._mid.y + dy;
        const box = [cx - z.w / 2, cy - z.h / 2, cx + z.w / 2, cy + z.h / 2];
        if (taken.some((t) => hit(box, t))) crowded.add(e.id); else taken.push(box);
      }
      gLabels.selectAll("g.ng-label").classed("ng-crowded", (e) => crowded.has(e.id));
    }
    // how far a node's drawing reaches: its shape, and for a circle its name and sub-line under it and
    // its tags above (text about 6 px a character), so captions never overprint each other
    function reach(n) {
      const s = size(n), base = (s.r || Math.max(s.w, s.h) / 2) + 24;
      if (!s.r) return base;
      const text = Math.max(String(n.label || "").length, String(n.sub || "").length, ...(n.tags || []).map((t) => String(t.text).length)) * 3.2 + 10;
      return Math.max(base, text, s.r + 12 + (n.sub ? 28 : 16));
    }
    function settle(movable, alpha, again) {
      if (sim) sim.stop();
      settling = { movable, refit: again };
      for (const n of NODES) { const hold = n.pin || !movable.has(n.id); n.fx = hold ? n.x : null; n.fy = hold ? n.y : null; }
      const w = W(), ax = (n) => (n.anchor ? n.anchor[0] * w : w / 2), ay = (n) => (n.anchor ? n.anchor[1] * H : H / 2);
      sim = d3.forceSimulation(NODES)
        .force("link", d3.forceLink(EDGES).id((d) => d.id).distance((e) => e.distance || 110).strength((e) => e.strength ?? 0.6))
        .force("charge", d3.forceManyBody().strength((n) => n.charge ?? -480))
        .force("x", d3.forceX(ax).strength((n) => (n.anchor ? 0.15 : 0.04)))     // weak gravity; anchored nodes pulled to their spot
        .force("y", d3.forceY(ay).strength((n) => (n.anchor ? 0.15 : 0.04)))
        .force("collide", d3.forceCollide(reach))
        .force("boundary", boundary ? keepOutside : null)
        .force("edge", boundary ? towardEdge : null)
        .alpha(alpha);
      const whole = movable.size === NODES.length;
      // the first settling is shown fitted once most of its movement is done, not while it flies apart
      // the first settling is shown once it has settled, fitted once; a later one (new data) keeps the
      // viewer's view unless asked (tidy, reset) or something new would be out of view
      if (hidden()) sim.alphaMin(REVEAL_ALPHA / 4);
      sim.on("tick", tick)
        .on("end", () => { settling = null; const added = NODES.some((n) => n._new); for (const n of NODES) { n.fx = n.fy = null; n._new = false; }
          if (isolatedRow && whole) rowIsolated();
          save(); relabel();
          if (again && !userZoomed && (!autoFitted || asked || added || outOfView())) { refit(!hidden()); autoFitted = true; }
          asked = false; reveal(); });
      tick();
    }
    // the nodes linked to nothing (not placed by the viewer): in rows directly under the rest
    // (netgraph-geometry.js isolatedRows), never left wherever the forces threw them
    function rowIsolated() {
      const linked = new Set(EDGES.flatMap((e) => [e.source.id, e.target.id]));
      const lone = NODES.filter((n) => !linked.has(n.id) && !n.pin && !n.tether && n.x !== undefined), rest = NODES.filter((n) => linked.has(n.id) && n.x !== undefined);
      const at = isolatedRows(lone, rest);
      for (const n of lone) if (at[n.id]) [n.x, n.y] = at[n.id];
      tick();
    }
    // whether any node is out of the view as it is now
    const outOfView = () => { const t = d3.zoomTransform(svgEl); return outside(t.k, t.x, t.y).length > 0; };
    let asked = false;                                // tidy or reset: the next settling refits
    // lay it out again: around the viewer's placements, or (``reset``) from nothing
    function tidy(reset) {
      if (!NODES.length) return;
      asked = true;
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
        frameLabel.attr("x", b.x0 + 14).attr("y", b.y0 - 6).text(boundary.label || "the system");   // above the frame: no flow label crosses it
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
      }).each(function (e) {
        // a label set away from its line keeps a thin leader to the line's middle
        const [dx, dy] = LABEL_AT[e.id] || [0, 0], s = labelSize(e) || { w: 12, h: 16 }, base = e.label ? 11 : 13, far = Math.hypot(dx, dy) > 24;
        const mx = -dx, my = -dy + s.h / 2 - base, top = -base, bot = s.h - base;
        d3.select(this).select("line.ng-leader").style("display", far && e._mid ? null : "none")
          .attr("x1", mx).attr("y1", my).attr("x2", Math.max(-s.w / 2, Math.min(s.w / 2, mx))).attr("y2", Math.max(top, Math.min(bot, my)));
      });
      gNodes.selectAll("g.ng-node").attr("transform", (n) => (n.x === undefined ? null : `translate(${n.x},${n.y})`));
    }
    // hover: a node, its edges and their far ends; with two hops, also what those reach (a
    // machine, its event types, and the machines on the other side of them)
    function isolate(id) {
      if (pinned || focused) return;
      const ns = gNodes.selectAll("g.ng-node"), es = gEdges.selectAll("g.ng-edge"), ls = gLabels.selectAll("g.ng-label");
      // an edge with a ``hoverColor`` shows it while its neighbourhood is isolated, and goes back after
      const paint = (lit) => es.each(function (e) {
        if (!e.hoverColor) return;
        const col = lit && lit.has(e.id) ? e.hoverColor : e.color || "#4b5563";
        d3.select(this).select(".ng-line").attr("stroke", col).attr("marker-end", e.arrow === false ? null : marker(col)).attr("marker-start", e.both ? marker(col, true) : null).classed("ng-hover", !!(lit && lit.has(e.id)));
      });
      if (!id) { ns.classed("ng-dim", false); es.classed("ng-dim", false); ls.classed("ng-dim", false).classed("ng-lit", false); paint(null); return; }
      const { keep, lit } = neighbourhood(id);
      ns.classed("ng-dim", (n) => !keep.has(n.id)); es.classed("ng-dim", (e) => !lit.has(e.id)); ls.classed("ng-dim", (e) => !lit.has(e.id)).classed("ng-lit", (e) => lit.has(e.id));
      paint(lit);
    }
    // a loop or any set: these nodes and edges in gold, everything else faded
    function highlight(nodeIds, edgeIds) {
      pinned = nodeIds ? { nodes: nodeIds, edges: edgeIds } : null;
      const ns = gNodes.selectAll("g.ng-node"), es = gEdges.selectAll("g.ng-edge"), ls = gLabels.selectAll("g.ng-label");
      const N = new Set(nodeIds || []), E = new Set(edgeIds || []);
      if (nodeIds) for (const sel of [ns, es, ls]) sel.classed("ng-shade1 ng-shade2", false);
      ns.classed("ng-dim", (n) => !!nodeIds && !N.has(n.id)).classed("ng-hl", (n) => N.has(n.id));
      es.classed("ng-dim", (e) => !!nodeIds && !E.has(e.id)).classed("ng-hl", (e) => E.has(e.id));
      ls.classed("ng-dim", (e) => !!nodeIds && !E.has(e.id));
      if (!nodeIds && focused) applyFocus();
    }
    // a focus kept while a details panel is open: ``levelOf(node)`` is 1 (full colour), .7, .45 or
    // anything lower (dimmed, ng-dim); an edge takes the lesser of its ends unless ``edgeLevel(e)``
    // says otherwise. Hovering does not isolate while it holds; focus(null) lets go.
    let focused = null;
    const SHADES = [[0.7, "ng-shade1"], [0.45, "ng-shade2"]];
    function applyFocus() {
      const ns = gNodes.selectAll("g.ng-node"), es = gEdges.selectAll("g.ng-edge"), ls = gLabels.selectAll("g.ng-label");
      const lv = new Map(NODES.map((n) => [n.id, focused ? focused.levelOf(n) : 1]));
      const edgeLv = (e) => { const own = focused && focused.edgeLevel ? focused.edgeLevel(e) : null;
        return own != null ? own : Math.min(lv.get(e.source.id) ?? 0, lv.get((e.toEdge ? e.toEdge.target : e.target).id) ?? 0); };
      const cls = (sel, level) => { sel.classed("ng-dim", (x) => level(x) < 0.45); for (const [v, c] of SHADES) sel.classed(c, (x) => level(x) >= v && level(x) < (v === 0.7 ? 1 : 0.7)); };
      cls(ns, (n) => lv.get(n.id) ?? 0); cls(es, edgeLv); cls(ls, edgeLv);
      ns.classed("ng-focus", (n) => !!focused && focused.id === n.id);
    }
    function focus(spec) {
      focused = spec;
      if (!spec) { const all = [gNodes.selectAll("g.ng-node"), gEdges.selectAll("g.ng-edge"), gLabels.selectAll("g.ng-label")];
        for (const sel of all) sel.classed("ng-dim ng-shade1 ng-shade2 ng-focus", false);
        if (pinned) highlight(pinned.nodes, pinned.edges); return; }
      if (!pinned) applyFocus();
    }
    // redraw the decorations of the given nodes (live data) without touching the layout
    function refreshNodes(update) {
      gNodes.selectAll("g.ng-node").each(function (n) { const u = update(n); if (u) { Object.assign(n, u); drawNode(d3.select(this), n); } });
    }
    // change edges' labels without a new layout: ``labelOf(e)`` -> {label, quiet, warn} or null to
    // leave one; ``warn`` marks the edge and its label in the warning colour (style.css .ng-warn)
    function setLabels(labelOf) {
      let changed = false;
      for (const e of ALLEDGES) { const u = labelOf(e); if (!u) continue;
        if (JSON.stringify(u.label) !== JSON.stringify(e.label) || !!u.quiet !== !!e.quiet || !!u.warn !== !!e.warn) { e.label = u.label; e.quiet = !!u.quiet; e.warn = !!u.warn; changed = true; } }
      if (!changed) return;
      gLabels.selectAll("g.ng-label").each(function (e) { drawLabel(d3.select(this), e); d3.select(this).classed("ng-quiet", !!e.quiet).classed("ng-warn", !!e.warn); });
      gEdges.selectAll("g.ng-edge").classed("ng-quiet", (e) => !!e.quiet).classed("ng-warn", (e) => !!e.warn);
      relabel();
    }
    function setRates(rateOf) {
      gEdges.selectAll("g.ng-edge").each(function (e) {
        const r = rateOf(e), g = d3.select(this); g.selectAll(".ng-flowdash").remove();
        if (r && r > 0.01) g.append("path").attr("class", "ng-flowdash").attr("d", g.select(".ng-line").attr("d")).style("animation-duration", `${Math.max(0.25, Math.min(6, 8 / Math.sqrt(r))).toFixed(2)}s`);
      });
    }
    return { render, highlight, focus, refreshNodes, setRates, setLabels, fit, fitAround, tidy, zoomed: () => userZoomed, edgesBetween: (ids) => EDGES.filter((e) => ids.includes(e.source.id) && ids.includes(e.target.id)) };
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

  return { create, loopList };
})();
