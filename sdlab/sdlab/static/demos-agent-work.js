// Demo 13, agent work as stocks (docs/demos/agent-work.md): a simulated team of AI agents working tickets, the model
// discovery found from the ticket counts, and what it says about throughput, rework and the bottleneck, beside the
// true model. API: /api/demos/agent-work/{overview,sweep,forecast} (sdlab/demos/agent_work.py). Read only.
(function () {
  "use strict";
  const API = "/api/demos/agent-work";
  const STAGE = { backlog: "var(--faint)", in_progress: "var(--accent)", in_review: "var(--eq)", merging: "var(--accent2)" };
  const STAGES = Object.keys(STAGE);
  const SHORT = { backlog: "backlog", in_progress: "in progress", in_review: "in review", merging: "merging", none: "none" };

  function ui(p, h) {
    const { get, esc, fmt } = h;
    const st = { ov: null, strategy: null };
    const q = (s) => p.querySelector(s);
    p.innerHTML = `<p class="busy">Loading the agent team…</p>`;

    const rel = (f, t) => (f === null || f === undefined || !t ? null : (f - t) / Math.abs(t));
    const near = (f, t, tol = 0.05) => { const r = rel(f, t); return r !== null && Math.abs(r) <= tol; };
    const pctAbs = (x) => (x === null || x === undefined || !isFinite(x) ? "–" : `${(100 * x).toFixed(1)}%`);
    const off = (f, t) => { const r = rel(f, t); return r === null ? "" : ` <span class="muted small">(${r >= 0 ? "+" : ""}${(100 * r).toFixed(1)}%)</span>`; };

    async function start() {
      try { st.ov = await get(`${API}/overview`); } catch (e) { p.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const ov = st.ov;
      if (!ov.models.length) {
        p.innerHTML = `<div class="verdict bad"><p>No cached found model. Run <span class="mono">uv run python -m sdlab.demos.agent_work precompute</span> (a few minutes, single-threaded).</p></div>`;
        return;
      }
      st.strategy = ov.models[0].strategy;
      const d = ov.day, sw = ov.switch;
      const tDays = ov.t.map((x) => Math.round((10 * (x - ov.t[0])) / d) / 10);
      const mark = [{ t: sw / d, label: `${ov.agents[0]} → ${ov.agents[1]} agents` }];
      p.innerHTML = `<p class="what"><b>The idea</b> (OPERATIONALIZATION.md, ideas 41-46): an AI agent orchestrator's tickets are stocks by state, and the agents are the machines that move them.
        Discover the model from the ticket counts alone, then read off what a manager wants to know: how much one agent gets done, how much review sends back, where tickets pile up, and what adding agents would buy.</p>
        <div class="hint small"><b>The simulated team</b> (a new system made for this demo, not a ladder case; one step is one hour, 30 days measured):
          tickets arrive (${fmt(ov.arrivals_per_day)} a day on average, more by day than by night), are picked up from the backlog, worked by the agents, reviewed, and landed by a merge gate.
          The true model: ${ov.true_flows.map((f) => `<span class="mono">${esc(f.ends)}</span> = <span class="mono">${esc(f.rate)}</span>`).join("; ")}.
          The number of agents is measured and set by hand: ${ov.agents[0]}, then ${ov.agents[1]} from day ${sw / d}. Measurements are exact (no noise).</div>
        <div class="grid">
          <div class="panel"><h3>tickets at each stage <span class="tag">measured</span></h3>
            ${h.chart(tDays, STAGES.map((s) => ({ ys: ov.series[s], color: STAGE[s], label: SHORT[s] })), { h: 140, zero: true, marks: mark, label: "tickets by stage" })}
            <div class="legend">${STAGES.map((s) => `<span><span class="key" style="border-color:${STAGE[s]}"></span>${SHORT[s]}</span>`).join("")}<span>x: day</span></div></div>
          <div class="panel"><h3>tickets done <span class="tag">a counter</span></h3>
            ${h.chart(tDays, [{ ys: ov.series.done, color: "var(--good)", label: "done" }], { h: 140, zero: true, marks: mark, label: "tickets done" })}
            <p class="small muted">With ${ov.agents[0]} agents the work piles up <i>in progress</i>; with ${ov.agents[1]} that pile drains and the next one forms at <i>merging</i>.</p></div>
        </div>
        <div class="controls" style="margin-top:10px"><label>Found model <select id="aw-strategy">${ov.models.map((m) => `<option value="${esc(m.strategy)}">${esc(m.strategy)}</option>`).join("")}</select></label>
          <span id="aw-src" class="src"></span></div>
        <div id="aw-found"></div>
        <h3 style="margin:16px 0 4px">Where do tickets pile up as agents are added?</h3>
        <p class="what">Each row runs both models two weeks on from day 30 with that many agents (the same arrivals), and reads the last week: tickets done a day, the stage where tickets pile up (the one growing fastest, or holding the most when none grows), and the lead time by Little's law (tickets in the system ÷ tickets done an hour).</p>
        <div class="controls"><label>arrivals <select id="aw-sx"><option value="0">as measured (${fmt(ov.arrivals_per_day)} a day)</option><option value="0.6">a busier month: +0.6 an hour (${fmt(ov.arrivals_per_day + 0.6 * d)} a day)</option></select></label></div>
        <div id="aw-sweep"><p class="busy">Running both models for each team size…</p></div>
        <h3 style="margin:16px 0 4px">What if we add more agents?</h3>
        <div class="controls"><label>add <input id="aw-add" type="number" value="4" min="-6" max="40" step="1" style="width:5em"> agents to today's ${ov.agents[1]}</label>
          <label>and <input id="aw-extra" type="number" value="0" min="-1.5" max="5" step="0.1" style="width:5em"> more tickets an hour arriving</label>
          <button class="primary" id="aw-run">Run two weeks</button></div>
        <div id="aw-what"></div>
        <h3 style="margin:16px 0 4px">The found model over the measured month</h3>
        <p class="small muted">The model's prediction of every stage beside the counts, and each flow's amount an hour beside the true model's (the simulation's record). The agents are set by hand (${ov.agents[0]} → ${ov.agents[1]} on day ${sw / d}); no flow moves them, so a model run free keeps the first day's ${ov.agents[0]}.</p>
        <div id="aw-view"></div>`;
      q("#aw-strategy").onchange = () => { st.strategy = q("#aw-strategy").value; foundUI(); sweepUI(); whatUI(); viewUI(); };
      q("#aw-run").onclick = whatUI;
      q("#aw-sx").onchange = sweepUI;
      foundUI(); sweepUI(); whatUI(); viewUI();
    }

    function viewUI() {
      const el = q("#aw-view");
      el.innerHTML = "";
      h.modelView(el, { source: "agent-work", strategy: st.strategy });
      if (h.toTop) h.toTop(el, "aw-view");
    }

    function foundUI() {
      const ov = st.ov, m = ov.models.find((x) => x.strategy === st.strategy), r = m.readings, T = ov.true, d = ov.day;
      q("#aw-src").innerHTML = `discovered once by <b>${esc(m.strategy)}</b> (code ${esc(m.commit)}${m.dirty ? ", uncommitted changes" : ""}, ${fmt(m.seconds)} s, ${esc(m.at)}) from the measured levels, the arrivals and the announced agent changes; cached in <span class="mono">~/.cache/sdlab/demos/agent-work/</span>${m.stale ? ` <b style="color:var(--bad)">(stale: the demo's true model changed since; re-run precompute)</b>` : ""}`;
      const row = (label, f, t, unit, note, tol) => {
        const ok = f !== null && f !== undefined && t !== null && t !== undefined && near(f, t, tol);
        const cls = f === null || f === undefined ? "bad" : ok ? "good" : "warn";
        const word = f === null || f === undefined ? "missed" : ok ? "matches" : "off";
        return `<tr><td>${label}</td><td class="num">${f === null || f === undefined ? "–" : fmt(f, 4) + unit}${off(f, t)}</td><td class="num">${t === null || t === undefined ? "–" : fmt(t, 4) + unit}</td>
          <td><span class="verdict-word" style="color:var(--${cls});font-weight:600">${word}</span> <span class="small muted">${esc(note || "")}</span></td></tr>`;
      };
      const n = (x, k = 1) => (x === null || x === undefined ? null : x * k);
      const okAgent = near(r.per_agent, T.per_agent), okRework = near(r.rework_share, T.rework_share), okGate = near(r.merge_cap, T.merge_cap) && near(r.merge_cap_16, T.merge_cap_16);
      const nOk = [okAgent, okRework, okGate].filter(Boolean).length;
      q("#aw-found").innerHTML = `<div class="verdict ${nOk === 3 ? "good" : nOk === 0 ? "bad" : "warn"}">
          <p><b>${nOk} of 3</b> things a manager asks were recovered: the agents' throughput ${okAgent ? "yes" : "<b>no</b>"}, the rework loop ${okRework ? "yes" : "<b>no</b>"}, the merge gate ${okGate ? "yes" : "<b>no</b>"}.</p>
          <div class="tablewrap"><table><thead><tr><th></th><th class="num">found</th><th class="num">true</th><th></th></tr></thead><tbody>
          ${row("tickets a day per agent (most an agent gets done)", n(r.per_agent, d), T.per_agent * d, "", r.agent_note)}
          ${row("share of reviewed tickets sent back to backlog (rework)", r.rework_share, T.rework_share, "", r.rework_note, 0.05)}
          ${row(`merge gate: most tickets landed a day, ${ov.agents[1]} agents`, n(r.merge_cap, d), T.merge_cap * d, "", r.merge_note)}
          ${row(`merge gate: most tickets landed a day, ${2 * ov.agents[1]} agents`, n(r.merge_cap_16, d), T.merge_cap_16 * d, "", "")}
          ${row("agents needed to keep up with arrivals + rework (flow balance)", m.agents_needed, ov.agents_needed_true, "", "arrivals a day ÷ (1 − rework share) ÷ tickets a day per agent")}
          </tbody></table></div></div>
        <details><summary class="small muted">every flow: true beside found</summary><div class="tablewrap"><table><thead><tr><th>between</th><th>true</th><th>found</th><th></th></tr></thead><tbody>
          ${m.flows.map((f) => `<tr><td class="mono small">${esc(f.ends)}</td><td class="mono small">${esc(f.true || "–")}</td><td class="mono small">${esc(f.found || "–")}</td>
            <td style="color:var(--${f.status === "found" ? "good" : "bad"})">${f.status === "false" ? "not in the truth" : f.status}</td></tr>`).join("")}</tbody></table></div>
          <p class="small muted">"found" means a flow between the same two stages; its equation may still differ (read the two columns).</p></details>`;
    }

    async function sweepUI() {
      const out = q("#aw-sweep");
      out.innerHTML = `<p class="busy">Running both models for each team size…</p>`;
      let r;
      try { r = await get(`${API}/sweep?strategy=${encodeURIComponent(st.strategy)}&extra=${encodeURIComponent(q("#aw-sx").value)}`); } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const xs = r.rows.map((x) => x.agents);
      const pile = (s) => `${SHORT[s.pile]}${s.growing ? " ↑" : s.why === "at its cap" ? " (at its cap)" : ""}`;
      const agree = r.rows.filter((x) => x.found.pile === x.truth.pile).length;
      const top = (k) => Math.max(...r.rows.map((x) => x[k].done_per_day));
      const enough = (k) => (r.rows.find((x) => x[k].done_per_day >= 0.98 * top(k)) || {}).agents;
      const tTop = top("truth"), fTop = top("found"), okTop = near(fTop, tTop, 0.03);
      const limit = r.rows[r.rows.length - 1].truth.pile;
      out.innerHTML = `<div class="verdict ${okTop && agree === r.rows.length ? "good" : okTop ? "warn" : "bad"}">
          <p>True model: past <b>${enough("truth")} agents</b> more agents buy nothing; the most it gets done is <b>${fmt(tTop)}</b> a day${limit !== "none" ? `, held there by <b>${SHORT[limit]}</b>` : ""}${tTop < r.arrivals_per_day * 0.98 ? ` (fewer than the ${fmt(r.arrivals_per_day)} arriving: the backlog of work grows)` : " (all that arrive)"}.</p>
          <p>Found model: past ${enough("found")} agents, at most <b>${fmt(fTop)}</b> a day${off(fTop, tTop)}${okTop ? "" : `: <b>wrong</b>, it ${fTop > tTop ? "promises more than the team can deliver" : "promises less than the team delivers"}`}. The bottleneck stage agrees on ${agree} of ${r.rows.length} team sizes.</p></div>
        <div class="grid"><div class="panel"><h3>tickets done a day <span class="tag">last week of two</span></h3>
          ${h.chart(xs, [{ ys: r.rows.map((x) => x.truth.done_per_day), color: "var(--fg)", dash: "4 3", label: "true model" }, { ys: r.rows.map((x) => x.found.done_per_day), color: "var(--accent)", label: "found model" }],
            { h: 140, zero: true, hline: r.arrivals_per_day, label: "done a day by agents" })}
          <div class="legend"><span><span class="key" style="border-color:var(--fg);border-top-style:dashed"></span>true</span><span><span class="key" style="border-color:var(--accent)"></span>found</span>
            <span><span class="key" style="border-color:var(--bad);border-top-style:dashed"></span>tickets arriving a day</span><span>x: agents</span></div></div>
        <div class="panel tablewrap"><table><thead><tr><th class="num">agents</th><th class="num">done a day: found</th><th class="num">true</th><th>pile: found</th><th>true</th><th class="num">lead time (h): found</th><th class="num">true</th></tr></thead><tbody>
          ${r.rows.map((x) => `<tr${x.add === 0 ? ` style="font-weight:600"` : ""}><td class="num">${x.agents}${x.add === 0 ? " (today)" : ""}</td><td class="num">${fmt(x.found.done_per_day)}</td><td class="num">${fmt(x.truth.done_per_day)}</td>
            <td style="color:var(--${x.found.pile === x.truth.pile ? "good" : "bad"})">${pile(x.found)}</td><td>${pile(x.truth)}</td><td class="num">${fmt(x.found.lead_hours)}</td><td class="num">${fmt(x.truth.lead_hours)}</td></tr>`).join("")}</tbody></table>
          <p class="small muted">pile: the bottleneck. ↑: still growing in the last week (more arrives there than leaves); "at its cap": its outflow runs at the most it can at least 5% of hours; none: every stage keeps up.</p></div></div>`;
    }

    async function whatUI() {
      const out = q("#aw-what");
      out.innerHTML = `<p class="busy">Simulating two weeks…</p>`;
      let r;
      try { r = await get(`${API}/forecast?strategy=${encodeURIComponent(st.strategy)}&add=${encodeURIComponent(q("#aw-add").value)}&extra=${encodeURIComponent(q("#aw-extra").value)}`); } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const f = r.summary.found, t = r.summary.truth, d = st.ov.day;
      const ok = near(f.done_per_day, t.done_per_day, 0.05);
      const days = r.t.map((x) => Math.round((10 * (x - r.t[0])) / d) / 10);
      out.innerHTML = `<div class="verdict ${ok && f.pile === t.pile ? "good" : ok || f.pile === t.pile ? "warn" : "bad"}">
          <p>With <b>${r.agents} agents</b>${r.extra ? ` and ${fmt(r.extra)} more tickets an hour` : ""}, in the second week: the found model says <b>${fmt(f.done_per_day)}</b> tickets done a day, the true model does <b>${fmt(t.done_per_day)}</b>${off(f.done_per_day, t.done_per_day)}.</p>
          <p>Bottleneck: found <b>${SHORT[f.pile]}</b> (${esc(f.why)}), true <b>${SHORT[t.pile]}</b> (${esc(t.why)}). Lead time (Little's law): found ${fmt(f.lead_hours)} h, true ${fmt(t.lead_hours)} h; tickets in the system: found ${fmt(f.wip)}, true ${fmt(t.wip)}.</p></div>
        <div class="legend"><span><span class="key" style="border-color:var(--accent)"></span>found model</span><span><span class="key" style="border-color:var(--fg);border-top-style:dashed"></span>true model</span><span>x: days from day 30</span></div>
        <div class="grid">${[...STAGES, "done"].map((s) => `<div class="panel"><h3>${s === "done" ? "done" : SHORT[s]} <span class="tag">tickets</span></h3>
          ${h.chart(days, [{ ys: r.truth[s], color: "var(--fg)", dash: "4 3", label: "true" }, { ys: r.found[s], color: "var(--accent)", label: "found" }], { h: 100, zero: true, label: s })}</div>`).join("")}</div>`;
    }

    start();
  }

  function register() { window.SDDemos.register({ tab: "agent-work", title: "13. Agent work as stocks", ui }); }
  if (window.SDDemos) register(); else window.addEventListener("load", register);
})();
