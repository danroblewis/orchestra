// The Dashboard's "Where this is going" panel: the model's projection in words (projection.js) for
// the three stocks that move most, each with a sparkline of its history and its projection; the
// machines' predictions still waiting for their horizon and the last three verdicts
// (sd/predictions.py, /api/dynamics/predictions); and the flows not moving as their equations say
// (flow-check.js). Each part is read on its own and fails on its own: no model, or a simulation
// that does not run, is said in the panel and the rest of the Dashboard stands (AGENTS.md rule 8's
// spirit). ``WherePanel.render`` is pure, for the Node tests.
const WherePanel = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const PAL = ["#60a5fa", "#f59e0b", "#22c55e", "#e879f9", "#f87171", "#38bdf8"];
  const sig2 = (v) => (v == null || !isFinite(v) ? "—" : v === 0 ? "0" : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : String(+(+v).toPrecision(2)));
  const per = (m) => ({ minute: "/min", hour: "/h" })[(m && m.time_unit) || "minute"] || "/s";

  // the flows whose observed rate parts from their equation's over the same buckets (as the Model panel and Dynamics say)
  function misses(m, h) {
    if (!m || !h || !h.ok) return [];
    const levels = (id) => (h.stocks || {})[id] || (h.inputs || {})[id] || [];
    const levelAt = (id, t) => { let v = null; for (const [tt, x] of levels(id)) { if (tt > t) break; v = x; } return v; };
    return m.flows.filter((f) => !Evidence.tooFew(f) && (h.flows || {})[f.id]).map((f) => {
      const pts = h.flows[f.id], last = pts.slice(-4), minutes = last.length > 1 ? Math.max(0.5, (last[last.length - 1][0] - last[0][0]) / 60 * last.length / (last.length - 1)) : 2;
      const samplesIn = (a, b) => FlowCheck.reads(f).flatMap((id) => levels(id).map((p) => p[0]).filter((t) => t > a && t <= b));
      return { f, a: FlowCheck.against(f, pts, { step: h.flow_step || 30, levelAt, samplesIn, minutes }) }; }).filter((x) => x.a.differs);
  }
  const dur = (s) => (s < 90 ? "under 2 min" : s < 5400 ? `${Math.round(s / 60)} min` : s < 2 * 86400 ? `${+(s / 3600).toFixed(1)} h` : `${Math.round(s / 86400)} days`);

  // the machines' predictions: those waiting for their horizon, and the last three verdicts
  function predictions(ps, m, now, when) {
    const names = m ? { stock: (id) => SDGraph.stockName(m, id), flow: (id) => SDGraph.flowName(m, m.flows.find((f) => f.id === id)) || id } : {};
    const what = (p) => ((p.expect || []).length ? p.expect.map((e) => Predictions.expectText(e, names)).join(", ") : "nothing changes");
    const waiting = ps.filter((p) => p.status === "waiting").map((p) => `<div class="wline">${esc(p.source || "?")} predicted ${esc(what(p))}, ${p.judge_at != null
      ? (p.judge_at > now ? `judged in ${dur(p.judge_at - now)}` : "judged at the next look") : "waiting for its change to begin an era"}</div>`);
    const judged = ps.filter((p) => p.status === "judged" && p.verdict).sort((a, b) => (b.verdict.judged_at || 0) - (a.verdict.judged_at || 0)).slice(0, 3)
      .map((p) => `<div class="wline v-${esc((Predictions.CLASS[p.verdict.partial || p.verdict.verdict]) || "none")}">${esc(p.source || "?")} predicted ${esc(what(p))}: <b>${esc(p.verdict.verdict)}</b>${p.verdict.judged_at ? ` <span class="muted">(${esc(when(p.verdict.judged_at))})</span>` : ""}</div>`);
    if (!waiting.length && !judged.length) return '<div class="wline muted">No machine has made a prediction yet.</div>';
    return waiting.join("") + judged.join("");
  }

  // the panel's body: ``d`` = {model (or null), modelError, history, sim, preds, now, when, horizon}
  function render(d) {
    const m = d.model, when = d.when, out = [];
    // projected moves
    let proj;
    if (!m) proj = `<div class="wline muted">no model yet${d.modelError ? `: ${esc(d.modelError)}` : ""}</div>`;
    else {
      const blank = Projection.blank(m, d.sim);
      if (blank) proj = `<div class="wline muted">${esc(d.sim && !d.sim.ok ? `projection unavailable: ${d.sim.error || "the simulation did not run"}` : blank)}</div>`;
      else {
        const off = new Set(misses(m, d.history).map((x) => x.f.id));
        const mv = Projection.moves(m, d.sim, { names: { stock: (id) => SDGraph.stockName(m, id) }, when, differs: (f) => off.has(f.id), horizon: d.horizon });
        const top = mv.lines.slice(0, 3);
        proj = top.length ? top.map((l, i) => `<div class="wmove"><span class="wtext">${esc(l.text)}</span>${Projection.spark(((d.history || {}).stocks || {})[l.id], (d.sim.projection || {})[l.id], { color: PAL[i % PAL.length] })}</div>`).join("")
          : mv.holding.length ? `<div class="wline muted">Nothing moves within the next ${d.horizon} min if nothing changes.</div>` : "";
        const rest = mv.lines.length - top.length;
        if (rest > 0 || mv.none.length) proj += `<div class="wline muted">${rest > 0 ? `${rest} more move` : ""}${rest > 0 && mv.none.length ? "; " : ""}${mv.none.length ? `${top.length || mv.holding.length ? "no projection" : "No stock is projected"}: ${esc(Projection.noneText(mv.none))}` : ""} · <a href="/dynamics">Dynamics →</a></div>`;
      }
    }
    out.push(`<h4>Next ${esc(String(d.horizon))} min, if nothing changes</h4>${proj}`);
    // predictions
    out.push(`<h4>Predictions</h4>${d.preds == null ? '<div class="wline muted">not read: the server did not answer</div>' : d.preds.ok === false ? `<div class="wline muted">${esc(d.preds.error || "not read")}</div>` : predictions(d.preds.predictions || [], m, d.now, when)}`);
    // equation misses
    if (m) {
      const off = misses(m, d.history);
      out.push(`<h4>Equation misses</h4>${!d.history || !d.history.ok ? '<div class="wline muted">the rates are not read yet</div>'
        : off.length ? off.map(({ f, a }) => `<div class="wline miss">${esc(SDGraph.endName(m, f, "from"))} → ${esc(SDGraph.endName(m, f, "to"))} is not moving as its equation says <span class="muted">(equation ${sig2(a.eq)}${per(m)}, observed ${sig2(a.obs)}${per(m)})</span></div>`).join("")
        : '<div class="wline muted">Every fitted flow moves as its equation says.</div>'}`);
    }
    return out.join("");
  }
  return { render, misses, predictions };
})();

