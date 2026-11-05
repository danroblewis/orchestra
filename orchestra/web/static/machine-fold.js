// The Machines page's folded machines: off the cards and the Event Map, each in a collapsed group
// at the end of the page. Two reasons, both display only, both derived on read:
// - **announced only, never acted** (web/machines.py ``announced_only``): every event of the
//   machine on the bus is its own orchestra.machine.started, the first more than ten minutes ago
//   (a person a relay announced who never did anything). It returns by itself the moment it
//   publishes anything else;
// - **hidden by you** (``hidden``): the owner's ``ignore`` mark on the machine, a page control
//   (AGENTS.md rule 9 as amended), undone by "Show" (``unignore``). Hidden wins over announced only.
// A folded machine is still a machine, observed: nothing here deletes or alters an event, and
// discovery and the flows' hypotheses (sd/attribute.py) never read the fold.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.MachineFold = factory();
})(typeof self !== "undefined" ? self : this, function () {
  // why a machine is folded: "hidden", "announced", or null (shown)
  const why = (m) => (m.bootstrap ? null : m.hidden ? "hidden" : m.announced_only ? "announced" : null);
  function split(machines) {
    const out = { shown: [], announced: [], hidden: [] };
    for (const m of machines || []) { const w = why(m); (w ? out[w] : out.shown).push(m); }
    return out;
  }
  // the API's answer with the folded machines left out, and every hand-off, relay, counted edge,
  // declared edge and hub membership that names one, so the map draws no line to a machine it left
  // out; ``showFolded``: the answer as it is
  function forMap(d, showFolded) {
    const out = new Set((d.machines || []).filter(why).map((m) => m.id));
    if (showFolded || !out.size) return d;
    const keep = (...ids) => !ids.some((x) => out.has(x));
    return { ...d, machines: d.machines.filter((m) => !out.has(m.id)),
      handoffs: (d.handoffs || []).filter((h) => keep(h.from, h.to)),
      relays: (d.relays || []).filter((r) => keep(r.from, r.to, r.through)),
      counted: (d.counted || []).filter((e) => keep(e.machine)),
      intended_edges: (d.intended_edges || []).filter((e) => keep(e.from, e.to)),
      ...(Array.isArray(d.hubs) ? { hubs: d.hubs.filter((h) => keep(h.hub)).map((h) => ({ ...h, members: (h.members || []).filter((x) => keep(x)) })) } : {}) };
  }
  // the page control's body: hide (``ignore``) or show again (``unignore``) one machine or several
  // in one change (the "announced only" group's "Hide all of these")
  function body(control, ids) {
    const one = ids.length === 1;
    return { control, part: "machine", ...(one ? { id: ids[0] } : { keys: ids }), page: "machines",
             from: one ? "machine card" : "announced only, never acted" };
  }
  return { why, split, forMap, body };
});
