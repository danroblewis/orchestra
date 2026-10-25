// One network renderer for every graph in the UI (the Machines page's event map, the Dynamics
// page's stock-and-flow model): a d3 force layout with
//   nodes   circle (a machine: initial inside, name beneath, optional halo), box (an event type, a
//           stock: lines of text, optional decoration), valve (a flow: a small dot with a label),
//           cloud (outside: a source or a sink);
//   edges   solid or dashed, coloured, with an arrow, an optional label and sign, and optional
//           moving dashes whose speed follows a rate;
//   loops   elementary cycles of a directed graph, listed and clickable: clicking one highlights
//           its nodes and edges and fades the rest;
// plus drag, zoom and pan, hover to isolate a neighbourhood, and positions that persist across
// redraws (and reloads) so a live graph never reshuffles.
const NetGraph = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const POS_KEY = (k) => `orchestra.netgraph.${k}`;

  // ---- geometry ----
  function size(n) {
    if (n.kind === "circle") return { r: n.r || 22 };
    if (n.kind === "valve") return { r: 7 };
    if (n.kind === "cloud") return { r: 14 };
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
  function create(container, { key, height = 600, isolateHops = 1, onClick, tip } = {}) {
    container.innerHTML = "";
    const svgEl = document.createElementNS(NS, "svg");
    svgEl.setAttribute("class", "netgraph");
    container.appendChild(svgEl);
    const W = () => container.clientWidth || 1000, H = height;
    const svg = d3.select(svgEl).attr("viewBox", `0 0 ${W()} ${H}`).style("height", H + "px");
    const defs = svg.append("defs");
    defs.html(`<linearGradient id="ng-halo" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="60" y2="60"><stop offset="0" stop-color="#60a5fa"/><stop offset=".5" stop-color="#c084fc"/><stop offset="1" stop-color="#22c55e"/></linearGradient>`);
    const root = svg.append("g"), gEdges = root.append("g"), gLabels = root.append("g"), gNodes = root.append("g");
    svg.call(d3.zoom().scaleExtent([0.25, 4]).filter((ev) => ev.type === "wheel" || !ev.target.closest(".ng-node")).on("zoom", (ev) => root.attr("transform", ev.transform)));
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(POS_KEY(key)) || "{}"); } catch (e) {}
    const markers = new Set();
    const marker = (col) => {
      const id = "ng-arr-" + col.replace(/[^a-z0-9]/gi, "");
      if (!markers.has(id)) { markers.add(id); defs.append("marker").attr("id", id).attr("viewBox", "0 -4 8 8").attr("refX", 8).attr("refY", 0).attr("markerWidth", 7).attr("markerHeight", 7).attr("orient", "auto").append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", col); }
      return `url(#${id})`;
    };
    let sim = null, NODES = [], EDGES = [], sig = null, pinned = null;
    const tipEl = () => { let t = document.getElementById("ng-tip"); if (!t) { t = document.createElement("div"); t.id = "ng-tip"; t.className = "ng-tip"; document.body.appendChild(t); } return t; };
    const showTip = (html, ev) => { if (!html) return; const t = tipEl(); t.innerHTML = html; t.style.display = "block"; moveTip(ev); };
    const moveTip = (ev) => { const t = tipEl(), r = t.getBoundingClientRect(); t.style.left = Math.min(innerWidth - r.width - 8, ev.clientX + 14) + "px"; t.style.top = Math.min(innerHeight - r.height - 8, ev.clientY + 14) + "px"; };
    const hideTip = () => { tipEl().style.display = "none"; };

    function save() {
      const pos = Object.fromEntries(NODES.map((n) => [n.id, [Math.round(n.x), Math.round(n.y)]]));
      try { localStorage.setItem(POS_KEY(key), JSON.stringify(pos)); } catch (e) {}
    }
    function path(e) {
      const s = e.source, t = e.target;
      if (s === t) return `M${s.x},${s.y - 20} C${s.x + 50},${s.y - 70} ${s.x + 70},${s.y - 20} ${s.x + 20},${s.y}`;
      const dx = t.x - s.x, dy = t.y - s.y, d = Math.hypot(dx, dy) || 1, bend = e.bend ?? 22;
      const mx = (s.x + t.x) / 2 - dy / d * bend, my = (s.y + t.y) / 2 + dx / d * bend;
      const a = edgePoint(s, mx, my, 1), b = edgePoint(t, mx, my, 3);
      e._mid = { x: (a.x + 2 * mx + b.x) / 4, y: (a.y + 2 * my + b.y) / 4 };
      return `M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}`;
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
        g.append("circle").attr("r", s.r).attr("fill", n.color || "#94a3b8").attr("stroke", "var(--panel)").attr("stroke-width", 2);
      } else if (n.kind === "cloud") {
        g.append("path").attr("class", "ng-cloud").attr("d", "M-10,6 a6,6 0 0 1 0,-12 a8,8 0 0 1 14,-3 a6,6 0 0 1 8,9 a5,5 0 0 1 -4,6 Z");
      } else {
        g.append("rect").attr("class", "ng-box").attr("x", -s.w / 2).attr("y", -s.h / 2).attr("width", s.w).attr("height", s.h).attr("rx", n.rx ?? 5)
          .attr("stroke", n.color || "#6b5313").attr("fill", n.fill || "#0b0e14");
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
      NODES = nodes.map((n) => { const o = old.get(n.id); const p = o ? [o.x, o.y] : saved[n.id]; return { ...n, x: p ? p[0] : undefined, y: p ? p[1] : undefined }; });
      const byId = new Map(NODES.map((n) => [n.id, n]));
      EDGES = edges.filter((e) => byId.has(e.source) && byId.has(e.target)).map((e) => ({ ...e, source: byId.get(e.source), target: byId.get(e.target) }));
      const structural = newSig !== sig;
      sig = newSig;
      const edgeSel = gEdges.selectAll("g.ng-edge").data(EDGES, (e) => e.id).join("g").attr("class", (e) => `ng-edge ${e.cls || ""}`).attr("data-id", (e) => e.id);
      edgeSel.each(function (e) {
        const g = d3.select(this); g.selectAll("*").remove();
        const col = e.color || "#4b5563";
        g.append("path").attr("class", "ng-line").attr("stroke", col).attr("stroke-width", e.width || 1.6).attr("stroke-dasharray", e.dashed ? "5 4" : null).attr("marker-end", e.arrow === false ? null : marker(col));
        g.append("path").attr("class", "ng-hit");
        if (e.rate) g.append("path").attr("class", "ng-flowdash").style("animation-duration", `${Math.max(0.25, Math.min(6, 8 / Math.sqrt(e.rate))).toFixed(2)}s`);
        g.on("mouseenter", (ev) => showTip(tip && tip(e, "edge"), ev)).on("mousemove", moveTip).on("mouseleave", hideTip)
          .on("click", (ev) => { hideTip(); onClick && onClick(e, "edge"); });
      });
      const labelSel = gLabels.selectAll("g.ng-label").data(EDGES.filter((e) => e.label || e.sign), (e) => e.id).join("g").attr("class", "ng-label").attr("data-id", (e) => e.id);
      labelSel.each(function (e) {
        const g = d3.select(this); g.selectAll("*").remove();
        if (e.sign) g.append("text").attr("class", "ng-sign").attr("text-anchor", "middle").attr("fill", e.color || "var(--muted)").text(e.sign);
        if (e.label) { const t = g.append("text").attr("class", "ng-elabel").attr("text-anchor", "middle"); (Array.isArray(e.label) ? e.label : [e.label]).forEach((l, i) => t.append("tspan").attr("x", 0).attr("dy", i ? 12 : 0).attr("fill", i ? (e.color || "var(--muted)") : null).text(l)); }
      });
      const nodeSel = gNodes.selectAll("g.ng-node").data(NODES, (n) => n.id).join("g").attr("class", (n) => `ng-node ng-${n.kind} ${n.cls || ""}`).attr("data-id", (n) => n.id);
      nodeSel.each(function (n) { drawNode(d3.select(this), n); });
      nodeSel.on("mouseenter", (ev, n) => { isolate(n.id); showTip(tip && tip(n, "node"), ev); }).on("mousemove", moveTip)
        .on("mouseleave", () => { isolate(null); hideTip(); }).on("click", (ev, n) => { hideTip(); onClick && onClick(n, "node"); })
        .call(d3.drag().on("start", (ev, d) => { if (!ev.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on("drag", (ev, d) => { d.fx = ev.x; d.fy = ev.y; }).on("end", (ev, d) => { if (!ev.active) sim.alphaTarget(0); d.fx = d.fy = null; save(); }));
      if (sim) sim.stop();
      const w = W();
      sim = d3.forceSimulation(NODES)
        .force("link", d3.forceLink(EDGES).id((d) => d.id).distance((e) => e.distance || 110).strength((e) => e.strength ?? 0.6))
        .force("charge", d3.forceManyBody().strength((n) => n.charge ?? -480))
        .force("center", d3.forceCenter(w / 2, H / 2))
        .force("collide", d3.forceCollide((n) => { const s = size(n); return (s.r || Math.max(s.w, s.h) / 2) + 24; }));
      if (!structural && NODES.every((n) => n.x !== undefined)) sim.alpha(0.02);   // live update: barely move
      else if (NODES.every((n) => n.x !== undefined)) sim.alpha(0.15);
      sim.on("tick", tick).on("end", save);
      tick();
      if (pinned) highlight(pinned.nodes, pinned.edges);
    }
    function tick() {
      gEdges.selectAll("g.ng-edge").each(function (e) {
        if (e.source.x === undefined) return;
        const d = path(e), g = d3.select(this);
        g.selectAll("path").attr("d", d);
      });
      gLabels.selectAll("g.ng-label").attr("transform", (e) => (e._mid ? `translate(${e._mid.x},${e._mid.y - 6})` : null));
      gNodes.selectAll("g.ng-node").attr("transform", (n) => (n.x === undefined ? null : `translate(${n.x},${n.y})`));
    }
    // hover: a node, its edges and their far ends; with two hops, also what those reach (a
    // machine, its event types, and the machines on the other side of them)
    function isolate(id) {
      if (pinned) return;
      const ns = gNodes.selectAll("g.ng-node"), es = gEdges.selectAll("g.ng-edge"), ls = gLabels.selectAll("g.ng-label");
      if (!id) { ns.classed("ng-dim", false); es.classed("ng-dim", false); ls.classed("ng-dim", false); return; }
      const keep = new Set([id]), lit = new Set();
      let frontier = [id];
      for (let h = 0; h < isolateHops; h++) {
        const next = [];
        EDGES.forEach((e) => { for (const [a, b] of [[e.source.id, e.target.id], [e.target.id, e.source.id]]) if (frontier.includes(a)) { lit.add(e.id); if (!keep.has(b)) { keep.add(b); next.push(b); } } });
        frontier = next.filter((x) => (NODES.find((n) => n.id === x) || {}).hop);
      }
      ns.classed("ng-dim", (n) => !keep.has(n.id)); es.classed("ng-dim", (e) => !lit.has(e.id)); ls.classed("ng-dim", (e) => !lit.has(e.id));
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
    return { render, highlight, refreshNodes, setRates, edgesBetween: (ids) => EDGES.filter((e) => ids.includes(e.source.id) && ids.includes(e.target.id)) };
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

  return { create, cycles, loopList, size };
})();
