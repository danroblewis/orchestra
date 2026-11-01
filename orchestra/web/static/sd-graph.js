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
  // What to call each stock and flow. A series' name says what kind of thing it counts ("beads
  // issues"); its labels say which ones ("status: in_progress"). So a stock is named by the label
  // values that tell it apart from the other stocks of the same series, with the series' name as
  // its family, said apart (a caption): "in progress", family "beads issues".
  // - only labels whose values differ within the family are said; the one with the most values
  //   first and always, the others only where they are not the family's usual value ("open" and
  //   "open · cake" beside "closed", not "open · loaf");
  // - a series alone in its family is named by the series;
  // - a series alone in its family whose first word other stocks' series share (a namespace, by
  //   Prometheus' convention: bakery_orders_baking, bakery_shelf_items) has that word as its family;
  // - a flow is named by its counter: its series' name, then who moved what from where to where
  //   ("queue item moves · packer: WAITING → PACKING"), a lone end with its key ("from
  //   REJECTED"), and any other label that tells the family's flows apart, with its key ("status
  //   landed"). A counter several flows share says so ("one counter, 2 flows"); a flow whose events
  //   another counter also counts (evidence.same_as) says so beside its name (sameAs), not in it;
  // - a stock named by a label that also names the stocks of another series (pods by region, for
  //   two services) says its machine too ("search · eu-west"), so two services' regions never
  //   look alike. A remote machine's source prefix is left out (rig.search: "search").
  // Names are {name, family}; ``label`` is the name, with the family only where the name alone is
  // not unique in the model. The model's own ``name`` stays the full record.
  const IGNORE = new Set(["project", "machine", "instrument", "instance", "source"]);
  const words = (v) => String(v).replace(/_/g, " ");
  const seriesOf = (x) => x.series || x.counter || (x.measured_by && x.measured_by[0]) || null;
  const familyName = (n) => words(n.replace(/_total$/, ""));
  // a machine as a stock's name says it: without its source's prefix when the series has it
  const machineWord = (s) => { const mc = (s.labels || {}).machine; if (!mc) return null;
    const pre = s.name.includes(":") ? s.name.split(":")[0] + "." : null;
    return words(pre && mc.startsWith(pre) ? mc.slice(pre.length) : mc); };
  function nameFamily(items, drop = null) {
    const out = {}, fams = new Map(), said_by = {};
    for (const x of items) { const s = seriesOf(x); if (!s) continue; const k = s.name; fams.set(k, [...(fams.get(k) || []), x]); }
    for (const [fname, xs] of fams) {
      const labels = (x) => Object.fromEntries(Object.entries(seriesOf(x).labels || {}).filter(([k]) => !IGNORE.has(k)));
      const keys = [...new Set(xs.flatMap((x) => Object.keys(labels(x))))].map((k) => {
        const counts = new Map(); for (const x of xs) { const v = labels(x)[k] ?? ""; counts.set(v, (counts.get(v) || 0) + 1); }
        const top = [...counts.entries()].sort((a, b) => b[1] - a[1]);
        return { k, n: counts.size, usual: top.length > 1 && top[0][1] > top[1][1] ? top[0][0] : null };
      }).filter((c) => c.n > 1).sort((a, b) => b.n - a.n || a.k.localeCompare(b.k));
      const said = (x, all) => { const l = labels(x), gone = drop ? drop(x) : new Set();
        return keys.filter((c, i) => l[c.k] != null && !gone.has(l[c.k]) && (all || drop || i === 0 || l[c.k] !== c.usual)).map((c) => words(l[c.k])); };
      const fam = familyName(fname);
      let names = xs.map((x) => said(x, false).join(" · "));
      // leaving a usual value out must never make two names the same
      names = names.map((nm, i) => (names.filter((o) => o === nm).length > 1 ? said(xs[i], true).join(" · ") : nm));
      // a series alone in its family keeps the qualifier the model's own name gives it, when that is
      // all that narrows it ("orders open (web)": the one series of a family several machines write)
      const qualified = (x) => (!drop && typeof x.name === "string" && x.name.startsWith(fam + " (") && x.name.endsWith(")") ? x.name : fam);
      xs.forEach((x, i) => { out[x.id] = drop ? { name: fam + (names[i] ? " · " + names[i] : ""), family: "" }
        : names[i] ? { name: names[i], family: fam } : { name: qualified(x), family: "" };
        if (names[i]) said_by[x.id] = { fam: fname, keys: keys.map((c) => c.k), machine: machineWord(seriesOf(x)) }; });
    }
    if (!drop) {                        // a label that names the stocks of several series: say whose
      const famsOf = new Map();
      for (const v of Object.values(said_by)) for (const k of v.keys) famsOf.set(k, new Set([...(famsOf.get(k) || []), v.fam]));
      for (const [id, v] of Object.entries(said_by)) {
        if (v.machine && v.keys.some((k) => famsOf.get(k).size > 1) && !out[id].name.split(" · ").includes(v.machine)) out[id].name = `${v.machine} · ${out[id].name}`;
      }
    }
    // what no series measures: a stock by its own name; a flow is a balance's remainder, named by
    // what it does (its ends are always shown beside it)
    for (const x of items) if (!out[x.id]) out[x.id] = drop ? { name: `unmeasured ${x.from && x.to ? "flow" : x.from ? "outflow" : "inflow"}`, family: "" } : { name: x.name || nice(x.id), family: "" };
    if (!drop) {
      const first = (n) => n.split(" ")[0], alone = Object.values(out).filter((v) => !v.family && v.name.includes(" "));
      const shared = alone.map((v) => alone.filter((o) => first(o.name) === first(v.name)).length > 1);
      alone.forEach((v, i) => { if (shared[i]) { v.family = first(v.name); v.name = v.name.slice(v.family.length + 1); } });
    }
    return out;
  }
  const MOVE = new Set(["by", "from", "to"]);
  const labelsOf = (r) => Object.fromEntries(Object.entries((r && r.labels) || {}).filter(([k]) => !IGNORE.has(k)));
  // what a counter says of the move it counts: "worker: OPEN → IN PROGRESS", "from REJECTED", "planner"
  function moveText(l) {
    const move = l.from != null && l.to != null ? `${words(l.from)} → ${words(l.to)}` : l.from != null ? `from ${words(l.from)}` : l.to != null ? `to ${words(l.to)}` : "";
    const by = l.by != null ? words(l.by) : "";
    return by && move ? `${by}: ${move}` : by || move;
  }
  const refKey = (r) => r.name + JSON.stringify(Object.entries(labelsOf(r)).sort());
  function flowNames(fs) {
    const out = {}, fams = new Map(), byKey = new Map();
    for (const f of fs) { const c = seriesOf(f); if (!c) continue; fams.set(c.name, [...(fams.get(c.name) || []), f]); byKey.set(refKey(c), [...(byKey.get(refKey(c)) || []), f.id]); }
    for (const [fname, xs] of fams) {
      // the other labels that tell this family's flows apart, said with their key
      // (a family of one counter says every other label it has: "deploy runs · status landed")
      const one = new Set(xs.map((f) => refKey(seriesOf(f)))).size === 1;
      const differ = [...new Set(xs.flatMap((f) => Object.keys(labelsOf(seriesOf(f)))))].filter((k) => !MOVE.has(k) && (one || new Set(xs.map((f) => labelsOf(seriesOf(f))[k] ?? "")).size > 1)).sort();
      for (const f of xs) {
        const l = labelsOf(seriesOf(f)), parts = [moveText(l), ...differ.filter((k) => l[k] != null).map((k) => `${words(k)} ${words(l[k])}`)].filter(Boolean);
        const shared = byKey.get(refKey(seriesOf(f))).length;
        out[f.id] = { name: familyName(fname) + (parts.length ? " · " + parts.join(", ") : "") + (shared > 1 ? ` (one counter, ${shared} flows)` : ""), family: "" };
      }
    }
    for (const f of fs) if (!out[f.id]) out[f.id] = { name: `unmeasured ${f.from && f.to ? "flow" : f.from ? "outflow" : "inflow"}`, family: "" };
    return out;
  }
  // the other counters that count a flow's events (evidence.same_as), named as flows are: "same events as …"
  function sameAs(m, f) {
    const same = (f && f.evidence && f.evidence.same_as) || [];
    return same.map((r) => { const g = (m.flows || []).find((x) => x !== f && seriesOf(x) && refKey(seriesOf(x)) === refKey(r));
      return g ? flowName(m, g) : familyName(r.name) + (moveText(labelsOf(r)) ? " · " + moveText(labelsOf(r)) : ""); });
  }
  const NAMES = new WeakMap();
  function names(m) {
    if (!m) return { stocks: {}, flows: {} };
    if (NAMES.has(m)) return NAMES.get(m);
    const stocks = nameFamily(m.stocks || []);
    const flows = flowNames(m.flows || []);
    for (const group of [stocks, flows]) {
      const seen = new Map(); for (const v of Object.values(group)) seen.set(v.name, (seen.get(v.name) || 0) + 1);
      for (const v of Object.values(group)) v.label = v.family && seen.get(v.name) > 1 ? `${v.name} · ${v.family}` : v.name;
    }
    const out = { stocks, flows }; NAMES.set(m, out); return out;
  }
  const stockName = (m, id) => { const n = names(m).stocks[id]; return n ? n.label : nice(id); };
  const flowName = (m, f) => { if (!f) return null; const n = names(m).flows[f.id]; return n ? n.label : f.name; };
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

  // a flow into or out of a stock no counters balance, whose rate reads another series: its driver
  // was found by fitting the level's changes, a correlation that no experiment has tested
  const UNTESTED = "fitted from correlation; untested: no experiment has moved its driver";
  function correlational(m, f) {
    const e = f && f.current; if (!e || !(e.inputs || []).some((x) => x !== f.from && x !== f.to)) return false;
    const net = (id) => id && m.stocks.some((s) => s.id === id && s.evidence && s.evidence.net_flow);
    return !!((f.evidence && f.evidence.net_flow_of) || net(f.from) || net(f.to));
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
  // the machines a flow's label names: its hypotheses tied with the top confidence (within TIE), each
  // with a question mark; one leader "planner 94%?", a tie "reviewer / merge_gate?", more than two
  // "3 machines?"; none, or none with a confidence, no label. Never one name as a fact.
  const TIE = 0.02;
  function machineLabel(f, nameOf = (id) => id) {
    const hs = (f.machines || []).filter((h) => h.machine && h.confidence != null);
    if (!hs.length) return "";
    const top = Math.max(...hs.map((h) => h.confidence)), lead = hs.filter((h) => top - h.confidence <= TIE);
    if (lead.length === 1) return `${nameOf(lead[0].machine)} ${Math.round(100 * lead[0].confidence)}%?`;
    return lead.length > 2 ? `${lead.length} machines?` : `${lead.map((h) => nameOf(h.machine)).join(" / ")}?`;
  }

  // the graph: {nodes, edges, causal, flowEdge, flows, acc}. ``opts``: showAll (flows with no
  // events), showAcc (stocks that only fill that nothing shown feeds), keep (stock ids never hidden),
  // keepFlows (flow ids drawn with no events), and the colours
  // (mcolor(machine), stockColor(id)).
  function build(m, opts = {}) {
    const mcolor = opts.mcolor || (() => "#94a3b8"), stockColor = opts.stockColor || (() => "#cbd5e1");
    const byMachine = Object.fromEntries((m.machines || []).map((x) => [x.id, x]));
    // ``keepFlows``: flow ids drawn whatever their events (expected ones: an expectation stays on the diagram)
    const shown = (f) => (f.current && f.current.quality && f.current.quality.events > 0) || opts.showAll || !!(opts.keepFlows && opts.keepFlows.has(f.id));
    // a stock that only fills is where another stock's material ends up (the orders delivered) when a
    // flow shown drains a stock into it: drawn. One that no such flow feeds (the event bus's
    // length, a tally) starts hidden, with its flows; ``acc`` is those.
    const filling = new Set(m.stocks.filter((s) => s.evidence && s.evidence.accumulator).map((s) => s.id));
    const fed = new Set(m.flows.filter((f) => shown(f) && f.from && filling.has(f.to) && !filling.has(f.from)).map((f) => f.to));
    // ``keep``: stocks never hidden (one a declared part is placed beside)
    const acc = new Set([...filling].filter((id) => !fed.has(id) && !(opts.keep && opts.keep.has(id))));
    const hiddenStock = (id) => !opts.showAcc && acc.has(id);
    const flows = m.flows.filter((f) => shown(f) && !hiddenStock(f.from) && !hiddenStock(f.to));
    const nodes = [], edges = [], causal = [], flowEdge = {};
    const has = (id) => nodes.some((n) => n.id === id);
    const nm = names(m).stocks;
    for (const s of m.stocks.filter((s) => !hiddenStock(s.id))) { const { name, family } = nm[s.id] || { name: s.name, family: "" };
      nodes.push({ id: "s:" + s.id, kind: "box", sid: s.id, label: name, lines: [name], caption: family,
      // sized by the full name, as before the short names: the layout search is sensitive to box
      // sizes (narrower boxes break the layout tests' fixtures), which is its own open problem
      w: Math.max(180, s.name.length * 7 + 30), h: 92, dashed: !!(s.evidence && s.evidence.hidden), color: stockColor(s.id),
      fill: "#0b0e14", charge: -1600, sub: " " }); }
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
        cls: outside ? "ng-outside" : "", fid: f.id, flowPart: true, bend: outside ? 10 : 18, labelMuted: true,
        label: [shorten(eqText(m, f, true)), machineLabel(f, (id) => (byMachine[id] || {}).name || id)] });
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

  return { build, eqText, readsWithSign, readName, refOf, stockName, flowName, names, sameAs, nice, num, correlational, machineLabel, UNTESTED };
});
