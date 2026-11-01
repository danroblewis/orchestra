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
  const end = (id) => (id ? I().nameOf(id) : "outside");
  // a + row's button: expect is the one the panel suggests
  const button = (ctl, ch, from) => `<button class="ctl${ctl === "expect" ? " im-primary" : ""}" data-control="${esc(ctl)}"
    onclick="Intended.control('${esc(ctl)}','${esc(ch.part)}',${esc(JSON.stringify(ch.key))},'${esc(from)}')">${esc(ctl)}</button>`;
  function plus(ch, from) {
    const v = I().vlabel();
    let what, why;
    if (ch.part === "stock") {
      const s = MODEL.stocks.find((x) => x.id === ch.id) || {}, ev = s.evidence || {}, by = (s.series && s.series.labels && s.series.labels.instrument) || ev.written_by;
      what = `stock <b>${esc(I().nameOf(ch.id))}</b> ${I().tag("new · inferred", "im-t-new")}`;
      why = s.series ? `from the series <span class="ty">${esc(s.series.name)}</span>${by ? ` recorded by ${esc(by)}` : ""}${ev.net_flow ? "; no counters, its net flow fitted" : ""}` : esc(ch.why || `new in ${v}`);
    } else {
      const f = MODEL.flows.find((x) => x.id === ch.id);
      what = `flow <b>${esc(f ? `${end(f.from)} → ${end(f.to)}` : ch.key)}</b> ${I().tag("new", "im-t-new")}`;
      why = f ? `<span class="num">${esc(eqText(f))}</span>${SDGraph.correlational(MODEL, f) ? " · fitted from correlation; untested" : ""}` : esc(ch.why || "");
    }
    return `<div class="im-chg new" data-sign="+" data-key="${esc(ch.key)}"><span class="im-sign">+</span><div><div>${what}</div><div class="muted">${why}</div></div>
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
    const said = e.declared ? `declared by ${I().who(p)}` : `marked expected by ${I().who(p)}`;
    return `<div class="im-chg ghost" data-sign="o" data-key="${esc(ch.key || ch.id)}"><span class="im-sign">○</span><div><div>expected ${esc(ch.part)} <b>${esc(name)}</b> ${I().tag(ch.why || "expected", "im-t-ghost")}</div>
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
    const rows = x.changes.map((ch) => (ch.sign === "+" ? plus(ch, from) : ch.sign === "-" ? minus(ch, x) : missing(ch, x))).join("");
    const went = (x.came_and_went || []).map((w) => `<div class="im-chg"><span class="im-sign">·</span><div>${esc(w.part)} <span class="ty">${esc(w.key)}</span> <span class="muted">in ${esc(w.versions)} version${w.versions === 1 ? "" : "s"}${w.last ? `, last v${esc(w.last)}` : ""}</span></div><span></span></div>`).join("");
    const ign = (x.ignored || []).map((w) => `<div class="im-chg"><span class="im-sign">·</span><div>${esc(w.part)} <b>${esc(w.id ? (w.part === "stock" ? I().nameOf(w.id) : w.id) : w.key)}</b> <span class="muted">${w.present ? "present" : "not present"} · ignored by ${esc(I().who(w.provenance))}</span></div>
      <span></span></div>`).join("");
    const saved = x.since_saved_at ? `, saved ${I().agoText(x.since_saved_at)}` : "";
    panel.innerHTML = `<h2 style="margin-top:0"><span>Changes since v${esc(x.since)}</span><span class="count">${x.changes.length}</span></h2>
      ${rows || '<div class="muted">nothing changed</div>'}
      ${(x.came_and_went || []).length ? `<details class="im-fold" id="im-went"><summary>came and went <span class="count">${x.came_and_went.length}</span> <span class="muted">· suggestions that left before they settled; one returns if its key comes back</span></summary>${went}</details>` : ""}
      ${(x.ignored || []).length ? `<details class="im-fold" id="im-ignored"><summary>ignored <span class="count">${x.ignored.length}</span> <span class="muted">· to list one again, ask the Supervisor</span></summary>${ign}</details>` : ""}
      <div class="muted im-foot">Against version ${esc(x.since)}${esc(saved)}.${x.settled ? ` ${x.settled} settled: in enough versions running, no longer marked new.` : ""} <b>expect</b> keeps a part on the diagram whatever a later discovery finds; <b>ignore</b> takes it off this list.${(x.missing || []).length ? ` <span class="stale">Not read in time: ${esc(x.missing.join(", "))}.</span>` : ""}</div>
      <div class="stale im-note" id="im-note" style="display:none"></div>`;
  }
  function note(text) { const n = $("im-note"); if (n) { n.textContent = text; n.style.display = ""; } }
  return { render, note };
})();
