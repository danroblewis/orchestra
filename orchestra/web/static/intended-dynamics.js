// The intended model on the Dynamics page (docs/proposals/intended-model.md §3, §7; frames D1–D3):
// what the owner expects drawn beside what discovery found, from ``MODEL.intended`` (the
// /api/dynamics/model answer's declared layer, web/intended.py). It draws:
//   - ghosts: an expected stock or effect absent from the version shown, the same shape, darker
//     fill and dashed outline, label readable, its tag ("expected · not in vN", "not measured"),
//     and its candidate line ("may be: … · ask <machine> to link", naming the machine that listens
//     for requests, ``intended.askers``; intended-core.js); declared flows absent as
//     dashed ghost edges; ``intended.predicted`` flows as ghost edges;
//   - the marks: "new in vN" rings and tags, removed parts struck through as ghosts, the gold pin
//     on what is expected, simulated parts hatched and tagged;
//   - the version bar's "changes since vN" switch (on by default; off asks for ``since=off``), the
//     legend's entries, the Stocks table's Expected group and the tables' marks, and the Changes
//     panel beside the loops, with expect / ignore on every + row.
// The page controls are observations (POST /api/intended/control, AGENTS.md rule 9 as amended);
// everything else is read only, and what only a machine can do says to ask the one that listens for requests.
// The drawers are in intended-drawers.js. Nothing here changes how the page draws without it.
const Intended = (() => {
  let ON = new URLSearchParams(location.search).get("since") !== "off";   // "changes since" is on by default
  const it = () => (MODEL && MODEL.intended && !MODEL.intended.error ? MODEL.intended : null);
  const hhmm = (t) => new Date(t * 1000).toTimeString().slice(0, 5);
  const agoText = (t) => { const s = Date.now() / 1000 - t; return s < 90 ? "just now" : ago(s) + " ago"; };
  const vlabel = () => { const x = it(); return x && x.shown ? `v${x.shown}` : "this discovery"; };
  // the machines that listen for the owner's requests (web/intended.py askers), null while the bus is unread
  const askers = () => { const x = it(); return x && Array.isArray(x.askers) ? x.askers : null; };
  const ask = (what) => IntendedCore.asker(askers()).ask(what);

  // ---- keys: what marks match by, since discovered ids are not stable; the server's (sd/intended/keys.py),
  // sent as ``intended.keys`` ({stocks: {id: key}, flows: {id: key}}), never made here ----
  const keys = () => { const x = it(); return (x && x.keys) || { stocks: {}, flows: {} }; };
  const stockKey = (s) => (s ? keys().stocks[s.id] || null : null);
  const flowKey = (f) => (f ? keys().flows[f.id] || null : null);
  const stockOfKey = (key) => (key ? MODEL.stocks.find((s) => keys().stocks[s.id] === key || s.id === key) : null);
  const marksOf = (part, id) => { const x = it(); return (x && ((x.marks || {})[part === "stock" ? "stocks" : "flows"] || {})[id]) || []; };
  const hasEarlier = () => { const x = it(), vs = (MODEL && MODEL.versions) || []; return !!x && vs.findIndex((v) => v.version === x.shown) > 0; };
  const nameOf = (id) => (id && MODEL.stocks.some((s) => s.id === id) ? stockName(id) : nice(id));
  // a stock of the base version, named as the page names stocks: by this model when it has it, else
  // among this model's stocks from the base's own series (web/intended.py removed_facts)
  function baseEnd(id, series, full) {
    if (!id) return "outside";
    if (MODEL.stocks.some((s) => s.id === id)) return stockName(id);
    if (!series) return full || nice(id);
    const m = { stocks: [...MODEL.stocks, { id: "\u0000base", name: full || id, series }], flows: [] };
    return SDGraph.stockName(m, "\u0000base");
  }
  const removedStockName = (r) => baseEnd(r.id, r.series, r.full_name || r.name);
  // a removed flow by its counter, as the page names flows (its own family: its other labels said)
  const removedFlowName = (r) => (r.counter ? SDGraph.flowName({ stocks: [], flows: [{ id: "g", from: r.from, to: r.to, counter: r.counter }] }, { id: "g" }) : r.name || r.key);
  const who = (p) => { if (!p) return ""; if (p.author === "owner") return IntendedCore.owner(p); const w = p.source || p.author || ""; return w && `the ${w.charAt(0).toUpperCase() + w.slice(1)}`; };   // as byWhom on the Machines page
  // what a declared element's tag says: who put it there; "not in vN" only for a part an earlier
  // version had (a mark tracked by inference since a version), never for one never measured or
  // never found (mockups/README.md: a declared stock with no series is "not measured")
  const wasPresent = (x) => !!(x.was_present || (!x.declared && x.since_version != null));
  const declTag = (x) => {
    if (x.state === "proposed") return { text: `unconfirmed · proposed by ${who(x.provenance)}`, cls: "im-t-unconf" };
    if (x.present) return { text: "expected", cls: "im-t-exp" };
    if (hasEarlier() && wasPresent(x) && x.measured !== false) return { text: `expected · not in ${vlabel()}`, cls: "im-t-ghost" };
    const p = x.provenance || {};
    return { text: `expected · declared by ${who(p)}${p.at ? " · " + agoText(p.at) : ""}`, cls: p.author === "owner" ? "im-t-user" : "im-t-ghost" };
  };
  const recording = (x) => ((x.measure || {}).recording && x.measure.recording.points ? x.measure.recording : null);
  const subline = (x) => (!x.measured ? "not measured" : recording(x) ? "no series yet · recording" : "no series of its own");

  // ---- SVG marks: a pill tag, a ring, a pin, a hatch ----
  // ``max``: the widest it may be (a ghost's tags stay within its box); longer text is cut, in full on hover
  function svgTag(g, x, y, text, cls = "", max = Infinity) {
    const fit = Math.max(4, Math.floor((max - 14) / 5.6)), shown = text.length > fit ? text.slice(0, fit - 1) + "…" : text;
    const t = g.append("g").attr("class", "im-svgtag " + cls).attr("transform", `translate(${x},${y})`);
    if (shown !== text) t.append("title").text(text);
    t.append("rect").attr("x", 0).attr("y", -9).attr("width", shown.length * 5.6 + 14).attr("height", 16).attr("rx", 8);
    t.append("text").attr("x", 7).attr("y", 3).text(shown);
  }
  function svgRing(g, s) {
    g.insert("rect", ":first-child").attr("class", "im-ring").attr("x", -s.w / 2 - 6).attr("y", -s.h / 2 - 6).attr("width", s.w + 12).attr("height", s.h + 12).attr("rx", 10);
  }
  function svgPin(g, x, y, label) {
    const p = g.append("g").attr("class", "im-pin").attr("transform", `translate(${x},${y})`);
    p.append("circle").attr("cy", -6).attr("r", 4);
    p.append("line").attr("x1", 0).attr("y1", -2).attr("x2", 0).attr("y2", 5);
    if (label) p.append("text").attr("x", 7).attr("y", -2).text(label);
  }
  function hatch(g, s) {
    const svg = g.node().ownerSVGElement;
    if (svg && !svg.querySelector("#im-hatch")) d3.select(svg).insert("defs", ":first-child").html('<pattern id="im-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" class="im-hatchline"/></pattern>');
    g.append("rect").attr("class", "im-hatch").attr("x", -s.w / 2 + 1.5).attr("y", -s.h / 2 + 1.5).attr("width", s.w - 3).attr("height", s.h - 3).attr("rx", 4).attr("fill", "url(#im-hatch)");
  }

  // ---- the graph ----
  // what the page's SDGraph.build made, with the intended model's parts added and its marks set
  function extend(g) {
    const x = it();
    if (!x) return g;
    const has = (id) => g.nodes.some((n) => n.id === id);
    for (const n of g.nodes) if (n.sid) n.im = marksOf("stock", n.sid);
    // a flow the comparison marks is drawn even with no events yet (the page hides those otherwise)
    for (const f of MODEL.flows) {
      if (!marksOf("flow", f.id).length || g.edges.some((e) => e.flowPart && e.fid === f.id) || !(f.from && has("s:" + f.from)) || !(f.to && has("s:" + f.to))) continue;
      const id = `s:${f.from}>s:${f.to}:${f.id}`;
      g.edges.push({ id, source: "s:" + f.from, target: "s:" + f.to, color: "#94a3b8", width: 3, distance: 230, strength: 0.6, cls: "", fid: f.id, flowPart: true, bend: 18,
        label: [eqText(f, true), ""] });
      g.flowEdge["f:" + f.id] = id;
    }
    for (const e of g.edges) {
      if (!e.flowPart) continue;
      const mk = marksOf("flow", e.fid), extra = [];
      if (mk.includes("new")) { e.cls = (e.cls || "") + " im-new-edge"; e.color = "#6ea8fe"; extra.push(`new in ${vlabel()}`); }
      if (mk.includes("expected")) extra.push("⌖ expected");
      if (mk.includes("simulated")) { e.dash = "2 4"; e.cls = (e.cls || "") + " im-sim-edge"; extra.push("simulated"); }
      if (extra.length) e.label = [e.label[0], [e.label[1], ...extra].filter(Boolean).join(" · ")];
    }
    // an end of a declared or predicted flow: a stock shown, a ghost, a stock by its key, or outside
    const end = (ref, other, id, dir) => {
      if (ref == null) { const c = `c:${dir}:x:${id}`; if (other && !has(c)) g.nodes.push({ id: c, kind: "cloud", charge: -20, tether: other }); return other ? c : null; }
      const decl = x.expected.find((e) => e.id === ref && e.part !== "flow");
      if (decl) return decl.found_id && has("s:" + decl.found_id) ? "s:" + decl.found_id : has("x:" + ref) ? "x:" + ref : null;
      if (has("s:" + ref)) return "s:" + ref;
      const s = stockOfKey(ref);
      return s && has("s:" + s.id) ? "s:" + s.id : null;
    };
    for (const e of x.expected.filter((e) => e.part !== "flow" && !e.present)) {
      const id = "x:" + e.id, name = e.name || e.id;
      g.nodes.push({ id, kind: "box", ghost: e, label: name, lines: [name], caption: e.part === "effect" ? "expected effect" : "expected stock",
        w: Math.max(180, name.length * 7 + 30), h: 92, dashed: true, color: "#8b95a7", fill: "#07090d", charge: -1600, sub: " ",
        cls: "im-ghost" + (e.state === "proposed" ? " im-user" : "") + (e.simulated ? " im-sim" : "") });
      // drawn beside the stock the owner said it is near (an invisible link the layout pulls on)
      const near = stockOfKey(e.near);
      if (near && has("s:" + near.id)) g.edges.push({ id: `${id}~near`, source: "s:" + near.id, target: id, cls: "im-near", arrow: false, width: 0, distance: 200, strength: 0.4, color: "transparent" });
    }
    for (const r of (x.removed || {}).stocks || []) {
      const id = "x:gone:" + (r.id || r.key), name = removedStockName(r);
      g.nodes.push({ id, kind: "box", gone: r, label: name, lines: [name], caption: "removed stock", w: Math.max(180, name.length * 7 + 30), h: 92, dashed: true,
        color: "#5b6272", fill: "#07090d", charge: -1600, sub: " ", cls: "im-ghost im-gone" });
    }
    for (const r of (x.removed || {}).flows || []) {
      const a = r.from && has("s:" + r.from) ? "s:" + r.from : null, b = r.to && has("s:" + r.to) ? "s:" + r.to : null;
      if (!a || !b) continue;                            // a removed flow to or from outside is listed, not drawn
      g.edges.push({ id: "gone:" + (r.id || r.key), source: a, target: b, color: "#5b6272", dash: "3 5", width: 2.2, bend: 70, cls: "im-removed", gone: r,
        label: [`${r.rate && r.origin === "fitted" ? r.rate + " · " : ""}gone in ${vlabel()}`, `was ${r.origin || "found"} in v${r.in}`] });
    }
    for (const e of x.expected.filter((e) => e.part === "flow" && !e.present)) {
      const a = end(e.from, null, e.id, "in"), b = end(e.to, null, e.id, "out");
      const src = a || (b && e.from == null ? end(null, b, e.id, "in") : null), dst = b || (a && e.to == null ? end(null, a, e.id, "out") : null);
      if (src && dst) g.edges.push({ id: "x:flow:" + e.id, source: src, target: dst, color: "#8b95a7", dash: "7 5", width: 2, bend: 40, cls: "im-ghost-edge", ghostFlow: e,
        label: [e.name || "expected flow", e.why || "expected"] });
    }
    // flows a machine's draft expected effect predicts (rule 6 as amended: they carry no machine)
    // ``{from, to, appears, key, present, candidates}``: present, the flow found carries the mark; absent, a ghost
    (x.predicted || []).forEach((p, i) => {
      if (p.present) { const e = g.edges.find((y) => y.flowPart && y.fid === p.id); if (e) e.label = [e.label[0], [e.label[1], "predicted"].filter(Boolean).join(" · ")]; return; }
      const id = `${p.from || "outside"}>${p.to || "outside"}#${i}`;
      const a = end(p.from, null, id, "in"), b = end(p.to, null, id, "out");
      const src = a || (b && p.from == null ? end(null, b, id, "in") : null), dst = b || (a && p.to == null ? end(null, a, id, "out") : null);
      if (src && dst) g.edges.push({ id: "x:pred:" + id, source: src, target: dst, color: "#c4b5fd", dash: "2 5", width: 2, bend: 50, cls: "im-pred-edge", predicted: p,
        label: [`${nameOf(p.from)} → ${nameOf(p.to)}`, "predicted · a machine's expected effect"] });
    });
    return g;
  }
  // a node's drawing: the page's own (the tank, the sparkline), then the intended model's marks
  function decorator(n, base) {
    if (!n.ghost && !n.gone && !(n.im && n.im.length)) return base;
    return (g, node, s) => {
      if (base) base(g, node, s);
      if (node.ghost) return ghost(g, node.ghost, s);
      if (node.gone) { g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", -s.h / 2 + 48).text(`in v${node.gone.in}`); return svgTag(g, -s.w / 2, -s.h / 2 - 14, `gone in ${vlabel()}`, "im-t-gone"); }
      const mk = node.im || [];
      if (mk.includes("simulated")) { hatch(g, s); svgTag(g, -s.w / 2, s.h / 2 + 14, "simulated", "im-t-sim"); }
      if (mk.includes("new")) { svgRing(g, s); svgTag(g, -s.w / 2, -s.h / 2 - 16, `new in ${vlabel()}`, "im-t-new"); }
      if (mk.includes("expected")) svgPin(g, mk.includes("new") ? s.w / 2 - 70 : -s.w / 2 + 6, -s.h / 2 - 12, "expected");
    };
  }
  function ghost(g, x, s) {
    // a larger target than its box, for a finger on a phone
    g.insert("rect", ":first-child").attr("class", "ng-grab").attr("x", -s.w / 2 - 14).attr("y", -s.h / 2 - 22).attr("width", s.w + 28).attr("height", s.h + 44).attr("rx", 10);
    if (x.simulated) hatch(g, s);
    g.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", -s.h / 2 + 48).text(subline(x));
    // the header tag in full, centred on the box (frame D1); "not measured" is said once, by the box's line
    const t = declTag(x), tw = t.text.length * 5.6 + 14;
    svgTag(g, -tw / 2, -s.h / 2 - 14, t.text, t.cls);
    const below = [];
    if (x.simulated) below.push(["simulated", "im-t-sim"]);
    if (x.note) below.push([`your note · ${x.note}`, "im-t-user"]);
    if ((x.candidates || []).length) below.push([`may be: ${x.candidates.map((c) => nameOf(c.id)).join(", ")} · ${ask("link")}`, "im-t-ghost"]);
    below.forEach(([text, cls], i) => svgTag(g, -s.w / 2, s.h / 2 + 14 + i * 19, text, cls));
  }
  function tip(x) {
    if (x.ghost) return `<div class="tt">${esc(x.ghost.name || x.ghost.id)}</div><div class="muted">${esc(declTag(x.ghost).text)}${x.ghost.measured ? "" : " · not measured"}</div><div class="hint">click for how it is measured</div>`;
    if (x.gone) return `<div class="tt"><s>${esc(x.gone.counter || x.gone.from !== undefined ? `${baseEnd(x.gone.from, x.gone.from_series, x.gone.from_name)} → ${baseEnd(x.gone.to, x.gone.to_series, x.gone.to_name)}` : removedStockName(x.gone))}</s></div><div class="muted">${x.gone.counter ? esc(removedFlowName(x.gone)) + " · " : ""}gone in ${esc(vlabel())}; was ${esc(x.gone.origin || "found")} in v${esc(x.gone.in)}</div>`;
    if (x.ghostFlow) return `<div class="tt">${esc(x.ghostFlow.name)}</div><div class="muted">${esc(x.ghostFlow.why || "expected")}</div><div class="hint">click for details</div>`;
    if (x.predicted) return `<div class="tt">${esc(nameOf(x.predicted.from))} → ${esc(nameOf(x.predicted.to))}</div><div class="muted">predicted to appear by a machine's expected effect: a prediction, judged later, not an association</div>`
      + ((x.predicted.candidates || []).length ? `<div class="muted">may be: ${x.predicted.candidates.map((c) => esc(c.id || c.key)).join(", ")}</div>` : "");
    return null;
  }
  function click(x) {
    if (x.ghost) { IntendedDrawers.openExpected(x.ghost.id); return true; }
    if (x.ghostFlow) { IntendedDrawers.openExpectedFlow(x.ghostFlow.id); return true; }
    return !!(x.gone || x.predicted);
  }

  // ---- the version bar: "changes since vN", on by default ----
  function versionBar() {
    const x = it(), vs = MODEL.versions || [];
    if (!x || !hasEarlier()) return "";
    const i = vs.findIndex((v) => v.version === x.shown), base = x.since ?? (vs[i - 1] || {}).version;
    return (`<button type="button" class="im-toggle ${ON ? "on" : ""}" id="im-since" role="switch" aria-checked="${ON}" onclick="Intended.toggleSince()"
      title="draw what changed since the version before: new stocks and flows ringed, removed ones as ghosts"><span class="im-sw"></span>changes since v${esc(base)}</button>`);
  }
  async function toggleSince() { ON = !ON; await load(); const b = $("im-since"); if (b) b.focus({ preventScroll: true }); }
  const param = () => (ON ? "" : "since=off");

  // ---- the legend ----
  function legend() {
    const x = it();
    if (!x) return "";
    const sim = Object.values(x.marks || {}).some((m) => Object.values(m).some((v) => v.includes("simulated"))) || x.expected.some((e) => e.simulated);
    return `<span class="lg im-lg" title="a stock you said to expect, which this version has"><i class="im-sw-present"></i>expected, present</span>
      <span class="lg im-lg" title="a stock you said to expect, which this version does not have: drawn as a ghost"><i class="im-sw-ghost"></i>expected, missing (ghost)</span>
      ${hasEarlier() && ON && x.since != null ? `<span class="lg im-lg" title="found by this discovery, not in the version it is compared with"><i class="im-sw-new"></i>new in this version</span>
      <span class="lg im-lg" title="in the version it is compared with, not in this one"><i class="im-sw-gone"></i>removed since last version</span>` : ""}`
      + (sim ? `<span class="lg im-lg" title="fitted from a placeholder series, labelled simulated"><i class="im-sw-sim"></i>simulated</span>` : "")
      + ((x.predicted || []).some((p) => !p.present) ? `<span class="lg im-lg"><i class="im-sw-pred"></i>predicted by a machine's expected effect</span>` : "");
  }

  // ---- the tables: the Expected group, the marks, what was removed ----
  function statusText(x) {
    if (x.present) return `found as <b>${esc(nameOf(x.found_id || x.id))}</b>` + (x.declared ? "" : ` <span class="muted">· tracked by inference since v${esc(x.since_version ?? "?")}</span>`);
    const rec = recording(x), opt = rec && ((x.measure || {}).options || []).find((o) => o.key === x.measure.chosen);
    const parts = [!x.measured ? "not measured · no series yet" : rec ? `no series yet → <span class="im-recword">recording</span> <span class="muted">(${esc(rec.instrument || (opt || {}).instrument || "")}, since ${hhmm(rec.since)})</span>`
      : `no series of its own · discovery found none for it in ${esc(vlabel())}`];
    if (x.note) parts.push(`your note · ${esc(x.note)}`);
    if ((x.candidates || []).length) parts.push(`may be: ${x.candidates.map((c) => `<b>${esc(nameOf(c.id))}</b>`).join(", ")} <span class="muted">· ${esc(ask("link"))}</span>`);
    return parts.join("<br>");
  }
  const tag = (text, cls) => `<span class="im-tag ${cls}">${esc(text)}</span>`;
  function tables() {
    const x = it();
    if (!x) return;
    const st = $("stocks"), head = st.querySelector("tr");
    const exp = x.expected.filter((e) => e.part !== "flow"), rows = [];
    for (const e of exp) {
      const row = e.present && st.querySelector(`tr[data-sid="${CSS.escape(e.found_id || e.id || "")}"]`);
      if (row) { row.classList.add("im-exprow"); row.cells[0].insertAdjacentHTML("afterbegin", '<span class="im-pinchip" title="expected: always shown">⌖</span>'); rows.push(row.outerHTML); row.remove(); continue; }
      const t = declTag(e);
      rows.push(`<tr class="im-exprow" data-x="${esc(e.id)}" tabindex="0" role="button" onclick="IntendedDrawers.openExpected('${esc(e.id)}')" onkeydown="if(event.target===this&&(event.key==='Enter'||event.key===' ')){event.preventDefault();IntendedDrawers.openExpected('${esc(e.id)}')}" style="cursor:pointer"><td><span class="im-ghostdot"></span><b>${esc(e.name || nameOf(e.id))}</b>
        ${e.part === "effect" ? tag("effect", "im-t-ghost") : ""} ${tag(t.text.replace(/^expected · /, ""), t.cls)}${e.measured ? "" : " " + tag("not measured", "im-t-ghost")}${e.simulated ? " " + tag("simulated", "im-t-sim") : ""}</td><td class="num">—</td><td class="muted">—</td><td class="muted">${statusText(e)}</td></tr>`);
    }
    const found = st.querySelectorAll("tr[data-sid]").length;
    if (rows.length) head.insertAdjacentHTML("afterend", `<tr class="im-group"><td colspan="4">Expected <span class="count">${rows.length}</span> <span class="muted">· always shown, found or not</span></td></tr>${rows.join("")}
      <tr class="im-group"><td colspan="4">Found by discovery <span class="count">${found}</span></td></tr>`);
    if (rows.length) $("nstocks").textContent = `${MODEL.stocks.length} found · ${rows.length} expected`;
    for (const r of st.querySelectorAll("tr[data-sid]")) markRow(r, marksOf("stock", r.dataset.sid));
    for (const r of $("flows").querySelectorAll("tr[data-fid]")) {
      const mk = marksOf("flow", r.dataset.fid);
      markRow(r, mk);
      if (mk.includes("expected")) r.cells[0].insertAdjacentHTML("afterbegin", '<span class="im-pinchip" title="expected: always shown">⌖</span>');
    }
    for (const r of (x.removed || {}).stocks || []) st.insertAdjacentHTML("beforeend", `<tr class="im-gone"><td><s>${esc(removedStockName(r))}</s> ${tag(`gone in ${vlabel()}`, "im-t-gone")}</td><td class="num">—</td><td></td><td class="muted">${r.origin ? `${esc(r.origin)} ` : ""}in v${esc(r.in)}</td></tr>`);
    for (const e of x.expected.filter((e) => e.part === "flow")) {
      const t = declTag(e);
      $("flows").insertAdjacentHTML("beforeend", `<tr class="im-exprow"><td><span class="im-ghostdot"></span>${esc(e.name)} ${tag(t.text, t.cls)}<div class="muted" style="font-size:11px">${esc(nameOf(e.from) || "outside")} → ${esc(nameOf(e.to) || "outside")}</div></td>
        <td class="num muted">—</td><td><span class="origin declared">declared</span></td><td class="muted">${e.present ? `found as ${esc(e.found_id)}` : (e.candidates || []).length ? "may be: " + e.candidates.map((c) => esc(c.id)).join(", ") + " · " + esc(ask("link")) : "not found yet"}</td></tr>`);
    }
    for (const r of (x.removed || {}).flows || []) {
      $("flows").insertAdjacentHTML("beforeend", `<tr class="im-gone"><td><s>${esc(baseEnd(r.from, r.from_series, r.from_name))} → ${esc(baseEnd(r.to, r.to_series, r.to_name))}</s> ${tag(`gone in ${vlabel()}`, "im-t-gone")}<div class="muted" style="font-size:11px" title="${esc(r.key)}">${esc(r.counter ? removedFlowName(r) : r.key)}</div></td>
        <td class="num"><s>${esc(r.rate && r.origin === "fitted" ? r.rate : "—")}</s></td><td><span class="origin ${esc(r.origin || "")}">${esc(r.origin || "found")}</span> <span class="muted">in v${esc(r.in)}${r.from && r.to ? " · ghost shown" : ""}</span></td>
        <td class="muted">${(r.machines || []).map((m) => `${esc(m.machine)}${m.confidence != null ? " " + Math.round(100 * m.confidence) + "%" : ""}`).join(", ") || "no machine"} in v${esc(r.in)}</td></tr>`);
    }
    IntendedPanel.render(x);
  }
  function markRow(r, mk) {
    if (mk.includes("new")) r.cells[0].insertAdjacentHTML("beforeend", " " + tag(`new in ${vlabel()}`, "im-t-new"));
    if (mk.includes("simulated")) r.cells[0].insertAdjacentHTML("beforeend", " " + tag("simulated", "im-t-sim"));
  }

  // ---- the page controls: observations, recorded with the page as their provenance ----
  async function control(ctl, part, key, from, after) {
    let d;
    try {
      d = await (await fetch("/api/intended/control", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ control: ctl, part, key, from, page: "dynamics" }) })).json();
    } catch (e) { d = { ok: false, error: String(e) }; }
    if (!d.ok) { IntendedPanel.note(`${ctl} was not recorded: ${d.error || "no answer"}`); return d; }
    const name = part === "stock" ? nameOf((stockOfKey(key) || {}).id || key) : (() => { const f = MODEL.flows.find((y) => flowKey(y) === key); return f ? `${nameOf(f.from)} → ${nameOf(f.to)}` : key; })();
    const said = { expect: `${name} is expected: it stays on the diagram (unexpect in its drawer)`, unexpect: `${name} is no longer expected: a later discovery may drop it`,
      ignore: `${name} is ignored: it leaves this list (${ask("list it again")})`, confirm: `${name} is confirmed`, discard: `${name} is discarded` }[ctl];
    if (said) IntendedPanel.note(said, true);
    if (from && String(from).startsWith("changes since")) IntendedPanel.settled(ctl, part, key, name);
    await load();
    if (after) after();
    return d;
  }
  // what the poll compares, so a mark set elsewhere redraws the diagram
  const sig = (m) => JSON.stringify(m && m.intended ? [m.intended.version, m.intended.since, m.intended.marks, (m.intended.expected || []).map((e) => [e.id, e.present])] : null);

  // what is marked expected: those stocks, and those flows with both their ends, drawn whatever a
  // filter would hide (no events, a stock that only fills): {stocks, flows}
  function expectedIds() {
    const x = it(), stocks = new Set(), flows = new Set();
    if (!x) return { stocks, flows };
    for (const [id, mk] of Object.entries((x.marks || {}).stocks || {})) if (mk.includes("expected")) stocks.add(id);
    for (const [id, mk] of Object.entries((x.marks || {}).flows || {})) if (mk.includes("expected")) {
      flows.add(id); const f = MODEL.flows.find((y) => y.id === id); if (f) { if (f.from) stocks.add(f.from); if (f.to) stocks.add(f.to); } }
    return { stocks, flows };
  }
  // the stocks a declared part is placed near: never hidden, so a ghost sits where it was meant to
  function nearIds() {
    const x = it(); if (!x) return new Set();
    return new Set(x.expected.filter((e) => e.near).map((e) => stockOfKey(e.near)).filter(Boolean).map((s) => s.id));
  }
  return { extend, decorator, tip, click, versionBar, toggleSince, param, legend, tables, control, sig, it, marksOf, stockKey, flowKey,
    declTag, recording, nameOf, who, agoText, hhmm, vlabel, tag, nearIds, expectedIds, baseEnd, removedStockName, removedFlowName, askers };
})();
