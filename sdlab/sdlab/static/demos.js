// SD Lab demos (/demos; docs/DEMOS.md): operational uses of a discovered model, on a simulated service whose true
// model is known, so each demo shows what the found model says beside what really happened. Read only.
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (x, d = 3) => (x === null || x === undefined || !isFinite(x) ? "–" : Math.abs(x) >= 1000 ? Math.round(x).toLocaleString() : (+x).toPrecision(d).replace(/\.?0+$/, ""));
  const pct = (x) => (x === null || x === undefined || !isFinite(x) ? "–" : `${x >= 0 ? "+" : ""}${(100 * x).toFixed(1)}%`);
  const SCEN = "memory-oom";
  const S = { model: null, overview: null, pick: null };

  async function get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: ${r.status} ${await r.text()}`);
    return r.json();
  }
  const panel = (name) => document.querySelector(`[data-panel="${name}"]`);

  // ---------- a small line chart: series [{ys, color, dash, width, label}], marks [{t, label, color}], hline ----------
  function chart(t, series, opts = {}) {
    const W = 360, H = opts.h || 120, m = { l: 40, r: 6, t: 6, b: 16 };
    const all = series.flatMap((s) => (s.ys || []).filter((v) => v !== null && isFinite(v)));
    if (opts.hline !== undefined) all.push(opts.hline);
    if (!all.length) return `<svg viewBox="0 0 ${W} ${H}"></svg>`;
    let lo = Math.min(...all), hi = Math.max(...all);
    if (opts.zero) lo = Math.min(lo, 0);
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const t0 = t[0], t1 = t[t.length - 1];
    const X = (x) => m.l + ((x - t0) / (t1 - t0 || 1)) * (W - m.l - m.r);
    const Y = (y) => H - m.b - ((y - lo) / (hi - lo)) * (H - m.t - m.b);
    const path = (ys) => ys.map((v, i) => (v === null || !isFinite(v) ? null : `${X(t[i]).toFixed(1)},${Y(v).toFixed(1)}`)).filter(Boolean).join(" ");
    const lines = series.map((s) => s.ys ? `<polyline fill="none" stroke="${s.color}" stroke-width="${s.width || 1.4}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} points="${path(s.ys)}"><title>${esc(s.label || "")}</title></polyline>` : "").join("");
    const marks = (opts.marks || []).map((k) => `<line x1="${X(k.t)}" x2="${X(k.t)}" y1="${m.t}" y2="${H - m.b}" stroke="${k.color || "var(--fg)"}" stroke-dasharray="3 3" opacity="0.7"/><text x="${X(k.t) + 3}" y="${m.t + 9}" style="fill:${k.color || "var(--fg)"}">${esc(k.label || "")}</text>`).join("");
    const hl = opts.hline !== undefined ? `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(opts.hline)}" y2="${Y(opts.hline)}" stroke="var(--bad)" stroke-dasharray="4 3" opacity="0.8"/>` : "";
    const axes = `<line x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}" stroke="var(--rule)"/>
      <text x="${m.l - 4}" y="${Y(hi) + 4}" text-anchor="end">${fmt(hi)}</text><text x="${m.l - 4}" y="${Y(lo) + 3}" text-anchor="end">${fmt(lo)}</text>
      <text x="${m.l}" y="${H - 3}">step ${t0}</text><text x="${W - m.r}" y="${H - 3}" text-anchor="end">${t1}</text>`;
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opts.label || "chart")}">${axes}${hl}${lines}${marks}</svg>`;
  }

  // ---------- intro ----------
  function intro() {
    const o = S.overview.scenarios.find((x) => x.name === SCEN), src = o.source || {};
    $("#intro").innerHTML = `<p><b>${esc(o.title)}</b></p><p>${esc(o.about)}</p>
      <p class="src">The found model: <b>${esc(src.strategy)}</b>'s stored result #${esc(src.result)} on <span class="mono">${esc(src.case)}</span> ${esc(src.variant)} (${esc(src.status)}, code ${esc(src.commit)}), discovered from the measured levels alone.
      Every demo runs on a simulation whose true model is known, so it shows what the found model says <i>and</i> what really happened.
      Plans for these and the other demos: <span class="mono">docs/DEMOS.md</span>; the ideas behind them: <span class="mono">OPERATIONALIZATION.md</span>.</p>`;
  }

  // ---------- 1. residual watch ----------
  function residualUI() {
    const o = S.overview.scenarios.find((x) => x.name === SCEN);
    panel("residual").innerHTML = `<p class="what"><b>The idea:</b> discovery takes minutes to hours, but checking yesterday's model against today's data takes a second.
      Run today's measurements through yesterday's model, one step ahead; where it stops predicting well, something changed, and the stock where the gap appears points at the flows to look at.
      Alarm thresholds are calibrated on a quiet day (yesterday, no change). Today a change happens at step 1200.</p>
      <div class="controls"><label>Today's change <select id="r-change">${Object.entries(o.changes).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("")}</select></label>
      <label><input type="checkbox" id="r-noise"> counted measurements (Poisson noise)</label>
      <button class="primary" id="r-run">Watch today</button></div>
      <div id="r-out"></div>`;
    $("#r-run").onclick = runResidual;
    runResidual();
  }
  async function runResidual() {
    const out = $("#r-out");
    out.innerHTML = `<p class="busy">Running yesterday's model over today…</p>`;
    const ch = $("#r-change").value, noise = $("#r-noise").checked;
    let r;
    try { r = await get(`/api/demos/${SCEN}/residual?change=${encodeURIComponent(ch)}&noise=${noise}`); } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    const a = r.first_alarm, T = r.change.t;
    const hitFlow = a && r.suspects.includes(r.change.ends);
    let cls = "bad", head;
    if (!a) head = `<b>Missed:</b> no stock crossed its threshold.`;
    else if (a.t < T) head = `<b>False alarm first:</b> ${esc(a.stock)} at step ${a.t}, ${T - a.t} steps <i>before</i> the change.`;
    else { cls = hitFlow ? "good" : "warn"; head = `<b>Caught</b> ${a.after} step${a.after === 1 ? "" : "s"} after the change, on <b>${esc(a.stock)}</b>${hitFlow ? ", and the changed flow is among the suspects" : ", but the changed flow is not among the suspects"}.`; }
    out.innerHTML = `<div class="verdict ${cls}"><p>${head}</p>
        <p>What really changed at step ${T}: <b>${esc(r.change.label)}</b>, the flow <span class="mono">${esc(r.change.ends)}</span> (${esc(rateText(r.change.before))} → ${esc(rateText(r.change.rate))}).</p>
        ${a ? `<p>Suspects (the found model's flows at ${esc(a.stock)}): ${r.suspects.map((s) => `<span class="mono"${s === r.change.ends ? ` style="color:var(--good);font-weight:600"` : ""}>${esc(s)}</span>`).join(", ")}.
          Alarms in order: ${a.order.map(esc).join(" → ")}.</p>` : ""}
        ${r.false_alarms.length ? `<p class="muted">False alarms before the change: ${r.false_alarms.map(esc).join(", ")}.</p>` : ""}
        ${noise ? `<p class="muted small">With counted measurements the one-step check is much weaker: the model was fitted on noise-free data, and feeding it noisy levels biases its predictions (the same limit that makes the ladder's counts variants data-limited). A filter that tracks the state (Kalman) instead of trusting each noisy level is the next step.</p>` : ""}</div>
      <div class="legend"><span><span class="key" style="border-color:var(--accent)"></span>running alarm score (CUSUM of the residual, in units of yesterday's spread)</span>
        <span><span class="key" style="border-color:var(--bad);border-top-style:dashed"></span>its threshold (from yesterday)</span><span>dotted line: the true change; red: the stock's first alarm</span></div>
      <div class="grid">${order(r).map((s) => {
        const x = r.stocks[s];
        return `<div class="panel"><h3>${esc(s)} <span class="tag">${esc(x.unit || "")}</span>${x.alarm !== null ? `<span class="alarm">alarm at ${x.alarm}</span>` : ""}</h3>
          ${chart(r.t, [{ ys: x.cusum, color: "var(--accent)", label: "alarm score" }], { hline: x.threshold, zero: true, h: 90,
            marks: [{ t: T, label: "change", color: "var(--fg)" }].concat(x.alarm !== null ? [{ t: x.alarm, label: "", color: "var(--bad)" }] : []), label: `${s} alarm score` })}
          <details><summary class="small muted">measured vs predicted</summary>${chart(r.t, [{ ys: x.observed, color: "var(--faint)", label: "measured" }, { ys: x.predicted, color: "var(--accent2)", dash: "3 2", label: "predicted one step ahead" }], { h: 90, marks: [{ t: T, label: "change" }] })}</details></div>`;
      }).join("")}</div>`;
  }
  function order(r) {
    const al = (s) => (r.stocks[s].alarm === null ? Infinity : r.stocks[s].alarm);
    return Object.keys(r.stocks).sort((a, b) => al(a) - al(b));
  }
  function rateText(r) {
    if (!r || typeof r !== "object") return String(r);
    if (r.form === "proportional") return `${fmt(r.k)} × ${r.stock}`;
    if (r.form === "constant") return fmt(r.value);
    if (r.form === "expr") return r.expr;
    return JSON.stringify(r);
  }

  // ---------- 3. what-if ----------
  function whatifUI() {
    const m = S.model;
    const rows = m.numbers.map((n, i) => `<tr class="pick" data-i="${i}"><td class="mono small">${esc(n.ends)}</td><td class="mono small">${esc(n.label)}</td><td class="num">${fmt(n.value, 4)}</td></tr>`).join("");
    panel("whatif").innerHTML = `<p class="what"><b>The idea:</b> before changing a setting in production (a retry share, a capacity, an autoscaling target), change it in the model and see what it does.
      The found model's numbers are listed by flow; pick one, set a new value, and compare the found model's prediction with the true model's response to the same change.</p>
      <div class="split"><div class="panel tablewrap"><table><thead><tr><th>flow</th><th>term</th><th class="num">value</th></tr></thead><tbody id="w-rows">${rows}</tbody></table></div>
      <div><div class="controls"><span id="w-pick" class="mono small">pick a number on the left</span>
        <label>new value <input id="w-val" type="number" step="any" style="width:9em"></label>
        <label>steps <select id="w-steps"><option>500</option><option selected>1000</option><option>2000</option></select></label>
        <button class="primary" id="w-run" disabled>Simulate</button></div><div id="w-out"></div></div></div>`;
    panel("whatif").querySelectorAll("tr.pick").forEach((tr) => (tr.onclick = () => {
      panel("whatif").querySelectorAll("tr.on").forEach((x) => x.classList.remove("on"));
      tr.classList.add("on");
      S.pick = m.numbers[+tr.dataset.i];
      $("#w-pick").textContent = `${S.pick.ends}: ${S.pick.label} = ${fmt(S.pick.value, 4)}`;
      $("#w-val").value = +(S.pick.value * 1.5).toPrecision(4);
      $("#w-run").disabled = false;
    }));
    $("#w-run").onclick = runWhatif;
    const first = [...panel("whatif").querySelectorAll("tr.pick")].find((tr) => m.numbers[+tr.dataset.i].ends === "retries → queue") || panel("whatif").querySelector("tr.pick");
    if (first) { first.click(); runWhatif(); }
  }
  async function runWhatif() {
    const out = $("#w-out");
    out.innerHTML = `<p class="busy">Simulating…</p>`;
    let r;
    try { r = await get(`/api/demos/${SCEN}/whatif?key=${encodeURIComponent(S.pick.key)}&value=${encodeURIComponent($("#w-val").value)}&steps=${$("#w-steps").value}`); } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    const mean = (v) => (v && v.length ? v.reduce((a, b) => a + (b || 0), 0) / v.length : null);
    const rel = (a, b) => (a ? (b - a) / Math.abs(a) : null);
    const st = Object.entries(r.stocks).map(([s, x]) => ({ s, x, f: rel(mean(x.found), mean(x.found_edited)), tr: x.truth_edited ? rel(mean(x.truth), mean(x.truth_edited)) : null }));
    st.sort((a, b) => Math.abs(b.f || 0) - Math.abs(a.f || 0));
    const tc = r.truth_change;
    out.innerHTML = `<div class="verdict"><p>Changed <span class="mono">${esc(r.number.ends)}</span>: ${esc(r.number.label)} from ${fmt(r.number.value, 4)} to <b>${fmt(r.value, 4)}</b>.</p>
        <p>${tc.flow ? `The same change in the true model: its flow <span class="mono">${esc(tc.flow)}</span> scaled alike${tc.rate && tc.rate.approximate ? " (approximately: the true equation is written differently)" : ""}.` : `No matching change in the true model: ${esc(tc.why)}.`}</p>
        <table><thead><tr><th>stock</th><th class="num">found model: mean change</th><th class="num">true model: mean change</th></tr></thead><tbody>
        ${st.slice(0, 6).map((y) => `<tr><td class="mono">${esc(y.s)}</td><td class="num">${pct(y.f)}</td><td class="num">${pct(y.tr)}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend"><span><span class="key" style="border-color:var(--faint)"></span>found model, as is</span><span><span class="key" style="border-color:var(--accent)"></span>found model, changed</span>
        <span><span class="key" style="border-color:var(--faint);border-top-style:dashed"></span>true model, as is</span><span><span class="key" style="border-color:var(--accent2);border-top-style:dashed"></span>true model, changed</span></div>
      <div class="grid">${st.slice(0, 6).map((y) => `<div class="panel"><h3>${esc(y.s)} <span class="tag">${esc(y.x.unit || "")}</span></h3>
        ${chart(r.t, [{ ys: y.x.found, color: "var(--faint)", label: "found, as is" }, { ys: y.x.found_edited, color: "var(--accent)", label: "found, changed" },
          { ys: y.x.truth, color: "var(--faint)", dash: "4 3", label: "true, as is" }, { ys: y.x.truth_edited, color: "var(--accent2)", dash: "4 3", label: "true, changed" }], { h: 110, label: y.s })}</div>`).join("")}</div>`;
  }

  // ---------- 7. hidden stock ----------
  async function hiddenUI() {
    const p = panel("hidden");
    p.innerHTML = `<p class="busy">Loading…</p>`;
    let r;
    try { r = await get(`/api/demos/${SCEN}/hidden`); } catch (e) { p.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    p.innerHTML = `<p class="what"><b>The idea:</b> when discovery keeps needing a stock nobody measures, that stock is a clue: something accumulates that you cannot see.
      Here the strategy inferred one from the measured levels alone; the simulation knows what it really is, so the two can be compared.</p>
      ${r.hidden.map((h) => `<div class="verdict good"><p>The found model has an unmeasured stock (its own name <span class="mono">${esc(h.own_name)}</span>), growing about <b>${fmt(h.growth_per_step)} ${esc(h.unit_guess.join(", ") || "units")} a step</b>.</p>
        <p>Its flows: ${h.flows.map((f) => `<span class="mono">${esc(f)}</span>`).join("; ")}.</p>
        <p>Read by: ${h.read_by.map((f) => `<span class="mono small">${esc(f)}</span>`).join("; ") || "nothing"}.</p>
        ${h.truth ? `<p>It matches the true model's hidden stock <b>${esc(h.truth.id)}</b>: found level = ${fmt(h.truth.alpha)} + ${fmt(h.truth.beta, 4)} × ${esc(h.truth.id)} (R² ${fmt(h.truth.r2, 5)}).</p>` : `<p>The truth has no hidden stock it matches.</p>`}</div>
        <div class="panel" style="max-width:760px"><div class="legend"><span><span class="key" style="border-color:var(--accent)"></span>inferred by the found model, from measured levels only</span><span><span class="key" style="border-color:var(--accent2);border-top-style:dashed"></span>the true hidden level (the simulation's)</span></div>
        ${chart(r.t, [{ ys: h.level, color: "var(--accent)", width: 2, label: "inferred" }].concat(h.truth ? [{ ys: h.truth.level, color: "var(--accent2)", dash: "5 3", label: "true" }] : []), { h: 160, zero: true, label: "hidden stock" })}</div>`).join("")}
      ${r.hint ? `<div class="hint"><b>What to measure</b> (the scenario's reading, for a production system): ${esc(r.hint)}</div>` : ""}`;
  }

  // ---------- 8. leverage ----------
  function leverageUI() {
    const m = S.model;
    panel("leverage").innerHTML = `<p class="what"><b>The idea:</b> which small change would help most? Each number in the found model is nudged up 10% in turn and the model simulated; the numbers that move the goal most are the places to look.
      The top five are tried in the true model too, to see whether the found model ranks them right.</p>
      <div class="controls"><label>Goal <select id="l-goal">${Object.entries(m.goals).map(([k, g]) => `<option value="${esc(k)}">${esc(g.label)}</option>`).join("")}</select></label>
      <button class="primary" id="l-run">Rank the levers</button></div><div id="l-out"></div>`;
    $("#l-run").onclick = runLeverage;
    runLeverage();
  }
  async function runLeverage() {
    const out = $("#l-out");
    out.innerHTML = `<p class="busy">Simulating every nudge (a few seconds)…</p>`;
    let r;
    try { r = await get(`/api/demos/${SCEN}/leverage?goal=${encodeURIComponent($("#l-goal").value)}`); } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    const g = r.goal, big = Math.max(...r.rows.map((x) => Math.abs(x.change)), 1e-12);
    out.innerHTML = `<div class="verdict"><p>Goal: <b>${esc(g.label)}</b> over ${r.steps} steps: ${fmt(g.base)} in the found model, ${fmt(g.truth_base)} in the true model. Each number raised by ${Math.round(100 * r.nudge)}%.</p></div>
      <div class="panel tablewrap"><table><thead><tr><th>#</th><th>flow</th><th>term</th><th class="num">value</th><th>effect in the found model</th><th class="num">found</th><th class="num">true model</th></tr></thead><tbody>
      ${r.rows.slice(0, 15).map((x, i) => `<tr><td>${i + 1}</td><td class="mono small">${esc(x.ends)}</td><td class="mono small">${esc(x.label)}</td><td class="num">${fmt(x.value, 4)}</td>
        <td><span class="bar${x.change < 0 ? " neg" : ""}" style="width:${(120 * Math.abs(x.change) / big).toFixed(0)}px"></span></td>
        <td class="num">${x.change >= 0 ? "+" : ""}${fmt(x.change)} (${pct(x.relative)})</td>
        <td class="num">${x.truth ? (x.truth.flow ? `${x.truth.approximate ? `<span title="approximate: the true model writes this flow differently, so its nearest number was nudged instead (here it scales more of the flow than the found term does)">≈ </span>` : ""}${x.truth.change >= 0 ? "+" : ""}${fmt(x.truth.change)} (${pct(x.truth.relative)})` : `<span class="muted small" title="${esc(x.truth.why)}">no match</span>`) : `<span class="muted small">not tried</span>`}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="muted small">Orange bars lower the goal (better when lower). "≈": an approximate match, the true model writes that flow differently (hover). "no match": the true model has no number in the same place (the found model wrote that flow differently); hover for why.</p>`;
  }

  // ---------- planned ----------
  const PLANNED = [
    ["2", "Daily model diff", "two days of a service, the second changed; the diff of the two found models beside the true change"],
    ["4", "Capacity projection", "traffic ramped through the model; when each capped flow saturates and the headroom left"],
    ["5", "Risk calendar", "the next 30 days of known events through the model; the days a stock crosses a limit"],
    ["6", "Metastability scan", "the retry loop's tipping point: the load spike after which the system stays broken"],
    ["9", "Always-on discovery", "a live service whose model improves over time and catches a change mid-stream"],
    ["10", "Before/after attribution", "an SRE project's effect against the before model's counterfactual, with its uncertainty"],
    ["11", "Canary guard", "baseline and canary fitted side by side; stop or go from the difference in their numbers"],
    ["12", "Blast radius", "a slowdown in a shared database spreading through a multi-service model"],
    ["13", "Agent work as stocks", "tickets by state with agents as the flows: throughput, rework, bottleneck"],
    ["14", "Game-day microworld", "be on call in a simulated incident, then compare with the found model's predictions"],
    ["15", "Fleet view", "model health, unexplained diffs and confidence across many simulated services"],
  ];
  function plannedUI() {
    panel("planned").innerHTML = `<p class="what">Planned demos (docs/DEMOS.md has the effort and the ideas each one shows).</p>
      <ul class="planned">${PLANNED.map(([n, t, d]) => `<li><b>${n}. ${esc(t)}</b>: ${esc(d)}</li>`).join("")}</ul>`;
  }

  // ---------- extra demos: static/demos-<name>.js (listed by /api/demos/manifest) ----------
  // A demo script calls SDDemos.register({tab, title, ui(panelElement, helpers)}); it gets its own tab before
  // "More demos", and ui runs the first time the tab opens. helpers: get, esc, fmt, pct, chart, scenario, model.
  const extra = {};
  function register(d) {
    if (!d || !d.tab || extra[d.tab] || panel(d.tab)) return;
    extra[d.tab] = d;
    const btn = document.createElement("button");
    btn.setAttribute("role", "tab"); btn.dataset.tab = d.tab; btn.textContent = d.title; btn.setAttribute("aria-selected", "false");
    btn.onclick = () => show(d.tab);
    const planned = document.querySelector('#tabs [data-tab="planned"]');
    planned.parentNode.insertBefore(btn, planned);
    const sec = document.createElement("section"); sec.dataset.panel = d.tab; sec.hidden = true;
    panel("planned").parentNode.insertBefore(sec, panel("planned"));
    if (WANT === d.tab) show(d.tab);
  }
  const WANT = new URLSearchParams(location.search).get("demo");    // read before show() rewrites the URL: an extra tab opens once its script registers
  window.SDDemos = { register, helpers: () => ({ get, esc, fmt, pct, chart, scenario: SCEN, model: S.model, overview: S.overview }) };
  async function loadExtra() {
    try {
      const m = await get("/api/demos/manifest");
      for (const src of m.scripts || []) {
        const el = document.createElement("script"); el.src = src; el.async = false; document.body.appendChild(el);
      }
    } catch { /* no extra demos */ }
  }

  // ---------- tabs ----------
  const built = {};
  function show(tab) {
    document.querySelectorAll("#tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    document.querySelectorAll("[data-panel]").forEach((p) => { p.hidden = p.dataset.panel !== tab; });
    try { history.replaceState(null, "", `?demo=${tab}`); } catch { /* fine */ }
    if (built[tab]) return;
    built[tab] = true;
    if (extra[tab]) { try { extra[tab].ui(panel(tab), window.SDDemos.helpers()); } catch (e) { panel(tab).innerHTML = `<p class="bad">${esc(e.message)}</p>`; } return; }
    ({ residual: residualUI, whatif: whatifUI, hidden: hiddenUI, leverage: leverageUI, planned: plannedUI })[tab]();
  }
  document.querySelectorAll("#tabs [role=tab]").forEach((b) => (b.onclick = () => show(b.dataset.tab)));

  (async function start() {
    try {
      [S.overview, S.model] = await Promise.all([get("/api/demos"), get(`/api/demos/${SCEN}/model`)]);
    } catch (e) { $("#intro").innerHTML = `<p class="bad">Could not load the demos: ${esc(e.message)}</p>`; return; }
    intro();
    const want = new URLSearchParams(location.search).get("demo");
    show(["residual", "whatif", "hidden", "leverage", "planned"].includes(want) ? want : "residual");
    loadExtra();
  })();
})();
