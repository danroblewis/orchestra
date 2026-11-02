// The Dynamics page's Changes panel (docs/proposals/intended-model.md §3.3, §7, frame D2): beside
// the loops while "changes since vN" is on, every change of the version shown against its base,
// from ``MODEL.intended.changes``:
//   +  a part new since the base (a suggestion), with expect / ignore (observations: they record a
//      mark and change nothing else); a row settled here stays in its place, saying what was done;
//   −  a part the base had and this version does not, said as the base's record says it (how it
//      got there, its name, its ends);
//   ~  a − and a + of one counter: the same flow drawn between other stocks, one row;
//   ○  an expected part this version does not have, with its candidates ("suggested from labels: …", display only).
// Under them, collapsed: the suggestions that came and went, and the ignored ones (listing one again is asked of the machine that listens for requests: `unignore`).
// The panel is patched row by row (each row keyed), so a poll that changes nothing moves nothing,
// and a row redrawn under the keyboard's focus gives the focus to its own control again.
const IntendedPanel = (() => {
  const I = () => Intended;
  const ask = (what) => IntendedCore.asker(I().askers()).ask(what);
  // what this page settled from the panel: kept as a row ("expected ✓") after the server stops listing it
  const SETTLED = new Map();
  let NOTE = null;                                  // the last note, kept across redraws for a minute
  let ORDER = [];                                   // the rows' keys as last drawn: a settled row keeps its place
  const end = (id) => (id ? I().nameOf(id) : "outside");
  // a + row's button: expect is the one the panel suggests
  const button = (ctl, ch, from) => `<button class="ctl${ctl === "expect" ? " im-primary" : ""}" data-control="${esc(ctl)}"
    onclick="Intended.control('${esc(ctl)}','${esc(ch.part)}',${esc(JSON.stringify(ch.key))},'${esc(from)}')">${esc(ctl)}</button>`;
  const counterOf = (f) => (f && f.counter ? keyOf(f.counter) : "");
  function plus(ch, from) {
    const v = I().vlabel(), exp = (ch.controls || []).includes("unexpect");
    let what, why, title = "";
    if (ch.part === "stock") {
      const s = MODEL.stocks.find((x) => x.id === ch.id) || {}, ev = s.evidence || {}, by = (s.series && s.series.labels && s.series.labels.instrument) || ev.written_by;
      what = `stock <b>${esc(I().nameOf(ch.id))}</b> ${I().tag("new · inferred", "im-t-new")}`;
      why = s.series ? `from the series <span class="ty">${esc(s.series.name)}</span>${by ? ` recorded by ${esc(by)}` : ""}${ev.net_flow ? "; no counters, its net flow fitted" : ""}` : esc(ch.why || `new in ${v}`);
      title = s.series ? keyOf(s.series) : "";
    } else {
      const f = MODEL.flows.find((x) => x.id === ch.id);
      what = `flow <b>${esc(f ? `${end(f.from)} → ${end(f.to)}` : ch.key)}</b> ${I().tag("new", "im-t-new")}`;
      // its name and equation: two flows between the same ends are told apart; the raw counter is in the title (and the drawer)
      why = f ? `${esc(flowName(f))} · <span class="num">${esc(eqText(f))}</span>${SDGraph.correlational(MODEL, f) ? " · fitted from correlation; untested" : ""}` : esc(ch.why || "");
      title = f ? `counter ${counterOf(f)}` : ch.key;
    }
    return `<div class="im-chg new" data-sign="+" data-key="${esc(ch.key)}" title="${esc(title)}"><span class="im-sign">+</span><div><div>${what}${exp ? " " + I().tag("expected ✓", "im-t-exp") : ""}</div><div class="muted">${why}</div></div>
      <span class="im-acts">${(ch.controls || []).map((c) => button(c, ch, from)).join("")}</span></div>`;
  }
  // a removed part as the base version's record says it
  const ORIGIN = { fitted: "fitted", discovered: "discovered", declared: "declared" };
  function removedOf(ch, x) { return ((x.removed || {})[ch.part === "stock" ? "stocks" : "flows"] || []).find((y) => y.key === ch.key) || {}; }
  function goneName(ch, r) {
    if (ch.part === "stock") return I().removedStockName(r);
    return `${I().baseEnd(r.from, r.from_series, r.from_name)} → ${I().baseEnd(r.to, r.to_series, r.to_name)}`;
  }
  function minus(ch, x) {
    const r = removedOf(ch, x);
    const ms = (r.machines || []).map((m) => `${esc(m.machine)}${m.confidence != null ? " " + Math.round(100 * m.confidence) + "%" : ""}`).join(", ");
    const facts = [r.rate && r.origin === "fitted" ? `<span class="num">${esc(r.rate)}</span>` : "", ms].filter(Boolean).join(", ");
    const drawn = ch.part === "stock" || (r.from && r.to && MODEL.stocks.some((s) => s.id === r.from) && MODEL.stocks.some((s) => s.id === r.to));
    const named = ch.part === "flow" && r.counter ? `${esc(I().removedFlowName(r))} · ` : "";
    const how = r.origin ? `was ${ORIGIN[r.origin] || esc(r.origin)} in v${esc(ch.in)}` : `was in v${esc(ch.in)}`;
    const title = ch.part === "flow" && r.counter ? `counter ${keyOf(r.counter)}` : r.series ? keyOf(r.series) : ch.key;
    return `<div class="im-chg gone" data-sign="-" data-key="${esc(ch.key)}" title="${esc(title)}"><span class="im-sign">−</span><div><div>${esc(ch.part)} <s>${esc(goneName(ch, r))}</s> ${I().tag(`gone in ${I().vlabel()}`, "im-t-gone")}</div>
      <div class="muted">${named}${how}${facts ? ` (${facts})` : ""}${drawn ? " · ghost shown" : ""}</div></div><span></span></div>`;
  }
  // a − and a + of one counter: the flow moved between stocks, said once
  function moved(gone, add, x, from) {
    const r = removedOf(gone, x), f = MODEL.flows.find((y) => y.id === add.id);
    const now = f ? `${end(f.from)} → ${end(f.to)}` : add.key;
    return `<div class="im-chg new moved" data-sign="~" data-key="${esc(add.key)}" title="${esc(`counter ${counterOf(f)}`)}"><span class="im-sign">~</span><div><div>flow <s>${esc(goneName(gone, r))}</s> became <b>${esc(now)}</b> ${I().tag("same counter", "im-t-new")}${(add.controls || []).includes("unexpect") ? " " + I().tag("expected ✓", "im-t-exp") : ""}</div>
      <div class="muted">${f ? `${esc(flowName(f))} · <span class="num">${esc(eqText(f))}</span> · ` : ""}${r.origin ? `was ${esc(r.origin)} in v${esc(gone.in)}` : ""}</div></div>
      <span class="im-acts">${(add.controls || []).map((c) => button(c, add, from)).join("")}</span></div>`;
  }
  function missing(ch, x) {
    const e = x.expected.find((y) => (ch.id != null && y.id === ch.id) || (ch.key != null && y.key === ch.key)) || {};
    const name = e.name || I().nameOf(e.id || ch.id) || ch.key;
    const p = e.provenance || {}, cands = ch.candidates || [];
    const said = e.declared ? `declared by ${I().who(p)}` : `marked expected by ${I().who(p)}`, t = e.part ? I().declTag(e) : { text: ch.why || "expected", cls: "im-t-ghost" };
    return `<div class="im-chg ghost" data-sign="o" data-key="${esc(ch.key || ch.id)}"><span class="im-sign">○</span><div><div>expected ${esc(ch.part)} <b>${esc(name)}</b> ${I().tag(t.text, t.cls)}${e.part && e.measured === false ? " " + I().tag("not measured", "im-t-ghost") : ""}</div>
      <div class="muted">${esc(said)}; ${cands.length ? `suggested from labels: ${cands.map((c) => `<b>${esc(I().nameOf(c.id))}</b>`).join(", ")} · ${esc(ask("link"))}` : "discovery did not link it to anything it found"} · ghost shown</div></div><span></span></div>`;
  }
  // the rows, in the server's order, a − and + of one counter as one; each [key, html]
  function rowsOf(x, from) {
    const counterKey = (ch) => { if (ch.part !== "flow") return null;
      if (ch.sign === "-") { const r = removedOf(ch, x); return r.counter ? keyOf(r.counter) : null; }
      if (ch.sign === "+") return counterOf(MODEL.flows.find((f) => f.id === ch.id)) || null;
      return null; };
    // a + and a − of one counter pair once (the first − of that counter), the row where the + is
    const minusBy = new Map();
    for (const ch of x.changes) if (ch.sign === "-" && counterKey(ch) && !minusBy.has(counterKey(ch))) minusBy.set(counterKey(ch), ch);
    const pairOf = new Map(), usedMinus = new Set();
    for (const ch of x.changes) { const k = ch.sign === "+" && counterKey(ch), gone = k && minusBy.get(k);
      if (gone && !usedMinus.has(gone)) { pairOf.set(ch, gone); usedMinus.add(gone); } }
    const out = [];
    for (const ch of x.changes) {
      if (usedMinus.has(ch)) continue;
      if (pairOf.has(ch)) { out.push([ch.key, moved(pairOf.get(ch), ch, x, from)]); continue; }
      out.push([ch.key || ch.id, ch.sign === "+" ? plus(ch, from) : ch.sign === "-" ? minus(ch, x) : missing(ch, x)]);
    }
    return out;
  }
  // replace in ``host`` only the children whose html changed, matched by data-key; a child that had
  // the focus hands it to the same control in its replacement
  function patch(host, html) {
    const t = document.createElement("template"); t.innerHTML = html.trim();
    const fresh = [...t.content.children], have = new Map([...host.children].map((el) => [el.dataset.key, el]));
    const focus = document.activeElement, focusCtl = focus && host.contains(focus) ? focus.dataset.control || (focus.id ? "#" + focus.id : null) : null;
    let prev = null;
    for (const nu of fresh) {
      const k = nu.dataset.key, old = have.get(k);
      let el = old;
      if (!old || old.outerHTML !== nu.outerHTML) {
        if (old) { const had = old.contains(focus); old.replaceWith(nu);
          if (had) { const b = focusCtl && (focusCtl.startsWith("#") ? nu.querySelector(focusCtl) : nu.querySelector(`[data-control="${CSS.escape(focusCtl)}"]`)) || nu.querySelector("button"); if (b) b.focus({ preventScroll: true }); } }
        el = nu;
      }
      const at = prev ? prev.nextElementSibling : host.firstElementChild;
      if (at !== el) host.insertBefore(el, at);
      have.delete(k); prev = el;
    }
    for (const el of have.values()) el.remove();
  }
  function render(x) {
    const loops = $("loops");
    let row = loops.parentNode.classList.contains("im-loopsrow") ? loops.parentNode : null;
    if (!row) { row = document.createElement("div"); row.className = "im-loopsrow"; loops.parentNode.insertBefore(row, loops); row.appendChild(loops); }
    let panel = $("im-changes");
    const on = x && x.since != null;
    row.classList.toggle("solo", !on);
    if (!on) { if (panel) panel.remove(); return; }
    if (!panel) { row.insertAdjacentHTML("beforeend", '<div class="panel im-changes" id="im-changes"></div>'); panel = $("im-changes"); }
    const from = `changes since v${x.since}`;
    const listed = rowsOf(x, from), keys = new Set(listed.map(([k]) => k));
    // what was settled here and is no longer listed: still a row, in the place it had
    const rows = listed.slice();
    for (const [key, st] of SETTLED) {
      if (keys.has(key)) continue;
      const was = ORDER.indexOf(key), after = ORDER.slice(0, Math.max(0, was)).reverse().find((k) => rows.some(([r]) => r === k));
      const at = was < 0 ? rows.length : after == null ? 0 : rows.findIndex(([r]) => r === after) + 1;
      rows.splice(at, 0, [key, kept(key, st, from)]);
    }
    ORDER = rows.map(([k]) => k);
    const settledHere = rows.length - listed.length;
    // the header counts rows as drawn: a − and + of one counter are one change; ○ rows apart
    const nExpected = x.changes.filter((ch) => ch.sign === "o").length, nChanges = listed.length - nExpected;
    const went = (x.came_and_went || []).map((w) => `<div class="im-chg"><span class="im-sign">·</span><div>${esc(w.part)} <span class="ty">${esc(w.key)}</span> <span class="muted">in ${esc(w.versions)} version${w.versions === 1 ? "" : "s"}${w.last ? `, last v${esc(w.last)}` : ""}</span></div><span></span></div>`).join("");
    const ign = (x.ignored || []).map((w) => `<div class="im-chg"><span class="im-sign">·</span><div>${esc(w.part)} <b>${esc(w.id ? (w.part === "stock" ? I().nameOf(w.id) : w.id) : w.key)}</b> <span class="muted">${w.present ? "present" : "not present"} · ignored by ${esc(I().who(w.provenance))}</span></div>
      <span></span></div>`).join("");
    const saved = x.since_saved_at ? `, saved ${I().agoText(x.since_saved_at)}` : "";
    const counts = `${nChanges} change${nChanges === 1 ? "" : "s"}${nExpected ? ` · ${nExpected} expected` : ""}${settledHere ? ` · ${settledHere} settled` : ""}`;
    const html = `<div class="im-chead" data-key="#head"><h2 style="margin:0"><span>Changes since v${esc(x.since)}</span><span class="count">${counts}</span></h2><div class="muted im-against">Against version ${esc(x.since)}${esc(saved)}</div></div>
      ${rows.map(([, h]) => h).join("") || '<div class="muted" data-key="#none">nothing changed</div>'}
      ${(x.came_and_went || []).length ? `<details class="im-fold" id="im-went" data-key="#went"><summary>came and went <span class="count">${x.came_and_went.length}</span> <span class="muted">· suggestions that left before they settled; one returns if its key comes back</span></summary>${went}</details>` : ""}
      ${(x.ignored || []).length ? `<details class="im-fold" id="im-ignored" data-key="#ignored"><summary>ignored <span class="count">${x.ignored.length}</span> <span class="muted">· ${esc(ask("list one again"))}</span></summary>${ign}</details>` : ""}
      <div class="muted im-foot" data-key="#foot">${x.settled ? `${x.settled} settled: in enough versions running, no longer marked new. ` : ""}Either answer settles a + row: <b>expect</b> keeps the part on the diagram whatever a later discovery finds (the row stays, marked expected ✓); <b>ignore</b> takes it off this list.${(x.missing || []).length ? ` <span class="stale">Not read in time: ${esc(x.missing.join(", "))}.</span>` : ""}</div>
      <div class="im-note" id="im-note" data-key="#note" style="display:none" role="status"></div>`;
    // a details element keeps whether it is open across a redraw
    for (const id of ["im-went", "im-ignored"]) { const d = $(id); if (d && d.open) panel.dataset[id] = "1"; else if (d) delete panel.dataset[id]; }
    if (panel.dataset.html !== html) { panel.dataset.html = html; patch(panel, html); }
    for (const id of ["im-went", "im-ignored"]) { const d = $(id); if (d && panel.dataset[id]) d.open = true; }
    if (NOTE && Date.now() - NOTE.at < 60000) note(NOTE.text, NOTE.ok);
  }
  // a row this page settled after the server stopped listing it
  function kept(key, st, from) {
    const ch = { part: st.part, key };
    return `<div class="im-chg" data-sign="${st.ctl === "expect" ? "✓" : "·"}" data-key="${esc(key)}"><span class="im-sign">${st.ctl === "expect" ? "✓" : "·"}</span><div><div>${esc(st.part)} <b>${esc(st.name)}</b> ${st.ctl === "expect" ? I().tag("expected ✓", "im-t-exp") : I().tag("ignored", "im-t-ghost")}</div>
      <div class="muted">${st.ctl === "expect" ? "settled here: it stays on the diagram" : `settled here: off this list; ${esc(ask("list it again"))}`}</div></div>
      <span class="im-acts">${st.ctl === "expect" ? button("unexpect", ch, from) : ""}</span></div>`;
  }
  // a control answered: expect and ignore are remembered as rows; unexpect forgets the row
  function settled(ctl, part, key, name) {
    if (ctl === "expect" || ctl === "ignore") SETTLED.set(key, { ctl, part, name });
    else if (ctl === "unexpect") SETTLED.delete(key);
  }
  function note(text, ok = false) {
    NOTE = { text, ok, at: Date.now() };
    const n = $("im-note"); if (n) { n.textContent = text; n.style.display = ""; n.classList.toggle("stale", !ok); n.classList.toggle("im-ok", ok); }
  }
  return { render, note, settled };
})();
