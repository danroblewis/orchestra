// The Dynamics page's live layer, on top of the network the shared renderer draws (netgraph.js):
// - each stock box shows its current value, a tank fill (now ÷ the highest seen in the window)
//   and a sparkline of the window;
// - each flow carries moving dashes whose speed follows its recent rate;
// - hovering a stock or a flow shows a summary; clicking opens a drawer with its history, and
//   for a flow, its observed rate against what its fitted equation predicts;
// - a chart under the diagram plots every stock, each line toggled from its legend.
// Data: MODEL (/api/dynamics/model) and HISTORY (/api/dynamics/history), both read from the web
// server's caches; nothing here queries the metrics store directly.
const Live = (() => {
  let HISTORY = null;
  const stored = (() => { try { return JSON.parse(localStorage.getItem("orchestra.dyn.hidden")); } catch (e) { return null; } })();
  // until the viewer chooses, stocks that only fill start hidden: their scale flattens the rest
  let HIDDEN = stored ? new Set(stored) : null;
  const per = () => { const u = (MODEL && MODEL.time_unit) || "minute"; return u === "minute" ? "/min" : u === "hour" ? "/h" : "/s"; };
  // a whole number of items is said whole ("3", not "3.00"); a rate or a fraction keeps its decimals
  const fmt = (v) => (v == null ? "—" : Number.isInteger(v) ? v.toLocaleString() : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
  const rateFmt = (v) => (v == null ? "—" : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
  // counted traffic (orchestra.sources.traffic): what a series counts on another system's bus
  const trafficText = (t) => (t.direction === "backlog" ? `what waits in ${t.channel}` : `${t.direction === "out" ? "produced into" : "consumed from"} ${t.channel}`)
    + (t.machine ? ` by ${t.machine}` : t.direction === "backlog" ? "" : ", by no machine a source names (unattributed)") + "; a count, not events";
  const stockHist = (id) => (HISTORY && HISTORY.stocks && HISTORY.stocks[id]) || [];
  const flowHist = (id) => (HISTORY && HISTORY.flows && HISTORY.flows[id]) || [];
  const now = (id) => { const h = stockHist(id); return h.length ? h[h.length - 1][1] : (MODEL.levels[id] || {}).v; };
  const recentRate = (fid) => { const h = flowHist(fid).slice(-4); return h.length ? h.reduce((a, p) => a + p[1], 0) / h.length : null; };
  // the minutes the recent rate is over (its last four points)
  const recentMinutes = (fid) => { const h = flowHist(fid).slice(-4); return h.length > 1 ? Math.max(0.5, (h[h.length - 1][0] - h[0][0]) / 60 * h.length / (h.length - 1)) : 2; };
  // the observed rate against what the equation says now: {obs, eq, differs, quiet}. They differ when
  // nothing moved and the equation says something should, or by more than chance would explain
  // (the equation's count over the window, spread by its fitted dispersion, at two standard deviations)
  function against(f) {
    const obs = recentRate(f.id), eq = predicted(f, Date.now() / 1000);
    if (obs == null || eq == null) return { obs, eq, differs: false, quiet: obs === 0 };
    const q = (f.current && f.current.quality) || {}, w = recentMinutes(f.id), disp = Math.max(1, q.dispersion || 1);
    const tol = Math.max(0.25 * eq, 2 * Math.sqrt(Math.max(eq, 0.05) * disp / w));
    return { obs, eq, differs: (obs === 0 && eq > 0.01) || Math.abs(obs - eq) > tol, quiet: obs === 0, window: w };
  }
  const inputHist = (name) => (HISTORY && HISTORY.inputs && HISTORY.inputs[name]) || [];
  // what a chart's points span, said plainly: "since 01:37 · 6 min of data" (never "last hour" over minutes)
  const hm = (t) => new Date(t * 1000).toTimeString().slice(0, 5);
  const spanText = (pts) => { if (!pts || !pts.length) return "no data yet"; const a = pts[0][0], b = pts[pts.length - 1][0], m = (b - a) / 60;
    return `since ${hm(a)} · ${m < 1 ? `${Math.round(b - a)} s` : m < 90 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} h`} of data`; };
  // a flow's machines, as hypotheses with their confidence: never one name as if it were a fact
  const machinesText = (f) => (f.machines || []).length ? f.machines.map((h) => `${h.machine}${h.confidence != null ? ` ${Math.round(100 * h.confidence)}%` : ""}`).join(", ") : "none associated yet";
  // a stock's (or, by its SD Lab name, a measured input's) level at time t
  const levelAt = (sid, t) => { const h = stockHist(sid).length ? stockHist(sid) : inputHist(sid); let v = null; for (const [tt, x] of h) { if (tt > t) break; v = x; } return v; };
  // what the flow's fitted equation says its rate is, given the levels at time t
  function predicted(f, t) {
    const e = f.current; if (!e) return null;
    const sp = e.spec && e.spec.form ? e.spec : null;
    if (sp) {                                  // SD Lab's rate (effects left out: their curves are not shown here)
      const L = (x) => levelAt(x, t);
      if (sp.form === "constant") return sp.value;
      if (sp.form === "proportional") { const x = L(sp.stock); return x == null ? null : sp.k * x; }
      if (sp.form === "linear") { let r = sp.c || 0; for (const tm of sp.terms || []) { const x = L(tm.stock); if (x == null) return null; r += tm.k * x; } return Math.max(0, r); }
      if (sp.form === "gap") { const x = L(sp.stock); return x == null ? null : Math.max(0, (sp.goal - x) / sp.time); }
      return null;
    }
    const p = e.params, x = e.inputs && e.inputs[0] ? levelAt(e.inputs[0], t) : null;
    if (e.form === "constant") return p.c;
    if (x == null) return null;
    return e.form === "proportional" ? p.k * x : Math.max(0, p.c + p.k * x);
  }
  const flowsOf = (sid) => ({ in: MODEL.flows.filter((f) => f.to === sid), out: MODEL.flows.filter((f) => f.from === sid) });

  // ---- the diagram: what the network renderer draws inside each stock's box ----
  // the tank (now against the highest level in the hour), the value, and the hour's sparkline
  function decorateStock(g, n, sz) {
    const id = n.sid, h = stockHist(id), vals = h.map((p) => p[1]), v = now(id);
    const max = Math.max(1e-9, ...vals, v || 0), min = Math.min(0, ...vals), col = n.color;
    const frac = v == null ? 0 : Math.max(0, Math.min(1, (v - min) / (max - min || 1)));
    const x0 = -sz.w / 2, y0 = -sz.h / 2;
    g.append("rect").attr("x", x0 + 1.5).attr("y", y0 + 1.5 + (sz.h - 3) * (1 - frac)).attr("width", sz.w - 3).attr("height", (sz.h - 3) * frac).attr("rx", 3).attr("fill", col).attr("opacity", 0.16);
    const hidden = ((MODEL.stocks.find((s) => s.id === id) || {}).evidence || {}).hidden;
    g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", y0 + (n.caption ? 44 : 32)).attr("fill", col)
      .text(hidden ? (v == null ? "hidden · what its counters imply" : `${fmt(v)} implied · hidden`) : v == null ? "no data" : `${fmt(v)} now · max ${fmt(max)}`);
    // the machines that change this stock: one dot per machine whose flows fill or drain it
    const io = flowsOf(id), ms = [...new Set([...io.in, ...io.out].map((f) => f.machine).filter(Boolean))];
    ms.forEach((m, k) => g.append("circle").attr("cx", -x0 - 9 - k * 11).attr("cy", y0 + 10).attr("r", 4).attr("fill", mcolor(m)).append("title").text(m));
    if (h.length > 1) {
      const a = x0 + 10, b = -x0 - 10, top = -y0 - 34, bot = -y0 - 8, t0 = h[0][0], t1 = h[h.length - 1][0] || t0 + 1;
      g.append("path").attr("fill", "none").attr("stroke", col).attr("stroke-width", 1.4)
        .attr("d", h.map(([t, y], i) => `${i ? "L" : "M"}${(a + (b - a) * (t - t0) / (t1 - t0)).toFixed(1)},${(bot + (top - bot) * (y - min) / (max - min || 1)).toFixed(1)}`).join(" "));
    }
  }

  // an auxiliary (a measured level a rate reads, which no counters balance): its value now and its hour
  function decorateInput(g, n, sz) {
    const h = inputHist(n.input), vals = h.map((p) => p[1]), v = vals.length ? vals[vals.length - 1] : null;
    const max = Math.max(...vals, 1e-9), min = Math.min(...vals, 0), x0 = -sz.w / 2, y0 = -sz.h / 2;
    g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", y0 + 30).text(v == null ? "auxiliary · measured" : `${fmt(v)} now · auxiliary`);
    if (h.length > 1) {
      const a = x0 + 22, b = -x0 - 22, top = -y0 - 20, bot = -y0 - 6, t0 = h[0][0], t1 = h[h.length - 1][0] || t0 + 1;
      g.append("path").attr("fill", "none").attr("stroke", "#94a3b8").attr("stroke-width", 1.2)
        .attr("d", h.map(([t, y], i) => `${i ? "L" : "M"}${(a + (b - a) * (t - t0) / (t1 - t0)).toFixed(1)},${(bot + (top - bot) * (y - min) / (max - min || 1)).toFixed(1)}`).join(" "));
    }
  }

  // ---- hover and click ----
  function stockSummary(id) {
    const s = MODEL.stocks.find((x) => x.id === id), h = stockHist(id).map((p) => p[1]), v = now(id), io = flowsOf(id);
    const rows = [...io.in.map((f) => ["+", f]), ...io.out.map((f) => ["−", f])].map(([sg, f]) => `<div class="tr"><span>${sg} ${esc(flowName(f))}</span><b>${rateFmt(recentRate(f.id))}${per()}</b></div>`).join("");
    const changers = [...new Set([...io.in, ...io.out].flatMap((f) => (f.machines || []).map((x) => x.machine)))];
    const ev = s.evidence || {};
    return `<div class="tt">${stockHead(s.id)}</div><div class="tr"><span>now</span><b>${fmt(v)}</b></div>
      <div class="tr"><span>machines (hypotheses)</span><b>${changers.map((m) => `<span style="color:${mcolor(m)}">${esc(m)}</span>`).join(", ") || "—"}</b></div>
      <div class="tr"><span>${ev.hidden ? "its counters from" : "measured by"}</span><b>${esc(ev.hidden ? counterInstruments(ev) : ev.written_by || ev.machine || "—")}</b></div><div class="tr"><span>range, ${esc(spanText(stockHist(id)))}</span><b>${fmt(h.length ? Math.min(...h) : null)} – ${fmt(h.length ? Math.max(...h) : null)}</b></div>${rows}<div class="hint">click for history and details</div>`;
  }
  // the instruments that wrote a hidden stock's balance counters: what its level is implied from
  function counterInstruments(ev) {
    const ins = [...new Set((ev.balance || []).map((b) => (/instrument="([^"]+)"/.exec(b.series) || [])[1]).filter(Boolean))];
    return ins.join(", ") || "—";
  }
  function flowSummary(fid) {
    const f = MODEL.flows.find((x) => x.id === fid); if (!f) return "";
    const r = recentRate(f.id), pr = predicted(f, Date.now() / 1000);
    return `<div class="tt">${esc(flowName(f))}</div><div class="muted">${esc(f.from ? stockName(f.from) : "outside")} → ${esc(f.to ? stockName(f.to) : "outside")}</div>
      <div class="tr"><span>observed, last ${Math.round(recentMinutes(f.id))} min</span><b>${rateFmt(r)}${per()}</b></div><div class="tr"><span>equation says now</span><b>${rateFmt(pr)}${per()}</b></div>
      <div class="tr"><span>equation</span><b>${esc(eqText(f))}</b></div><div class="tr"><span>machines (hypotheses)</span><b>${esc(machinesText(f))}</b></div><div class="hint">click for history and fit</div>`;
  }
  // the stock's drawer: what it is, its level measured and as the equations run it (since the era
  // began, and projected ahead), and the flows that fill and drain it
  const horizon = () => { try { return +localStorage.getItem("orchestra.dyn.horizon") || 30; } catch (e) { return 30; } };
  // a stock no counters balance: the equation the model runs (SD Lab's flows when they predicted
  // the level better on held-out data, else the fitted net flow), the other as the alternative,
  // and every driver said to be a correlation no experiment has tested
  function netFlowRows(s, ev, io) {
    const nf = ev.net_flow, fit = `R² ${nf.r2} over ${nf.stretches} stretches of ${ago(nf.stretch_s)} · AIC ${nf.aic} against ${nf.aic_constant} for a steady drift · ${nf.forms_tried} forms tried`;
    const untested = [...io.in, ...io.out].some((f) => SDGraph.correlational(MODEL, f)) ? `<br><span class="muted">${esc(SDGraph.UNTESTED)}</span>` : "";
    if (ev.conservation_fit) {
      const eqs = [...io.in.map((f) => "+ " + eqText(f)), ...io.out.map((f) => "− " + eqText(f))].map((x) => `<span class="num">${esc(x)}</span>`).join("<br>");
      return `<div>equation</div><div>SD Lab's flows, which predicted it better on held-out data:<br>${eqs}${untested}</div>
        <div>alternative</div><div class="muted">least squares alone fitted <span class="num">${esc(nf.form)}</span> (${fit}), not used</div>`;
    }
    return `<div>net flow</div><div>no counters measure it: fitted as <span class="num">${esc(nf.form)}</span><br><span class="muted">${fit}</span>${untested}
      ${ev.sdlab_rejected ? `<br><span class="muted">SD Lab's flows not used: ${esc(ev.sdlab_rejected)}</span>` : ""}</div>`;
  }
  // how far to trust the stock (sd/stocktrust.py): each measurement of its evidence, the weakest as its score
  function trustRows(t) {
    if (Evidence.byConstruction(t)) return `<div>trust</div><div><b>by construction: no evidence (D33)</b>${(t.why || []).map((w) => `<br><span class="muted">${esc(w)}</span>`).join("")}</div>
      ${t.behaviour ? behaviourRows(t.behaviour) : ""}`;
    const pct = (x) => (x == null ? "—" : (+x).toFixed(2));
    const parts = Object.entries(t.components || {}).map(([k, v]) => `${esc(k.replace("_", " "))} ${pct(v)}`).join(" · ");
    const facts = [t.p_null != null ? `shift null p ${pct(t.p_null)}` : "", t.held_out_r2 != null ? `held-out R² ${pct(t.held_out_r2)}` : "",
      t.cum_residual_ratio != null ? `running residual ${pct(t.cum_residual_ratio)} × the level's spread` : "", t.units != null ? `judged on ${t.units} unit${t.units === 1 ? "" : "s"} (steps, or stretches between a slow level's writes)` : "",
      t.persistence != null ? (t.persistence_of > 1 ? `found the same way in ${Math.round(100 * t.persistence)}% of the last ${t.persistence_of} discoveries` : "first discovery: nothing to compare with yet") : ""].filter(Boolean).join(" · ");
    return `<div>trust</div><div><b>${pct(t.score)}</b> ${esc(t.level)} <span class="muted">(${esc(t.kind.replace("_", " "))}; the weakest of: ${parts})</span>
      ${facts ? `<br><span class="muted">${facts}</span>` : ""}${(t.why || []).map((w) => `<br><span class="muted">${esc(w)}</span>`).join("")}</div>
      ${t.behaviour ? behaviourRows(t.behaviour) : ""}`;
  }
  // how far to trust the stock's projection (sd/equations/heldout.py): the model run forward from part-way through its window
  function behaviourRows(b) {
    const pct = (x) => (x == null ? "—" : (+x).toFixed(2));
    return `<div>behaviour</div><div><b>${pct(b.score)}</b> ${esc(b.level)} <span class="muted">(its own runs from part-way through the window miss the level by ${pct(b.error)} × its spread; holding the level, ${pct(b.hold_error)})</span>
      ${(b.why || []).map((w) => `<br><span class="muted">${esc(w)}</span>`).join("")}</div>`;
  }
  // who wrote a series, as a link to the instrument when an instrument did
  const writerLink = (s, ev) => { const w = ev.written_by || ev.machine; if (!w) return "—";
    const inst = s.series && s.series.labels && s.series.labels.instrument;
    return inst && inst === w ? `<a href="/instruments#${encodeURIComponent(w)}" title="open it on the Instruments page">${esc(w)}</a>` : esc(w); };
  function openStock(id) {
    const s = MODEL.stocks.find((x) => x.id === id), io = flowsOf(id), ev = s.evidence || {};
    const rate = (f) => `${rateFmt(recentRate(f.id))}${per()}`;
    // each flow that fills or drains it opens its own drawer
    const flowRow = (f, sg) => `<div class="tr flowlink" tabindex="0" role="button" title="open this flow" onclick="Live.openFlow('${esc(f.id)}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();Live.openFlow('${esc(f.id)}')}"><span>${sg} <span class="mdot" style="--c:${mcolor(f.machine)}"></span>${esc(flowName(f))} <span class="muted">${esc(sg === "+" ? "from " + (f.from ? stockName(f.from) : "outside") : "to " + (f.to ? stockName(f.to) : "outside"))}</span></span> <b style="margin-left:10px">${rate(f)}</b></div>`;
    // outflows are drawn below zero, so what fills and what drains it read apart at a glance
    const lines = [...io.in.map((f) => ({ label: "in: " + flowName(f), points: flowHist(f.id), color: mcolor(f.machine) })),
      ...io.out.map((f) => ({ label: "out: " + flowName(f), points: flowHist(f.id).map(([t, v]) => [t, -v]), color: mcolor(f.machine), dash: "5 3" }))].filter((l) => l.points.length);
    const net = new Map();
    for (const l of lines) for (const [t, v] of l.points) net.set(t, (net.get(t) || 0) + v);
    if (lines.length > 1) lines.push({ label: "net (in − out)", points: [...net.entries()].sort((a, b) => a[0] - b[0]), color: "#e5e7eb" });
    openDrawer(`<h3 data-drawer-key="s:${esc(id)}">${stockHead(s.id)} <span class="tag">stock</span>${ev.hidden ? ' <span class="tag">hidden: found from the levels, not measured</span>' : ""}</h3>
      ${ev.hidden ? `<div class="muted" style="font-size:12px;margin-bottom:8px">A question about the system: ${esc(ev.note || "something in it is not measured or not understood yet")}.</div>` : ""}
      <div class="def"><div>now</div><div class="num">${fmt(now(id))}</div>
      <div>machines</div><div>${[...new Set([...io.in, ...io.out].flatMap((f) => (f.machines || []).map((h) => h.machine)))].map((m) => `<span class="mdot" style="--c:${mcolor(m)}"></span>${esc(m)}`).join(" ") || '<span class="muted">none associated yet</span>'} <span class="muted">(hypotheses, from its flows)</span></div>
      ${ev.hidden ? `<div>its counters from</div><div>${esc(counterInstruments(ev))} <span class="muted">(no series measures it: its level is what these counters imply)</span></div>` : `<div>measured by</div><div>${writerLink(s, ev)} <span class="muted">(wrote the series: an instrument, or the series' own label)</span></div>`}<div>bound to</div><div class="num">${esc(s.series ? keyOf(s.series) : "—")}</div>
      ${s.series && s.series.source && s.series.source !== "own" ? `<div>read from</div><div>source <b>${esc(s.series.source)}</b><div class="num" style="font-size:11.5px">${esc(s.series.query || "")}</div><div class="muted" style="font-size:11.5px">${esc((s.series.origin || []).join(" → "))}</div></div>` : ""}
      ${s.series && s.series.traffic ? `<div>counted</div><div>${esc(trafficText(s.series.traffic))}</div>` : ""}
      ${s.series && resOf(MODEL.discovery, keyOf(s.series)) ? `<div>resolution</div><div>${esc(resOf(MODEL.discovery, keyOf(s.series)))}</div>` : ""}
      ${ev.balance ? `<div>balance</div><div class="num">Δ =${ev.balance.map((b) => `<span class="bal-term">${b.sign > 0 ? "+" : "−"} ${esc(b.series)}</span>`).join("")}<span class="muted">${ev.trust && ev.trust.kind === "passage" ? "a passage: judged on its raw points; R² not used" : ev.balance_r2 == null ? (ev.by_construction ? "by construction: a count of reporters and its own turnover, so no evidence" : "measured by no series: no fit to report") : `R² ${ev.balance_r2} · exact in ${Math.round(100 * ev.exact_steps)}% of steps`}${ev.balance_r2_level != null ? ` · judged on the traffic through it (R² on the level itself ${ev.balance_r2_level})` : ""}</span></div>` : ""}
      ${ev.net_flow ? netFlowRows(s, ev, io) : ""}
      ${ev.trust ? trustRows(ev.trust) : ""}</div>
      <h4 style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">Level: measured, as the equations run it, and projected
        <label class="muted" style="font-weight:400;font-size:11.5px">project <input id="sim-h" type="number" min="1" max="1440" value="${horizon()}" style="width:58px"> min ahead</label></h4>
      <div id="sim-chart"><div class="muted">running the equations…</div></div><div id="sim-note" class="muted" style="font-size:11.5px"></div>
      <h4>Fills it <span class="muted">(inflows)</span></h4>${io.in.map((f) => flowRow(f, "+")).join("") || '<div class="muted">nothing flows in</div>'}
      <h4>Drains it <span class="muted">(outflows)</span></h4>${io.out.map((f) => flowRow(f, "−")).join("") || '<div class="muted">nothing flows out</div>'}
      <h4>Its flows' rates (${per()}), ${esc(spanText(lines.length ? lines[0].points : []))}: inflows above zero, outflows below</h4>${lines.length ? Charts.line(lines, { W: 700, H: 220, unit: per() }) : '<div class="muted">no flows measured</div>'}`, { key: "s:" + id });
    const inp = document.getElementById("sim-h");
    inp.addEventListener("change", () => { try { localStorage.setItem("orchestra.dyn.horizon", String(Math.max(1, +inp.value || 30))); } catch (e) {} simChart(id); });
    simChart(id);
    if (typeof IntendedDrawers !== "undefined") IntendedDrawers.expectSwitch("stock", id);     // "Expected: always show this stock" (intended-drawers.js)
  }
  async function simChart(id) {
    const el = document.getElementById("sim-chart"), note = document.getElementById("sim-note"); if (!el) return;
    let d;
    try { d = await (await fetch(`/api/dynamics/simulate?horizon_min=${horizon()}`)).json(); } catch (e) { d = { ok: false, error: String(e) }; }
    if (!document.getElementById("sim-chart")) return;
    // a hidden stock has no series: nothing measured to draw
    const hidden = ((MODEL.stocks.find((s) => s.id === id) || {}).evidence || {}).hidden;
    const measured = hidden ? null : { label: "measured", points: stockHist(id), color: stockColor(id) };
    if (!d.ok) { el.innerHTML = measured ? Charts.line([measured], { W: 700, H: 240 }) : '<div class="muted">nothing measured: a hidden stock</div>'; note.textContent = "Not simulated: " + d.error; return; }
    const era = (d.era || {})[id] || [], proj = (d.projection || {})[id] || [];
    // the y axis spans what was measured and replayed; a projection running past it is cut, its end said
    const seen = [...(measured ? measured.points : []), ...era].map((p) => p[1]), end = proj.length ? proj[proj.length - 1] : null;
    const yMax = seen.length ? Math.max(...seen) * 1.5 + 1 : null;
    const endText = end ? `+${horizon()} min: ${fmt(Math.round(end[1] * 100) / 100)}` : "";
    el.innerHTML = Charts.line([...(measured ? [measured] : []),
      { label: `the equations, from ${new Date(d.start * 1000).toTimeString().slice(0, 5)}`, points: era, color: "#e5e7eb", dash: "6 4" },
      { label: `projected, next ${horizon()} min${endText ? ` (${endText})` : ""}`, points: proj, color: stockColor(id), dash: "2 3" }],
      { W: 700, H: 240, now: d.now, yMax: yMax != null && end && end[1] > yMax ? yMax : null, notes: end ? [{ t: end[0], v: end[1], text: endText }] : [],
        marks: [{ t: d.now, label: "now" }, ...(era.length ? [{ t: d.start, label: "era began" }] : [])] });
    const rep = (d.replayed || []).map((fid) => flowName(MODEL.flows.find((f) => f.id === fid)) || fid);
    // where a flow of this stock is not moving as its equation says, the projection still assumes the equation
    const io = flowsOf(id), warn = [...io.in, ...io.out].map((f) => ({ f, a: against(f) })).filter((x) => x.a.differs)
      .map(({ f, a }) => `<div class="stale">${esc(flowName(f))}: the equation says ${rateFmt(a.eq)}${per()}; observed ${rateFmt(a.obs)}${per()} over the last ${Math.round(a.window)} min — the projection assumes the fitted rate</div>`).join("");
    note.innerHTML = warn + `The equations start from the measured levels when the era began (the start of the window the model was fitted on, when every series was being written), and run with nothing else but the measured inputs. The projection starts from the levels now and runs the fitted equations: constant flows continue at their fitted rate; measured inputs are held at their last value. Nothing leaves a stock that is not there.`
      + (rep.length ? ` <b>Replayed, not simulated</b> (no equation the simulator steps): ${rep.map(esc).join(", ")}: their observed rate, then their mean over the last 10 minutes.` : " Every flow was simulated from its equation.")
      + (yMax != null && end && end[1] > yMax ? ` The projection runs above the measured range: the chart is cut at ${fmt(Math.round(yMax))}, its end value is ${esc(endText)}.` : "")
      + (VERSION !== null ? " These are the latest discovery's equations, not this past version's." : "");
  }
  function openFlow(fid) {
    const f = MODEL.flows.find((x) => x.id === fid), e = f.current || {}, q = e.quality || {}, ev = f.evidence || {};
    const obs = flowHist(fid), model = obs.map(([t]) => [t, predicted(f, t)]).filter((p) => p[1] != null);
    // lower AIC is better; a form below the chosen one lost only because it did not beat the price of trying it
    const drv = ev.driver || {};
    // each form named as the page names what it reads; a better form was set aside for a reason, said
    const formName = (k) => { const rest = k.slice(4), form = ["proportional", "linear", "constant", "gap"].find((x) => rest === x || rest.startsWith(x + "_"));
      if (!form) return rest.replace(/_/g, " ");
      const what = rest.slice(form.length + 1);
      return what ? `${form} in ${readName(what)}` : form; };
    const refutedOf = (k) => { const rest = k.slice(4), what = rest.replace(/^(proportional|linear|constant|gap)_?/, "");
      return (drv.refuted || []).find((r) => [r.driver, r.stock, r.input, r.name].filter(Boolean).some((x) => x === what || "input:" + x === what || x === what.replace(/^input:/, ""))); };
    const alts = Object.entries(q).filter(([k]) => k.startsWith("aic_")).map(([k, v]) => { const dv = v - q.aic;
      let said = `worse by ${rateFmt(dv)}`;
      if (dv < 0) { const r = refutedOf(k);
        said = drv.price != null && -dv < drv.price ? `better by ${rateFmt(-dv)}, below the price (${rateFmt(drv.price)})`
          : r ? `better by ${rateFmt(-dv)}, but refuted: ${esc(r.why || "no reason given")}` : `better by ${rateFmt(-dv)}, beat the price; rejected: reason not recorded`; }
      return `<tr><td>${esc(formName(k))}</td><td class="num">${rateFmt(v)}</td><td class="num">${said}</td></tr>`; }).join("");
    const price = drv.price != null ? `<div class="muted" style="font-size:11.5px">a driver must beat the constant by ${rateFmt(drv.price)} AIC, the price for trying ${drv.tried ?? "its"} forms</div>` : "";
    // the counter's own ends, when they are not the ends drawn (a co-flow drawn through a stock it passes)
    const cl = (f.counter && f.counter.labels) || {}, endName = (id) => (id ? stockName(id) : "outside");
    const counts = cl.from && cl.to ? `counts ${cl.from} → ${cl.to}` : "";
    const differs = counts && ((f.from && !stockName(f.from).toUpperCase().includes(String(cl.from).replace(/_/g, " ").toUpperCase())) || (f.to && !stockName(f.to).toUpperCase().includes(String(cl.to).replace(/_/g, " ").toUpperCase())) || !f.from || !f.to);
    const through = (ev.through || []).map((id) => stockName(id)).join(", ");
    // a counter labelled with who moved it (by=, machine=) names an instrument's label, not evidence
    const byLabel = cl.by || cl.machine ? `<div class="muted" style="font-size:11.5px">its counter is labelled ${cl.by ? `by=${esc(cl.by)}` : `machine=${esc(cl.machine)}`}: the instrument's label, not evidence of who moved it</div>` : "";
    // a flow linked by name: its ends, and a click opens it
    const flowLink = (id) => { const g = MODEL.flows.find((x) => x.id === id); if (!g) return esc(id);
      return `<a href="#f:${encodeURIComponent(id)}" onclick="Live.openFlow('${esc(id)}');return false">${esc(flowName(g))}</a> <span class="muted">(${esc(endName(g.from))} → ${esc(endName(g.to))})</span>`; };
    const zeroEv = (q.events ?? 0) === 0 && f.current && (Object.values(e.params || {}).some((x) => x) || (e.spec && e.spec.value)) ? " · 0 increments seen in the window; the counter first appeared already above 0" : "";
    openDrawer(`<h3 data-drawer-key="f:${esc(fid)}">${esc(flowName(f))} <span class="tag">flow</span></h3>
      <div class="def"><div>moves</div><div>${esc(f.from ? stockName(f.from) : "outside")} → ${esc(f.to ? stockName(f.to) : "outside")}</div>
      <div>equation</div><div class="num">${esc(eqText(f))}${SDGraph.correlational(MODEL, f) ? `<div class="muted" style="font-family:inherit">${esc(SDGraph.UNTESTED)}</div>` : ""}</div><div>machines</div><div>${(f.machines || []).length ? f.machines.map((h) => `<div><span class="mdot" style="--c:${mcolor(h.machine)}"></span><b><a href="/machines#${encodeURIComponent(h.machine)}" title="open it on the Machines page">${esc(h.machine)}</a></b>${h.confidence != null ? ` <span class="num">${Math.round(100 * h.confidence)}%</span>` : ""} <span class="muted">${esc(h.why || h.origin || "")}</span></div>`).join("") + '<div class="muted" style="font-size:11.5px">hypotheses: a match in time, not a cause; they change no equation, and two similar flows between the same stocks may not be told apart</div>' + byLabel : `<span class="muted">${esc(f.association || "no machine associated yet")}</span>${byLabel}`}</div>
      <div>fit</div><div class="num">${Evidence.tooFew(f) ? `<b>${esc(Evidence.tooFewText(f))}</b>: ` : ""}${esc(e.origin || "")} by ${esc(e.method || "")} · ${esc(e.form || "")} · ${q.events ?? 0} events${q.live_minutes ? ` over ${q.live_minutes} min` : ""}${q.dispersion != null ? ` · dispersion ${rateFmt(q.dispersion)}` : ""}${zeroEv ? `<div class="muted" style="font-family:inherit">${esc(zeroEv.slice(3))}</div>` : ""}</div>
      ${(f.measured_by || []).length > 1 ? `<div>measured by</div><div class="num">${f.measured_by.map((c) => esc(c.name)).join(" + ")}</div>` : ""}
      ${SDGraph.sameAs(MODEL, f).length ? `<div>same events</div><div>as ${SDGraph.sameAs(MODEL, f).map(esc).join(", ")} <span class="muted">(another counter counts each of its events: one move, two names)</span></div>` : ""}
      <div>counter</div><div class="num">${esc(f.counter ? keyOf(f.counter) : "—")}${differs ? `<div class="muted" style="font-family:inherit">${esc(counts)}; drawn ${esc(endName(f.from))} → ${esc(endName(f.to))}${through ? ` because it passes through ${esc(through)}` : ""}</div>` : ""}</div>
      ${ev.co_flow_of ? `<div>co-flow</div><div>${esc(ev.note || "")} (see ${flowLink(ev.co_flow_of)})</div>` : ""}
      ${ev.copy_of ? `<div>copy</div><div>every event of ${esc(flowName(MODEL.flows.find((x) => x.id === ev.copy_of)) || ev.copy_of)} also fills ${esc(f.to ? stockName(f.to) : "this stock")}: one count filling several stocks, not a split</div>` : ""}
      ${(ev.copies || []).length ? `<div>copies</div><div>every event also fills ${ev.copies.map((id) => { const c = MODEL.flows.find((x) => x.id === id); return esc(c && c.to ? stockName(c.to) : id); }).join(", ")}</div>` : ""}
      ${(f.counter && f.counter.traffic) ? `<div>counted</div><div>${esc(trafficText(f.counter.traffic))}</div>` : ""}
      ${(ev.co_flows || []).length ? `<div>co-flows</div><div>the same events also move ${ev.co_flows.map(flowLink).join(", ")}</div>` : ""}
      ${(ev.conflicts || []).map((c) => `<div>also claimed</div><div>its ${c.end === "src" ? "source" : "destination"} by ${c.others.map((o) => `${esc(stockName(o.stock))} (explains ${Math.round(100 * o.share)}% of its changes)`).join(", ")}; kept ${esc(stockName(c.kept))}</div>`).join("")}</div>
      <h4>Rate (${per()}), ${esc(spanText(obs))}: observed and what the equation predicts from the levels</h4>
      ${Charts.line([{ label: "observed", points: obs, color: mcolor(f.machine) }, { label: "equation", points: model, color: "#e5e7eb", dash: "6 4" }], { W: 700, H: 240, unit: per() })}
      ${alts ? `<h4>Other forms considered (AIC; lower is better)</h4>${price}<table class="dt"><tr><th>form</th><th>AIC</th><th>against the chosen</th></tr><tr><td><b>${esc(e.form)}</b> (chosen)</td><td class="num">${rateFmt(q.aic)}</td><td></td></tr>${alts}</table>` : ""}`, { key: "f:" + fid });
    if (typeof IntendedDrawers !== "undefined") IntendedDrawers.expectSwitch("flow", fid);
  }

  // ---- the history chart ----
  function chart() {
    const el = document.getElementById("hist"); if (!el || !MODEL) return;
    const ids = MODEL.stocks.map((s) => s.id).filter((id) => stockHist(id).length);
    if (!ids.length) { el.innerHTML = '<div class="muted">No history yet.</div>'; return; }
    if (HIDDEN === null) { const near = typeof Intended !== "undefined" ? Intended.nearIds() : new Set();
      HIDDEN = new Set(MODEL.stocks.filter((s) => s.evidence && s.evidence.accumulator && !near.has(s.id)).map((s) => s.id)); }
    const tt = document.getElementById("hist-title"), all = ids.flatMap((id) => stockHist(id)).sort((a, b) => a[0] - b[0]);
    if (tt) tt.textContent = `Stocks, ${spanText(all)}`;
    const lines = ids.map((id, i) => ({ id, i, label: stockName(id), points: stockHist(id), color: stockColor(id) }));
    const shown = lines.filter((l) => !HIDDEN.has(l.id));
    document.getElementById("hist-keys").innerHTML = lines.map((l) => `<span class="hk ${HIDDEN.has(l.id) ? "off" : ""}" onclick="Live.toggle('${esc(l.id)}')"><i style="background:${stockColor(l.id)}"></i>${esc(l.label)} <b>${fmt(now(l.id))}</b></span>`).join("");
    // keep each stock's colour when others are hidden: pad hidden lines as empty
    el.innerHTML = shown.length ? Charts.line(lines.map((l) => (HIDDEN.has(l.id) ? { label: l.label, points: [], color: l.color } : l)), { W: el.clientWidth || 900, H: 220 })
      : '<div class="muted">Every stock is hidden; click one above.</div>';
    el.querySelectorAll(".ckeys").forEach((k) => k.remove());
  }
  function toggle(id) { HIDDEN = HIDDEN || new Set(); HIDDEN.has(id) ? HIDDEN.delete(id) : HIDDEN.add(id); try { localStorage.setItem("orchestra.dyn.hidden", JSON.stringify([...HIDDEN])); } catch (e) {} chart(); }

  // a flow's label on the diagram: the equation, or, where the observed rate parts from it, the
  // observed rate first ("0.00 now · eq 1.50 /min"); quiet when nothing moved over the recent window
  function edgeLabel(e) {
    const f = MODEL && MODEL.flows.find((x) => x.id === e.fid); if (!f || !e.eqLabel) return null;
    const a = against(f), first = a.differs ? `${rateFmt(a.obs)} now · eq ${rateFmt(a.eq)} ${per()}` : e.eqLabel;
    return { label: [first, ...(Array.isArray(e.label) ? e.label.slice(1) : [])], quiet: !!a.quiet && HISTORY != null };
  }
  let GRAPH = null;
  async function refresh() {
    try { const d = await (await fetch("/api/dynamics/history")).json(); if (d.ok) HISTORY = d; if (typeof online === "function") online(); }
    catch (e) { if (typeof offline === "function") offline(); return; }
    if (GRAPH) {
      GRAPH.refreshNodes((n) => (n.sid || n.input ? {} : null));
      GRAPH.setRates((e) => (e.flowPart ? recentRate(e.fid) : 0));
      GRAPH.setLabels((e) => (e.flowPart && e.fid ? edgeLabel(e) : null));
    }
    chart();
  }
  function drawn(graph) { GRAPH = graph; graph.setRates((e) => (e.flowPart ? recentRate(e.fid) : 0)); chart(); }
  return { refresh, drawn, toggle, openStock, openFlow, decorateStock, decorateInput, stockSummary, flowSummary, edgeLabel, against, fmt };
})();
Live.refresh(); setInterval(Live.refresh, 15000);
