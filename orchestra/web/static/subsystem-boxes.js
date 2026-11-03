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
// - **Declared** (B14, §5): a group a declared subsystem names or gathers carries its ``name``: the
//   box is titled by it, "named by <who>" (its provenance) and the raw value said on hover; a member
//   it gathers that the model (or the map) no longer has is drawn as a ghost in its box (``ghosts``).
// - **The Machines page's event map** (``applyMap``, step 3): every group a box, as on the Dynamics
//   diagram (the owner, 2026-11-02: "The event map should show multiple system boxes as well"), laid
//   side by side; a box around the machines of its group, one no machine acts only in drawn with its
//   line inside ("no machine acts only here"), the machines acting there and elsewhere outside it,
//   named on hover; an event type inside a box when the API placed it there (every machine on it is
//   in the box); a hand-off between machines of two boxes drawn across, each pair's count between them.
// - **Offered** partitions (``Orchestra.subsystems.offer``, subsystem-offers.js) are listed after the
//   ones the API reports, display only, stored nowhere.
//
// Shared by the pages (global SubsystemBoxes) and the Node tests (tests/subsystems).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SubsystemBoxes = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  // a partition as the control names it: "workflow · 2 boxes · 3 crossing"; every group is a box on
  // both maps (on the event map one no machine acts only in is drawn empty, its line inside it)
  const drawable = (p) => p.groups.length;
  const isMap = (p) => p.groups.some((g) => g.events);
  // how many machines a map partition puts in a box
  const boxedMachines = (p) => p.groups.reduce((a, g) => a + (g.machines || []).length, 0);
  // the control's name: "workflow · 2 boxes · 1 crossing"; on the map "place · 1 box · 5 machines"
  const nameOf = (p) => (isMap(p) ? `${p.label} · ${plural(drawable(p), "box", "boxes")} · ${plural(boxedMachines(p), "machine", "machines")}${p.crossed ? ` · ${p.crossed} crossing` : ""}`
    : `${p.label} · ${plural(drawable(p), "box", "boxes")} · ${p.crossed} crossing${p.crossed_simulated ? ` (${p.crossed_simulated} simulated)` : ""}`);
  // the control's entries: each partition the API reports, the default first, then the offered
  // (``offered``: partitions made from a page extension's offer), then off
  function choices(subs, offered = []) {
    const parts = ((subs && subs.partitions) || []).slice();
    const d = subs && subs.default;
    parts.sort((a, b) => (a.label === d ? -1 : b.label === d ? 1 : 0));
    const taken = new Set(parts.map((p) => p.label));
    return [...parts.map((p) => ({ value: p.label, text: nameOf(p) })),
            ...offered.filter((p) => !taken.has(p.label)).map((p) => ({ value: p.label, text: `${nameOf(p)} · offered` })), { value: "off", text: "off" }];
  }
  // which partition is drawn: what the viewer chose (``wanted``, from the hash: a label or "off"),
  // when the API still reports it or an extension still offers it; else the default; null for none
  function choose(subs, wanted, offered = []) {
    const parts = [...((subs && subs.partitions) || []), ...offered];
    if (wanted === "off") return null;
    return parts.find((p) => p.label === wanted) || parts.find((p) => p.label === (subs && subs.default)) || null;
  }
  // why the machines in several groups are outside every box, in the owner's terms (a machine belongs
  // to one subsystem only): "6 machines act in both workflows (delivery_sail, pr_watch): outside every
  // box"; when no box holds a machine, said so. "" when no machine is in two groups and some box holds one
  function outsideNote(p) {
    if (!p) return "";
    const by = new Map();
    for (const s of p.spanning || []) { const k = s.groups.join("|"); by.set(k, [...(by.get(k) || []), s.machine]); }
    const said = [...by].map(([k, ms]) => { const gs = k.split("|");
      return `${plural(ms.length, "machine acts", "machines act")} in ${gs.length === 2 ? "both" : gs.length} ${p.label}s (${gs.join(", ")})`; });
    if (!said.length) return boxedMachines(p) ? "" : `no machine's guessed flows lie in one ${p.label}: no box holds a machine`;
    return `${said.join("; ")}: outside every box${boxedMachines(p) ? "" : ", so no box holds a machine"} (a machine belongs to one subsystem only)`;
  }
  // the machines that act in a group and elsewhere (in two groups or more): outside its box
  const actingIn = (partition, v) => ((partition && partition.spanning) || []).filter((s) => s.groups.includes(v)).map((s) => s.machine);
  // the line inside a box no machine acts only in
  const EMPTY_LINE = "no machine acts only here";
  const emptyHint = (partition, v, name = (id) => id) => { const ms = actingIn(partition, v).map(name);
    return ms.length ? `${EMPTY_LINE}: ${ms.join(", ")} ${ms.length === 1 ? "acts" : "act"} here and elsewhere, outside every box` : `${EMPTY_LINE}: no machine acts here`; };
  // a group's title: a declared subsystem's name, else its value
  const titleOf = (g) => (g && g.name) || (g && g.value);
  const titles = (partition) => { const m = new Map(((partition && partition.groups) || []).map((g) => [g.value, titleOf(g)])); return (v) => m.get(v) ?? v; };
  // who named a declared subsystem, from its provenance: "you" for the owner on a page, "the owner
  // (quoted), per <source>" through a plugin, else its author ("the Supervisor"); confirmed by the owner said so
  function namedBy(g) {
    if (!g || !g.declared) return "";
    const p = g.provenance || {}, src = p.source || p.author || "a plugin";
    const who = p.author === "owner" ? (p.via === "page" || !p.via ? "you" : `the owner (quoted), per ${src}`) : `the ${src.charAt(0).toUpperCase() + src.slice(1)}`;
    return `named by ${who}${g.confirmed && g.confirmed.by === "owner" && p.author !== "owner" ? ", confirmed by you" : ""}`;
  }
  // what a box's title says on hover: who named it and the raw value it names (B14: "the label's raw
  // value is shown in the box's drawer only"), its note, its ghosts
  function hintOf(partition, v) {
    const g = ((partition && partition.groups) || []).find((x) => x.value === v); if (!g) return "";
    const ghosts = g.ghosts ? [...(g.ghosts.stocks || []), ...(g.ghosts.flows || []), ...(g.ghosts.machines || [])] : [];
    const empty = g.events && !(g.machines || []).length && !((g.ghosts && g.ghosts.machines) || []).length;
    return [namedBy(g), g.declared && partition.source !== "declared" ? `${partition.label} = ${g.value}` : "", g.note || "", empty ? emptyHint(partition, v) : "",
            ghosts.length ? `${plural(ghosts.length, "member", "members")} no longer here, drawn as ghosts` : ""].filter(Boolean).join(" · ");
  }
  const between = (a, b) => `${a} and ${b}`;
  // what is written between two boxes: "2 flows between delivery and hotfix", the simulated said
  // apart; on the event map "1 hand-off between a and b · 3 subjects". ``title``: a value's title
  function pairText(c, title = (v) => v) {
    const [a, b] = c.between.map(title);
    if (c.handoffs) return `${plural(c.count, "hand-off", "hand-offs")} between ${between(a, b)}${c.subjects ? ` · ${plural(c.subjects, "subject", "subjects")}` : ""}`;
    if (!c.count && c.simulated) return `${plural(c.simulated, "simulated flow", "simulated flows")} between ${between(a, b)}`;
    return `${plural(c.count, "flow", "flows")} between ${between(a, b)}${c.simulated ? ` · ${c.simulated} simulated` : ""}`;
  }
  const shortText = (c) => (c.handoffs ? plural(c.count, "hand-off", "hand-offs")
    : c.count ? `${plural(c.count, "flow", "flows")}${c.simulated ? ` · ${c.simulated} simulated` : ""}` : `${c.simulated} simulated`);

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
    // a member a declared subsystem gathers that the model no longer has: a ghost in its box
    for (const g of partition.groups) for (const [kind, keys] of [["stock", (g.ghosts && g.ghosts.stocks) || []], ["flow", (g.ghosts && g.ghosts.flows) || []]])
      for (const k of keys) outNodes.push(ghost(`sub-ghost:${kind}:${k}`, k, g, kind === "stock" ? "gathered stock · not in this model" : "gathered flow · not in this model"));
    const values = partition.groups.map((g) => g.value).filter((v) => outNodes.some((n) => n.box === v));
    const pairs = pairsOf(partition);
    return { nodes: outNodes, edges: outEdges, boxes: values, pairs,
             outside: { stocks: (partition.unassigned.stocks || []).slice(), machines: partition.spanning.map((s) => ({ machine: s.machine, groups: s.groups.slice() })) } };
  }

  const ghost = (id, label, g, caption) => ({ id, kind: "box", label, lines: [label], caption, color: "#5b6272", fill: "#07090d", cls: "im-ghost im-gone",
    box: g.value, subGhost: { group: titleOf(g), caption } });
  // each pair's count, written between its boxes
  function pairsOf(partition) {
    const t = titles(partition);
    return partition.crossing.filter((c) => c.count || c.simulated).map((c) => ({ between: c.between, count: c.count, simulated: c.simulated,
      text: pairText(c, t), short: shortText(c), dashed: !c.count && !c.handoffs, flows: c.flows || [], handoffs: c.handoffs }));
  }

  // The Machines page's event map (machines.html, its nodes and edges as NetGraph draws them) with
  // ``partition``'s boxes (/api/machines ``subsystems``): a machine node ("m:<id>") gains ``box``, its
  // group's value; an event type node ("ev:<type>", or several types folded into one node, ``labels``)
  // is in a box when every type on it is inside that box; channels and stubs in none; an edge between
  // two nodes of different boxes is drawn across (``cross``). A machine a declared subsystem gathers
  // that the map does not show is a ghost in its box. -> {nodes, edges, boxes, pairs, outside: {machines, spanning}}
  function applyMap(nodes, edges, partition) {
    if (!partition) return { nodes, edges, boxes: [], pairs: [], outside: { machines: [], spanning: [] } };
    const mBox = new Map(), eBox = new Map();
    for (const g of partition.groups) { for (const m of g.machines || []) mBox.set(m, g.value); for (const t of g.events || []) eBox.set(t, g.value); }
    const boxOf = (n) => {
      if (n.machine || /^m:/.test(n.id)) return mBox.get(n.mid || n.id.replace(/^m:/, ""));
      if (!/^ev:/.test(n.id)) return undefined;
      const vs = new Set((n.labels || [n.label]).map((t) => eBox.get(t)));
      return vs.size === 1 && !vs.has(undefined) ? [...vs][0] : undefined;
    };
    const outNodes = nodes.map((n) => { const v = boxOf(n); return v == null ? n : { ...n, box: v, anchor: undefined }; });
    const shown = new Set(nodes.filter((n) => n.machine || /^m:/.test(n.id)).map((n) => n.mid || n.id.replace(/^m:/, "")));
    for (const g of partition.groups) for (const m of (g.ghosts && g.ghosts.machines) || []) if (!shown.has(m))
      outNodes.push({ id: "sub-ghost:m:" + m, kind: "circle", label: m, color: "#07090d", stroke: "#5b6272", cls: "im-ghost", box: g.value,
        subGhost: { group: titleOf(g), caption: "gathered machine · not on the bus" } });
    const at = new Map(outNodes.map((n) => [n.id, n.box]));
    const outEdges = edges.map((e) => { const a = at.get(e.source), b = at.get(e.target);
      return a != null && b != null && a !== b ? { ...e, cross: [a, b], cls: `${e.cls || ""} ng-box-cross` } : e; });
    // every group is a box (as on the Dynamics diagram): one with nothing in it holds its muted line
    for (const g of partition.groups) if (!outNodes.some((n) => n.box === g.value)) outNodes.push(emptyNode(partition, g));
    const values = partition.groups.map((g) => g.value);
    return { nodes: outNodes, edges: outEdges, boxes: values, pairs: pairsOf(partition),
             outside: { machines: (partition.unassigned.machines || []).slice(), spanning: partition.spanning.map((s) => ({ machine: s.machine, groups: s.groups.slice() })) } };
  }
  // a box no machine acts only in: its line, muted, inside it (inert: it opens nothing); the machines
  // acting there and elsewhere named on hover
  const emptyNode = (partition, g) => ({ id: "sub-empty:" + g.value, kind: "box", inert: true, cls: "ng-sub-empty", label: EMPTY_LINE, lines: [EMPTY_LINE],
    color: "transparent", fill: "transparent", textColor: "var(--muted)", box: g.value, subEmpty: { group: titleOf(g), acting: actingIn(partition, g.value) } });
  // where each box's members are pulled on the map: the boxes side by side in rows filling a wide view
  // (as the Dynamics diagram packs them), in the partition's order (they replace the announced groups'
  // anchors while boxes are on); {value: [fx, fy]}
  function anchors(partition) {
    const vs = ((partition && partition.groups) || []).map((g) => g.value);
    const cols = Math.min(vs.length, Math.ceil(Math.sqrt(vs.length * 2.1))) || 1, rows = Math.ceil(vs.length / cols) || 1;
    const at = (i, n) => (n < 2 ? 0.5 : 0.15 + 0.7 * i / (n - 1));
    return Object.fromEntries(vs.map((v, i) => { const r = Math.floor(i / cols), inRow = r < rows - 1 ? cols : vs.length - r * cols;
      return [v, [at(i % cols, inRow), at(r, rows)]]; }));
  }
  // A focus on a box no machine acts only in (its title pressed): the focus names no machine, so the
  // map cut to it (focus.js eventMap) is empty; the box is drawn with its line and each machine acting
  // there (in it and elsewhere) as a grey named stub, joined to the box, as a focus draws what is
  // outside it. ``fc``: Focus.eventMap's answer; ``nodes``: the map before the cut; ``name(node)``: a
  // stub's name. -> fc, with the box and the stubs added (unchanged for any other focus)
  function focusEmpty(fc, partition, title, nodes, { name } = {}) {
    const g = ((partition && partition.groups) || []).find((x) => titleOf(x) === title);
    const box = g && nodes.find((n) => n.id === "sub-empty:" + g.value);
    if (!box) return fc;
    const ms = actingIn(partition, g.value).map((m) => nodes.find((n) => n.machine && (n.mid || n.id.replace(/^m:/, "")) === m)).filter(Boolean);
    const stubs = ms.map((n, i) => ({ id: "out:" + n.id, kind: "cloud", stub: true, charge: -120, label: (name && name(n)) || n.label, of: n.id, outside: true,
      anchor: [0.04, (i + 1) / (ms.length + 1)] }));
    const edges = stubs.map((s) => ({ id: s.id + ">" + box.id, source: s.id, target: box.id, cls: "ng-focus-cross", dash: "2 4", width: 1, color: "#64748b",
      vias: [`${s.label} acts here and elsewhere: outside every box`] }));
    const have = new Set(fc.nodes.map((n) => n.id));
    return { ...fc, nodes: [...fc.nodes.filter((n) => n.id !== box.id), box, ...stubs.filter((s) => !have.has(s.id))], edges: [...fc.edges, ...edges],
             outside: [...new Set([...fc.outside, ...stubs.map((s) => s.label)])] };
  }

  // a box's title is a focus chip of the core's own offer (B11): one offer per group, titled by its
  // title (a declared name, else its value), its subset the group's stocks, flows, machines and event
  // types (by id); listed on the box, not in the row
  function offers(partition) {
    return ((partition && partition.groups) || []).map((g) => ({ title: titleOf(g), row: false,
      subtitle: g.stocks ? `${plural(g.stocks.length, "stock", "stocks")}` : `${plural((g.machines || []).length, "machine", "machines")}`,
      get: () => ({ stocks: (g.stocks || []).slice(), flows: (g.flows || []).slice(), machines: (g.machines || []).slice(), events: (g.events || []).slice(),
                    reason: g.name ? `${g.name}: its box` : `the ${partition.label} ${g.value}: its box` }) }));
  }

  // the phone list's sections (B13): one per group (its stocks, its flows; on the map its machines,
  // and for a group no machine acts only in, the line saying so), then "between subsystems"
  // with the crossing flows by pair, then "outside every subsystem" with the unassigned stocks and
  // flows and the machines in no group or in several. Ids only; the page names them.
  // ``name(id)``: how a machine is named in an empty group's line
  function sections(partition, { name } = {}) {
    if (!partition) return null;
    const t = titles(partition);
    return { groups: partition.groups.map((g) => ({ value: g.value, title: titleOf(g), stocks: (g.stocks || []).slice(), flows: (g.flows || []).slice(),
                                                    machines: (g.machines || []).slice(), events: (g.events || []).slice(), acting: actingIn(partition, g.value),
                                                    // the phone list's line under an empty group's heading (the map's machines only)
                                                    ...(g.events && !(g.machines || []).length ? { empty: true, line: emptyHint(partition, g.value, name) } : {}) })),
             between: partition.crossing.map((c) => ({ between: c.between, flows: (c.flows || []).slice(), handoffs: (c.handoffs || []).slice(), text: pairText(c, t) })),
             outside: { stocks: (partition.unassigned.stocks || []).slice(), flows: (partition.unassigned.flows || []).slice(), machines: (partition.unassigned.machines || []).slice(),
                        events: (partition.unassigned.events || []).slice(), spanning: partition.spanning.map((s) => ({ machine: s.machine, groups: s.groups.slice() })) } };
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

  return { choices, choose, outsideNote, emptyHint, EMPTY_LINE, focusEmpty, boxedMachines, apply, applyMap, anchors, offers, sections, pairText, spanText, nameOf, titleOf, titles, namedBy, hintOf, fromHash, hashWith, layoutKey };
});
