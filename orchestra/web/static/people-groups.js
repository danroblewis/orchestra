// The people relayed from one system, drawn as one group on the Machines page (web/people.py; the
// owner, 2026-11-04: "way too many people names sometimes, and it's breaking various things"). The
// page asks /api/machines?people=grouped: each system's people (``person.<system>.<account>``, at
// least eight of them) come as one row, "Jira people (600)", with ``people_group``; every line that
// named one of them names the group, summed. The group is one card, which opens into a list of its
// people with search (fetched on demand, /api/machines/people), and one node on the Event Map,
// which opens into the people one by one (``expand``, remembered) and folds back into one. Display
// only: each person is still a machine, observed (AGENTS.md rule 2), and nothing here changes the
// bus, discovery or the declared layer. An owner-mapped person.<key> is never grouped.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.PeopleGroups = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const KEY = "orchestra.evmap.people.expanded";
  const isGroup = (m) => !!(m && m.people_group);
  // the machines a row stands for: a group's people, or the machine itself
  const ids = (m) => (isGroup(m) ? m.people_group.ids || [] : [m.id]);
  // every machine's id, the groups' people included (the colours' order is the same on every page)
  function allIds(d) {
    const out = new Set();
    for (const m of (d && d.machines) || []) for (const id of ids(m)) out.add(id);
    for (const g of (d && d.people_groups) || []) for (const id of ids(g)) out.add(id);
    return [...out].sort();
  }
  // what the cards are: each machine not in a group, and each group once (expanded on the map or not);
  // its people, expanded on the map, are in its list, not cards of their own
  function forCards(d) {
    const groups = new Map(((d && d.people_groups) || []).map((g) => [g.id, g]));
    const out = [];
    for (const m of (d && d.machines) || []) {
      if (m.in_people) continue;
      out.push(isGroup(m) ? groups.get(m.id) || m : m);
      groups.delete(m.id);
    }
    return [...out, ...groups.values()];
  }
  // the people of a group a search names: by name or id, any part, any case
  function search(members, q) {
    const s = String(q || "").trim().toLowerCase();
    return s ? (members || []).filter((p) => (p.name || "").toLowerCase().includes(s) || p.id.toLowerCase().includes(s)) : members || [];
  }
  // the groups opened into their people on the map, remembered across loads
  function expanded(store) {
    try { const v = JSON.parse((store || localStorage).getItem(KEY) || "[]"); return new Set(Array.isArray(v) ? v : []); } catch (e) { return new Set(); }
  }
  function remember(set, store) { try { (store || localStorage).setItem(KEY, JSON.stringify([...set].sort())); } catch (e) {} }
  // the query the page asks with: grouped, and the groups it opened
  const query = (set) => "people=grouped" + (set && set.size ? "&expand=" + encodeURIComponent([...set].sort().join(",")) : "");
  // a group's summary line: how many, how many active, and a few names
  function summary(g) {
    const p = g.people_group, more = p.size - p.names.length;
    return `${p.size} people relayed from ${p.system}${p.group ? ` (${p.group})` : ""} · ${p.active} active`
      + (p.announced_only ? ` · ${p.announced_only} announced only` : "") + ` · ${p.names.join(", ")}${more > 0 ? ` and ${more} more` : ""}`;
  }
  return { KEY, isGroup, ids, allIds, forCards, search, expanded, remember, query, summary };
});
