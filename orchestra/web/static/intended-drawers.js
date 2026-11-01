// The intended model's drawers on the Dynamics page (docs/proposals/intended-model.md §7):
//   - an expected stock or effect that is not found (frame D1): who declared it and their words,
//     its status, and "How to measure it": the options the Supervisor recorded (how collected,
//     instrument kind, cost, caveat, clearance, provenance), the chosen one's recording line and
//     sparkline, its script and [[collect]] entry (/api/intended/script); the radios are read
//     only: switching is the Supervisor's, so the drawer says to tell it;
//   - a declared flow that is not found;
//   - on a discovered stock's or flow's own drawer (frame D3): the switch "Expected: always show
//     this stock" (expect / unexpect, observations) and where the mark came from.
const IntendedDrawers = (() => {
  const I = () => Intended;
  const find = (id) => { const x = I().it(); return x ? x.expected.find((e) => e.id === id && e.part !== "flow") : null; };
  const toml = (entry) => Object.entries(entry || {}).map(([k, v]) => `${k} = ${typeof v === "string" ? JSON.stringify(v) : Array.isArray(v) || typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("\n");
  function spark(pts) {
    if (!pts || pts.length < 2) return "";
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0] || t0 + 1, vs = pts.map((p) => p[1]), lo = Math.min(...vs), hi = Math.max(...vs);
    const x = (t) => 4 + (t - t0) / (t1 - t0 || 1) * 232, y = (v) => 30 - (v - lo) / (hi - lo || 1) * 26;
    const line = pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    return `<svg class="im-spark" viewBox="0 0 240 34"><path class="a" d="${line} L${x(t1).toFixed(1)},34 L${x(t0).toFixed(1)},34 Z"/><path class="l" d="${line}"/>${pts.map(([t, v]) => `<circle cx="${x(t).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.6"/>`).join("")}</svg>`;
  }
  function option(o, chosen) {
    const on = o.key === chosen;
    const facts = [o.cost && `cost: ${o.cost}`, o.caveat && `caveat: ${o.caveat}`, o.clearance && `clearance: ${o.clearance}`, o.provenance && `${o.provenance}`,
      o.commit && `commit ${o.commit}`, !on && (o.first_points || []).length && `first points: ${o.first_points.map((p) => p[1]).join(", ")}`].filter(Boolean);
    return `<div class="im-opt ${on ? "on" : ""}" data-option="${esc(o.key)}"><span class="im-radio" role="radio" aria-checked="${on}" aria-disabled="true" title="read only: tell the Supervisor to switch"></span>
      <div><div><b>${esc(o.key)}</b> ${esc(o.title || "")}${on ? " " + I().tag("chosen", "im-t-chosen") : ""}</div>${o.how ? `<div class="muted">${esc(o.how)}</div>` : ""}
      ${facts.length ? `<div class="muted im-facts">${facts.map(esc).join(" · ")}</div>` : ""}${o.instrument ? `<div class="muted im-facts">instrument <span class="ty">${esc(o.instrument)}</span></div>` : ""}</div>
      <span class="ty im-kind">${esc(o.kind || "")}${o.simulated && !/simulated/.test(o.kind || "") ? " · simulated" : ""}</span></div>`;
  }
  function recordingBlock(m) {
    const opt = m.options.find((o) => o.key === m.chosen) || {}, rec = m.recording || {};
    const line = rec.points
      ? `<span class="im-live"></span>recording since ${I().hhmm(rec.since)} · instrument <b>${esc(rec.instrument || opt.instrument)}</b> · ${rec.points} point${rec.points === 1 ? "" : "s"} <span class="muted">${rec.every_s ? `· every ${esc(ago(rec.every_s))} ` : ""}${rec.last != null ? `· last ${esc(rec.last)}` : ""}</span>`
      : `<span class="im-idle"></span>chosen · instrument <b>${esc(opt.instrument || "—")}</b> · no points yet`;
    return `<div class="im-rec"><div class="im-recline">${line}</div>${spark(rec.points_series)}<div id="im-script" class="im-script"><span class="muted">reading the script…</span></div></div>`;
  }
  async function script(instrument) {
    const el = () => document.getElementById("im-script");
    let d;
    try { d = await (await fetch(`/api/intended/script?instrument=${encodeURIComponent(instrument)}`)).json(); } catch (e) { d = { ok: false, error: String(e) }; }
    if (!el()) return;
    if (!d.ok && !d.entry) { el().innerHTML = `<span class="muted">the script: ${esc(d.error || "not readable")}</span>`; return; }
    const text = (d.script && d.script.text) || "", lines = text.split("\n").filter((l, i, a) => i < a.length - 1 || l);
    const path = d.script ? d.script.path : "";
    el().innerHTML = `<details><summary>the script <span class="muted">· ${esc(path ? path.split("/").slice(-2).join("/") : "no script file")} and its [[collect]] entry${lines.length ? ` · ${lines.length} lines` : ""}${d.error ? " · " + esc(d.error) : ""}</span></summary>
      <div class="im-full">${text ? `<pre>${esc(text)}</pre>` : ""}<pre>[[collect]]\n${esc(toml(d.entry))}</pre></div></details>
      <div class="im-peek">${text ? `<pre>${esc(lines.slice(0, 6).join("\n"))}${lines.length > 6 ? "\n…" : ""}</pre>` : ""}<pre>[[collect]]\n${esc(toml(d.entry))}</pre></div>`;
  }
  function targetLine(t) {
    if (!t) return "";
    return `<div>target</div><div>${esc(t.op)} ${esc(t.value)}${t.hi != null ? "–" + esc(t.hi) : ""} over ${esc(ago(t.over_s))} · <b>${esc(t.met)}</b>${t.mean != null ? ` <span class="muted">(mean ${esc(t.mean)})</span>` : ""}${t.why ? ` <span class="muted">${esc(t.why)}</span>` : ""}</div>`;
  }
  // an expected stock or effect (frame D1)
  function openExpected(id) {
    const x = find(id);
    if (!x) return;
    if (x.present && x.found_id && MODEL.stocks.some((s) => s.id === x.found_id)) { Live.openStock(x.found_id); return; }
    const p = x.provenance || {}, t = I().declTag(x), m = x.measure, near = x.near && MODEL.stocks.find((s) => I().stockKey(s) === x.near || s.id === x.near);
    const by = I().who(p), owner = p.author === "owner";
    const said = owner ? `You declared it ${I().agoText(p.at)}${p.source === "supervisor" ? " in the Supervisor's chat" : ""}` : `${by[0].toUpperCase() + by.slice(1)} ${x.state === "proposed" ? "proposed" : "declared"} it ${I().agoText(p.at)}`;
    const quote = p.quote ? `: <i>"${esc(p.quote)}"</i>` : ".";
    const proposed = x.state === "proposed" ? `<div class="im-status">unconfirmed: ${esc(by)} proposed it, and it is not expected until you confirm it
      <span class="im-acts"><button class="ctl im-primary" onclick="Intended.control('confirm','${esc(x.part)}','${esc(x.id)}','its drawer',()=>IntendedDrawers.openExpected('${esc(x.id)}'))">confirm</button>
      <button class="ctl" onclick="Intended.control('discard','${esc(x.part)}','${esc(x.id)}','its drawer',closeDrawer)">discard</button></span></div>` : "";
    const pending = (x.pending || []).map((c) => `<div class="im-status">a change waiting for you: ${esc(c.summary || c.change || c.id || JSON.stringify(c))}</div>`).join("");
    const status = !x.measured ? "not measured: nothing records it yet" : I().recording(x) ? 'no series yet → <span class="im-recword">recording</span> <span class="muted">(the option chosen below)</span>'
      : "no series of its own yet";
    openDrawer(`<h3>${esc(x.name || x.id)} <span class="tag">${esc(x.part)}</span> ${I().tag(t.text, t.cls)} ${I().tag(x.measured ? "no series yet" : "not measured", "im-t-ghost")}${x.simulated ? " " + I().tag("simulated", "im-t-sim") : ""}</h3>
      ${proposed}${pending}
      <div class="muted im-said">${said}${quote} It is expected, not found: drawn as a ghost until a series measures it and a discovery finds it. Nothing about the model changes until then.</div>
      <div class="def"><div>now</div><div class="num">—</div>
      <div>status</div><div>${status}</div>
      <div>declared</div><div>by ${esc(by)}${p.at ? " · " + I().hhmm(p.at) : ""}${near ? ` · beside <b>${esc(stockName(near.id))}</b>` : x.near ? ` · near <span class="ty">${esc(x.near)}</span>` : ""}${x.note ? ` <span class="muted">(${esc(x.note)})</span>` : ""}</div>
      ${(x.candidates || []).length ? `<div>may be</div><div>${x.candidates.map((c) => `<b>${esc(I().nameOf(c.id))}</b> <span class="muted">(${esc(c.why)})</span>`).join(", ")}<br><span class="muted">whether it is this ${esc(x.part)} is for you to say: ask the Supervisor to link them</span></div>` : ""}
      ${targetLine(x.target)}
      <div>machines</div><div><span class="muted">none: an expected ${esc(x.part)} has no flows until discovery finds one</span></div></div>
      <h4>How to measure it <span class="muted im-h4note">· the Supervisor's options; it chose one with you in its chat</span></h4>
      ${m && (m.options || []).length ? `<div class="im-opts">${m.options.map((o) => option(o, m.chosen) + (o.key === m.chosen ? recordingBlock(m) : "")).join("")}</div>
        <div class="muted im-facts" style="margin-top:6px">The choice is read only here: to switch to another option, tell the Supervisor in its chat.</div>`
        : '<div class="muted">No way to measure it is recorded yet: ask the Supervisor to measure it.</div>'}
      <h4>Level</h4><div class="muted" style="font-size:12px">No series is bound to it yet: nothing to draw. Once a discovery finds a stock in what ${m && m.recording && m.recording.instrument ? esc(m.recording.instrument) : "its instrument"} records, it is shown here, and you can tell the Supervisor whether that is this ${esc(x.part)}.</div>`);
    const opt = m && (m.options || []).find((o) => o.key === m.chosen);
    if (opt && opt.instrument) script(opt.instrument);
  }
  // a declared flow (dashed ghost on the diagram)
  function openExpectedFlow(id) {
    const x = I().it(), e = x && x.expected.find((y) => y.part === "flow" && y.id === id);
    if (!e) return;
    const p = e.provenance || {};
    openDrawer(`<h3>${esc(e.name)} <span class="tag">flow</span> ${I().tag(e.why || "expected", "im-t-ghost")}</h3>
      <div class="def"><div>moves</div><div>${esc(I().nameOf(e.from))} → ${esc(I().nameOf(e.to))}</div>
      <div>declared</div><div>by ${esc(I().who(p))}${p.at ? " · " + I().agoText(p.at) : ""}${p.quote ? `: <i>"${esc(p.quote)}"</i>` : ""}</div>
      <div>found</div><div>${e.present ? `as <b>${esc(e.found_id)}</b>` : (e.candidates || []).length ? `may be: ${e.candidates.map((c) => `<span class="ty">${esc(c.id || c.key)}</span>`).join(" ")} <span class="muted">(${esc(e.candidates[0].why)}; ask the Supervisor to link)</span>` : '<span class="muted">no flow between its ends yet</span>'}</div>
      ${targetLine(e.target)}</div>`);
  }
  // the switch at the top of a discovered stock's or flow's drawer (frame D3)
  function expectSwitch(part, id) {
    const x = I().it();
    if (!x) return;
    const mk = I().marksOf(part, id), on = mk.includes("expected");
    const obj = part === "stock" ? MODEL.stocks.find((s) => s.id === id) : MODEL.flows.find((f) => f.id === id);
    if (!obj) return;
    const key = part === "stock" ? I().stockKey(obj) : I().flowKey(obj);
    const entry = x.expected.find((e) => e.part === part && (e.found_id === id || (!e.declared && e.id === id)));
    const h3 = document.querySelector("#drawer h3");
    if (!h3) return;
    if (on) h3.insertAdjacentHTML("beforeend", " " + I().tag("⌖ expected", "im-t-exp"));
    if (mk.includes("new")) h3.insertAdjacentHTML("beforeend", " " + I().tag(`new in ${I().vlabel()}`, "im-t-new"));
    if (mk.includes("simulated")) h3.insertAdjacentHTML("beforeend", " " + I().tag("simulated", "im-t-sim"));
    const word = part === "stock" ? "stock" : "flow", p = (entry && entry.provenance) || {};
    if (entry && entry.declared) {
      h3.insertAdjacentHTML("afterend", `<div class="im-expect on"><b>Expected:</b> declared by ${esc(I().who(p))} as <b>${esc(entry.name || entry.id)}</b>, found as this ${word} <span class="muted">· to stop expecting it, ask the Supervisor</span></div>`);
      return;
    }
    const facts = on ? [`confirmed expected`, `present in ${I().vlabel()}`, entry && entry.since_version ? `tracked by inference since v${entry.since_version}` : ""].filter(Boolean).join(" · ")
      + (p.author ? ` <span class="im-sep">·</span> ${p.author === "owner" ? "confirmed by you" : "marked by " + esc(I().who(p))} ${esc(I().agoText(p.at))}${p.from ? `, from "${esc(p.from)}"` : ""}` : "")
      : `not expected: a later discovery may drop it unmarked${mk.includes("new") ? ` · new in ${I().vlabel()}, not yet settled` : ""}`;
    const reopen = part === "stock" ? `()=>Live.openStock('${esc(id)}')` : `()=>Live.openFlow('${esc(id)}')`;
    h3.insertAdjacentHTML("afterend", `<div class="im-expect ${on ? "on" : ""}"><label class="im-toggle ${on ? "on" : ""}" id="im-expect" role="switch" aria-checked="${on}"
      onclick="Intended.control('${on ? "unexpect" : "expect"}','${part}',${esc(JSON.stringify(key))},'its drawer',${esc(reopen)})"><span class="im-sw"></span><b>Expected:</b>&nbsp;always show this ${word}</label>
      <div class="muted">${facts}</div></div>`);
  }
  return { openExpected, openExpectedFlow, expectSwitch };
})();