if (typeof Orchestra !== "undefined" && Orchestra.panels) Orchestra.panels.register({ id: "where", title: "Where this is going", size: { w: 7, h: 10 }, mount(body, ui) {
  const horizon = () => { try { return +localStorage.getItem("orchestra.dyn.horizon") || 30; } catch (e) { return 30; } };
  const get = async (url) => { try { return await (await fetch(url)).json(); } catch (e) { return null; } };
  async function refresh() {
    const h = horizon();
    const [md, history, preds] = await Promise.all([get("/api/dynamics/model"), get("/api/dynamics/history"), get("/api/dynamics/predictions")]);
    const m = md && md.model && (md.model.stocks || []).length ? md.model : null;
    // one simulate, only when there is something fitted to run
    const sim = m && Projection.fitted(m).length ? (await get(`/api/dynamics/simulate?horizon_min=${h}`)) || { ok: false, error: "the server did not answer" } : null;
    try {
      body.innerHTML = WherePanel.render({ model: m, modelError: md ? (md.reason && md.reason.headline) || null : "the server did not answer", history, sim, preds, now: Date.now() / 1000, when: (t) => Orchestra.when(t), horizon: h });
      ui.setSub(m ? (sim && sim.ok ? `the model's projection, next ${h} min` : "projection unavailable") : "no model yet");
    } catch (e) { body.innerHTML = `<div class="wline muted">projection unavailable: ${String(e)}</div>`; }
  }
  refresh(); setInterval(refresh, 30000);
} });
if (typeof module !== "undefined") module.exports = WherePanel;
