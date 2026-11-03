// A partition a page extension offers (docs/proposals/subsystems.md B15): a plugin that knows how
// the system divides where no label says it (the Workflows plugin: one group per definition, the
// machines its definitions name) offers it as it offers a focus, and both pages list it after the
// partitions the API reports, under the boxes control. Display only: it is kept in the page's memory
// while the extension offers it, and stored nowhere (no request, no browser storage, no version).
//
//   Orchestra.subsystems.offer({title, groups: [{title, machines, events, stocks, flows}]})
//   Orchestra.subsystems.withdraw(title)
//   Orchestra.subsystems.offers()          -> the offers, as given (normalised)
//
// Each group is a focus subset in the same keys (focus.js): machines by id (or the name a machine is
// shown by), event types, stocks and flows by the series they are bound to (``{name, labels}``, keyed
// by ``Focus.keyOf``), that key already made, or an id. The pages turn an offer into a partition of
// the API's shape by the API's rules (sd/subsystems.py, web/machine_subsystems.py): the stocks named
// are in their group, a flow by its ends unless a group names it, a machine by its hypotheses unless
// a group names it (one named by two groups is outside every box); on the event map, an event type
// is inside a box when every machine on it is, and a hand-off between two boxes crosses. The core
// knows no offer's meaning (AGENTS.md rule 1).
(function (root, factory) {
  const S = factory(typeof module === "object" && module.exports ? require("./focus.js") : root.Focus);
  if (typeof module === "object" && module.exports) module.exports = S;
  else { root.SubsystemOffers = S; if (root.Orchestra) S.install(root.Orchestra); }
})(typeof self !== "undefined" ? self : this, function (Focus) {
  const strs = (x) => (Array.isArray(x) ? x : x == null ? [] : [x]).map((v) => (v && typeof v === "object" && v.name ? Focus.keyOf(v) : String(v)));
  // an offer as given, normalised: a title and its groups, every field a list of strings; null if unusable
  function normal(o) {
    if (!o || !o.title || !Array.isArray(o.groups)) return null;
    const groups = o.groups.filter((g) => g && g.title != null).map((g) => ({ title: String(g.title), machines: strs(g.machines), events: strs(g.events), stocks: strs(g.stocks), flows: strs(g.flows) }));
    return groups.length ? { title: String(o.title), groups } : null;
  }
  // a value -> group map from a list per group; a key named by two groups is in neither (spanning)
  function assign(groups, field, match) {
    const where = new Map(), span = new Map();
    for (const g of groups) for (const x of match(g[field])) { if (span.has(x)) span.get(x).push(g.title); else if (where.has(x) && where.get(x) !== g.title) { span.set(x, [where.get(x), g.title]); where.delete(x); } else where.set(x, g.title); }
    return { where, span };
  }
  const empty = (o) => ({ label: o.title, source: "offered", groups: o.groups.map((g) => ({ value: g.title })), crossed_simulated: 0 });

  // The Dynamics diagram's partition from an offer (sd/subsystems.py's rules), over ``model`` (as
  // /api/dynamics/model gives it).
  function dynamics(o, model) {
    const out = empty(o), stocks = (model && model.stocks) || [], flows = (model && model.flows) || [], machines = (model && model.machines) || [];
    const ids = (keys, list, ref) => { const k = new Set(keys); return list.filter((x) => k.has(x.id) || (ref(x) && k.has(Focus.keyOf(ref(x))))).map((x) => x.id); };
    const sg = assign(o.groups, "stocks", (keys) => ids(keys, stocks, (s) => s.series)).where;
    const fg = assign(o.groups, "flows", (keys) => ids(keys, flows, (f) => f.counter)).where;
    const mg = assign(o.groups, "machines", (keys) => keys);
    const G = new Map(out.groups.map((g) => [g.value, Object.assign(g, { stocks: [], flows: [], machines: [] })]));
    const un = { stocks: [], flows: [], machines: [] }, crossing = new Map(), flowGroups = new Map();
    let joined = 0;
    for (const s of stocks) (sg.has(s.id) ? G.get(sg.get(s.id)).stocks : un.stocks).push(s.id);
    for (const f of flows) {
      const ends = [f.from, f.to].map((e) => (e == null ? null : sg.get(e) ?? "")), sim = !!(f.evidence || {}).simulated;
      let inner = new Set(ends.filter(Boolean));
      if (fg.has(f.id)) inner = new Set([fg.get(f.id)]);
      if (!fg.has(f.id) && ends.includes("")) { un.flows.push(f.id); flowGroups.set(f.id, inner); }
      else if (inner.size === 1) { const g = [...inner][0]; G.get(g).flows.push(f.id); flowGroups.set(f.id, inner); if (!ends.includes(null) && !sim) joined++; }
      else if (!inner.size) { un.flows.push(f.id); flowGroups.set(f.id, inner); }
      else { const pair = [...inner].sort(), k = pair.join("|"), c = crossing.get(k) || { between: pair, flows: [], count: 0, simulated: 0, simulated_flows: [] };
        c.flows.push(f.id); if (sim) { c.simulated++; c.simulated_flows.push(f.id); } else c.count++; crossing.set(k, c); flowGroups.set(f.id, inner); }
    }
    const spanning = [];
    const hyps = (fid) => ((flows.find((f) => f.id === fid) || {}).machines || []).map((h) => h.machine);
    for (const m of machines) {
      const named = mg.where.get(m.id) ?? mg.where.get(m.name), twice = mg.span.get(m.id) || mg.span.get(m.name);
      const gs = twice ? twice : named != null ? [named] : [...new Set([...flowGroups].filter(([fid]) => hyps(fid).includes(m.id)).flatMap(([, g]) => [...g]))].sort();
      if (gs.length === 1) G.get(gs[0]).machines.push(m.id); else if (gs.length) spanning.push({ machine: m.id, groups: gs }); else un.machines.push(m.id);
    }
    const cross = [...crossing.values()].sort((a, b) => b.count - a.count || a.between.join().localeCompare(b.between.join()));
    return { ...out, unassigned: un, crossing: cross, spanning, joined, crossed: cross.reduce((a, c) => a + c.count, 0), crossed_simulated: cross.reduce((a, c) => a + c.simulated, 0) };
  }

  const hears = (p, t) => p === t || p === "*" || (p.endsWith(".*") && t.startsWith(p.slice(0, -1)));
  // The Machines page's partition from an offer (web/machine_subsystems.py's rules), over ``d`` (as
  // /api/machines gives it).
  function eventMap(o, d) {
    const out = empty(o), ms = (d && d.machines) || [];
    const mg = assign(o.groups, "machines", (keys) => { const k = new Set(keys); return ms.filter((m) => k.has(m.id) || (m.name != null && k.has(m.name))).map((m) => m.id); });
    const G = new Map(out.groups.map((g) => [g.value, Object.assign(g, { machines: [], events: [] })]));
    const un = { machines: [], events: [] };
    for (const m of ms) { if (mg.where.has(m.id)) G.get(mg.where.get(m.id)).machines.push(m.id); else if (!mg.span.has(m.id)) un.machines.push(m.id); }
    const between = [];
    for (const t of (d && d.types) || []) {
      const on = ms.filter((m) => (m.publishes || []).some((p) => p.type === t) || (m.subscribes || []).some((p) => hears(p, t))).map((m) => m.id);
      const vs = new Set(on.map((id) => mg.where.get(id)));
      if (!on.length || vs.has(undefined)) un.events.push(t);
      else if (vs.size === 1) G.get([...vs][0]).events.push(t);
      else between.push({ type: t, groups: [...vs].sort() });
    }
    const crossing = new Map(), inside = new Set();
    for (const h of (d && d.handoffs) || []) {
      const a = mg.where.get(h.from), b = mg.where.get(h.to);
      if (h.from === h.to || a == null || b == null) continue;
      if (a === b) { inside.add(h.from + ">" + h.to); continue; }
      const pair = [a, b].sort(), k = pair.join("|"), c = crossing.get(k) || { between: pair, handoffs: [], count: 0, subjects: 0, pairs: new Set() };
      c.handoffs.push({ from: h.from, via: h.via, to: h.to, count: h.count }); c.pairs.add(h.from + ">" + h.to); c.subjects += h.count || 0; crossing.set(k, c);
    }
    const cross = [...crossing.values()].map(({ pairs, ...c }) => ({ ...c, count: pairs.size })).sort((a, b) => b.count - a.count || a.between.join().localeCompare(b.between.join()));
    return { ...out, by: "offer", unassigned: un, between, crossing: cross, spanning: [...mg.span].map(([machine, groups]) => ({ machine, groups })),
             joined: inside.size, crossed: cross.reduce((a, c) => a + c.count, 0) };
  }

  // The browser's side: the offers, in memory only; a change is announced as "orchestra:subsystems"
  function install(Orchestra) {
    if (Orchestra.subsystems) return;
    const offers = new Map();
    const changed = () => { try { document.dispatchEvent(new CustomEvent("orchestra:subsystems")); } catch (e) {} };
    Orchestra.subsystems = {
      offer(o) { const n = normal(o); if (!n) return; const same = offers.has(n.title) && JSON.stringify(offers.get(n.title)) === JSON.stringify(n); offers.set(n.title, n); if (!same) changed(); },
      withdraw(title) { if (offers.delete(String(title))) changed(); },
      offers() { return [...offers.values()]; },
    };
  }
  return { normal, dynamics, eventMap, install };
});
