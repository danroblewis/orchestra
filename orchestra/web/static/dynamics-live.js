// The Dynamics page's live layer, on top of the diagram SD Lab's code draws (sd-diagram.js):
// - each stock box shows its current value, a tank fill (now ÷ the highest seen in the window)
//   and a sparkline of the window;
// - each flow carries moving dashes whose speed follows its recent rate;
// - hovering a stock or a flow shows a summary; clicking opens a drawer with its history, and
//   for a flow, its observed rate against what its fitted equation predicts;
// - a chart under the diagram plots every stock, each line toggled from its legend.
// Data: MODEL (/api/dynamics/model) and HISTORY (/api/dynamics/history), both read from the web
// server's caches; nothing here queries the metrics store directly.
const Live = (() => {
  let HISTORY = null, CTX = null;          // CTX: {D, box, color}: what draw() laid out
  const stored = (() => { try { return JSON.parse(localStorage.getItem("orchestra.dyn.hidden")); } catch (e) { return null; } })();
  // until the viewer chooses, stocks that only fill start hidden: their scale flattens the rest
  let HIDDEN = stored ? new Set(stored) : null;
  const per = () => { const u = (MODEL && MODEL.time_unit) || "minute"; return u === "minute" ? "/min" : u === "hour" ? "/h" : "/s"; };
  const fmt = (v) => (v == null ? "—" : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
  const stockHist = (id) => (HISTORY && HISTORY.stocks && HISTORY.stocks[id]) || [];
  const flowHist = (id) => (HISTORY && HISTORY.flows && HISTORY.flows[id]) || [];
  const now = (id) => { const h = stockHist(id); return h.length ? h[h.length - 1][1] : (MODEL.levels[id] || {}).v; };
  const recentRate = (fid) => { const h = flowHist(fid).slice(-4); return h.length ? h.reduce((a, p) => a + p[1], 0) / h.length : null; };
  const levelAt = (sid, t) => { const h = stockHist(sid); let v = null; for (const [tt, x] of h) { if (tt > t) break; v = x; } return v; };
  // what the flow's fitted equation says its rate is, given the levels at time t
  function predicted(f, t) {
    const e = f.current; if (!e) return null;
    const p = e.params, x = e.inputs && e.inputs[0] ? levelAt(e.inputs[0], t) : null;
    if (e.form === "constant") return p.c;
    if (x == null) return null;
    return e.form === "proportional" ? p.k * x : Math.max(0, p.c + p.k * x);
  }
  const flowsOf = (sid) => ({ in: MODEL.flows.filter((f) => f.to === sid), out: MODEL.flows.filter((f) => f.from === sid) });

  // ---- the diagram ----
  function stockGroup(id) { return document.querySelector(`#sd g.dstock.st-${CSS.escape(id)}`); }
  function decorate() {
    if (!CTX || !MODEL) return;
    const { box, color } = CTX;
    for (const s of MODEL.stocks) {
      const g = stockGroup(s.id); if (!g) continue;
      g.querySelectorAll(".live").forEach((x) => x.remove());
      g.querySelectorAll("title").forEach((x) => x.remove());
      const h = stockHist(s.id), vals = h.map((p) => p[1]), v = now(s.id);
      const max = Math.max(1e-9, ...vals, v || 0), min = Math.min(0, ...vals);
      const col = color("st-" + s.id), NS = "http://www.w3.org/2000/svg";
      const mk = (tag, attrs, before) => { const e = document.createElementNS(NS, tag); for (const [k, x] of Object.entries(attrs)) e.setAttribute(k, x); e.classList.add("live"); before ? g.insertBefore(e, before) : g.appendChild(e); return e; };
      // the tank: how full the stock is against the highest level seen in the window
      const frac = v == null ? 0 : Math.max(0, Math.min(1, (v - min) / (max - min || 1)));
      const firstText = g.querySelector("text");
      mk("rect", { x: 1.5, y: box.h - 1.5 - (box.h - 3) * frac, width: box.w - 3, height: (box.h - 3) * frac, rx: 2, fill: col, opacity: 0.16, "pointer-events": "none" }, firstText);
      // the value, under the name
      const sub = g.querySelectorAll("text")[1];
      if (sub) sub.textContent = v == null ? "no data" : `${fmt(v)} now · max ${fmt(max)}`;
      // the sparkline, along the bottom of the box
      if (h.length > 1) {
        const x0 = 10, x1 = box.w - 10, y0 = box.h - 8, y1 = box.h - 30, t0 = h[0][0], t1 = h[h.length - 1][0] || t0 + 1;
        const d = h.map(([t, y], i) => `${i ? "L" : "M"}${(x0 + (x1 - x0) * (t - t0) / (t1 - t0)).toFixed(1)},${(y0 + (y1 - y0) * (y - min) / (max - min || 1)).toFixed(1)}`).join(" ");
        mk("path", { d, fill: "none", stroke: col, "stroke-width": 1.4, opacity: 0.9, "pointer-events": "none" });
      }
    }
    // moving dashes on each flow, faster the higher its recent rate
    const flowGs = [...document.querySelectorAll("#sd g.dflow")];
    CTX.D.flows.forEach((f, i) => {
      const g = flowGs[i]; if (!g) return;
      g.querySelectorAll(".flowdash").forEach((x) => x.remove());
      g.querySelectorAll("title").forEach((x) => x.remove());
      const r = recentRate(f.fid), line = g.querySelector("path");
      if (!line || !r || r <= 0.01) return;
      const dash = line.cloneNode(); dash.removeAttribute("marker-end"); dash.setAttribute("class", "flowdash");
      dash.style.animationDuration = `${Math.max(0.25, Math.min(6, 8 / Math.sqrt(r))).toFixed(2)}s`;
      g.appendChild(dash);
    });
    document.querySelectorAll("#sd g.dlabel title").forEach((x) => x.remove());
  }

  // ---- hover and click ----
  const tip = () => { let t = document.getElementById("sdtip"); if (!t) { t = document.createElement("div"); t.id = "sdtip"; t.className = "sdtip"; document.body.appendChild(t); } return t; };
  function stockSummary(id) {
    const s = MODEL.stocks.find((x) => x.id === id), h = stockHist(id).map((p) => p[1]), v = now(id), io = flowsOf(id);
    const rows = [...io.in.map((f) => ["+", f]), ...io.out.map((f) => ["−", f])].map(([sg, f]) => `<div class="tr"><span>${sg} ${esc(f.name)}</span><b>${fmt(recentRate(f.id))}${per()}</b></div>`).join("");
    return `<div class="tt">${esc(s.name)}</div><div class="tr"><span>now</span><b>${fmt(v)}</b></div><div class="tr"><span>range, last hour</span><b>${fmt(h.length ? Math.min(...h) : null)} – ${fmt(h.length ? Math.max(...h) : null)}</b></div>${rows}<div class="hint">click for history and details</div>`;
  }
  function flowSummary(f) {
    const r = recentRate(f.id), pr = predicted(f, Date.now() / 1000);
    return `<div class="tt">${esc(f.name)}</div><div class="muted">${esc(f.from ? stockName(f.from) : "outside")} → ${esc(f.to ? stockName(f.to) : "outside")}</div>
      <div class="tr"><span>observed, last 2 min</span><b>${fmt(r)}${per()}</b></div><div class="tr"><span>equation says now</span><b>${fmt(pr)}${per()}</b></div>
      <div class="tr"><span>equation</span><b>${esc(eqText(f))}</b></div>${f.machine ? `<div class="tr"><span>machine</span><b>${esc(f.machine)}</b></div>` : ""}<div class="hint">click for history and fit</div>`;
  }
  function wire() {
    const show = (html, ev) => { const t = tip(); t.innerHTML = html; t.style.display = "block"; place(ev); };
    const place = (ev) => { const t = tip(), r = t.getBoundingClientRect(); t.style.left = Math.min(innerWidth - r.width - 8, ev.clientX + 14) + "px"; t.style.top = Math.min(innerHeight - r.height - 8, ev.clientY + 14) + "px"; };
    const hide = () => { tip().style.display = "none"; };
    for (const s of MODEL.stocks) {
      const g = stockGroup(s.id); if (!g) continue;
      g.style.cursor = "pointer";
      g.onmouseenter = (ev) => show(stockSummary(s.id), ev); g.onmousemove = place; g.onmouseleave = hide;
      g.onclick = () => { hide(); openStock(s.id); };
    }
    const flowGs = [...document.querySelectorAll("#sd g.dflow")], labelGs = [...document.querySelectorAll("#sd g.dlabel")];
    CTX.D.flows.forEach((df, i) => {
      const f = MODEL.flows.find((x) => x.id === df.fid);
      for (const g of [flowGs[i], labelGs[i]]) {
        if (!g || !f) continue;
        g.style.cursor = "pointer";
        g.onmouseenter = (ev) => show(flowSummary(f), ev); g.onmousemove = place; g.onmouseleave = hide;
        g.onclick = () => { hide(); openFlow(f.id); };
      }
    });
  }
  function openStock(id) {
    const s = MODEL.stocks.find((x) => x.id === id), io = flowsOf(id), ev = s.evidence || {};
    const lines = [...io.in.map((f) => ({ label: "+ " + f.name, points: flowHist(f.id) })), ...io.out.map((f) => ({ label: "− " + f.name, points: flowHist(f.id).map(([t, v]) => [t, v]) }))].filter((l) => l.points.length);
    openDrawer(`<h3>${esc(s.name)} <span class="tag">stock</span></h3>
      <div class="def"><div>now</div><div class="num">${fmt(now(id))}</div><div>bound to</div><div class="num">${esc(s.series ? s.series.name + JSON.stringify(Object.fromEntries(Object.entries(s.series.labels).filter(([k]) => k !== "project"))) : "—")}</div>
      ${ev.balance ? `<div>balance</div><div class="num">Δ = ${ev.balance.map((b) => `${b.sign > 0 ? "+" : "−"} ${esc(b.series)}`).join(" ")}<br><span class="muted">R² ${ev.balance_r2} · exact in ${Math.round(100 * ev.exact_steps)}% of steps</span></div>` : ""}</div>
      <h4>Level, last hour</h4>${Charts.line([{ label: s.name, points: stockHist(id) }], { W: 700, H: 220 })}
      <h4>Its flows' rates (${per()})</h4>${lines.length ? Charts.line(lines, { W: 700, H: 220, unit: per() }) : '<div class="muted">no flows</div>'}`);
  }
  function openFlow(fid) {
    const f = MODEL.flows.find((x) => x.id === fid), e = f.current || {}, q = e.quality || {};
    const obs = flowHist(fid), model = obs.map(([t]) => [t, predicted(f, t)]).filter((p) => p[1] != null);
    const alts = Object.entries(q).filter(([k]) => k.startsWith("aic_")).map(([k, v]) => `<tr><td>${esc(k.slice(4).replace(/_/g, " "))}</td><td class="num">${fmt(v)}</td><td class="num">${fmt(v - q.aic)}</td></tr>`).join("");
    openDrawer(`<h3>${esc(f.name)} <span class="tag">flow</span></h3>
      <div class="def"><div>moves</div><div>${esc(f.from ? stockName(f.from) : "outside")} → ${esc(f.to ? stockName(f.to) : "outside")}</div>
      <div>equation</div><div class="num">${esc(eqText(f))}</div><div>machine</div><div>${esc(f.machine || "none")}</div>
      <div>fit</div><div class="num">${esc(e.origin || "")} · ${esc(e.form || "")} · ${q.events ?? 0} events over ${q.live_minutes ?? "?"} min · dispersion ${fmt(q.dispersion)}</div>
      <div>counter</div><div class="num">${esc(f.counter ? f.counter.name : "—")}</div></div>
      <h4>Rate, last hour (${per()}): observed and what the equation predicts from the levels</h4>
      ${Charts.line([{ label: "observed", points: obs }, { label: "equation", points: model }], { W: 700, H: 240, unit: per() })}
      ${alts ? `<h4>Other forms considered (AIC; lower is better)</h4><table class="dt"><tr><th>form</th><th>AIC</th><th>worse by</th></tr><tr><td><b>${esc(e.form)}</b> (chosen)</td><td class="num">${fmt(q.aic)}</td><td></td></tr>${alts}</table>` : ""}`);
  }

  // ---- the history chart ----
  function chart() {
    const el = document.getElementById("hist"); if (!el || !MODEL) return;
    const ids = MODEL.stocks.map((s) => s.id).filter((id) => stockHist(id).length);
    if (!ids.length) { el.innerHTML = '<div class="muted">No history yet.</div>'; return; }
    if (HIDDEN === null) HIDDEN = new Set(MODEL.stocks.filter((s) => s.evidence && s.evidence.accumulator).map((s) => s.id));
    const lines = ids.map((id, i) => ({ id, i, label: stockName(id), points: stockHist(id) }));
    const shown = lines.filter((l) => !HIDDEN.has(l.id));
    document.getElementById("hist-keys").innerHTML = lines.map((l) => `<span class="hk ${HIDDEN.has(l.id) ? "off" : ""}" onclick="Live.toggle('${esc(l.id)}')"><i style="background:${Charts.PAL[l.i % Charts.PAL.length]}"></i>${esc(l.label)} <b>${fmt(now(l.id))}</b></span>`).join("");
    // keep each stock's colour when others are hidden: pad hidden lines as empty
    el.innerHTML = shown.length ? Charts.line(lines.map((l) => (HIDDEN.has(l.id) ? { label: l.label, points: [] } : l)), { W: el.clientWidth || 900, H: 220 })
      : '<div class="muted">Every stock is hidden; click one above.</div>';
    el.querySelectorAll(".ckeys").forEach((k) => k.remove());
  }
  function toggle(id) { HIDDEN = HIDDEN || new Set(); HIDDEN.has(id) ? HIDDEN.delete(id) : HIDDEN.add(id); try { localStorage.setItem("orchestra.dyn.hidden", JSON.stringify([...HIDDEN])); } catch (e) {} chart(); }

  async function refresh() {
    try { const d = await (await fetch("/api/dynamics/history")).json(); if (d.ok) HISTORY = d; } catch (e) {}
    decorate(); chart();
  }
  function drawn(ctx) { CTX = ctx; decorate(); wire(); chart(); }
  return { refresh, drawn, toggle, openStock, openFlow };
})();
Live.refresh(); setInterval(Live.refresh, 15000);
