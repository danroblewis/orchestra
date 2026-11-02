// Line charts and sparklines with hover: a crosshair, the nearest point of each line, and a
// tooltip with every line's value at that time. Charts are HTML strings; hover is one delegated
// listener, so charts can be re-rendered freely.
const Charts = (() => {
  const PAL = ["#60a5fa", "#f59e0b", "#22c55e", "#e879f9", "#f87171", "#38bdf8", "#facc15", "#a78bfa", "#fb923c", "#94a3b8"];
  const REG = new Map();
  let seq = 0;
  const num = (v) => (v == null ? "—" : Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : Math.abs(v) >= 10 ? (+v).toFixed(1) : (+v).toPrecision(3).replace(/\.?0+$/, ""));
  // both ends of a range in one format, the larger end's (998–1,002, never 998.0–1,002)
  const range = (lo, hi) => {
    const m = Math.max(Math.abs(lo), Math.abs(hi));
    const f = m >= 1000 ? (v) => Math.round(v).toLocaleString() : m >= 10 ? (v) => (+v).toFixed(1) : num;
    return `${f(lo)}–${f(hi)}`;
  };
  // an axis label short enough for the gutter: 193G, 4.5M, 12k, 0.25
  const compact = (v) => {
    const a = Math.abs(v);
    if (a < 10000) return String(+v.toPrecision(6));
    const [d, u] = [[1e15, "P"], [1e12, "T"], [1e9, "G"], [1e6, "M"], [1e3, "k"]].find(([d]) => a >= d);
    return `${+(v / d).toPrecision(3)}${u}`;
  };
  const tlabel = (t, span) => { const d = new Date(t * 1000); return span > 2 * 86400 ? `${d.getMonth() + 1}/${d.getDate()}` : d.toTimeString().slice(0, 5); };
  // a time after ``now`` (a projection) is said from now, "+30 min": never a clock time a DST change can run backwards
  const rel = (t, now) => { const m = Math.round((t - now) / 60); return m < 90 ? `+${m} min` : `+${(m / 60).toFixed(1)} h`; };
  // a round step for about ``n`` gaps over ``span``: 1, 2, 2.5 or 5 × a power of ten
  const niceStep = (span, n = 2) => { const x = span / n || 1, e = 10 ** Math.floor(Math.log10(x)), f = x / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e; };
  const colorOf = (l, i) => l.color || PAL[i % PAL.length];     // a line may carry its own colour
  const register = (spec) => { const id = "c" + ++seq; REG.set(id, spec); if (REG.size > 60) REG.delete(REG.keys().next().value); return id; };

  // W is the drawing width in pixels: pass the container's width so text and lines keep their size.
  // A line may be dashed (``dash``: an SVG dash array); ``marks`` are labelled vertical lines
  // ([{t, label}], such as "now"). ``tight`` fits the y axis to the lines' own range instead of
  // always including zero. A line may carry a ``band`` ([[t, lo, hi]]: a forecast's 10–90% range),
  // drawn as a light fill in its colour behind the lines and read out on hover. A colour may be a
  // CSS variable (``var(--x)``): strokes are set as styles, so a page's theme can change them.
  // ``yMax``: the y axis stops there and a line running past it is cut at the plot's edge (a
  // projection far above what was measured); ``notes``: [{t, v, text}] said beside a point (its end
  // value), at the edge when the point is past it. ``range``: [t0, t1], the x axis's span whatever
  // the points cover (the range the viewer picked); ``onePoint``: what is said when every line has
  // one point, placed away from the dot
  function line(lines, { unit = "", H = 200, W = 720, marks = [], tight = false, now = null, yMax = null, notes = [],
    range = null, onePoint: onePointText = "one point so far" } = {}) {
    const pts = lines.flatMap((l) => [...l.points, ...(l.band || []).flatMap(([t, a, b]) => [[t, a], [t, b]])]);
    if (!pts.length) return `<div class="empty">no points in this range</div>`;
    W = Math.max(320, Math.round(W));
    const L = 46, B = 18, T = 6, R = 8;
    let t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(...pts.map((p) => p[0])) || t0 + 1;
    if (range && range[1] > range[0]) { t0 = Math.min(t0, range[0]); t1 = Math.max(t1, range[1]); }
    if (t1 <= t0) { t0 -= 60; t1 += 60; }             // one instant: the point in the middle of two minutes
    let hi = Math.max(...pts.map((p) => p[1])), lo = Math.min(...pts.map((p) => p[1]));
    if (yMax != null && hi > yMax) hi = yMax;
    if (tight) { const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.05 || 1; hi += pad; lo = lo >= 0 ? Math.max(0, lo - pad) : lo - pad; }   // never below zero for what never is
    else { hi = Math.max(0, hi); lo = Math.min(0, lo); }  // not tight: the axis includes zero
    // the y axis ends on round numbers, so its ticks read as numbers a person would choose
    const stepY = niceStep(hi - lo || Math.abs(hi) || 1);
    lo = Math.floor(lo / stepY + 1e-9) * stepY; hi = Math.ceil(hi / stepY - 1e-9) * stepY; if (hi === lo) hi = lo + stepY;
    const span = hi - lo || 1;
    const x = (t) => L + (W - L - R) * (t - t0) / Math.max(1, t1 - t0), y = (v) => T + (H - T - B) * (1 - (v - lo) / span);
    const id = register({ lines, x, y, t0, t1, L, R, W, H, T, B, unit, dots: true });
    const yt = []; for (let v = lo; v <= hi + stepY * 1e-6; v += stepY) yt.push(+v.toPrecision(12));
    const tnum = compact;
    const ticks = yt.map((v) => `<line class="ax" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke-dasharray="2 4"/><text x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${tnum(v)}</text>`).join("");
    const xt = [0, 0.5, 1].map((f) => `<text x="${L + (W - L - R) * f}" y="${H - 4}" text-anchor="${f === 0 ? "start" : f === 1 ? "end" : "middle"}">${now != null && t0 + (t1 - t0) * f > now + 30 ? rel(t0 + (t1 - t0) * f, now) : tlabel(t0 + (t1 - t0) * f, t1 - t0)}</text>`).join("");
    const mk = marks.filter((m) => m.t >= t0 && m.t <= t1).map((m) => `<line class="ax" x1="${x(m.t)}" x2="${x(m.t)}" y1="${T}" y2="${H - B}" stroke-dasharray="3 3"/><text x="${x(m.t) + 3}" y="${T + 10}">${esc(m.label)}</text>`).join("");
    const bands = lines.map((l, i) => (l.band && l.band.length > 1 ? `<path class="band" data-i="${i}" style="fill:${colorOf(l, i)}" d="${l.band.map(([t, , b], j) => (j ? "L" : "M") + x(t).toFixed(1) + "," + y(b).toFixed(1)).join(" ")} ${l.band.slice().reverse().map(([t, a]) => "L" + x(t).toFixed(1) + "," + y(a).toFixed(1)).join(" ")} Z"/>` : "")).join("");
    const clip = `clip-${id}`;
    const said = notes.filter((n) => n.t >= t0 && n.t <= t1).map((n) => `<text class="cnote" x="${Math.min(W - R - 2, x(n.t))}" y="${Math.max(T + 10, y(Math.min(hi, n.v)) - 5)}" text-anchor="end">${esc(n.text)}${n.v > hi ? " ↑" : ""}</text>`).join("");
    // a line of one point is a dot, since a path through one point draws nothing
    const paths = lines.map((l, i) => l.points.length === 1
      ? `<circle data-i="${i}" cx="${x(l.points[0][0]).toFixed(1)}" cy="${y(l.points[0][1]).toFixed(1)}" r="3.5" style="fill:${colorOf(l, i)}"/>`
      : `<path data-i="${i}" style="stroke:${colorOf(l, i)}"${l.dash ? ` stroke-dasharray="${l.dash}"` : ""} d="${l.points.map(([t, v], j) => (j ? "L" : "M") + x(t).toFixed(1) + "," + y(v).toFixed(1)).join(" ")}"/>`).join("");
    const dotX = Math.max(...lines.filter((l) => l.points.length).map((l) => x(l.points[0][0])));
    const left = dotX > (L + W - R) / 2;              // the note on the side away from the dot
    const onePoint = lines.every((l) => l.points.length <= 1)
      ? `<text class="cnote" x="${left ? L + 6 : W - R - 6}" y="${T + 12}" text-anchor="${left ? "start" : "end"}">${esc(onePointText)}</text>` : "";
    return `<svg class="chart" data-cid="${id}" viewBox="0 0 ${W} ${H}">${ticks}${xt}${mk}<clipPath id="${clip}"><rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}"/></clipPath><g class="bands" clip-path="url(#${clip})">${bands}</g><g class="lines" clip-path="url(#${clip})">${paths}</g>${said}${onePoint}<g class="hov"></g><rect class="hit" x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/></svg>
      <div class="ckeys" data-for="${id}">${lines.map((l, i) => `<span data-i="${i}"><i style="${l.dash ? `background:none;border-top:2px dashed ${colorOf(l, i)};height:0` : `background:${colorOf(l, i)}`}${l.band ? `;box-shadow:0 0 0 3px color-mix(in srgb, ${colorOf(l, i)} 25%, transparent)` : ""}"></i>${esc(l.label)}</span>`).join("")}${unit ? `<span class="muted">${esc(unit)}</span>` : ""}</div>`;
  }

  function spark(points, { unit = "", w = 300, h = 34, cls = "", note = null, label = "" } = {}) {
    if (!points || points.length < 2) return `<div class="spark empty">collecting…</div>`;
    const t0 = points[0][0], t1 = points[points.length - 1][0] || t0 + 1;
    const vs = points.map((p) => p[1]), lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1;
    const x = (t) => w * (t - t0) / Math.max(1, t1 - t0), y = (v) => h - 3 - (h - 6) * (v - lo) / span;
    const id = register({ lines: [{ label: label || "value", points }], x, y, t0, t1, L: 0, R: 0, W: w, H: h, T: 0, B: 0, unit, dots: false });
    const d = points.map(([t, v], i) => (i ? "L" : "M") + x(t).toFixed(1) + "," + y(v).toFixed(1)).join(" ");
    return `<svg class="spark ${cls}" data-cid="${id}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path class="a" d="${d} L${w},${h} L0,${h} Z"/><path class="l" d="${d}"/><g class="hov"></g></svg>
      <div class="lbl-row"><span>${range(lo, hi)}${unit}</span><span>${note ?? `last 15m · ${points.length} points from the store`}</span></div>`;
  }

  // nearest point at or around t, by binary search
  function nearest(points, t) {
    let a = 0, b = points.length - 1;
    while (b - a > 1) { const m = (a + b) >> 1; if (points[m][0] < t) a = m; else b = m; }
    return Math.abs(points[a][0] - t) <= Math.abs(points[b][0] - t) ? points[a] : points[b];
  }
  const bandAt = (l, t) => { const b = (l.band || []).find((r) => r[0] === t); return b ? `<span class="muted"> (${num(b[1])}–${num(b[2])})</span>` : ""; };
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
      + (c.dots ? at.map((h) => `<circle cx="${c.x(h.p[0])}" cy="${c.y(h.p[1])}" r="3.2" style="fill:${colorOf(h.l, h.i)}"/>`).join("") : "");
    const rows = at.slice().sort((a, b) => b.p[1] - a.p[1]).slice(0, 14);
    const el = tipEl();
    el.innerHTML = `<div class="tt">${typeof Orchestra !== "undefined" && Orchestra.when ? Orchestra.when(tt, { date: true, seconds: true }) : new Date(tt * 1000).toLocaleString()}</div>` + rows.map((h) =>
      `<div class="tr">${c.lines.length > 1 ? `<i style="background:${colorOf(h.l, h.i)}"></i>` : ""}<span class="tl">${esc(h.l.label)}</span><b>${num(h.p[1])}${esc(c.unit && c.lines.length === 1 ? c.unit : "")}</b>${bandAt(h.l, h.p[0])}</div>`).join("")
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
