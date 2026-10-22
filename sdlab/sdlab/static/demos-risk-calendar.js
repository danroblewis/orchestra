// SD Lab demo 5, risk calendar (docs/demos/risk-calendar.md): the next 30 days of known events through a stored
// found model and the true model of ladder case 311 (a node pool); a calendar of each day's worst level of a risk
// stock against a limit, found beside true. Read only: /api/demos/risk-calendar/days.
(function () {
  "use strict";
  if (!window.SDDemos) return;
  const num = (x) => (x === null || x === undefined || !isFinite(x) ? "–" : Math.abs(x) >= 100 ? Math.round(x).toLocaleString() : String(+(+x).toPrecision(3)));
  const css = document.createElement("style");
  css.textContent = `
    .rc-cal { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 3px; }
    .rc-cal .hd { font-size: 11px; color: var(--muted); text-align: center; }
    .rc-cal .d { border: 1px solid var(--rule); border-radius: 4px; padding: 2px 4px; min-height: 46px; font-size: 11px; line-height: 1.25; background: var(--surface); position: relative; }
    .rc-cal .d .n { color: var(--muted); }
    .rc-cal .d .v { font-variant-numeric: tabular-nums; font-weight: 600; }
    .rc-cal .d.lo { background: color-mix(in srgb, var(--good) 10%, var(--surface)); }
    .rc-cal .d.mid { background: color-mix(in srgb, var(--warn) 22%, var(--surface)); }
    .rc-cal .d.hi { background: color-mix(in srgb, var(--bad) 30%, var(--surface)); border-color: var(--bad); }
    .rc-cal .d.beyond { border-style: dashed; border-width: 2px; }
    .rc-cal .d .ev { position: absolute; right: 3px; top: 2px; font-size: 10px; font-weight: 700; color: var(--fg); }
    .rc-cal .d.miss { outline: 2px solid var(--bad); outline-offset: -4px; }
    .rc-cal .d.false { outline: 2px dotted var(--warn); outline-offset: -4px; }
    .rc-form label { white-space: nowrap; }
    .rc-form input[type=number] { width: 4.5em; }`;
  document.head.appendChild(css);
  const EV = { launch: "L", maintenance: "M", failure: "F" };

  function ui(p, h) {
    const dayOpts = (sel) => `<option value="-1">none</option>` + Array.from({ length: 30 }, (_, d) => `<option value="${d}"${d === sel ? " selected" : ""}>day ${d + 1} (${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d % 7]})</option>`).join("");
    p.innerHTML = `<p class="what"><b>This demo uses ladder case 311</b> (a node pool: three nodes of 4 pods each; pending pods start only while there is room), not the 310 scenario above.
      <b>The idea:</b> the next 30 days hold events you already know about: the weekly traffic pattern (quiet weekends), a product launch, a planned node maintenance.
      Run them through the model and mark the days a stock is projected to cross a limit, so you can move the maintenance or add a node before the day comes.
      Here the same days also run through the true model, so the calendar shows which flagged days the found model gets right, which it misses and which it flags falsely.</p>
      <div class="controls rc-form">
        <label>Found model <select id="rc-strat">${["milp", "combined2", "kalman_lna", "structures", "engine_forms"].map((s) => `<option>${s}</option>`).join("")}</select></label>
        <label>Risk <select id="rc-stock"><option value="queue">requests waiting (queue)</option><option value="pending">pods pending</option><option value="retries">requests waiting to retry</option></select></label>
        <label>Limit <input type="number" id="rc-limit" step="any" style="width:6.5em"></label>
        <label>Nodes <select id="rc-nodes"><option value="3">3 (today)</option><option value="4">4</option><option value="5">5</option><option value="6">6</option></select></label></div>
      <div class="controls rc-form">
        <label>Launch <select id="rc-launch">${dayOpts(15)}</select></label>
        <label>+<input type="number" id="rc-boost" value="40" min="0" max="200">% that day, +<input type="number" id="rc-after" value="10" min="0" max="100">% after</label></div>
      <div class="controls rc-form">
        <label>Node maintenance <select id="rc-mday">${dayOpts(22)}</select></label>
        <label>from <input type="number" id="rc-mhour" value="12" min="0" max="23">:00 for <input type="number" id="rc-mhours" value="4" min="1" max="12"> h</label>
        <label><input type="checkbox" id="rc-fail"> also the case's node failures (Mon, Wed, Fri 10:50)</label>
        <button class="primary" id="rc-run">Run the 30 days</button></div>
      <div id="rc-out"></div>`;
    const lim = { queue: 6000, pending: 5, retries: 500 };
    const st = p.querySelector("#rc-stock"), li = p.querySelector("#rc-limit");
    li.value = lim.queue;
    st.onchange = () => { li.value = lim[st.value]; run(p, h); };
    p.querySelector("#rc-run").onclick = () => run(p, h);
    run(p, h);
  }

  function cls(v, limit) { const x = v / limit; return x >= 1 ? "hi" : x >= 0.7 ? "mid" : "lo"; }

  function cal(h, r, who) {
    const other = who === "found" ? "truth" : "found";
    const cells = r.days.map((d) => {
      const v = d[who], flag = d[`${who}_flag`], oflag = d[`${other}_flag`];
      const mark = who === "found" ? (flag && !oflag ? " false" : !flag && oflag ? " miss" : "") : "";
      const beyond = who === "found" && d.beyond.length ? " beyond" : "";
      const ev = d.events.map((e) => EV[e]).filter(Boolean);
      const tip = `day ${d.day + 1} (${d.weekday}): worst ${num(v)} ${r.risk.unit}${flag ? `, over the limit for ${d[`${who}_hours`]} h` : ""}${d.events.length ? `; events: ${d.events.join(", ")}` : ""}${beyond ? `; the found model goes past the data's range on ${d.beyond.join(", ")}` : ""}`;
      return `<div class="d ${cls(v, r.limit)}${beyond}${mark}" title="${h.esc(tip)}"><span class="n">${d.day + 1}</span>${ev.length ? `<span class="ev">${[...new Set(ev)].join("")}</span>` : ""}<br><span class="v">${num(v)}</span></div>`;
    });
    return `<div class="rc-cal">${["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((w) => `<div class="hd">${w}</div>`).join("")}${cells.join("")}</div>`;
  }

  async function run(p, h) {
    const out = p.querySelector("#rc-out");
    out.innerHTML = `<p class="busy">Running 30 days (8,640 five-minute steps) through both models…</p>`;
    const v = (id) => encodeURIComponent(p.querySelector(id).value);
    const q = `strategy=${v("#rc-strat")}&stock=${v("#rc-stock")}&limit=${v("#rc-limit")}&nodes=${v("#rc-nodes")}&launch_day=${v("#rc-launch")}` +
      `&launch_boost=${(+p.querySelector("#rc-boost").value || 0) / 100}&after_boost=${(+p.querySelector("#rc-after").value || 0) / 100}` +
      `&maint_day=${v("#rc-mday")}&maint_hour=${v("#rc-mhour")}&maint_hours=${v("#rc-mhours")}&failures=${p.querySelector("#rc-fail").checked}`;
    let r;
    try { r = await h.get(`/api/demos/risk-calendar/days?${q}`); } catch (e) { out.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
    const f = r.flagged, src = r.source;
    const dl = (xs) => (xs.length ? xs.map((d) => `day ${d + 1} (${r.days[d].weekday})`).join(", ") : "none");
    const beyondDays = r.days.filter((d) => d.beyond.length);
    const missing = r.caps.filter((c) => !c.has_min);
    const ok = !f.found_only.length && !f.truth_only.length;
    const evs = r.events.filter((e) => e.kind !== "failure");
    out.innerHTML = `<div class="verdict ${ok ? (beyondDays.length ? "warn" : "good") : "bad"}">
        <p>Limit: <b>${h.esc(r.risk.label)} ≥ ${num(r.limit)}</b> ${h.esc(r.risk.unit)}, ${r.nodes} nodes. Events: ${evs.map((e) => `day ${e.day + 1}: ${h.esc(e.label)}`).join("; ") || "none"}${r.events.length > evs.length ? `; ${r.events.length - evs.length} node failures` : ""}.</p>
        <p>Flagged by both: <b>${dl(f.both)}</b>.</p>
        <p>${f.truth_only.length ? `<b style="color:var(--bad)">Missed by the found model</b> (the truth crosses the limit): ${dl(f.truth_only)}.` : "Missed by the found model: none."}
           ${f.found_only.length ? `<b style="color:var(--warn)">False alarms</b> (found model only): ${dl(f.found_only)}.` : "False alarms: none."}</p>
        ${beyondDays.length ? `<p><b>Past the data:</b> on ${beyondDays.length} of 30 days the found model takes ${h.esc([...new Set(beyondDays.flatMap((d) => d.beyond))].join(", "))} more than 5% past the highest level in the data it was fitted on (dashed cells): there it extrapolates.
          ${missing.length ? `It has no ${missing.map((c) => h.esc(c.what.split(":")[0])).join(", ")} (the data never reached ${missing.length > 1 ? "them" : "it"}), so where that would bind its forecast is unsupported.` : ""}</p>` : ""}
      </div>
      <p class="src">Found model: <b>${h.esc(src.strategy)}</b>'s stored result #${h.esc(src.result)} on <span class="mono">${h.esc(src.case)}</span> ${h.esc(src.variant)} (${h.esc(src.status)}, code ${h.esc(src.commit)}), fitted on one week of data. Day 1 is a Monday; a step is 5 minutes.</p>
      <div class="legend"><span>cell colour: the day's worst level against the limit (green under 70%, amber 70–100%, red over)</span><span>L launch, M maintenance, F node failure</span>
        <span>found calendar: red outline = missed day, dotted amber = false alarm, dashed border = past the data</span></div>
      <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(330px,1fr))">
        <div class="panel"><h3>Found model's forecast</h3>${cal(h, r, "found")}</div>
        <div class="panel"><h3>What the true model does</h3>${cal(h, r, "truth")}</div></div>
      <div class="panel" style="margin-top:10px;max-width:700px"><h3>${h.esc(r.risk.label)} over the 30 days <span class="tag">${h.esc(r.risk.unit)}, hourly</span></h3>
        <div class="legend"><span><span class="key" style="border-color:var(--accent)"></span>found model</span><span><span class="key" style="border-color:var(--accent2);border-top-style:dashed"></span>true model</span><span><span class="key" style="border-color:var(--bad);border-top-style:dashed"></span>limit</span></div>
        ${h.chart(r.t, [{ ys: r.series.found, color: "var(--accent)", label: "found model" }, { ys: r.series.truth, color: "var(--accent2)", dash: "4 3", label: "true model" }],
          { h: 140, zero: true, hline: r.limit, marks: evs.map((e) => ({ t: e.day * r.steps_per_day + 1, label: EV[e.kind], color: "var(--fg)" })), label: r.risk.label })}</div>
      <div class="panel tablewrap" style="margin-top:10px;max-width:700px"><table><thead><tr><th>day</th><th>events</th><th class="num">found: worst</th><th class="num">hours over</th><th class="num">true: worst</th><th class="num">hours over</th></tr></thead><tbody>
        ${r.days.filter((d) => d.found_flag || d.truth_flag || d.events.length).map((d) => `<tr><td>${d.day + 1} ${d.weekday}</td><td>${h.esc(d.events.join(", "))}</td>
          <td class="num">${num(d.found)}</td><td class="num">${d.found_hours}</td><td class="num">${num(d.truth)}</td><td class="num">${d.truth_hours}</td></tr>`).join("")}</tbody></table></div>`;
  }

  window.SDDemos.register({ tab: "risk-calendar", title: "5. Risk calendar", ui });
})();
