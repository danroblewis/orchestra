// The model's projection (/api/dynamics/simulate: sd/simulate.py, sd/projection.py) as the pages say
// it: the Dynamics page's stocks chart (its band, its line ends), its projections strip and flows
// table, and the Dashboard's "Where this is going". Pure: every function takes what it reads and
// returns data or HTML, so the Node tests run it on a saved simulate response.
//
// A stock is projected unless the server said why not (``no_projection``: "no level measured",
// "worse than holding") or the page finds its equations wrong now: a flow that fills or drains it,
// stepped from its equation, not moving as the equation says (flow-check.js, judged by the caller:
// ``differs(f)``). Each "no projection" is said with its reason.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Projection = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  // a projected level, said as a person would: "7", "2.5", "0.3"
  const level = (v) => (v == null || !isFinite(v) ? "—" : Math.abs(v) >= 10 ? Math.round(v).toLocaleString() : String(+(+v).toFixed(1)));
  const dur = (s) => (s >= 5400 ? `${+(s / 3600).toFixed(1)} h` : `${Math.max(1, Math.round(s / 60))} min`);
  const tooFew = (f) => !!(f && f.current && f.current.origin === "fitted" && (((f.current.quality || {}).events) ?? 0) < 5);
  // flows with an equation fitted from enough events: without one, nothing is projected from an equation
  const fitted = (m) => ((m && m.flows) || []).filter((f) => f.current && ["fitted", "discovered"].includes(f.current.origin) && !tooFew(f));
  const stepped = (sim, f) => !tooFew(f) && !(sim.replayed || []).includes(f.id) && !(sim.too_few || []).includes(f.id);

  // the flows of a stock not moving as their equations say (only those stepped from an equation)
  function wrong(m, sim, id, differs) {
    return ((m && m.flows) || []).filter((f) => (f.from === id || f.to === id) && stepped(sim, f) && differs(f));
  }
  // why a stock has no projection, in a few words, or null
  function reason(m, sim, id, differs) {
    const s = ((sim && sim.stocks) || {})[id];
    if (!s) return "not simulated";
    if (s.no_projection) return s.no_projection;
    if (differs && wrong(m, sim, id, differs).length) return "equations wrong now";
    return null;
  }
  // a flow's projected count over the horizon, or null where there is none: replayed, too few
  // events, or not moving as its equation says now
  function count(sim, f, differs) {
    const c = ((sim && sim.flows) || {})[f.id];
    if (!c || c.replayed || !stepped(sim, f) || (differs && differs(f))) return null;
    return c.count;
  }
  // the band, split where the held-out runs stop: [tested, beyond] as Charts' [[t, lo, hi]]
  function bands(s) {
    const b = (s && s.band) || [], cut = s && s.tested_until;
    if (!b.length || cut == null) return [b, []];
    return [b.filter((r) => r[0] <= cut), b.filter((r) => r[0] >= cut)];
  }
  const trustText = (s) => (s.trust ? `trusted ${dur(s.trust.trusted_s)}` : "trust not measured");
  // a declared expectation on the stock (the intended model's target), and where the run crosses it
  function target(m, id) {
    const t = (((m || {}).intended || {}).targets || []).find((x) => x.part !== "flow" && x.id === id);
    return t && t.target && t.target.value != null ? t.target : null;
  }
  const meets = (t, v) => (t.op === "below" ? v < t.value : t.op === "above" ? v > t.value : v >= t.value && v <= (t.hi ?? t.value));
  const targetText = (t) => (t.op === "within" ? `within ${level(t.value)}–${level(t.hi)}` : `${t.op} ${level(t.value)}`);
  function crossing(t, pts) {
    if (!t || !pts.length) return null;
    const first = meets(t, pts[0][1]), p = pts.find(([, v]) => meets(t, v) !== first);
    return p ? { t: p[0], leaves: first } : null;
  }

  // every projected stock, said: the ones that move (an emptying or a crossing first, then by how
  // far they move), the ones that hold, and the ones with no projection and why.
  // ``o``: {names: {stock(id)}, when(t), differs(f), horizon (min)}
  function moves(m, sim, o) {
    const out = { lines: [], holding: [], none: [] };
    for (const st of (m && m.stocks) || []) {
      const id = st.id, why = reason(m, sim, id, o.differs), name = o.names.stock(id);
      if (why) { out.none.push({ id, name, why }); continue; }
      const s = sim.stocks[id], pts = (sim.projection || {})[id] || [];
      if (!pts.length) { out.none.push({ id, name, why: "not simulated" }); continue; }
      const a = s.start, b = s.end, far = Math.max(...pts.map(([, v]) => Math.abs(v - a)));
      const t = target(m, id), x = crossing(t, pts);
      const empties = s.empties_at != null;
      const moved = far >= Math.max(0.5, 0.05 * Math.max(Math.abs(a), Math.abs(b)));
      if (!moved && !empties && !x) { out.holding.push({ id, name }); continue; }
      const by = o.when(sim.now + (sim.horizon || o.horizon * 60));
      const run = `${level(a)} → ${level(b)} by ${by} if nothing changes (${trustText(s)})`;
      const first = empties ? `${name} empties by ${o.when(s.empties_at)}` : x ? `${name} ${x.leaves ? "leaves" : "reaches"} its expected level (${targetText(t)}) at ${o.when(x.t)}` : "";
      out.lines.push({ id, flagged: empties ? 2 : x ? 1 : 0, size: far / Math.max(1, Math.abs(a)), text: first ? `${first}: ${run}` : `${name}: ${run}` });
    }
    out.lines.sort((p, q) => (q.flagged - p.flagged) || q.size - p.size);
    return out;
  }
  // why nothing is projected at all, or null
  function blank(m, sim) {
    if (!m || !(m.stocks || []).length) return "No projection: there is no model yet.";
    if (!fitted(m).length) return "No projection: the model has no fitted flows yet, so its equations say nothing of what comes next.";
    if (!sim) return "Running the equations…";
    if (!sim.ok) return `No projection: ${sim.error || "the simulation did not run"}.`;
    return null;
  }
  // the Dynamics page's strip: one line per stock that moves (at most ``max``), then what holds,
  // then what has no projection and why
  function strip(m, sim, o, max = 6) {
    const none = blank(m, sim);
    if (none) return `<div class="pline muted">${esc(none)}</div>`;
    const mv = moves(m, sim, o), shown = mv.lines.slice(0, max), more = mv.lines.length - shown.length;
    const rest = [more ? `${more} more that move` : "", mv.holding.length ? `${mv.holding.length} ${more ? "" : "more "}that hold${mv.holding.length === 1 ? "s" : ""}` : ""].filter(Boolean);
    return (shown.length ? shown.map((l) => `<div class="pline${l.flagged ? " flag" : ""}" data-sid="${esc(l.id)}">${esc(l.text)}</div>`).join("")
      : mv.holding.length ? `<div class="pline muted">Nothing moves within the next ${dur(sim.horizon || o.horizon * 60)} if nothing changes.</div>` : "")
      + (rest.length && shown.length ? `<div class="pline muted">and ${rest.join(", ")}</div>` : "")
      + (mv.none.length ? `<div class="pline muted">${shown.length || mv.holding.length ? "no projection" : "No stock is projected"}: ${esc(noneText(mv.none))}</div>` : "");
  }
  // the stocks with no projection, grouped by why: "in change, in review (worse than holding); in sail (no level measured)"
  function noneText(none) {
    const by = new Map(); for (const n of none) by.set(n.why, [...(by.get(n.why) || []), n.name]);
    return [...by.entries()].map(([why, ns]) => `${ns.join(", ")} (${why})`).join("; ");
  }
  // a sparkline of a stock's history and its projection, dashed after now (inline SVG, no axes)
  function spark(hist, proj, { w = 120, h = 26, color = "#60a5fa" } = {}) {
    const pts = [...(hist || []), ...(proj || [])];
    if (pts.length < 2) return "";
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0], vs = pts.map((p) => p[1]), lo = Math.min(...vs), hi = Math.max(...vs);
    const x = (t) => (w * (t - t0) / Math.max(1, t1 - t0)).toFixed(1), y = (v) => (h - 2 - (h - 4) * (v - lo) / (hi - lo || 1)).toFixed(1);
    const d = (ps) => ps.map(([t, v], i) => `${i ? "L" : "M"}${x(t)},${y(v)}`).join(" ");
    return `<svg class="pspark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" preserveAspectRatio="none" aria-hidden="true">${(hist || []).length > 1 ? `<path d="${d(hist)}" fill="none" stroke="${color}" stroke-width="1.4"/>` : ""}${(proj || []).length > 1 ? `<path d="${d(proj)}" fill="none" stroke="${color}" stroke-width="1.4" stroke-dasharray="3 2" opacity=".85"/>` : ""}</svg>`;
  }
  return { noneText, reason, wrong, count, bands, moves, strip, blank, spark, fitted, level, dur, trustText };
});
