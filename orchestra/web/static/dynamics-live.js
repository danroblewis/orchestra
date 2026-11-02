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
  // a rate (or any measured value said in passing) to two significant digits: "0.31", "29", "1,200"
  const sig2 = (v) => (v == null || !isFinite(v) ? "—" : v === 0 ? "0" : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : String(+(+v).toPrecision(2)));
  // counted traffic (orchestra.sources.traffic): what a series counts on another system's bus
  const trafficText = (t) => (t.direction === "backlog" ? `what waits in ${t.channel}` : `${t.direction === "out" ? "produced into" : "consumed from"} ${t.channel}`)
    + (t.machine ? ` by ${t.machine}` : t.direction === "backlog" ? "" : ", by no machine a source names (unattributed)") + "; a count, not events";
  const stockHist = (id) => (HISTORY && HISTORY.stocks && HISTORY.stocks[id]) || [];
  const flowHist = (id) => (HISTORY && HISTORY.flows && HISTORY.flows[id]) || [];
  const now = (id) => { const h = stockHist(id); return h.length ? h[h.length - 1][1] : (MODEL.levels[id] || {}).v; };
  const recentRate = (fid) => { const h = flowHist(fid).slice(-4); return h.length ? h.reduce((a, p) => a + p[1], 0) / h.length : null; };
  // the minutes the recent rate is over (its last four points)
  const recentMinutes = (fid) => { const h = flowHist(fid).slice(-4); return h.length > 1 ? Math.max(0.5, (h[h.length - 1][0] - h[0][0]) / 60 * h.length / (h.length - 1)) : 2; };
  // the observed rate against the equation over the same buckets (flow-check.js): {obs, eq, differs, quiet}
  const flowStep = () => (HISTORY && HISTORY.flow_step) || 30;
  // when the levels an equation reads were sampled inside (a, b]
  const samplesIn = (f) => (a, b) => [...new Set(FlowCheck.reads(f).flatMap((id) => (stockHist(id).length ? stockHist(id) : inputHist(id)).map((p) => p[0]).filter((t) => t > a && t <= b)))].sort((x, y) => x - y);
  const against = (f) => FlowCheck.against(f, flowHist(f.id), { step: flowStep(), levelAt, samplesIn: samplesIn(f), minutes: recentMinutes(f.id) });
  const inputHist = (name) => (HISTORY && HISTORY.inputs && HISTORY.inputs[name]) || [];
  // what a chart's points span, said plainly: "since 01:37 · 6 min of data" (never "last hour" over minutes)
  const hm = (t) => Orchestra.when(t);
  const spanText = (pts) => { if (!pts || !pts.length) return "no data yet"; const a = pts[0][0], b = pts[pts.length - 1][0], m = (b - a) / 60;
    return `since ${hm(a)} · ${m < 1 ? `${Math.round(b - a)} s` : m < 90 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1)} h`} of data`; };
  // a flow's machines, as hypotheses with their confidence (none on a flow with too few events): never one name as if it were a fact
  const machinesText = (f) => (f.machines || []).length ? f.machines.map((h) => `${h.machine}${Evidence.confidence(f, h)}${Evidence.chance(f, h)}`).join(", ") : "none associated yet";
  // a stock's (or, by its SD Lab name, a measured input's) level at time t
  const levelAt = (sid, t) => { const h = stockHist(sid).length ? stockHist(sid) : inputHist(sid); let v = null; for (const [tt, x] of h) { if (tt > t) break; v = x; } return v; };
  // a hidden stock's own level series, written for its place but not read as its level (sd/passing.py
  // ``unread``): {key, title, why} ("reads 0 at every step it was sampled: what enters leaves within a step"), or null
  const unreadLevel = (s) => { const p = ((s || {}).evidence || {}).passing;
    return p && p.level_series ? { key: p.level_series, title: p.level_title || p.level_series, why: String(p.level_why || "").replace(/^written, but /, "") } : null; };
  // a stock with no measurement of its level: hidden, or trusted at 0 for want of one (never projected)
  const unprojected = (s) => { const ev = (s || {}).evidence || {}, t = ev.trust || {}; return !!ev.hidden || (t.score === 0 && t.kind === "unmeasured"); };
  // how long the oldest has waited in a stock's place (its instrument's age view, sd/history.py ``ages``):
  // "6m 45s", or "" when none is written; a measurement shown beside the stock, never part of it
  const oldest = (sid) => { const a = HISTORY && HISTORY.ages && HISTORY.ages[sid]; if (!a || a[1] == null) return "";
    const x = Math.max(0, Math.round(a[1])); return x < 60 ? `${x}s` : x < 3600 ? `${Math.floor(x / 60)}m ${x % 60}s` : `${(x / 3600).toFixed(1)}h`; };
  const flowsOf = (sid) => ({ in: MODEL.flows.filter((f) => f.to === sid), out: MODEL.flows.filter((f) => f.from === sid) });

  // inside each stock's box on the diagram: the tank (now against the highest level in the hour), the value, and the hour's sparkline
  function decorateStock(g, n, sz) {
    const id = n.sid, h = stockHist(id), vals = h.map((p) => p[1]), v = now(id);
    const max = Math.max(1e-9, ...vals, v || 0), min = Math.min(0, ...vals), col = n.color;
    const frac = v == null ? 0 : Math.max(0, Math.min(1, (v - min) / (max - min || 1)));
    const x0 = -sz.w / 2, y0 = -sz.h / 2;
    g.append("rect").attr("x", x0 + 1.5).attr("y", y0 + 1.5 + (sz.h - 3) * (1 - frac)).attr("width", sz.w - 3).attr("height", (sz.h - 3) * frac).attr("rx", 3).attr("fill", col).attr("opacity", 0.16);
    const hidden = ((MODEL.stocks.find((s) => s.id === id) || {}).evidence || {}).hidden;
    const caps = Array.isArray(n.caption) ? n.caption.length : n.caption ? 1 : 0;         // the caption's lines push the value down
    g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", y0 + 32 + 12 * caps).attr("fill", col)
      .text(hidden ? (v == null ? "hidden · what its counters imply" : `${fmt(v)} implied · hidden`) : HISTORY == null ? "loading levels…" : v == null ? "no data" : `${fmt(v)} now · max ${fmt(max)}${oldest(id) ? ` · oldest ${oldest(id)}` : ""}`);
    // the machines that change this stock: one dot per machine whose flows fill or drain it
    const io = flowsOf(id), ms = [...new Set([...io.in, ...io.out].map((f) => f.machine).filter(Boolean))];
    ms.forEach((m, k) => g.append("circle").attr("cx", -x0 - 9 - k * 11).attr("cy", y0 + 10).attr("r", 4).attr("fill", mcolor(m)).append("title").text(m));
    if (h.length > 1) {
      const a = x0 + 10, b = -x0 - 10, top = -y0 - 34, bot = -y0 - 8, t0 = h[0][0], t1 = h[h.length - 1][0] || t0 + 1;
      // a count holds its value until it changes: step-after, never a slope between 0 and 1
      g.append("path").attr("fill", "none").attr("stroke", col).attr("stroke-width", 1.4)
        .attr("d", Charts.pathOf(h, (t) => a + (b - a) * (t - t0) / (t1 - t0), (y) => bot + (top - bot) * (y - min) / (max - min || 1), true));
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

  // the summary shown on hovering a stock
  function stockSummary(id) {
    const s = MODEL.stocks.find((x) => x.id === id), h = stockHist(id).map((p) => p[1]), v = now(id), io = flowsOf(id);
    const rows = [...io.in.map((f) => ["+", f]), ...io.out.map((f) => ["−", f])].map(([sg, f]) => `<div class="tr"><span>${sg} ${esc(flowName(f))}</span><b>${sig2(recentRate(f.id))}${per()}</b></div>`).join("");
    const changers = [...new Set([...io.in, ...io.out].flatMap((f) => (f.machines || []).map((x) => x.machine)))];
    const ev = s.evidence || {};
    return `<div class="tt">${stockHead(s.id)}</div>${stockAbout(s.id)}<div class="tr"><span>now</span><b>${fmt(v)}</b></div>
      <div class="tr"><span>machines (hypotheses)</span><b>${changers.map((m) => `<span style="color:${mcolor(m)}">${esc(m)}</span>`).join(", ") || "—"}</b></div>
      <div class="tr"><span>${ev.hidden ? "its counters from" : "measured by"}</span><b>${esc(ev.hidden ? counterInstruments(ev) : ev.written_by || ev.machine || "—")}</b></div><div class="tr"><span>range, ${esc(spanText(stockHist(id)))}</span><b>${fmt(h.length ? Math.min(...h) : null)} – ${fmt(h.length ? Math.max(...h) : null)}</b></div>${rows}<div class="hint">click for history and details</div>`;
  }
  // why what the page shows as one stock is one: a passage's counters count the same items in and
  // out of a state no series measures; twins are one stock measured by several series (the owner,
  // 2026-11-01, read a passage named by its counter's labels as three things in one stock)
  function whyOne(s, io) {
    const ev = s.evidence || {}, rows = [];
    if (ev.passing) {
      const ends = (fs, end) => [...new Set(fs.map((f) => SDGraph.endName(MODEL, f, end)))].join(" or ");
      rows.push(`<div>why one stock</div><div>items leave ${esc(ends(io.in, "from"))} and reach ${esc(ends(io.out, "to"))} within one step of the grid, and the counters that move them count the same items (${ev.passing.ins.length + ev.passing.outs.length} counters, their totals agree): ${ev.hidden ? "no series measures the state between, so it is one stock whose level is what they imply" : "the level between is measured, and rises and falls with them"}.</div>`);
      // a passage through several places is named by its first and last (sd/titles.py): the places it spans, in order
      if ((ev.spans || []).length > 1) rows.push(`<div>the steps it spans</div><div>${ev.spans.map(esc).join(" → ")}</div>`);
    }
    if ((ev.twins || []).length) {
      rows.push(`<div>why one stock</div><div>one stock, measured ${ev.twins.length + 1} ways: ${esc(s.series ? keyOf(s.series) : s.id)} (kept)${ev.twins.map((t) => `, ${esc(t.series)} <span class="muted">(changes equal in ${Math.round(100 * (t.equal_steps || 0))}% of steps${t.change_correlation != null ? `, correlate by ${(+t.change_correlation).toFixed(2)}` : ""})</span>`).join("")}</div>`);
    }
    // a level that counts this stock's servers busy (sd/capacity.py): its capacity, not a second stock
    for (const v of ev.capacity_of || []) {
      const k = v.capacity, u = v.utilisation != null ? `, busy ${Math.round(100 * v.utilisation)}% of the time${k > 1 && v.mean_occupancy != null ? ` (mean occupancy ${(+v.mean_occupancy).toFixed(2)})` : ""}` : "";
      rows.push(`<div>capacity ${esc(String(k))}</div><div>${esc(v.series)}: the same items as ${esc(stockName(s.id))}, capacity ${esc(String(k))}${u}. It counts the ones being served (started by ${esc((v.starts || []).join(", "))}), never holds more than this stock, and its items leave as this stock's do (${esc((v.ends_as || []).join(", "))}), on its own writes within ${esc(String(v.tolerance_s))} s: counted once, here, not as a second stock.</div>`);
    }
    return rows.join("");
  }
  // the instruments that wrote a hidden stock's balance counters: what its level is implied from
  function counterInstruments(ev) {
    const ins = [...new Set((ev.balance || []).map((b) => (/instrument="([^"]+)"/.exec(b.series) || [])[1]).filter(Boolean))];
    return ins.join(", ") || "—";
  }
  function flowSummary(fid) {
    const f = MODEL.flows.find((x) => x.id === fid); if (!f) return "";
    const r = recentRate(f.id), pr = against(f).eq, few = Evidence.tooFew(f);
    return `<div class="tt">${esc(flowName(f))}</div><div class="muted">${esc(SDGraph.endName(MODEL, f, "from"))} → ${esc(SDGraph.endName(MODEL, f, "to"))}</div>
      <div class="tr"><span>observed, last ${Math.round(recentMinutes(f.id))} min</span><b>${sig2(r)}${per()}</b></div>${few ? `<div class="tr"><span>equation</span><b>${esc(Evidence.tooFewText(f))}</b></div>`
      : `<div class="tr"><span>equation, same ${Math.round(recentMinutes(f.id))} min</span><b>${sig2(pr)}${per()}</b></div><div class="tr"><span>equation</span><b>${esc(eqText(f))}</b></div>`}<div class="tr"><span>machines (hypotheses)</span><b>${esc(machinesText(f))}</b></div><div class="hint">click for history and fit</div>`;
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
  // a reason not already said by the headline printed beside it (each fact said once)
  const fresh = (ws, said) => (ws || []).filter((w) => w && !said.some((x) => x && (x === w || x.includes(w) || w.includes(x))));
  function trustRows(t, said = []) {
    if (Evidence.byConstruction(t)) return `<div>trust</div><div><b>${esc(Evidence.BY_CONSTRUCTION)}</b>${fresh(t.why, [Evidence.BY_CONSTRUCTION]).map((w) => `<br><span class="muted">${esc(w)}</span>`).join("")}</div>
      ${t.behaviour ? behaviourRows(t.behaviour) : ""}`;
    // a hidden stock's why is the question said at the top of its drawer (``said``): not again here
    if (t.kind === "unmeasured") return `<div>trust</div><div><b>0</b> <span class="muted">no measurement of its level</span>${fresh(t.why, said).map((w) => `<br><span class="muted">${esc(w)}</span>`).join("")}</div>`;
    const pct = (x) => (x == null ? "—" : (+x).toFixed(2));
    const parts = Object.entries(t.components || {}).map(([k, v]) => `${esc(k.replace("_", " "))} ${pct(v)}`).join(" · ");
    const facts = [t.matched_counts ? esc(t.matched_counts) : "", t.p_null != null ? `shift null p ${pct(t.p_null)}` : "", t.held_out_r2 != null ? `held-out R² ${pct(t.held_out_r2)}` : "",
      t.cum_residual_ratio != null ? `running residual ${pct(t.cum_residual_ratio)} × the level's spread` : "", t.units != null ? `judged on ${t.units} unit${t.units === 1 ? "" : "s"} (steps, or stretches between a slow level's writes)` : "",
      t.persistence != null ? (t.persistence_of > 1 ? `found the same way in ${Math.round(100 * t.persistence)}% of the last ${t.persistence_of} discoveries` : "first discovery: nothing to compare with yet") : ""].filter(Boolean).join(" · ");
    return `<div>trust</div><div><b>${pct(t.score)}</b> ${esc(t.level)} <span class="muted">(${esc(t.kind.replace("_", " "))}; the weakest of: ${parts})</span>
      ${facts ? `<br><span class="muted">${facts}</span>` : ""}${(t.why || []).map((w) => `<br><span class="muted">${esc(w)}</span>`).join("")}</div>
      ${t.behaviour ? behaviourRows(t.behaviour) : ""}`;
  }
  // how far to trust the stock's projection (sd/equations/heldout.py): the model run forward from part-way through its window
  function behaviourRows(b) {
    const pct = (x) => (x == null ? "—" : (+x).toFixed(2));
    const head = b.beats_hold === false ? "the equations do worse than holding the level" : "";
    return `<div>behaviour</div><div><b>${pct(b.score)}</b> ${esc(b.level)} <span class="muted">(its own runs from part-way through the window miss the level by ${pct(b.error)} × its spread; holding the level, ${pct(b.hold_error)})</span>${head ? `<br><span class="stale">${head}</span>` : ""}
      ${fresh(b.why, [head]).map((w) => `<br><span class="muted">${esc(w)}</span>`).join("")}</div>`;
  }
  // who wrote a series, as a link to the instrument when an instrument did
  const writerLink = (s, ev) => { const w = ev.written_by || ev.machine; if (!w) return "—";
    const inst = s.series && s.series.labels && s.series.labels.instrument;
    return inst && inst === w ? `<a href="/instruments#${encodeURIComponent(w)}" title="open it on the Instruments page">${esc(w)}</a>` : esc(w); };
  // a balance's term by the flow its counter measures ("+ write → open_pr", a link that opens it),
  // the series a muted second line; a counter no flow shows keeps its title or its key
  function balanceTerm(b) {
    const g = MODEL.flows.find((f) => f.counter && keyOf(f.counter) === b.series), sg = b.sign > 0 ? "+" : "−";
    const title = ((MODEL.discovery || {}).titles || {})[b.series];
    const head = g ? `<a href="#f:${encodeURIComponent(g.id)}" onclick="Live.openFlow('${esc(g.id)}');return false">${esc(flowName(g))}</a>` : esc(title || b.series);
    return `<span class="bal-term">${sg} ${head}${g || title ? `<span class="muted num" style="display:block;font-size:11px">${esc(b.series)}</span>` : ""}</span>`;
  }
  // what a stock is bound to: its series by the title the Instruments page gives it (the selector on
  // hover); a hidden stock's own level series, written and not used, with why; else —
  function boundTo(s) {
    if (s.series) { const k = keyOf(s.series), t = ((MODEL.discovery || {}).titles || {})[k] || (s.evidence && s.evidence.named ? s.name : SDGraph.seriesName(s.series, MODEL.views).name);
      return `<span title="${esc(k)}">${esc(t)}</span><div class="muted num" style="font-size:11px">${esc(k)}</div>`; }
    const u = unreadLevel(s);
    return u ? `<span title="${esc(u.key)}">${esc(u.title)}</span> <span class="muted">written, not used: ${esc(u.why)}</span>` : '<span class="muted">—</span>';
  }
  function openStock(id) {
    const s = MODEL.stocks.find((x) => x.id === id), io = flowsOf(id), ev = s.evidence || {};
    const rate = (f) => `${sig2(recentRate(f.id))}${per()} <span class="muted" style="font-weight:400">observed, last ${Math.round(recentMinutes(f.id))} min</span>`;
    // each flow that fills or drains it opens its own drawer
    const flowRow = (f, sg) => `<div class="tr flowlink" tabindex="0" role="button" title="open this flow" onclick="Live.openFlow('${esc(f.id)}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();Live.openFlow('${esc(f.id)}')}"><span>${sg} ${esc(flowName(f))} <span class="muted">${esc(sg === "+" ? "from " + SDGraph.endName(MODEL, f, "from") : "to " + SDGraph.endName(MODEL, f, "to"))}</span></span> <b style="margin-left:10px">${rate(f)}</b></div>`;
    // outflows are drawn below zero, so what fills and what drains it read apart at a glance
    const lines = [...io.in.map((f, i) => ({ label: "in: " + flowName(f), points: flowHist(f.id), color: STOCK_PAL[i % STOCK_PAL.length] })),
      ...io.out.map((f, i) => ({ label: "out: " + flowName(f), points: flowHist(f.id).map(([t, v]) => [t, -v]), color: STOCK_PAL[(io.in.length + i) % STOCK_PAL.length], dash: "5 3" }))].filter((l) => l.points.length);
    const net = new Map();
    for (const l of lines) for (const [t, v] of l.points) net.set(t, (net.get(t) || 0) + v);
    if (lines.length > 1) lines.push({ label: "net (in − out)", points: [...net.entries()].sort((a, b) => a[0] - b[0]), color: "#e5e7eb" });
    openDrawer(`<h3 data-drawer-key="s:${esc(id)}">${stockHead(s.id)} <span class="tag">stock</span>${ev.hidden ? ' <span class="tag">hidden: found from the levels, not measured</span>' : ""}</h3>
      ${stockAbout(s.id)}
      ${ev.hidden ? `<div class="muted" style="font-size:12px;margin-bottom:8px">A question about the system: ${esc(ev.note || (ev.passing && ev.passing.note) || "something in it is not measured or not understood yet")}.</div>` : ""}
      <div class="def"><div>now</div><div class="num">${HISTORY == null ? '<span class="muted">loading levels…</span>' : fmt(now(id))}</div>
      ${oldest(id) ? `<div>oldest waiting</div><div class="num">${esc(oldest(id))} <span class="muted" style="font-family:inherit">(its instrument's age of this place, as last written: a measurement, not part of the model)</span></div>` : ""}
      ${whyOne(s, io)}
      <div>machines</div><div>${[...new Set([...io.in, ...io.out].flatMap((f) => (f.machines || []).map((h) => h.machine)))].map((m) => `<span class="mdot" style="--c:${mcolor(m)}"></span>${esc(m)}`).join(" ") || '<span class="muted">none associated yet</span>'} <span class="muted">(hypotheses, from its flows)</span></div>
      ${ev.hidden ? `<div>its counters from</div><div>${esc(counterInstruments(ev))} <span class="muted">(its level is what these counters imply)</span></div>` : `<div>measured by</div><div>${writerLink(s, ev)} <span class="muted">(wrote the series: an instrument, or the series' own label)</span></div>`}<div>bound to</div><div>${boundTo(s)}</div>
      ${s.series && s.series.source && s.series.source !== "own" ? `<div>read from</div><div>source <b>${esc(s.series.source)}</b><div class="num" style="font-size:11.5px">${esc(s.series.query || "")}</div><div class="muted" style="font-size:11.5px">${esc((s.series.origin || []).join(" → "))}</div></div>` : ""}
      ${s.series && s.series.traffic ? `<div>counted</div><div>${esc(trafficText(s.series.traffic))}</div>` : ""}
      ${s.series && resOf(MODEL.discovery, keyOf(s.series)) ? `<div>resolution</div><div>${esc(resOf(MODEL.discovery, keyOf(s.series)))}</div>` : ""}
      ${ev.balance ? `<div>balance</div><div>Δ =${ev.balance.map((b) => balanceTerm(b)).join("")}<span class="muted">${ev.trust && ev.trust.kind === "passage" ? "a passage: judged on its raw points; R² not used" : ev.balance_r2 == null ? (ev.by_construction ? "a count and its own turnover (see trust)" : "measured by no series: no fit to report") : `R² ${ev.balance_r2} · exact in ${Math.round(100 * ev.exact_steps)}% of steps`}${ev.balance_r2_level != null ? ` · judged on the traffic through it (R² on the level itself ${ev.balance_r2_level})` : ""}</span></div>` : ""}
      ${ev.net_flow ? netFlowRows(s, ev, io) : ""}
      ${ev.quiet ? `<div>held</div><div>from v${esc(String(ev.quiet.version))}: ${esc(ev.quiet.why)}</div>` : ""}
      ${ev.trust ? trustRows(ev.trust, ev.hidden ? [ev.note, ev.passing && ev.passing.note, ...(ev.trust.why || [])] : []) : ""}</div>
      ${unprojected(s) ? `<h4>Level</h4><div class="muted">not projected: no measurement of its level</div>` : `<h4 style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">Level: measured, as the equations run it, and projected
        <label class="muted" style="font-weight:400;font-size:11.5px">project <input id="sim-h" type="number" min="1" max="1440" value="${horizon()}" style="width:58px"> min ahead</label></h4>
      <div id="sim-chart"><div class="muted">running the equations…</div></div><div id="sim-note" class="muted" style="font-size:11.5px"></div>`}
      <h4>Fills it <span class="muted">(inflows)</span></h4>${io.in.map((f) => flowRow(f, "+")).join("") || '<div class="muted">nothing flows in</div>'}
      <h4>Drains it <span class="muted">(outflows)</span></h4>${io.out.map((f) => flowRow(f, "−")).join("") || '<div class="muted">nothing flows out</div>'}
      <h4>Its flows' rates (${per()}), ${esc(spanText(lines.length ? lines[0].points : []))}: inflows above zero, outflows below</h4>${lines.length ? Charts.line(lines, { W: 700, H: 220, unit: per() }) : '<div class="muted">no flows measured</div>'}`, { key: "s:" + id });
    const inp = document.getElementById("sim-h");
    if (inp) inp.addEventListener("change", () => { try { localStorage.setItem("orchestra.dyn.horizon", String(Math.max(1, +inp.value || 30))); } catch (e) {} simChart(id); });
    if (inp) simChart(id);
    if (typeof IntendedDrawers !== "undefined") IntendedDrawers.expectSwitch("stock", id);     // "Expected: always show this stock" (intended-drawers.js)
  }
  async function simChart(id) {
    const el = document.getElementById("sim-chart"), note = document.getElementById("sim-note"); if (!el) return;
    let d;
    try { d = await (await fetch(`/api/dynamics/simulate?horizon_min=${horizon()}`)).json(); } catch (e) { d = { ok: false, error: String(e) }; }
    if (!document.getElementById("sim-chart")) return;
    // a hidden stock has no series: nothing measured to draw
    const hidden = ((MODEL.stocks.find((s) => s.id === id) || {}).evidence || {}).hidden;
    const measured = hidden ? null : { label: "measured", points: stockHist(id), color: stockColor(id), step: true };
    if (!d.ok) { el.innerHTML = measured ? Charts.line([measured], { W: 700, H: 240 }) : '<div class="muted">nothing measured: a hidden stock</div>'; note.textContent = "Not simulated: " + d.error; return; }
    const era = (d.era || {})[id] || [];
    // no projection where the equations are already wrong now: a flow of this stock not moving as its
    // equation says (and not replayed), or equations that do worse than holding the level
    const st = MODEL.stocks.find((x) => x.id === id) || {}, beh = (((st.evidence || {}).trust) || {}).behaviour;
    const io = flowsOf(id), replayedIds = new Set([...(d.replayed || []), ...(d.too_few || [])]);
    const off = [...io.in, ...io.out].filter((f) => !replayedIds.has(f.id) && !Evidence.tooFew(f)).map((f) => ({ f, a: against(f) })).filter((x) => x.a.differs);
    const noProj = off.length ? `no projection: ${off.map(({ f, a }) => `${flowName(f)} is not moving as its equation says (equation ${sig2(a.eq)}${per()}, observed ${sig2(a.obs)}${per()})`).join("; ")}`
      : beh && beh.beats_hold === false ? "no projection: the equations do worse than holding the level" : "";
    const proj = noProj ? [] : (d.projection || {})[id] || [];
    // the y axis spans what was measured and replayed; a projection running past it is cut, its end said
    const seen = [...(measured ? measured.points : []), ...era].map((p) => p[1]), end = proj.length ? proj[proj.length - 1] : null;
    const yMax = seen.length ? Math.max(...seen) * 1.5 + 1 : null;
    const endText = end ? `+${horizon()} min: ${sig2(end[1])}` : "";
    el.innerHTML = Charts.line([...(measured ? [measured] : []),
      { label: `the equations, from ${Orchestra.when(d.start)}`, points: era, color: "#e5e7eb", dash: "6 4" },
      ...(noProj ? [] : [{ label: `projected, next ${horizon()} min${endText ? ` (${endText})` : ""}`, points: proj, color: stockColor(id), dash: "2 3" }])],
      { W: 700, H: 240, now: d.now, yMax: yMax != null && end && end[1] > yMax ? yMax : null, notes: end ? [{ t: end[0], v: end[1], text: endText }] : [],
        marks: [{ t: d.now, label: "now" }, ...(era.length ? [{ t: d.start, label: "era began" }] : [])] });
    const nameOf = (fid) => flowName(MODEL.flows.find((f) => f.id === fid)) || fid;
    const few = (d.too_few || []).map(nameOf), rep = (d.replayed || []).filter((fid) => !(d.too_few || []).includes(fid)).map(nameOf);
    const replayedText = rep.length || few.length ? ` <b>Replayed, not simulated</b>: their observed rate, then their mean over the last 10 minutes: ${[...rep.map((n) => `${esc(n)} (no equation the simulator steps)`), ...few.map((n) => `${esc(n)} (too few events to fit)`)].join(", ")}.` : " Every flow was simulated from its equation.";
    note.innerHTML = (noProj ? `<div class="stale">${esc(noProj)}</div>` : "") + `The equations start from the measured levels when the era began (the start of the window the model was fitted on, when every series was being written), and run with nothing else but the measured inputs.${noProj ? "" : " The projection starts from the levels now and runs the fitted equations: constant flows continue at their fitted rate; measured inputs are held at their last value. Nothing leaves a stock that is not there."}`
      + replayedText
      + (yMax != null && end && end[1] > yMax ? ` The projection runs above the measured range: the chart is cut at ${fmt(Math.round(yMax))}, its end value is ${esc(endText)}.` : "")
      + (VERSION !== null ? " These are the latest discovery's equations, not this past version's." : "");
  }
  // what an equation reads, by the name the page gives it: a stock's name, or a measured series' title
  // (sd/titles.py, as the Instruments page names it), else its words
  function driverName(x) {
    const n = String(x).replace(/^input:/, ""), titles = (MODEL.discovery || {}).titles || {};
    if (MODEL.stocks.some((s) => s.id === n)) return stockName(n);
    const k = Object.keys(titles).find((key) => key === n || key.startsWith(n + "{") || slugs(key).includes(n));
    return k ? titles[k] : readName(x);
  }
  // the names a series key goes by as a slug (a measured input's SD Lab name): its name and its label
  // values, with or without the labels that only say who wrote it
  function slugs(key) {
    const m = /^([^{]+)(?:\{(.*)\})?$/.exec(key); if (!m) return [];
    const pairs = [...(m[2] || "").matchAll(/(\w+)="([^"]*)"/g)].map((x) => [x[1], x[2]]);
    const slug = (ps) => [m[1], ...ps.map((p) => p[1])].join("_").replace(/[^a-z0-9]+/gi, "_").replace(/^_+|_+$/g, "");
    const who = new Set(["instrument", "machine", "source", "project"]);
    return [slug(pairs), slug(pairs.filter((p) => !who.has(p[0]))), key.replace(/[^a-z0-9]+/gi, "_").replace(/_+$/, "")];
  }
  function openFlow(fid) {
    const f = MODEL.flows.find((x) => x.id === fid), e = f.current || {}, q = e.quality || {}, ev = f.evidence || {};
    const few = Evidence.tooFew(f);
    // the equation over the same buckets as the observed line, from every level sample inside each
    const obs = flowHist(fid), model = few ? [] : FlowCheck.line(f, obs, flowStep(), levelAt, samplesIn(f));
    // lower AIC is better; a form below the chosen one lost only because it did not beat the price of trying it
    const drv = ev.driver || {};
    // each form named as the page names what it reads; a better form was set aside for a reason, said
    const formName = (k) => { const rest = k.slice(4), form = ["proportional", "linear", "constant", "gap"].find((x) => rest === x || rest.startsWith(x + "_"));
      if (!form) return rest.replace(/_/g, " ");
      const what = rest.slice(form.length + 1);
      return what ? `${form} in ${driverName(what)}` : form; };
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
    const cl = (f.counter && f.counter.labels) || {}, endName = (g, which) => SDGraph.endName(MODEL, g, which);
    const apart = SDGraph.drawnApart(MODEL, f);
    const through = (ev.through || []).map((id) => stockName(id)).join(", ");
    // a counter labelled with who moved it (by=, machine=) names an instrument's label, not evidence
    const byLabel = cl.by || cl.machine ? `<div class="muted" style="font-size:11.5px">its counter is labelled ${cl.by ? `by=${esc(cl.by)}` : `machine=${esc(cl.machine)}`}: the instrument's label, not evidence of who moved it</div>` : "";
    // a flow linked by name: its ends, and a click opens it
    const flowLink = (id) => { const g = MODEL.flows.find((x) => x.id === id); if (!g) return esc(id);
      return `<a href="#f:${encodeURIComponent(id)}" onclick="Live.openFlow('${esc(id)}');return false">${esc(flowName(g))}</a> <span class="muted">(${esc(endName(g, "from"))} → ${esc(endName(g, "to"))})</span>`; };
    const zeroEv = (q.events ?? 0) === 0 && f.current && (Object.values(e.params || {}).some((x) => x) || (e.spec && e.spec.value)) ? " · 0 increments seen in the window; the counter first appeared already above 0" : "";
    openDrawer(`<h3 data-drawer-key="f:${esc(fid)}">${esc(flowName(f))} <span class="tag">flow</span></h3>
      <div class="def"><div>moves</div><div>${esc(SDGraph.endName(MODEL, f, "from"))} → ${esc(SDGraph.endName(MODEL, f, "to"))}</div>
      <div>equation</div><div class="num">${few ? "—" : esc(eqText(f))}${SDGraph.correlational(MODEL, f) ? `<div class="muted" style="font-family:inherit">${esc(SDGraph.untestedText(MODEL, f))}</div>` : ""}</div><div>machines</div><div>${(f.machines || []).length ? f.machines.map((h) => `<div><span class="mdot" style="--c:${mcolor(h.machine)}"></span><b><a href="/machines#${encodeURIComponent(h.machine)}" title="open it on the Machines page">${esc(h.machine)}</a></b>${Evidence.confidence(f, h) ? ` <span class="num">${Evidence.confidence(f, h).trim()}${esc(Evidence.chance(f, h))}</span>` : ""} <span class="muted">${esc(h.why || h.origin || "")}</span></div>`).join("") + (Evidence.untold(MODEL, f) ? `<div class="muted" style="font-size:11.5px">${esc(Evidence.untold(MODEL, f))}</div>` : "") + '<div class="muted" style="font-size:11.5px">hypotheses: a match in time, not a cause; they change no equation, and two similar flows between the same stocks may not be told apart</div>' + byLabel : `<span class="muted">${esc(f.association || "no machine associated yet")}</span>${byLabel}`}</div>
      <div>fit</div><div class="num">${few ? `<b>${esc(Evidence.tooFewText(f))}</b>` : `${esc(e.origin || "")} by ${esc(e.method || "")} · ${esc(e.form || "")} · ${q.events ?? 0} events in the fit window${q.live_minutes ? ` (${q.live_minutes} min)` : ""}${q.dispersion != null ? ` · dispersion ${sig2(q.dispersion)}` : ""}`}${zeroEv ? `<div class="muted" style="font-family:inherit">${esc(zeroEv.slice(3))}</div>` : ""}</div>
      <div>rate</div><div class="num">${sig2(recentRate(fid))}${per()} <span class="muted" style="font-family:inherit">observed, last ${Math.round(recentMinutes(fid))} min</span>${few ? "" : `<br>${sig2(against(f).eq)}${per()} <span class="muted" style="font-family:inherit">the fitted equation over the same buckets, from the levels sampled in them</span>`}</div>
      ${(f.measured_by || []).length > 1 ? `<div>measured by</div><div class="num">${f.measured_by.map((c) => esc(c.name)).join(" + ")}</div>` : ""}
      ${SDGraph.sameAs(MODEL, f).length ? `<div>same events</div><div>as ${SDGraph.sameAs(MODEL, f).map(esc).join(", ")} <span class="muted">(another counter counts each of its events: one move, two names)</span></div>` : ""}
      <div>counter</div><div>${f.counter ? `<span title="${esc(keyOf(f.counter))}">${esc(((MODEL.discovery || {}).titles || {})[keyOf(f.counter)] || SDGraph.seriesName(f.counter, MODEL.views).name)}</span><div class="muted num" style="font-size:11px">${esc(keyOf(f.counter))}</div>` : "—"}${apart ? `<div class="muted" style="font-family:inherit">${esc(apart)}${through ? `, because it passes through ${esc(through)}` : ""}</div>` : ""}</div>
      ${ev.co_flow_of ? `<div>co-flow</div><div>${esc(ev.note || "")} (see ${flowLink(ev.co_flow_of)})</div>` : ""}
      ${ev.copy_of ? `<div>copy</div><div>every event of ${esc(flowName(MODEL.flows.find((x) => x.id === ev.copy_of)) || ev.copy_of)} also fills ${esc(f.to ? stockName(f.to) : "this stock")}: one count filling several stocks, not a split</div>` : ""}
      ${(ev.copies || []).length ? `<div>copies</div><div>every event also fills ${ev.copies.map((id) => { const c = MODEL.flows.find((x) => x.id === id); return esc(c && c.to ? stockName(c.to) : id); }).join(", ")}</div>` : ""}
      ${(f.counter && f.counter.traffic) ? `<div>counted</div><div>${esc(trafficText(f.counter.traffic))}</div>` : ""}
      ${(ev.co_flows || []).length ? `<div>co-flows</div><div>the same events also move ${ev.co_flows.map(flowLink).join(", ")}</div>` : ""}
      ${(ev.conflicts || []).map((c) => `<div>also claimed</div><div>its ${c.end === "src" ? "source" : "destination"} by ${c.others.map((o) => `${esc(stockName(o.stock))} (explains ${Math.round(100 * o.share)}% of its changes)`).join(", ")}; kept ${esc(stockName(c.kept))}</div>`).join("")}</div>
      <h4>Rate (${per()}), ${esc(spanText(obs))}: ${few ? "observed (too few events for an equation)" : "observed and what the equation predicts from the levels"}</h4>
      ${Charts.line([{ label: "observed", points: obs, color: SDGraph.FLOW_INK }, ...(few ? [] : [{ label: "equation", points: model, color: "#e5e7eb", dash: "6 4" }])], { W: 700, H: 240, unit: per() })}
      ${alts ? `<h4>Other forms considered (AIC; lower is better)</h4>${price}<table class="dt"><tr><th>form</th><th>AIC</th><th>against the chosen</th></tr><tr><td><b>${esc(e.form)}</b> (chosen)</td><td class="num">${rateFmt(q.aic)}</td><td></td></tr>${alts}</table>` : ""}`, { key: "f:" + fid });
    if (typeof IntendedDrawers !== "undefined") IntendedDrawers.expectSwitch("flow", fid);
  }

  // the history chart under the diagram: every stock, each toggled from its key
  function chart() {
    const el = document.getElementById("hist"); if (!el || !MODEL) return;
    const ids = MODEL.stocks.map((s) => s.id).filter((id) => stockHist(id).length);
    if (!ids.length) { el.innerHTML = HISTORY == null ? '<div class="muted">loading levels…</div>' : '<div class="muted">No history yet.</div>'; return; }
    if (HIDDEN === null) { const near = typeof Intended !== "undefined" ? Intended.nearIds() : new Set();
      HIDDEN = new Set(MODEL.stocks.filter((s) => s.evidence && s.evidence.accumulator && !near.has(s.id)).map((s) => s.id)); }
    const tt = document.getElementById("hist-title"), all = ids.flatMap((id) => stockHist(id)).sort((a, b) => a[0] - b[0]);
    if (tt) tt.textContent = `Stocks, ${spanText(all)}`;
    const lines = ids.map((id, i) => ({ id, i, label: stockName(id), points: stockHist(id), color: stockColor(id), step: true }));
    const shown = lines.filter((l) => !HIDDEN.has(l.id));
    document.getElementById("hist-keys").innerHTML = lines.map((l) => `<span class="hk ${HIDDEN.has(l.id) ? "off" : ""}" onclick="Live.toggle('${esc(l.id)}')"><i style="background:${stockColor(l.id)}"></i>${esc(l.label)} <b>${fmt(now(l.id))}</b></span>`).join("");
    // keep each stock's colour when others are hidden: pad hidden lines as empty
    el.innerHTML = shown.length ? Charts.line(lines.map((l) => (HIDDEN.has(l.id) ? { label: l.label, points: [], color: l.color } : l)), { W: el.clientWidth || 900, H: 220, integer: shown.every((l) => l.points.every((p) => Number.isInteger(p[1]))) })
      : '<div class="muted">Every stock is hidden; click one above.</div>';
    el.querySelectorAll(".ckeys").forEach((k) => k.remove());
  }
  function toggle(id) { HIDDEN = HIDDEN || new Set(); HIDDEN.has(id) ? HIDDEN.delete(id) : HIDDEN.add(id); try { localStorage.setItem("orchestra.dyn.hidden", JSON.stringify([...HIDDEN])); } catch (e) {} chart(); }

  // a flow's label on the diagram: the observed rate first, then the equation's ("0.31 /min observed ·
  // equation 1.5 /min"), and ``warn`` where they part by more than chance; quiet when nothing moved over
  // the recent window. A flow with too few events to fit has no equation: its label says so
  function edgeLabel(e) {
    const f = MODEL && MODEL.flows.find((x) => x.id === e.fid); if (!f || !e.eqLabel) return null;
    const a = against(f), few = typeof Evidence !== "undefined" && Evidence.tooFew(f);
    const eq = a.eq != null ? `equation ${sig2(a.eq)} ${per()}` : `equation ${e.eqLabel}`;
    const first = few ? Evidence.tooFewText(f) : a.obs != null ? `${sig2(a.obs)} ${per()} observed · ${eq}` : eq;
    return { label: [first, ...(Array.isArray(e.label) ? e.label.slice(1) : [])], quiet: !!a.quiet && HISTORY != null, warn: !few && !!a.differs };
  }
  let GRAPH = null;
  async function refresh() {
    const first = HISTORY == null;
    try { const d = await (await fetch("/api/dynamics/history")).json(); if (d.ok) HISTORY = d; if (typeof online === "function") online(); }
    catch (e) { if (typeof offline === "function") offline(); return; }
    // the first levels: draw the diagram again with them (what moves now, the levels in the boxes)
    if (first && HISTORY != null && typeof MODEL !== "undefined" && MODEL && typeof draw === "function") { try { draw(); } catch (e) {} }
    if (GRAPH) {
      GRAPH.refreshNodes((n) => (n.sid || n.input ? {} : null));
      GRAPH.setRates((e) => (e.flowPart ? recentRate(e.fid) : 0));
      GRAPH.setLabels((e) => (e.flowPart && e.fid ? edgeLabel(e) : null));
    }
    chart();
    // the tables read the observed rates too (observed first, a missed equation said): redrawn when they changed
    if (typeof MODEL !== "undefined" && MODEL && typeof tables === "function") { try { tables(); } catch (e) {} }
  }
  function drawn(graph) { GRAPH = graph; graph.setRates((e) => (e.flowPart ? recentRate(e.fid) : 0)); chart(); }
  return { unreadLevel, recentRate, refresh, drawn, toggle, openStock, openFlow, decorateStock, decorateInput, stockSummary, flowSummary, edgeLabel, against, now: (id) => now(id), sig2, per, recentMinutes, has: () => HISTORY != null };
})();
Live.refresh(); setInterval(Live.refresh, 15000);
