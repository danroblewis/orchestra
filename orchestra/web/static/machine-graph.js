// The Machines page's event map as a graph (machines.html draws it): machines publish event types
// (machine → event) and listen for them (event → machine), and which machine passed what to whom.
//
// What a machine announces it listens for is a declaration, not a hand-off (AGENTS.md rule 2): an
// edge from an event type to a machine is **observed** only when a hand-off through that type to
// that machine was seen on some subject in the era (the API's ``handoffs``: a machine acted on a
// subject right after another's event of that type about it). A listener that announced the type
// and never received a hand-off through it keeps its edge as a **declared listener** (drawn faint),
// and a machine → machine chain through it is not a communication: cycles are made only of
// observed chains. A hand-off through a type the machine never announced is **inferred** (dotted).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MachineGraph = factory();
})(typeof self !== "undefined" ? self : this, function () {
  // d: the API's answer (machines, handoffs). opts.intended: the declared layer's links
  // ({machine, kind: "publishes"|"listens", type, observed, gone, added}); opts.showAll: keep event
  // types nobody listens for.
  function graph(d, opts = {}) {
    const nodes = {}, evNodes = {}, links = {};
    for (const m of d.machines) nodes["m:" + m.id] = { id: "m:" + m.id, kind: m.bootstrap ? "program" : "machine", label: m.name || m.id, mid: m.id, group: m.group,
                                                       bootstrap: m.bootstrap, active: m.active, machine: true, instances: m.instances, mode: m.mode };
    const day = {};
    for (const m of d.machines) for (const p of m.publishes) day[p.type] = (day[p.type] || 0) + p.day;
    const evNode = (type) => { const id = "ev:" + type; evNodes[id] = evNodes[id] || { id, kind: "event", label: type, cnt: day[type] || 0 }; return id; };
    const link = (a, b, seen, inferred = false) => { const k = a + ">" + b;
      links[k] = links[k] || { source: a, target: b, seen: 0, inferred, handoffs: 0, observed: 0, from: {} };
      if (!inferred) { links[k].inferred = false; links[k].seen += seen || 0; } return links[k]; };
    for (const m of d.machines) {
      for (const p of m.publishes) link("m:" + m.id, evNode(p.type), p.day);
      for (const t of m.subscribes) link(evNode(t), "m:" + m.id, day[t] || 0);
    }
    // hand-offs: a machine acted on a subject right after another machine's event about it. Through
    // a type it announced, that listener edge is observed; through one it did not, the edge is inferred
    for (const h of d.handoffs || []) {
      if (!nodes["m:" + h.to] || !h.via || (opts.hidden && opts.hidden(h.via))) continue;
      const l = link(evNode(h.via), "m:" + h.to, 0, true);
      l.handoffs += h.day; l.observed += h.count || 0;
      l.from["m:" + h.from] = (l.from["m:" + h.from] || 0) + (h.count || 0);   // who handed it on
      if (l.inferred) l.seen += h.day;
    }
    // what a declaration says a machine listens for and emits: drawn even when nobody listens yet;
    // a link the latest change removed stays, as a ghost
    for (const e of opts.intended || []) {
      if (!nodes["m:" + e.machine]) continue;
      const [a, b] = e.kind === "publishes" ? ["m:" + e.machine, evNode(e.type)] : [evNode(e.type), "m:" + e.machine];
      const fresh = links[a + ">" + b] === undefined, l = link(a, b, 0);
      if (fresh) l.declared = !e.observed;
      if (e.gone) l.gone = true;
      else if (e.added) l.added = true;
    }
    // a listener edge no hand-off came through: the machine only said it listens
    for (const l of Object.values(links)) l.declaredListener = l.source.startsWith("ev:") && !l.observed;
    // An event nobody listens for is a dead end on the map; hide those unless asked, so the
    // picture is the communication pattern rather than the catalogue of everything published.
    let ls = Object.values(links);
    if (!opts.showAll) { const watched = new Set(ls.filter((l) => l.source.startsWith("ev:")).map((l) => l.source)); ls = ls.filter((l) => !l.target.startsWith("ev:") || watched.has(l.target) || l.declared || l.gone); }
    // Collapse event nodes that connect exactly the same publishers and listeners, the same way
    // (observed or only declared), into one multi-line node: the map is who talks to whom
    const sig = {};
    for (const n of Object.values(evNodes)) {
      const ins = ls.filter((l) => l.target === n.id).map((l) => l.source).sort().join(","),
            outs = ls.filter((l) => l.source === n.id).map((l) => l.target + (l.declaredListener ? "?" : "")).sort().join(",");
      if (!ins && !outs) continue;
      (sig[ins + "|" + outs] = sig[ins + "|" + outs] || []).push(n);
    }
    const alias = {};
    for (const group of Object.values(sig)) {
      if (group.length < 2) continue;
      group.sort((a, b) => b.cnt - a.cnt || a.label.localeCompare(b.label));
      const id = "ev:group:" + group.map((n) => n.id).join("+");
      evNodes[id] = { id, kind: "event", label: group[0].label, labels: group.map((n) => n.label), cnt: group.reduce((a, n) => a + n.cnt, 0) };
      for (const n of group) { alias[n.id] = id; delete evNodes[n.id]; }
    }
    if (Object.keys(alias).length) {
      const merged = {};
      for (const l of ls) { const a = alias[l.source] || l.source, b = alias[l.target] || l.target, k = a + ">" + b;
        merged[k] = merged[k] || { ...l, source: a, target: b, seen: 0, handoffs: 0, observed: 0, from: {} };
        const x = merged[k]; x.seen += l.seen; x.handoffs += l.handoffs || 0; x.observed += l.observed || 0;
        for (const [m, n] of Object.entries(l.from || {})) x.from[m] = (x.from[m] || 0) + n;
        x.inferred = x.inferred && l.inferred; x.declared = x.declared && l.declared; x.gone = x.gone && l.gone; x.added = x.added || l.added;
        x.declaredListener = x.declaredListener && l.declaredListener; }
      ls = Object.values(merged);
    }
    const used = new Set(ls.flatMap((l) => [l.source, l.target]));
    // every machine is drawn, connected or not; events only when something links them
    return { nodes: [...Object.values(nodes), ...Object.values(evNodes).filter((n) => used.has(n.id))], links: ls };
  }

  // machine → machine, through an event type one publishes and the other listens for. ``observed``:
  // a hand-off from that publisher through it to that listener was seen on some subject; only those
  // are communication (and cycles). Another publisher's hand-offs through the same type do not count
  function chains(links) {
    const id = (l) => l.id || l.source + ">" + l.target, out = [];
    for (const a of links) if (a.source.startsWith("m:") && a.target.startsWith("ev:") && !a.gone)
      for (const b of links) if (b.source === a.target && b.target.startsWith("m:") && !b.gone)
        out.push({ source: a.source, target: b.target, via: a.target, evIds: [id(a), id(b)], seen: Math.min(a.seen, b.seen),
                   inferred: b.inferred, observed: !!(b.from && b.from[a.source]), handoffs: (b.from && b.from[a.source]) || 0 });
    return out;
  }

  return { graph, chains };
});
