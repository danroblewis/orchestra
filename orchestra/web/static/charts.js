// Line charts and sparklines with hover: a crosshair, the nearest point of each line, and a
// tooltip with every line's value at that time. Charts are HTML strings; hover is one delegated
// listener, so charts can be re-rendered freely.
const Charts = (() => {
  const PAL = ["#60a5fa", "#f59e0b", "#22c55e", "#e879f9", "#f87171", "#38bdf8", "#facc15", "#a78bfa", "#fb923c", "#94a3b8"];
  const REG = new Map();
  let seq = 0;
  const num = (v) => (v == null ? "—" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : Math.abs(v) >= 10 ? (+v).toFixed(1) : (+v).toPrecision(3).replace(/\.?0+$/, ""));
  const tlabel = (t, span) => { const d = new Date(t * 1000); return span > 2 * 86400 ? `${d.getMonth() + 1}/${d.getDate()}` : d.toTimeString().slice(0, 5); };
  const register = (spec) => { const id = "c" + ++seq; REG.set(id, spec); if (REG.size > 60) REG.delete(REG.keys().next().value); return id; };

  // W is the drawing width in pixels: pass the container's width so text and lines keep their size
  function line(lines, { unit = "", H = 200, W = 720 } = {}) {
    const pts = lines.flatMap((l) => l.points);
    if (!pts.length) return `<div class="empty">no points in this range</div>`;
    W = Math.max(320, Math.round(W));
    const L = 46, B = 18, T = 6, R = 8;
    const t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(...pts.map((p) => p[0])) || t0 + 1;
    const hi = Math.max(0, ...pts.map((p) => p[1])), lo = Math.min(0, ...pts.map((p) => p[1])), span = hi - lo || 1;
    const x = (t) => L + (W - L - R) * (t - t0) / Math.max(1, t1 - t0), y = (v) => T + (H - T - B) * (1 - (v - lo) / span);
    const id = register({ lines, x, y, t0, t1, L, R, W, H, T, B, unit, dots: true });
    const ticks = [lo, lo + span / 2, hi].map((v) => `<line class="ax" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke-dasharray="2 4"/><text x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${num(v)}</text>`).join("");
    const xt = [0, 0.5, 1].map((f) => `<text x="${L + (W - L - R) * f}" y="${H - 4}" text-anchor="${f === 0 ? "start" : f === 1 ? "end" : "middle"}">${tlabel(t0 + (t1 - t0) * f, t1 - t0)}</text>`).join("");
    const paths = lines.map((l, i) => `<path data-i="${i}" stroke="${PAL[i % PAL.length]}" d="${l.points.map(([t, v], j) => (j ? "L" : "M") + x(t).toFixed(1) + "," + y(v).toFixed(1)).join(" ")}"/>`).join("");
    return `<svg class="chart" data-cid="${id}" viewBox="0 0 ${W} ${H}">${ticks}${xt}<g class="lines">${paths}</g><g class="hov"></g><rect class="hit" x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/></svg>
      <div class="ckeys" data-for="${id}">${lines.map((l, i) => `<span data-i="${i}"><i style="background:${PAL[i % PAL.length]}"></i>${esc(l.label)}</span>`).join("")}${unit ? `<span class="muted">${esc(unit)}</span>` : ""}</div>`;
  }

  function spark(points, { unit = "", w = 300, h = 34, cls = "", note = null, label = "" } = {}) {
    if (!points || points.length < 2) return `<div class="spark empty">collecting…</div>`;
    const t0 = points[0][0], t1 = points[points.length - 1][0] || t0 + 1;
    const vs = points.map((p) => p[1]), lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1;
    const x = (t) => w * (t - t0) / Math.max(1, t1 - t0), y = (v) => h - 3 - (h - 6) * (v - lo) / span;
    const id = register({ lines: [{ label: label || "value", points }], x, y, t0, t1, L: 0, R: 0, W: w, H: h, T: 0, B: 0, unit, dots: false });
    const d = points.map(([t, v], i) => (i ? "L" : "M") + x(t).toFixed(1) + "," + y(v).toFixed(1)).join(" ");
    return `<svg class="spark ${cls}" data-cid="${id}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="a" d="${d} L${w},${h} L0,${h} Z"/><path class="l" d="${d}"/><g class="hov"></g></svg>
      <div class="lbl-row"><span>${num(lo)}–${num(hi)}${unit}</span><span>${note ?? `last 15m · ${points.length} points from the store`}</span></div>`;
  }

  // nearest point at or around t, by binary search
  function nearest(points, t) {
    let a = 0, b = points.length - 1;
    while (b - a > 1) { const m = (a + b) >> 1; if (points[m][0] < t) a = m; else b = m; }
    return Math.abs(points[a][0] - t) <= Math.abs(points[b][0] - t) ? points[a] : points[b];
  }
  let tip = null;
  function tipEl() {
    if (!tip) { tip = document.createElement("div"); tip.className = "charttip"; document.body.appendChild(tip); }
    return tip;
  }
  function clear(svg) { const g = svg.querySelector("g.hov"); if (g) g.innerHTML = ""; if (tip) tip.style.display = "none"; }
  function move(svg, ev) {
    const c = REG.get(svg.dataset.cid);
    if (!c) return;
    const p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY;
    const v = p.matrixTransform(svg.getScreenCTM().inverse());
    const t = c.t0 + (v.x - c.L) / Math.max(1, c.W - c.L - c.R) * (c.t1 - c.t0);
    const hits = c.lines.map((l, i) => ({ l, i, p: l.points.length ? nearest(l.points, t) : null })).filter((h) => h.p);
    if (!hits.length) return clear(svg);
    const tt = hits.reduce((best, h) => (Math.abs(h.p[0] - t) < Math.abs(best - t) ? h.p[0] : best), hits[0].p[0]);
    const at = hits.filter((h) => h.p[0] === tt || c.lines.length > 1);
    const X = c.x(tt);
    svg.querySelector("g.hov").innerHTML = `<line x1="${X}" x2="${X}" y1="${c.T}" y2="${c.H - c.B}" class="xh"/>`
      + (c.dots ? at.map((h) => `<circle cx="${c.x(h.p[0])}" cy="${c.y(h.p[1])}" r="3.2" fill="${PAL[h.i % PAL.length]}"/>`).join("") : "");
    const rows = at.slice().sort((a, b) => b.p[1] - a.p[1]).slice(0, 14);
    const el = tipEl();
    el.innerHTML = `<div class="tt">${new Date(tt * 1000).toLocaleString()}</div>` + rows.map((h) =>
      `<div class="tr">${c.lines.length > 1 ? `<i style="background:${PAL[h.i % PAL.length]}"></i>` : ""}<span class="tl">${esc(h.l.label)}</span><b>${num(h.p[1])}${esc(c.unit && c.lines.length === 1 ? c.unit : "")}</b></div>`).join("")
      + (at.length > rows.length ? `<div class="muted">+${at.length - rows.length} more</div>` : "");
    el.style.display = "block";
    const r = el.getBoundingClientRect();
    el.style.left = Math.min(window.innerWidth - r.width - 8, ev.clientX + 14) + "px";
    el.style.top = Math.max(8, ev.clientY - r.height - 10) + "px";
  }
  document.addEventListener("mousemove", (ev) => {
    const svg = ev.target.closest && ev.target.closest("svg[data-cid]");
    document.querySelectorAll("svg[data-cid] g.hov:not(:empty)").forEach((g) => { if (g.ownerSVGElement !== svg) clear(g.ownerSVGElement); });
    if (svg) move(svg, ev);
  });
  // hovering a legend key brings its line forward and fades the rest
  document.addEventListener("mouseover", (ev) => {
    const k = ev.target.closest && ev.target.closest(".ckeys span[data-i]");
    document.querySelectorAll("svg.chart.focus").forEach((s) => s.classList.remove("focus"));
    document.querySelectorAll("svg.chart path.on").forEach((p) => p.classList.remove("on"));
    if (!k) return;
    const svg = document.querySelector(`svg[data-cid="${k.parentElement.dataset.for}"]`);
    if (!svg) return;
    svg.classList.add("focus");
    svg.querySelector(`path[data-i="${k.dataset.i}"]`)?.classList.add("on");
  });
  return { line, spark, PAL, num };
})();
