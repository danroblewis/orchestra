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
//
// **The protocol** (the owner, 2026-11-01: "most of the agents look like they both publish and
// subscribe to the same events"): a machine that exchanges event types both ways with at least two
// others (it publishes a type each of them announces it listens for, and listens for a type each of
// them publishes) is a **hub**, and those machines are its members (the widest first: a member of a
// hub is no hub itself, so roles that pass the hub's type to each other stay roles). The types between a hub and a
// member, and the types the hub both publishes and listens for (its own bookkeeping), are the hub's
// protocol: the plumbing every member shares, which says nothing about who hands work to whom. The
// map draws them folded into one thin edge per member, labelled by their families ("x.*" for x.made, x.done), and
// shows them only when asked. Who hands work to whom through a hub is the relay the API records (a
// subject handed to the hub by one machine and on by it to another): drawn as a hand-off from the
// one to the other "via" the hub. Publishing is what was observed or declared; listening what was
// announced or declared. No event type's name is known here (AGENTS.md rule 1).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MachineGraph = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const hears = (pattern, type) => pattern === type || pattern === "*" || (pattern.endsWith(".*") && type.startsWith(pattern.slice(0, -1)));
  const family = (type) => type.split(".")[0] + ".*";
  // the hubs and their members (the API's ``hubs`` when served, else found here by the same rule), and
  // whether a type from one machine to another is a hub's protocol.
  // d: the API's answer; intended: the declared layer's links ({machine, kind: "publishes"|"listens", type})
  function protocol(d, intended = []) {
    const pub = new Map(), sub = new Map(), add = (m, id, t) => { if (!m.has(id)) m.set(id, new Set()); m.get(id).add(t); };
    for (const m of d.machines || []) { for (const p of m.publishes || []) add(pub, m.id, p.type); for (const t of m.subscribes || []) add(sub, m.id, t); }
    for (const e of intended || []) add(e.kind === "publishes" ? pub : sub, e.machine, e.type);
    const listens = (id, type) => [...(sub.get(id) || [])].some((p) => hears(p, type));
    const sends = (a, b) => [...(pub.get(a) || [])].filter((t) => listens(b, t));     // types a publishes that b listens for
    // only a machine that publishes and listens can exchange both ways (hundreds of people a relay
    // announced, who listen for nothing, are never a pair to try)
    const ids = [...new Set([...pub.keys(), ...sub.keys()])].filter((id) => pub.has(id) && sub.has(id)), hubs = new Map();
    // the server's hubs when it serves them (web/hubs.py: one answer for this page and the Supervisor)
    if (Array.isArray(d.hubs)) for (const x of d.hubs) hubs.set(x.hub, new Set(x.members || []));
    else {
      // the widest first: a member of a hub is no hub of its own (roles that pass the hub's own type
      // to each other are its members, and what they hand each other stays drawn)
      const cands = ids.map((h) => [h, new Set(ids.filter((m) => m !== h && sends(h, m).length && sends(m, h).length))])
        .filter(([, ms]) => ms.size >= 2).sort((a, b) => b[1].size - a[1].size || a[0].localeCompare(b[0]));
      for (const [h, members] of cands) if (![...hubs.values()].some((ms) => ms.has(h))) hubs.set(h, members);
    }
    // a type from ``a`` that ``b`` receives is protocol: between a hub and its member, or a hub's own
    const is = (a, type, b) => (a === b ? hubs.has(a) && listens(a, type)
      : (hubs.has(a) && hubs.get(a).has(b)) || (hubs.has(b) && hubs.get(b).has(a)));
    // each hub and member, with the families of the types between them, both ways
    const folds = [];
    for (const [h, members] of hubs) for (const m of members) {
      const types = [...new Set([...sends(h, m), ...sends(m, h)])].sort();
      folds.push({ hub: h, member: m, types, families: [...new Set(types.map(family))] });
    }
    const own = [...hubs.keys()].flatMap((h) => sends(h, h));
    const families = [...new Set([...folds.flatMap((f) => f.families), ...own.map(family)])].sort();
    return { hubs, is, folds, families };
  }

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
      links[k] = links[k] || { source: a, target: b, seen: 0, inferred, handoffs: 0, observed: 0, from: {}, fromDay: {} };
      if (!inferred) { links[k].inferred = false; links[k].seen += seen || 0; } return links[k]; };
    for (const m of d.machines) {
      for (const p of m.publishes) link("m:" + m.id, evNode(p.type), p.day);
      for (const t of m.subscribes) link(evNode(t), "m:" + m.id, day[t] || 0);
    }
    // hand-offs: a machine acted on a subject right after another machine's event about it. Through
    // a type it announced, that listener edge is observed; through one it did not, the edge is inferred
    // A hand-off credited to no type (the receiver announced none it took: ``via`` null) is the
    // receiver acting next on the subject, never a type it listens for: ``acts``, drawn machine to
    // machine, with the sender's last type said (``after``)
    const acts = [];
    for (const h of d.handoffs || []) {
      if (!h.via && nodes["m:" + h.to] && nodes["m:" + h.from] && h.from !== h.to && !(h.after && opts.hidden && opts.hidden(h.after)))
        acts.push({ source: "m:" + h.from, target: "m:" + h.to, after: h.after || null, count: h.count || 0, day: h.day || 0 });
      if (!nodes["m:" + h.to] || !h.via || (opts.hidden && opts.hidden(h.via))) continue;
      const l = link(evNode(h.via), "m:" + h.to, 0, true);
      l.handoffs += h.day; l.observed += h.count || 0;
      l.from["m:" + h.from] = (l.from["m:" + h.from] || 0) + (h.count || 0);   // who handed it on
      l.fromDay["m:" + h.from] = (l.fromDay["m:" + h.from] || 0) + (h.day || 0);   // ... in the last 24 h
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
    // a hub's protocol: a publish edge whose every receiver is the hub's (or a member's) by it, and a
    // listen edge whose every sender is
    const proto = protocol(d, opts.intended), all = Object.values(links), type = (id) => id.slice(3);
    for (const l of all) {
      const ev = l.source.startsWith("ev:") ? l.source : l.target;
      const pubs = all.filter((x) => x.target === ev).map((x) => x.source.slice(2)), subs = all.filter((x) => x.source === ev).map((x) => x.target.slice(2));
      const [ps, ss] = l.source.startsWith("ev:") ? [[...pubs, ...Object.keys(l.from).map((k) => k.slice(2))], [l.target.slice(2)]] : [[l.source.slice(2)], subs];
      l.protocol = ps.length > 0 && ss.length > 0 && ps.every((a) => ss.every((b) => proto.is(a, type(ev), b)));
    }
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
        merged[k] = merged[k] || { ...l, source: a, target: b, seen: 0, handoffs: 0, observed: 0, from: {}, fromDay: {} };
        const x = merged[k]; x.seen += l.seen; x.handoffs += l.handoffs || 0; x.observed += l.observed || 0;
        for (const [m, n] of Object.entries(l.from || {})) x.from[m] = (x.from[m] || 0) + n;
        for (const [m, n] of Object.entries(l.fromDay || {})) x.fromDay[m] = (x.fromDay[m] || 0) + n;
        x.inferred = x.inferred && l.inferred; x.declared = x.declared && l.declared; x.gone = x.gone && l.gone; x.added = x.added || l.added;
        x.declaredListener = x.declaredListener && l.declaredListener; x.protocol = x.protocol && l.protocol; }
      ls = Object.values(merged);
    }
    const used = new Set(ls.flatMap((l) => [l.source, l.target]));
    // every machine is drawn, connected or not; events only when something links them
    return { nodes: [...Object.values(nodes), ...Object.values(evNodes).filter((n) => used.has(n.id))], links: ls, protocol: proto, acts };
  }

  // machine → machine, through an event type one publishes and the other listens for. ``observed``:
  // a hand-off from that publisher through it to that listener was seen on some subject; only those
  // are communication (and cycles). Another publisher's hand-offs through the same type do not count
  function chains(links) {
    const id = (l) => l.id || l.source + ">" + l.target, out = [];
    for (const a of links) if (a.source.startsWith("m:") && a.target.startsWith("ev:") && !a.gone)
      for (const b of links) if (b.source === a.target && b.target.startsWith("m:") && !b.gone)
        out.push({ source: a.source, target: b.target, via: a.target, evIds: [id(a), id(b)], seen: Math.min(a.seen, b.seen),
                   inferred: b.inferred, observed: !!(b.from && b.from[a.source]), handoffs: (b.from && b.from[a.source]) || 0,
                   day: (b.fromDay && b.fromDay[a.source]) || 0,
                   protocol: !!(a.protocol || b.protocol) });
    // a machine's edge to itself is drawn only when it handed something to itself and it is no hub's bookkeeping
    return out.filter((c) => c.source !== c.target || (c.observed && !c.protocol));
  }

  // who handed work to whom through a hub: a relay (the API's ``relays``) whose hand-off from the hub
  // is its protocol, as a chain from the one to the other "via" the hub ({source, target, through, seen, observed})
  function relays(d, proto) {
    const out = new Map();
    for (const r of d.relays || []) {
      if (r.from === r.to || !proto.hubs.has(r.through) || !proto.is(r.through, r.through_via || "", r.to)) continue;
      const k = r.from + ">" + r.to + ">" + r.through, x = out.get(k) || { source: "m:" + r.from, target: "m:" + r.to, through: r.through, seen: 0, count: 0, observed: true, vias: [] };
      x.seen += r.day || 0; x.count += r.count || 0; if (r.via && !x.vias.includes(r.via)) x.vias.push(r.via); out.set(k, x);
    }
    return [...out.values()];
  }

  return { graph, chains, protocol, relays };
});
