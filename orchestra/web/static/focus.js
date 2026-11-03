// A focus: a sub-graph of the one system shown on its own (the owner, 2026-11-02: "the proper
// solution is to show a sub-graph of the event graph or system dynamics model ... they deserve to be
// shown on their own, but they are inherently interconnected to the whole system"). A page
// extension (a plugin's every-page script) names a subset; the Machines page's event map and the
// Dynamics diagram draw only it, with what crosses its edge drawn to small grey named stubs, and the
// cards and tables under them are filtered the same way. A focus hides: it never changes what is
// computed (hypotheses, counts, loops, titles), and it is never a separate model. The core never
// knows what a focus is about (AGENTS.md rule 1): a title, the ids, the event types and the series
// keys, nothing else.
//
//   Orchestra.focus.set({title, machines: [ids], events: [types], stocks: [keys], flows: [keys], reason})
//   Orchestra.focus.clear()
//   Orchestra.focus.offer({title, subtitle, get: () => subset})   a chip above each diagram; click sets, again clears
//   Orchestra.focus.update(title, {subtitle})                     an offer's chip says something new
//   Orchestra.focus.withdraw(title)                               an offer no longer made (a focus set from it cleared)
//
// An offer with ``row: false`` draws no chip in the row: its chip is elsewhere (a subsystem's box
// title, subsystem-boxes.js), and it is toggled from there (``toggle(title)``).
//
// ``stocks`` and ``flows`` name a stock or a flow by the series it is bound to: ``{name, labels}``,
// keyed here as a discovery keys a series (``name{label="value",...}``, sorted, without the project
// label: LeftOut.keyOf), or that key already made, or by its id. The focus is kept in the page's hash (``#focus=<title>``) so a link carries it; on load it
// is restored only when an extension offers that title again.
//
// The pure part (Focus.eventMap, Focus.dynamics, Focus.resolve) is used by the pages and by the Node
// tests (tests/focus); the state, the chips and the bar exist only in a browser.
(function (root, factory) {
  const F = factory();
  if (typeof module === "object" && module.exports) module.exports = F;
  else { root.Focus = F; if (root.Orchestra) F.install(root.Orchestra); }
})(typeof self !== "undefined" ? self : this, function () {
  // a series as a discovery keys it (left-out.js LeftOut.keyOf; the same here so the tests need no page)
  const keyOf = (ref) => { if (!ref) return null; const ls = Object.entries(ref.labels || {}).filter(([k]) => k !== "project").sort(([a], [b]) => (a < b ? -1 : 1));
    return ref.name + (ls.length ? "{" + ls.map(([k, v]) => `${k}="${v}"`).join(",") + "}" : ""); };
  // a field's entries as strings; a series given as {name, labels} is keyed here, so no extension
  // keeps a copy of the key's rule
  const one = (x) => (x && typeof x === "object" && x.name ? keyOf(x) : String(x));
  const list = (x) => (Array.isArray(x) ? x.map(one) : x == null ? [] : [one(x)]);
  // a subset as given, normalised: every field a list of strings
  function normal(f) {
    if (!f || !f.title) return null;
    return { title: String(f.title), machines: list(f.machines), events: list(f.events), stocks: list(f.stocks), flows: list(f.flows), reason: f.reason ? String(f.reason) : "" };
  }
  // the model's stock and flow ids a focus names, by series key or id: {stocks: Set, flows: Set}
  function resolve(model, f) {
    const sk = new Set(f.stocks), fk = new Set(f.flows);
    const stocks = new Set(((model && model.stocks) || []).filter((s) => sk.has(s.id) || (s.series && sk.has(keyOf(s.series)))).map((s) => s.id));
    const flows = new Set(((model && model.flows) || []).filter((x) => fk.has(x.id) || (x.counter && fk.has(keyOf(x.counter)))).map((x) => x.id));
    return { stocks, flows };
  }
  // the machines a focus names, of those a page lists: by id, or by the name it is shown by
  const machineIn = (f, m) => !!m && (f.machines.includes(m.id) || (m.name != null && f.machines.includes(m.name)));

  const STUB = { kind: "cloud", stub: true, charge: -120 };
  // The event map's nodes and edges (as machines.html hands them to NetGraph) cut to a focus:
  // the named machines; the event types and channels between them (with ``events`` named, only those
  // types); every edge among them as it is (a relay through a hub outside stays a relay); and each
  // machine outside that hands work in or takes it out drawn once, as a small grey stub named for it,
  // set at the left edge when it only hands in, the right when it only takes out.
  // ``name(id)``: a node's name. -> {nodes, edges, inside: n, total: N, outside: [names]}
  function eventMap(nodes, edges, f, { name } = {}) {
    const isM = (n) => !!(n.machine || /^m:/.test(n.id)), mid = (n) => n.mid || n.id.replace(/^m:/, "");
    const named = new Set(f.machines), evs = new Set(f.events);
    const keep = new Set(nodes.filter((n) => isM(n) && (named.has(mid(n)) || named.has(n.label))).map((n) => n.id));
    const machinesIn = new Set(keep);
    const links = (id) => edges.filter((e) => !e.toEdge && (e.source === id || e.target === id)).map((e) => (e.source === id ? e.target : e.source));
    for (const n of nodes) {
      if (isM(n)) continue;
      const types = n.labels || [n.label];
      const typeOk = !/^ev:/.test(n.id) || !evs.size || types.some((t) => evs.has(t));
      if (typeOk && links(n.id).some((x) => machinesIn.has(x))) keep.add(n.id);
    }
    const byId = new Map(nodes.map((n) => [n.id, n])), stubs = new Map(), outEdges = [];
    for (const e of edges) {
      if (e.toEdge) { if (keep.has(e.source)) outEdges.push(e); continue; }
      const a = keep.has(e.source), b = keep.has(e.target);
      if (a && b) { outEdges.push(e); continue; }
      if (!a && !b) continue;
      const other = byId.get(a ? e.target : e.source);
      if (!other || !isM(other)) continue;                       // an event type or channel outside: not drawn
      const id = "out:" + other.id, s = stubs.get(id) || { id, ...STUB, label: (name && name(other)) || other.label || mid(other), of: other.id, outside: true, ins: 0, outs: 0 };
      if (a) s.outs++; else s.ins++;
      stubs.set(id, s);
      outEdges.push({ ...e, [a ? "target" : "source"]: id, cls: `${e.cls || ""} ng-focus-cross`, label: undefined, width: Math.min(e.width || 1.6, 1.6) });
    }
    // where each stub sits: those that only hand work in at the left, the rest at the right, spread down
    const left = [...stubs.values()].filter((s) => !s.outs), right = [...stubs.values()].filter((s) => s.outs);
    left.forEach((s, i) => { s.anchor = [0.04, (i + 1) / (left.length + 1)]; });
    right.forEach((s, i) => { s.anchor = [0.96, (i + 1) / (right.length + 1)]; });
    const total = nodes.filter(isM).length;
    return { nodes: [...nodes.filter((n) => keep.has(n.id)), ...stubs.values()], edges: outEdges, inside: machinesIn.size, total, outside: [...stubs.values()].map((s) => s.label) };
  }

  // The Dynamics diagram's nodes and edges (sd-graph.js) cut to a focus: the named stocks (and the
  // ends of the named flows that are stocks), every flow from or to one of them, with an end that is
  // a stock outside drawn as a small grey stub named for that stock, just outside the system's frame
  // beside the stock inside (one per pair, tethered as a cloud is); the clouds, places and
  // auxiliaries those flows touch; the influences on them (one from a stock outside, from its stub);
  // and a stub for the stock a drawn flow's co-flow moves (its twin's counter, ``<flow>@<writer>``).
  // ``ids``: Focus.resolve's answer; ``name(id)``: a stock node's name.
  // -> {nodes, edges, inside, total, outside, left: the stocks it leaves out with no stub, by name}
  function dynamics(nodes, edges, ids, { name } = {}) {
    const byId = new Map(nodes.map((n) => [n.id, n])), isStock = (n) => !!(n && n.sid);
    const inside = new Set(nodes.filter((n) => isStock(n) && ids.stocks.has(n.sid)).map((n) => n.id));
    const flowEdges = edges.filter((e) => !e.toEdge && e.flowPart);
    for (const e of flowEdges) if (ids.flows.has(e.fid)) for (const end of [e.source, e.target]) if (isStock(byId.get(end))) inside.add(end);
    const keep = new Set(inside), stubs = new Map(), outEdges = [], kept = new Map();
    const stub = (outsideId, insideId) => {
      const id = `stub:${outsideId}@${insideId}`, n = byId.get(outsideId);
      if (!stubs.has(id)) stubs.set(id, { id, ...STUB, charge: -20, tether: insideId, label: (name && name(n)) || n.label, of: outsideId, outside: true });
      return id;
    };
    for (const e of flowEdges) {
      const a = inside.has(e.source), b = inside.has(e.target);
      if (!a && !b && !ids.flows.has(e.fid)) continue;
      const end = (id, other) => { const n = byId.get(id); if (inside.has(id)) return id;
        if (isStock(n)) return inside.has(other) ? stub(id, other) : null;
        keep.add(id); return id; };                              // a cloud, a place: drawn with its flow
      const s = end(e.source, e.target), t = end(e.target, e.source);
      if (!s || !t) continue;
      const crosses = s !== e.source || t !== e.target;
      const x = crosses ? { ...e, source: s, target: t, cls: `${e.cls || ""} ng-focus-cross` } : e;
      outEdges.push(x); kept.set(e.id, x);
    }
    for (const e of edges) {
      if (!e.toEdge || !kept.has(e.toEdge)) continue;
      const src = byId.get(e.source); if (!src) continue;
      const fe = kept.get(e.toEdge), anchor = [fe.source, fe.target].find((x) => inside.has(x));
      if (keep.has(e.source)) outEdges.push(e);
      else if (isStock(src) && anchor) outEdges.push({ ...e, source: stub(e.source, anchor), cls: `${e.cls || ""} ng-focus-cross` });
      else if (!isStock(src)) { keep.add(e.source); outEdges.push(e); }   // an auxiliary the rate reads
    }
    // a co-flow (the same counter's events moving another machine's stock: ids "<flow>@<writer>") of a
    // flow drawn: its stock outside is a stub beside the stock its twin moves, never dropped unsaid
    const base = (fid) => String(fid || "").split("@")[0];
    const twins = new Map();
    for (const e of flowEdges) if (kept.has(e.id)) { const at = [e.source, e.target].find((x) => inside.has(x)); if (at) twins.set(base(e.fid), at); }
    for (const e of flowEdges) {
      if (kept.has(e.id) || !twins.has(base(e.fid))) continue;
      for (const end of [e.source, e.target]) if (isStock(byId.get(end)) && !inside.has(end)) stubs.get(stub(end, twins.get(base(e.fid)))).co = true;
    }
    // a cloud stays only with a flow that is drawn
    const used = new Set(outEdges.flatMap((e) => [e.source, e.target]));
    const drawn = nodes.filter((n) => keep.has(n.id) && (inside.has(n.id) || used.has(n.id)));
    const stubbed = new Set([...stubs.values()].map((s) => s.of));
    return { nodes: [...drawn, ...stubs.values()], edges: outEdges, inside: inside.size, total: nodes.filter(isStock).length,
             outside: [...new Set([...stubs.values()].map((s) => s.label))],
             // the stocks it leaves out with no stub: named, so nothing is dropped silently
             left: [...new Set(nodes.filter((n) => isStock(n) && !inside.has(n.id) && !stubbed.has(n.id)).map((n) => (name && name(n)) || n.label))] };
  }

  // a page's hash holds what it opens (a machine's id) and the focus beside it: "#worker&focus=t".
  // ``hashId``: the part that is not the focus; ``hashWith(id, hash)``: the hash for ``id``, the focus kept
  // (``boxes=``, the subsystems' boxes, subsystem-boxes.js, is kept beside the focus the same way)
  const kept = (p) => p.startsWith("focus=") || p.startsWith("boxes=");
  const hashId = (hash) => decodeURIComponent(String(hash || "").replace(/^#/, "").split("&").filter((p) => p && !kept(p))[0] || "");
  const hashWith = (id, hash) => { const f = String(hash || "").replace(/^#/, "").split("&").filter(kept);
    const h = [...(id ? [encodeURIComponent(id)] : []), ...f].join("&"); return h ? "#" + h : ""; };

  // The browser's side: one focus at a time, the offers, the hash, the chips and the bar.
  function install(Orchestra) {
    if (Orchestra.focus) return;
    const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    let current = null;
    const offers = new Map(), mounts = new Map();
    const fromHash = () => { const m = /(?:^#|&)focus=([^&]*)/.exec(location.hash); return m ? decodeURIComponent(m[1]) : null; };
    let waiting = fromHash();                                  // restored when an extension offers it again
    const writeHash = () => {
      const rest = location.hash.replace(/^#/, "").split("&").filter((p) => p && !p.startsWith("focus="));
      const h = [...rest, ...(current ? ["focus=" + encodeURIComponent(current.title)] : [])].join("&");
      try { history.replaceState(null, "", location.pathname + location.search + (h ? "#" + h : "")); } catch (e) {}
    };
    const changed = () => { for (const [el, c] of mounts) draw(el, c); document.dispatchEvent(new CustomEvent("orchestra:focus", { detail: current })); };
    const subtitleOf = (o) => { try { return typeof o.subtitle === "function" ? o.subtitle() : o.subtitle; } catch (e) { return ""; } };
    const api = {
      set(f) { const n = normal(f); if (!n) return; current = n; waiting = null; writeHash(); changed(); },
      clear() { if (!current) return; current = null; waiting = null; writeHash(); changed(); },
      current() { return current; },
      // an offer is idempotent by title: offering it again replaces it (and refreshes a focus set from it)
      offer(o) {
        if (!o || !o.title || typeof o.get !== "function") return;
        const t = String(o.title); offers.set(t, { title: t, subtitle: o.subtitle, get: o.get, row: o.row !== false });
        if (waiting === t || (current && current.title === t && current.offered)) {
          try { const n = normal({ ...o.get(), title: t }); if (n) { n.offered = true; const same = current && JSON.stringify(current) === JSON.stringify(n); current = n; waiting = null; writeHash(); if (!same) { changed(); return; } } } catch (e) {}
        }
        for (const [el, c] of mounts) draw(el, c);
      },
      update(title, { subtitle } = {}) { const o = offers.get(String(title)); if (!o) return; o.subtitle = subtitle; for (const [el, c] of mounts) draw(el, c); },
      withdraw(title) {
        const t = String(title); if (!offers.delete(t)) return;
        if (current && current.title === t && current.offered) { current = null; writeHash(); changed(); return; }
        for (const [el, c] of mounts) draw(el, c);
      },
      offers() { return [...offers.values()]; },
      toggle(title) {
        const o = offers.get(String(title)); if (!o) return;
        if (current && current.title === o.title) { api.clear(); return; }
        try { const n = normal({ ...o.get(), title: o.title }); if (n) { n.offered = true; current = n; waiting = null; writeHash(); changed(); } } catch (e) {}
      },
      // the row above a diagram: the offers as chips, and with a focus set, the bar that says what is
      // shown of what and clears it. ``counts``: {shown, total, noun} for the bar
      mount(el, counts) { if (!el) return; mounts.set(el, counts || mounts.get(el) || null); draw(el, mounts.get(el)); },
    };
    function draw(el, c) {
      if (!el.isConnected) { mounts.delete(el); return; }
      const chips = [...offers.values()].filter((o) => o.row).map((o) => { const on = current && current.title === o.title, sub = subtitleOf(o);
        return `<button type="button" class="focus-chip${on ? " on" : ""}" data-title="${esc(o.title)}" aria-pressed="${on ? "true" : "false"}" title="${on ? "showing this part of the system: press to show everything" : "show only this part of the system"}">${esc(o.title)}${sub ? ` <span class="muted">${esc(sub)}</span>` : ""}</button>`; }).join("");
      const bar = current && c ? `<div class="focus-bar" role="status">showing <b>${esc(current.title)}</b>: ${c.shown} of ${c.total} ${esc(c.noun || "")}${current.reason ? ` <span class="muted">· ${esc(current.reason)}</span>` : ""}${c.outside ? ` <span class="muted">· grey stubs: ${esc(c.outside)} outside it</span>` : ""}${c.left ? ` <span class="muted">· not shown: ${esc(c.left)}</span>` : ""} · <a href="#" class="focus-clear">show everything</a></div>` : "";
      const html = (chips ? `<div class="focus-chips">${chips}</div>` : "") + bar;
      if (el.dataset.html === html) return;
      el.dataset.html = html; el.innerHTML = html;
      el.querySelectorAll(".focus-chip").forEach((b) => b.addEventListener("click", () => api.toggle(b.dataset.title)));
      const clr = el.querySelector(".focus-clear"); if (clr) clr.addEventListener("click", (ev) => { ev.preventDefault(); api.clear(); });
    }
    Orchestra.focus = api;
  }

  return { normal, resolve, keyOf, machineIn, eventMap, dynamics, hashId, hashWith, install };
});
