// The Dynamics page's Changes panel (docs/proposals/intended-model.md §3.3, §7, frame D2): beside
// the loops while "changes since vN" is on, every change of the version shown against its base,
// from ``MODEL.intended.changes``:
//   +  a part new since the base (a suggestion), with expect / ignore (observations: they record a
//      mark and change nothing else); settled suggestions are not listed, only counted;
//   −  a part the base had and this version does not;
//   ○  an expected part this version does not have, with its candidates ("may be: …").
// Under them, collapsed: the suggestions that came and went, and the ignored ones (listing one again is the Supervisor's: `unignore`).
const IntendedPanel = (() => {
  const I = () => Intended;
  // what this page settled from the panel: kept as a row ("expected ✓") after the server stops listing it
  const SETTLED = new Map();
  let NOTE = null;                                  // the last note, kept across redraws for a minute
  const end = (id) => (id ? I().nameOf(id) : "outside");
  // a + row's button: expect is the one the panel suggests
  const button = (ctl, ch, from) => `<button class="ctl${ctl === "expect" ? " im-primary" : ""}" data-control="${esc(ctl)}"
    onclick="Intended.control('${esc(ctl)}','${esc(ch.part)}',${esc(JSON.stringify(ch.key))},'${esc(from)}')">${esc(ctl)}</button>`;
  function plus(ch, from) {
    const v = I().vlabel(), exp = (ch.controls || []).includes("unexpect");
    let what, why;
    if (ch.part === "stock") {
      const s = MODEL.stocks.find((x) => x.id === ch.id) || {}, ev = s.evidence || {}, by = (s.series && s.series.labels && s.series.labels.instrument) || ev.written_by;
      what = `stock <b>${esc(I().nameOf(ch.id))}</b> ${I().tag("new · inferred", "im-t-new")}`;
      why = s.series ? `from the series <span class="ty">${esc(s.series.name)}</span>${by ? ` recorded by ${esc(by)}` : ""}${ev.net_flow ? "; no counters, its net flow fitted" : ""}` : esc(ch.why || `new in ${v}`);
    } else {
      const f = MODEL.flows.find((x) => x.id === ch.id);
      what = `flow <b>${esc(f ? `${end(f.from)} → ${end(f.to)}` : ch.key)}</b> ${I().tag("new", "im-t-new")}`;
      // its name and counter: two flows between the same ends are told apart
      why = f ? `${esc(flowName(f))}${f.counter ? ` · <span class="num">${esc(keyOf(f.counter))}</span>` : ""}<br><span class="num">${esc(eqText(f))}</span>${SDGraph.correlational(MODEL, f) ? " · fitted from correlation; untested" : ""}` : esc(ch.why || "");
    }
    return `<div class="im-chg new" data-sign="+" data-key="${esc(ch.key)}"><span class="im-sign">+</span><div><div>${what}${exp ? " " + I().tag("expected ✓", "im-t-exp") : ""}</div><div class="muted">${why}</div></div>
      <span class="im-acts">${(ch.controls || []).map((c) => button(c, ch, from)).join("")}</span></div>`;
  }
  function minus(ch, x) {
    const r = ((x.removed || {})[ch.part === "stock" ? "stocks" : "flows"] || []).find((y) => y.key === ch.key) || {};
    const name = ch.part === "stock" ? r.name || ch.id || ch.key : `${end(r.from)} → ${end(r.to)}`;
    const ms = (r.machines || []).map((m) => `${esc(m.machine)}${m.confidence != null ? " " + Math.round(100 * m.confidence) + "%" : ""}`).join(", ");
    const facts = [r.rate ? `<span class="num">${esc(r.rate)}</span>` : "", ms].filter(Boolean).join(", ");
    const drawn = ch.part === "stock" || (r.from && r.to && MODEL.stocks.some((s) => s.id === r.from) && MODEL.stocks.some((s) => s.id === r.to));
    return `<div class="im-chg gone" data-sign="-" data-key="${esc(ch.key)}"><span class="im-sign">−</span><div><div>${esc(ch.part)} <s>${esc(name)}</s> ${I().tag(`gone in ${I().vlabel()}`, "im-t-gone")}</div>
      <div class="muted">was ${ch.part === "flow" ? "fitted" : "found"} in v${esc(ch.in)}${facts ? ` (${facts})` : ""}${drawn ? " · ghost shown" : ""}</div></div><span></span></div>`;
  }
  function missing(ch, x) {
    const e = x.expected.find((y) => (ch.id != null && y.id === ch.id) || (ch.key != null && y.key === ch.key)) || {};
    const name = e.name || I().nameOf(e.id || ch.id) || ch.key;
    const p = e.provenance || {}, cands = ch.candidates || [];
    const said = e.declared ? `declared by ${I().who(p)}` : `marked expected by ${I().who(p)}`, t = e.part ? I().declTag(e) : { text: ch.why || "expected", cls: "im-t-ghost" };
    return `<div class="im-chg ghost" data-sign="o" data-key="${esc(ch.key || ch.id)}"><span class="im-sign">○</span><div><div>expected ${esc(ch.part)} <b>${esc(name)}</b> ${I().tag(t.text, t.cls)}${e.part && e.measured === false ? " " + I().tag("not measured", "im-t-ghost") : ""}</div>
      <div class="muted">${esc(said)}; ${cands.length ? `may be: ${cands.map((c) => `<b>${esc(I().nameOf(c.id))}</b>`).join(", ")} · ask the Supervisor to link` : "discovery did not link it to anything it found"} · ghost shown</div></div><span></span></div>`;
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
    let rows = x.changes.map((ch) => (ch.sign === "+" ? plus(ch, from) : ch.sign === "-" ? minus(ch, x) : missing(ch, x))).join("");
    // what was settled here and is no longer listed: still a row, saying what was done
    const listed = new Set(x.changes.map((ch) => ch.key));
    for (const [key, st] of SETTLED) if (!listed.has(key)) rows += kept(key, st, from);
    const went = (x.came_and_went || []).map((w) => `<div class="im-chg"><span class="im-sign">·</span><div>${esc(w.part)} <span class="ty">${esc(w.key)}</span> <span class="muted">in ${esc(w.versions)} version${w.versions === 1 ? "" : "s"}${w.last ? `, last v${esc(w.last)}` : ""}</span></div><span></span></div>`).join("");
    const ign = (x.ignored || []).map((w) => `<div class="im-chg"><span class="im-sign">·</span><div>${esc(w.part)} <b>${esc(w.id ? (w.part === "stock" ? I().nameOf(w.id) : w.id) : w.key)}</b> <span class="muted">${w.present ? "present" : "not present"} · ignored by ${esc(I().who(w.provenance))}</span></div>
      <span></span></div>`).join("");
    const saved = x.since_saved_at ? `, saved ${I().agoText(x.since_saved_at)}` : "";
    panel.innerHTML = `<h2 style="margin-top:0"><span>Changes since v${esc(x.since)}</span><span class="count">${x.changes.length}</span></h2>
      ${rows || '<div class="muted">nothing changed</div>'}
      ${(x.came_and_went || []).length ? `<details class="im-fold" id="im-went"><summary>came and went <span class="count">${x.came_and_went.length}</span> <span class="muted">· suggestions that left before they settled; one returns if its key comes back</span></summary>${went}</details>` : ""}
      ${(x.ignored || []).length ? `<details class="im-fold" id="im-ignored"><summary>ignored <span class="count">${x.ignored.length}</span> <span class="muted">· to list one again, ask the Supervisor</span></summary>${ign}</details>` : ""}
      <div class="muted im-foot">Against version ${esc(x.since)}${esc(saved)}.${x.settled ? ` ${x.settled} settled: in enough versions running, no longer marked new.` : ""} Either answer settles a + row: <b>expect</b> keeps the part on the diagram whatever a later discovery finds (the row stays, marked expected ✓); <b>ignore</b> takes it off this list.${(x.missing || []).length ? ` <span class="stale">Not read in time: ${esc(x.missing.join(", "))}.</span>` : ""}</div>
      <div class="im-note" id="im-note" style="display:none" role="status"></div>`;
    if (NOTE && Date.now() - NOTE.at < 60000) note(NOTE.text, NOTE.ok);
  }
  // a row this page settled after the server stopped listing it
  function kept(key, st, from) {
    const ch = { part: st.part, key };
    return `<div class="im-chg" data-sign="${st.ctl === "expect" ? "✓" : "·"}" data-key="${esc(key)}"><span class="im-sign">${st.ctl === "expect" ? "✓" : "·"}</span><div><div>${esc(st.part)} <b>${esc(st.name)}</b> ${st.ctl === "expect" ? I().tag("expected ✓", "im-t-exp") : I().tag("ignored", "im-t-ghost")}</div>
      <div class="muted">${st.ctl === "expect" ? "settled here: it stays on the diagram" : "settled here: off this list; to list it again, ask the Supervisor"}</div></div>
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
