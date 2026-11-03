// Subsystems drawn as boxes in the one Dynamics diagram (docs/proposals/subsystems.md B10–B14): the
// partitions the API reports (``model.subsystems``, sd/subsystems.py) turned into what the renderer
// draws. A box is a group of one partition; a part is in at most one; nothing is split, recomputed
// or stored. The core knows no label's name (AGENTS.md rule 1): a partition's label and its values
// are data, said as they are.
//
// - **The choice** (``choices``, ``choose``): off, or one of the partitions the API reports, the
//   default first, each named "label · N boxes · M crossing". The page opens with the default on (the
//   owner, 2026-11-02: "sub 1. yes, boxes on"); the viewer's choice is kept in the hash (``boxes=``).
// - **Members** (``apply``): a stock is in its group's box; a place (a counter's end kept as no stock)
//   and an auxiliary are in a box only when every flow they touch or drive is inside that one box;
//   the clouds stay outside the frame by the cloud rule; an unassigned stock sits outside every box,
//   inside the frame. A flow between two boxes is drawn box to box, dashed when it is simulated, and
//   each pair's count is written between them ("2 flows between delivery and hotfix").
// - **Machines** spanning two groups are outside every box (the owner, 2026-11-02: "a machine should
//   only belong to one subsystem ... if it needs to belong to 2, it is probably outside of the box"),
//   listed as outside, "in two subsystems". The Dynamics diagram draws no machine node; the lists do.
// - **Tags** (B14): the partition label's tag ("workflow=hotfix") is left off the parts inside their
//   box (its title says it once), kept on the unassigned; a crossing flow's ends are named by their boxes.
//
// Shared by the page (global SubsystemBoxes) and the Node tests (tests/subsystems).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SubsystemBoxes = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  // a partition as the control names it: "workflow · 2 boxes · 3 crossing"
  const nameOf = (p) => `${p.label} · ${plural(p.groups.length, "box", "boxes")} · ${p.crossed} crossing${p.crossed_simulated ? ` (${p.crossed_simulated} simulated)` : ""}`;
  // the control's entries: each partition the API reports, the default first, then off
  function choices(subs) {
    const parts = ((subs && subs.partitions) || []).slice();
    const d = subs && subs.default;
    parts.sort((a, b) => (a.label === d ? -1 : b.label === d ? 1 : 0));
    return [...parts.map((p) => ({ value: p.label, text: nameOf(p) })), { value: "off", text: "off" }];
  }
  // which partition is drawn: what the viewer chose (``wanted``, from the hash: a label or "off"),
  // when the API still reports it; else the default; null for none
  function choose(subs, wanted) {
    const parts = (subs && subs.partitions) || [];
    if (wanted === "off") return null;
    return parts.find((p) => p.label === wanted) || parts.find((p) => p.label === (subs && subs.default)) || null;
  }
  const between = (a, b) => `${a} and ${b}`;
  // what is written between two boxes: "2 flows between delivery and hotfix", the simulated said apart
  function pairText(c) {
    const [a, b] = c.between;
    if (!c.count && c.simulated) return `${plural(c.simulated, "simulated flow", "simulated flows")} between ${between(a, b)}`;
    return `${plural(c.count, "flow", "flows")} between ${between(a, b)}${c.simulated ? ` · ${c.simulated} simulated` : ""}`;
  }

  // The diagram's nodes and edges (sd-graph.js build) with ``partition``'s boxes: every member node
  // gains ``box`` (its group's value), tags of the label dropped inside a box; a crossing flow gains
  // ``cross`` [from box, to box], drawn box to box (dashed when simulated, its ends named by their
  // boxes). -> {nodes, edges, boxes: [values], pairs: [{between, count, simulated, text, dashed, flows}],
  //            outside: {stocks, machines: [{machine, groups}]}}
  function apply(nodes, edges, partition) {
    if (!partition) return { nodes, edges, boxes: [], pairs: [], outside: { stocks: [], machines: [] } };
    const label = partition.label, stockBox = new Map(), flowBox = new Map(), cross = new Map();
    for (const g of partition.groups) { for (const s of g.stocks) stockBox.set(s, g.value); for (const f of g.flows) flowBox.set(f, g.value); }
    for (const c of partition.crossing) for (const f of c.flows) cross.set(f, c);
    const flowEdges = edges.filter((e) => !e.toEdge && e.flowPart);
    const edgeById = new Map(flowEdges.map((e) => [e.id, e]));
    // a flow's box: the group it is inside, or null (crossing, touching the unassigned, unknown)
    const boxOfFlow = (fid) => (flowBox.has(fid) ? flowBox.get(fid) : null);
    const only = (values) => { const s = new Set(values); return s.size === 1 && !s.has(null) ? [...s][0] : null; };
    const box = new Map();
    for (const n of nodes) if (n.sid && stockBox.has(n.sid)) box.set(n.id, stockBox.get(n.sid));
    for (const n of nodes) {
      if (box.has(n.id) || n.kind === "cloud" || n.sid) continue;
      if (n.place) {                                       // a place: by the flows that end at it
        const fs = flowEdges.filter((e) => e.source === n.id || e.target === n.id).map((e) => boxOfFlow(e.fid));
        const v = only(fs); if (v != null) box.set(n.id, v);
      } else if (n.input) {                                // an auxiliary: by the flows whose rates read it
        const fs = edges.filter((e) => e.toEdge && e.source === n.id).map((e) => edgeById.get(e.toEdge)).filter(Boolean).map((e) => boxOfFlow(e.fid));
        const v = only(fs); if (v != null) box.set(n.id, v);
      }
    }
    const scope = (v) => `${label}=${v}`;
    const outNodes = nodes.map((n) => {
      if (!box.has(n.id)) return n;
      const v = box.get(n.id), tags = n.tags && n.tags.filter((t) => t.text !== scope(v));
      const x = { ...n, box: v };
      if (n.tags) { if (tags.length) x.tags = tags; else delete x.tags; }
      return x;
    });
    const outEdges = edges.map((e) => {
      if (e.toEdge || !e.flowPart || !cross.has(e.fid)) return e;
      const c = cross.get(e.fid), a = box.get(e.source), b = box.get(e.target);
      if (a == null || b == null || a === b) return e;
      const sim = (c.simulated_flows || []).includes(e.fid);
      const lines = Array.isArray(e.label) ? e.label.slice() : e.label ? [e.label] : [];
      return { ...e, cross: [a, b], cls: `${e.cls || ""} ng-box-cross`, ...(sim ? { dash: "6 4" } : {}),
               label: lines.length ? [lines[0], `${a} → ${b}`, ...lines.slice(1)] : [`${a} → ${b}`] };
    });
    const values = partition.groups.map((g) => g.value).filter((v) => outNodes.some((n) => n.box === v));
    const pairs = partition.crossing.filter((c) => c.count || c.simulated).map((c) => ({ between: c.between, count: c.count, simulated: c.simulated,
      text: pairText(c), short: c.count ? `${plural(c.count, "flow", "flows")}${c.simulated ? ` · ${c.simulated} simulated` : ""}` : `${c.simulated} simulated`, dashed: !c.count, flows: c.flows }));
    return { nodes: outNodes, edges: outEdges, boxes: values, pairs,
             outside: { stocks: partition.unassigned.stocks.slice(), machines: partition.spanning.map((s) => ({ machine: s.machine, groups: s.groups.slice() })) } };
  }

  // a box's title is a focus chip of the core's own offer (B11): one offer per group, titled by its
  // value, its subset the group's stocks, flows and machines (by id); listed on the box, not in the row
  function offers(partition) {
    return ((partition && partition.groups) || []).map((g) => ({ title: g.value, row: false,
      subtitle: `${plural(g.stocks.length, "stock", "stocks")}`,
      get: () => ({ stocks: g.stocks.slice(), flows: g.flows.slice(), machines: g.machines.slice(), reason: `the ${partition.label} ${g.value}: its box` }) }));
  }

  // the phone list's sections (B13): one per group (its stocks, its flows), then "between subsystems"
  // with the crossing flows by pair, then "outside every subsystem" with the unassigned stocks and
  // flows and the machines in no group or in several. Ids only; the page names them.
  function sections(partition) {
    if (!partition) return null;
    return { groups: partition.groups.map((g) => ({ value: g.value, stocks: g.stocks.slice(), flows: g.flows.slice(), machines: g.machines.slice() })),
             between: partition.crossing.map((c) => ({ between: c.between, flows: c.flows.slice(), text: pairText(c) })),
             outside: { stocks: partition.unassigned.stocks.slice(), flows: partition.unassigned.flows.slice(), machines: partition.unassigned.machines.slice(),
                        spanning: partition.spanning.map((s) => ({ machine: s.machine, groups: s.groups.slice() })) } };
  }
  // how a machine outside every box is said: "in two subsystems (a, b): outside the boxes"
  const spanText = (s) => `in ${s.groups.length === 2 ? "two" : s.groups.length} subsystems (${s.groups.join(", ")}): outside the boxes`;

  // the hash: "#boxes=<label>" beside "focus=" and a part's id (focus.js); "off" when turned off
  const fromHash = (hash) => { const m = /(?:^#|&)boxes=([^&]*)/.exec(String(hash || "")); return m ? decodeURIComponent(m[1]) : null; };
  function hashWith(value, hash) {
    const rest = String(hash || "").replace(/^#/, "").split("&").filter((p) => p && !p.startsWith("boxes="));
    const h = [...(value != null ? ["boxes=" + encodeURIComponent(value)] : []), ...rest].join("&");
    return h ? "#" + h : "";
  }
  // the layout key of a partition: each keeps its own saved layout (B12)
  const layoutKey = (base, partition) => (partition ? `${base}|boxes=${partition.label}` : base);

  return { choices, choose, apply, offers, sections, pairText, spanText, nameOf, fromHash, hashWith, layoutKey };
});
