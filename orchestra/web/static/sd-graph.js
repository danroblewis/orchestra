// The model as a graph to draw: pure functions of the model, used by the Dynamics page and by the
// layout tests (tests/layout), so what is tested is what is drawn.
//
// Stocks are boxes, each flow is one arrow from its source to its destination (a cloud when either
// is outside), influences are dashed links from what a rate reads to the middle of its flow, and
// measured levels a rate reads that no counters balance are auxiliaries (round boxes). Feedback
// loops are cycles of the causal graph: a flow adds to its destination (+) and takes from its
// source (−); a rate depends on what it reads with the sign of its coefficient.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SDGraph = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const nice = (s) => (s || "outside").toLowerCase().replace(/_/g, " ");
  const num = (v, short) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(short ? 2 : 3));
  const stockName = (m, id) => { const s = m && m.stocks.find((x) => x.id === id); return s ? s.name : nice(id); };
  // what an equation reads, by name: a stock, or a measured input (input:<name>)
  const readName = (m, x) => { if (!x) return "?"; const n = x.startsWith("input:") ? x.slice(6) : x;
    return m && m.stocks.some((s) => s.id === n) ? stockName(m, n) : n.replace(/_/g, " "); };
  const refOf = (m, x) => (m && m.stocks.some((s) => s.id === x) ? x : "input:" + x);

  function eqText(m, f, short) {
    const e = f.current; if (!e) return "no equation yet";
    const unit = (m && m.time_unit) || "hour", per = `/${unit === "minute" ? "min" : unit === "hour" ? "h" : "s"}`;
    const sp = e.spec && e.spec.form ? e.spec : null, p = e.params;
    if (sp) {                                   // SD Lab's rate, in full
      const fx = (sp.effects || []).map((ef) => ` × f(${readName(m, ef.stock)})`).join("");
      const t = { constant: () => num(sp.value, short),
        proportional: () => `${num(sp.k, short)} × ${readName(m, sp.stock)}`,
        linear: () => [num(sp.c || 0, short), ...(sp.terms || []).map((t) => `${t.k < 0 ? "−" : "+"} ${num(Math.abs(t.k), short)} × ${readName(m, t.stock)}`)].join(" "),
        gap: () => `(${num(sp.goal, short)} − ${readName(m, sp.stock)}) / ${num(sp.time, short)}`,
        available: () => `all of ${f.from ? stockName(m, f.from) : "it"}`,
        expr: () => sp.expr }[sp.form];
      return (t ? t() : sp.form) + fx + (sp.form === "expr" ? "" : " " + per);
    }
    const x = (e.inputs && e.inputs[0]) || f.from;
    if (e.form === "constant") return `${num(p.c, short)} ${per}`;
    if (e.form === "proportional") return `${num(p.k, short)} × ${readName(m, x)} ${per}`;
    if (e.form === "linear") return `${num(p.c, short)} ${p.k < 0 ? "−" : "+"} ${num(Math.abs(p.k), short)} × ${readName(m, x)} ${per}`;
    return JSON.stringify(p);
  }

  // the sign of each thing a rate reads: + more of it, more flow; − more of it, less flow; ~ unknown
  function readsWithSign(m, f) {
    const e = f.current; if (!e) return [];
    const sp = e.spec && e.spec.form ? e.spec : null, out = [];
    if (sp) {
      if (sp.form === "proportional" && sp.stock) out.push([refOf(m, sp.stock), 1]);
      if (sp.form === "gap" && sp.stock) out.push([refOf(m, sp.stock), -1]);
      for (const t of sp.terms || []) out.push([refOf(m, t.stock), Math.sign(t.k) || 1]);
      for (const ef of sp.effects || []) out.push([refOf(m, ef.stock), 0]);
      return out;
    }
    const x = e.inputs && e.inputs[0];
    if (x && e.form === "proportional") out.push([x, 1]);
    if (x && e.form === "linear") out.push([x, Math.sign(e.params.k) || 1]);
    return out;
  }

  const shorten = (t, n = 44) => (t.length > n ? t.slice(0, n - 2) + "…" : t);

  // the graph: {nodes, edges, causal, flowEdge, flows, acc}. ``opts``: showAll (flows with no
  // events), showAcc (stocks that only fill), and the colours (mcolor(machine), stockColor(id)).
  function build(m, opts = {}) {
    const mcolor = opts.mcolor || (() => "#94a3b8"), stockColor = opts.stockColor || (() => "#cbd5e1");
    const byMachine = Object.fromEntries((m.machines || []).map((x) => [x.id, x]));
    // stocks that only fill (like the event bus's length) start hidden, with their flows
    const acc = new Set(m.stocks.filter((s) => s.evidence && s.evidence.accumulator).map((s) => s.id));
    const hiddenStock = (id) => !opts.showAcc && acc.has(id);
    const flows = m.flows.filter((f) => ((f.current && f.current.quality && f.current.quality.events > 0) || opts.showAll)
      && !hiddenStock(f.from) && !hiddenStock(f.to));
    const nodes = [], edges = [], causal = [], flowEdge = {};
    const has = (id) => nodes.some((n) => n.id === id);
    for (const s of m.stocks.filter((s) => !hiddenStock(s.id))) nodes.push({ id: "s:" + s.id, kind: "box", sid: s.id, label: s.name, lines: [s.name],
      w: Math.max(180, s.name.length * 7 + 30), h: 92, dashed: !!(s.evidence && s.evidence.hidden), color: stockColor(s.id),
      fill: "#0b0e14", charge: -1600, sub: " " });
    for (const f of flows) {
      // in the causal graph used for loops, a flow is a node between its ends ("f:<id>")
      const col = mcolor(f.machine), v = "f:" + f.id, e = f.current || {};
      // one cloud per stock and direction, named for the stock (flow ids change between discoveries;
      // a stock's place outside does not); it sits just outside the frame by its stock (tethered)
      const src = f.from ? "s:" + f.from : "c:in:" + (f.to || f.id), dst = f.to ? "s:" + f.to : "c:out:" + (f.from || f.id);
      if (!f.from && f.to && !has(src)) nodes.push({ id: src, kind: "cloud", charge: -20, tether: "s:" + f.to });
      if (!f.to && f.from && !has(dst)) nodes.push({ id: dst, kind: "cloud", charge: -20, tether: "s:" + f.from });
      const fe = `${src}>${dst}:${f.id}`, outside = !f.from || !f.to;
      edges.push({ id: fe, source: src, target: dst, color: col, width: outside ? 2 : 3.4, distance: outside ? 60 : 230, strength: outside ? 0.05 : 0.6,
        cls: outside ? "ng-outside" : "", fid: f.id, flowPart: true, bend: outside ? 10 : 18,
        label: [shorten(eqText(m, f, true)), f.machine ? (byMachine[f.machine] || {}).name || f.machine : ""] });
      flowEdge[v] = fe;
      if (f.to) causal.push({ source: v, target: "s:" + f.to, sign: 1 });
      if (f.from) causal.push({ source: v, target: "s:" + f.from, sign: -1 });
      for (const [x, sign] of readsWithSign(m, f)) {
        const isInput = x.startsWith("input:"), name = isInput ? x.slice(6) : x, node = (isInput ? "i:" : "s:") + name;
        if (!isInput && hiddenStock(name)) continue;
        // a measured level the rate reads that no counters balance: an auxiliary, inside the system
        // like everything but the clouds, drawn round so it does not read as a stock
        if (isInput && !has(node)) nodes.push({ id: node, kind: "box", input: name, label: name.replace(/_/g, " "), lines: [name.replace(/_/g, " ")],
          w: Math.max(140, name.length * 6.2 + 30), h: 52, rx: 26, color: "#64748b", fill: "#0e1118", charge: -600, sub: " " });
        if (sign !== 0) causal.push({ source: node, target: v, sign });
        // an influence: a dashed link to the middle of the flow it drives (not a flow's plain dependence on its own source)
        const plain = !isInput && name === f.from && (e.form === "proportional" || (e.spec && e.spec.form === "proportional"));
        if (!plain && has(node)) edges.push({ id: `${node}>${fe}:info`, source: node, toEdge: fe, color: col, dashed: true, width: 1.4,
          sign: sign < 0 ? "−" : sign > 0 ? "+" : "~", bend: 36, fid: f.id });
      }
    }
    // stocks with flows from or to outside are drawn toward the frame's edge, so those stubs stay short
    for (const n of nodes) if (n.sid) n.edgeward = flows.some((f) => (f.to === n.sid && !f.from) || (f.from === n.sid && !f.to));
    return { nodes, edges, causal, flowEdge, flows, acc };
  }

  return { build, eqText, readsWithSign, readName, refOf, stockName, nice, num };
});
