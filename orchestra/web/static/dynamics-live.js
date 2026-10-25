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
  const fmt = (v) => (v == null ? "—" : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
  const stockHist = (id) => (HISTORY && HISTORY.stocks && HISTORY.stocks[id]) || [];
  const flowHist = (id) => (HISTORY && HISTORY.flows && HISTORY.flows[id]) || [];
  const now = (id) => { const h = stockHist(id); return h.length ? h[h.length - 1][1] : (MODEL.levels[id] || {}).v; };
  const recentRate = (fid) => { const h = flowHist(fid).slice(-4); return h.length ? h.reduce((a, p) => a + p[1], 0) / h.length : null; };
  const inputHist = (name) => (HISTORY && HISTORY.inputs && HISTORY.inputs[name]) || [];
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
    g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", y0 + 32).attr("fill", col).text(v == null ? "no data" : `${fmt(v)} now · max ${fmt(max)}`);
    // the machines that change this stock: one dot per machine whose flows fill or drain it
    const io = flowsOf(id), ms = [...new Set([...io.in, ...io.out].map((f) => f.machine).filter(Boolean))];
    ms.forEach((m, k) => g.append("circle").attr("cx", -x0 - 9 - k * 11).attr("cy", y0 + 10).attr("r", 4).attr("fill", mcolor(m)).append("title").text(m));
    if (h.length > 1) {
      const a = x0 + 10, b = -x0 - 10, top = -y0 - 34, bot = -y0 - 8, t0 = h[0][0], t1 = h[h.length - 1][0] || t0 + 1;
      g.append("path").attr("fill", "none").attr("stroke", col).attr("stroke-width", 1.4)
        .attr("d", h.map(([t, y], i) => `${i ? "L" : "M"}${(a + (b - a) * (t - t0) / (t1 - t0)).toFixed(1)},${(bot + (top - bot) * (y - min) / (max - min || 1)).toFixed(1)}`).join(" "));
    }
  }

  // a measured input, outside the system: its value now and its hour
  function decorateInput(g, n, sz) {
    const h = inputHist(n.input), vals = h.map((p) => p[1]), v = vals.length ? vals[vals.length - 1] : null;
    const max = Math.max(...vals, 1e-9), min = Math.min(...vals, 0), x0 = -sz.w / 2, y0 = -sz.h / 2;
    g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", y0 + 30).text(v == null ? "measured input" : `${fmt(v)} now · input`);
    if (h.length > 1) {
      const a = x0 + 8, b = -x0 - 8, top = -y0 - 24, bot = -y0 - 6, t0 = h[0][0], t1 = h[h.length - 1][0] || t0 + 1;
      g.append("path").attr("fill", "none").attr("stroke", "#94a3b8").attr("stroke-width", 1.2)
        .attr("d", h.map(([t, y], i) => `${i ? "L" : "M"}${(a + (b - a) * (t - t0) / (t1 - t0)).toFixed(1)},${(bot + (top - bot) * (y - min) / (max - min || 1)).toFixed(1)}`).join(" "));
    }
  }

  // ---- hover and click ----
  function stockSummary(id) {
    const s = MODEL.stocks.find((x) => x.id === id), h = stockHist(id).map((p) => p[1]), v = now(id), io = flowsOf(id);
    const rows = [...io.in.map((f) => ["+", f]), ...io.out.map((f) => ["−", f])].map(([sg, f]) => `<div class="tr"><span>${sg} ${esc(f.name)}</span><b>${fmt(recentRate(f.id))}${per()}</b></div>`).join("");
    const changers = [...new Set([...io.in, ...io.out].map((f) => f.machine).filter(Boolean))];
    return `<div class="tt">${esc(s.name)}</div><div class="tr"><span>now</span><b>${fmt(v)}</b></div>
      <div class="tr"><span>changed by</span><b>${changers.map((m) => `<span style="color:${mcolor(m)}">${esc(m)}</span>`).join(", ") || "—"}</b></div>
      <div class="tr"><span>measured by</span><b>${esc((s.evidence && s.evidence.machine) || "—")}</b></div><div class="tr"><span>range, last hour</span><b>${fmt(h.length ? Math.min(...h) : null)} – ${fmt(h.length ? Math.max(...h) : null)}</b></div>${rows}<div class="hint">click for history and details</div>`;
  }
  function flowSummary(fid) {
    const f = MODEL.flows.find((x) => x.id === fid); if (!f) return "";
    const r = recentRate(f.id), pr = predicted(f, Date.now() / 1000);
    return `<div class="tt">${esc(f.name)}</div><div class="muted">${esc(f.from ? stockName(f.from) : "outside")} → ${esc(f.to ? stockName(f.to) : "outside")}</div>
      <div class="tr"><span>observed, last 2 min</span><b>${fmt(r)}${per()}</b></div><div class="tr"><span>equation says now</span><b>${fmt(pr)}${per()}</b></div>
      <div class="tr"><span>equation</span><b>${esc(eqText(f))}</b></div>${f.machine ? `<div class="tr"><span>machine</span><b>${esc(f.machine)}</b></div>` : ""}<div class="hint">click for history and fit</div>`;
  }
  // the stock's drawer: what it is, its level measured and as the equations run it (since the era
  // began, and projected ahead), and the flows that fill and drain it
  const horizon = () => { try { return +localStorage.getItem("orchestra.dyn.horizon") || 30; } catch (e) { return 30; } };
  function openStock(id) {
    const s = MODEL.stocks.find((x) => x.id === id), io = flowsOf(id), ev = s.evidence || {};
    const rate = (f) => `${fmt(recentRate(f.id))}${per()}`;
    const flowRow = (f, sg) => `<div class="tr"><span>${sg} <span class="mdot" style="--c:${mcolor(f.machine)}"></span>${esc(f.name)} <span class="muted">${esc(sg === "+" ? "from " + (f.from ? stockName(f.from) : "outside") : "to " + (f.to ? stockName(f.to) : "outside"))}</span></span> <b style="margin-left:10px">${rate(f)}</b></div>`;
    // outflows are drawn below zero, so what fills and what drains it read apart at a glance
    const lines = [...io.in.map((f) => ({ label: "in: " + f.name, points: flowHist(f.id), color: mcolor(f.machine) })),
      ...io.out.map((f) => ({ label: "out: " + f.name, points: flowHist(f.id).map(([t, v]) => [t, -v]), color: mcolor(f.machine), dash: "5 3" }))].filter((l) => l.points.length);
    const net = new Map();
    for (const l of lines) for (const [t, v] of l.points) net.set(t, (net.get(t) || 0) + v);
    if (lines.length > 1) lines.push({ label: "net (in − out)", points: [...net.entries()].sort((a, b) => a[0] - b[0]), color: "#e5e7eb" });
    openDrawer(`<h3>${esc(s.name)} <span class="tag">stock</span>${ev.hidden ? ' <span class="tag">hidden: found from the levels, not measured</span>' : ""}</h3>
      <div class="def"><div>now</div><div class="num">${fmt(now(id))}</div>
      <div>changed by</div><div>${[...new Set([...io.in, ...io.out].map((f) => f.machine).filter(Boolean))].map((m) => `<span class="mdot" style="--c:${mcolor(m)}"></span>${esc(m)}`).join(" ") || "—"}</div>
      <div>measured by</div><div>${esc(ev.machine || "—")} <span class="muted">(writes the series)</span></div><div>bound to</div><div class="num">${esc(s.series ? s.series.name + JSON.stringify(Object.fromEntries(Object.entries(s.series.labels).filter(([k]) => k !== "project"))) : "—")}</div>
      ${ev.balance ? `<div>balance</div><div class="num">Δ = ${ev.balance.map((b) => `${b.sign > 0 ? "+" : "−"} ${esc(b.series)}`).join(" ")}<br><span class="muted">R² ${ev.balance_r2} · exact in ${Math.round(100 * ev.exact_steps)}% of steps</span></div>` : ""}</div>
      <h4 style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">Level: measured, as the equations run it, and projected
        <label class="muted" style="font-weight:400;font-size:11.5px">project <input id="sim-h" type="number" min="1" max="1440" value="${horizon()}" style="width:58px"> min ahead</label></h4>
      <div id="sim-chart"><div class="muted">running the equations…</div></div><div id="sim-note" class="muted" style="font-size:11.5px"></div>
      <h4>Fills it <span class="muted">(inflows)</span></h4>${io.in.map((f) => flowRow(f, "+")).join("") || '<div class="muted">nothing flows in</div>'}
      <h4>Drains it <span class="muted">(outflows)</span></h4>${io.out.map((f) => flowRow(f, "−")).join("") || '<div class="muted">nothing flows out</div>'}
      <h4>Its flows' rates (${per()}): inflows above zero, outflows below</h4>${lines.length ? Charts.line(lines, { W: 700, H: 220, unit: per() }) : '<div class="muted">no flows measured</div>'}`);
    const inp = document.getElementById("sim-h");
    inp.addEventListener("change", () => { try { localStorage.setItem("orchestra.dyn.horizon", String(Math.max(1, +inp.value || 30))); } catch (e) {} simChart(id); });
    simChart(id);
  }
  async function simChart(id) {
    const el = document.getElementById("sim-chart"), note = document.getElementById("sim-note"); if (!el) return;
    let d;
    try { d = await (await fetch(`/api/dynamics/simulate?horizon_min=${horizon()}`)).json(); } catch (e) { d = { ok: false, error: String(e) }; }
    if (!document.getElementById("sim-chart")) return;
    const measured = { label: "measured", points: stockHist(id), color: stockColor(id) };
    if (!d.ok) { el.innerHTML = Charts.line([measured], { W: 700, H: 240 }); note.textContent = "Not simulated: " + d.error; return; }
    const era = (d.era || {})[id] || [], proj = (d.projection || {})[id] || [];
    el.innerHTML = Charts.line([measured,
      { label: `the equations, from ${new Date(d.start * 1000).toTimeString().slice(0, 5)}`, points: era, color: "#e5e7eb", dash: "6 4" },
      { label: `projected, next ${horizon()} min`, points: proj, color: stockColor(id), dash: "2 3" }],
      { W: 700, H: 240, marks: [{ t: d.now, label: "now" }, ...(era.length ? [{ t: d.start, label: "era began" }] : [])] });
    const rep = (d.replayed || []).map((fid) => (MODEL.flows.find((f) => f.id === fid) || {}).name || fid);
    note.innerHTML = `The equations start from the measured levels when the era began (the start of the window the model was fitted on, when every series was being written), and run with nothing else but the measured inputs; the projection starts from the levels now, with each input held at its last value. Nothing leaves a stock that is not there.`
      + (rep.length ? ` <b>Replayed, not simulated</b> (no equation the simulator steps): ${rep.map(esc).join(", ")}: their observed rate, then their mean over the last 10 minutes.` : " Every flow was simulated from its equation.")
      + (VERSION !== null ? " These are the latest discovery's equations, not this past version's." : "");
  }
  function openFlow(fid) {
    const f = MODEL.flows.find((x) => x.id === fid), e = f.current || {}, q = e.quality || {};
    const obs = flowHist(fid), model = obs.map(([t]) => [t, predicted(f, t)]).filter((p) => p[1] != null);
    const alts = Object.entries(q).filter(([k]) => k.startsWith("aic_")).map(([k, v]) => `<tr><td>${esc(k.slice(4).replace(/_/g, " "))}</td><td class="num">${fmt(v)}</td><td class="num">${fmt(v - q.aic)}</td></tr>`).join("");
    openDrawer(`<h3>${esc(f.name)} <span class="tag">flow</span></h3>
      <div class="def"><div>moves</div><div>${esc(f.from ? stockName(f.from) : "outside")} → ${esc(f.to ? stockName(f.to) : "outside")}</div>
      <div>equation</div><div class="num">${esc(eqText(f))}</div><div>machine</div><div>${esc(f.machine || "none")}</div>
      <div>fit</div><div class="num">${esc(e.origin || "")} by ${esc(e.method || "")} · ${esc(e.form || "")} · ${q.events ?? 0} events${q.live_minutes ? ` over ${q.live_minutes} min` : ""}${q.dispersion != null ? ` · dispersion ${fmt(q.dispersion)}` : ""}</div>
      ${(f.measured_by || []).length > 1 ? `<div>measured by</div><div class="num">${f.measured_by.map((c) => esc(c.name)).join(" + ")}</div>` : ""}
      <div>counter</div><div class="num">${esc(f.counter ? f.counter.name : "—")}</div></div>
      <h4>Rate, last hour (${per()}): observed and what the equation predicts from the levels</h4>
      ${Charts.line([{ label: "observed", points: obs, color: mcolor(f.machine) }, { label: "equation", points: model, color: "#e5e7eb" }], { W: 700, H: 240, unit: per() })}
      ${alts ? `<h4>Other forms considered (AIC; lower is better)</h4><table class="dt"><tr><th>form</th><th>AIC</th><th>worse by</th></tr><tr><td><b>${esc(e.form)}</b> (chosen)</td><td class="num">${fmt(q.aic)}</td><td></td></tr>${alts}</table>` : ""}`);
  }

  // ---- the history chart ----
  function chart() {
    const el = document.getElementById("hist"); if (!el || !MODEL) return;
    const ids = MODEL.stocks.map((s) => s.id).filter((id) => stockHist(id).length);
    if (!ids.length) { el.innerHTML = '<div class="muted">No history yet.</div>'; return; }
    if (HIDDEN === null) HIDDEN = new Set(MODEL.stocks.filter((s) => s.evidence && s.evidence.accumulator).map((s) => s.id));
    const lines = ids.map((id, i) => ({ id, i, label: stockName(id), points: stockHist(id), color: stockColor(id) }));
    const shown = lines.filter((l) => !HIDDEN.has(l.id));
    document.getElementById("hist-keys").innerHTML = lines.map((l) => `<span class="hk ${HIDDEN.has(l.id) ? "off" : ""}" onclick="Live.toggle('${esc(l.id)}')"><i style="background:${stockColor(l.id)}"></i>${esc(l.label)} <b>${fmt(now(l.id))}</b></span>`).join("");
    // keep each stock's colour when others are hidden: pad hidden lines as empty
    el.innerHTML = shown.length ? Charts.line(lines.map((l) => (HIDDEN.has(l.id) ? { label: l.label, points: [], color: l.color } : l)), { W: el.clientWidth || 900, H: 220 })
      : '<div class="muted">Every stock is hidden; click one above.</div>';
    el.querySelectorAll(".ckeys").forEach((k) => k.remove());
  }
  function toggle(id) { HIDDEN = HIDDEN || new Set(); HIDDEN.has(id) ? HIDDEN.delete(id) : HIDDEN.add(id); try { localStorage.setItem("orchestra.dyn.hidden", JSON.stringify([...HIDDEN])); } catch (e) {} chart(); }

  let GRAPH = null;
  async function refresh() {
    try { const d = await (await fetch("/api/dynamics/history")).json(); if (d.ok) HISTORY = d; } catch (e) {}
    if (GRAPH) {
      GRAPH.refreshNodes((n) => (n.sid || n.input ? {} : null));
      GRAPH.setRates((e) => (e.flowPart ? recentRate(e.fid) : 0));
    }
    chart();
  }
  function drawn(graph) { GRAPH = graph; graph.setRates((e) => (e.flowPart ? recentRate(e.fid) : 0)); chart(); }
  return { refresh, drawn, toggle, openStock, openFlow, decorateStock, decorateInput, stockSummary, flowSummary };
})();
Live.refresh(); setInterval(Live.refresh, 15000);
