// Demo 16, verify an AI agent's effect (docs/demos/agent-verify.md): a discrete-event simulation of an on-call
// support flow, a best-effort SD model discovered from its counts, an AI agent (a separate program emitting events)
// added at day 21, and the design's intended effect checked against the model's view and the truth from the event
// log. API: /api/demos/agent-verify/{overview,verify} (sdlab/demos/agent_verify.py). Read only.
(function () {
  "use strict";
  const API = "/api/demos/agent-verify";
  const STOCK = { queued: "waiting for triage", in_triage: "in triage", in_fix: "in fix" };
  const WORD = { yes: "Yes", partly: "Partly", no: "No" };
  const CLS = { yes: "good", partly: "warn", no: "bad" };

  function ui(p, h) {
    const { get, esc, fmt } = h;
    const st = { ov: null };
    const q = (s) => p.querySelector(s);
    const pc = (x, d = 0) => (x === null || x === undefined || !isFinite(x) ? "–" : `${(100 * x).toFixed(d)}%`);
    const sg = (x) => (x === null || x === undefined || !isFinite(x) ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(100 * x).toFixed(0)}%`);
    p.innerHTML = `<p class="busy">Loading the on-call simulation…</p>`;

    function val(c, x) {
      if (x === null || x === undefined) return `<span class="muted">cannot see</span>`;
      if (c.kind === "share") return pc(x, 1);
      if (c.kind === "change") return sg(x);
      if (c.kind === "speed") return `×${fmt(x)}`;
      return `${x >= 0 ? "+" : ""}${fmt(x)} a day`;
    }
    const mark = (m) => (m === null || m === undefined ? "" : m ? ` <span style="color:var(--good)">✓</span>` : ` <span style="color:var(--bad)">✗</span>`);

    async function start() {
      try { st.ov = await get(`${API}/overview`); } catch (e) { p.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const ov = st.ov, D = ov.design, S = ov.system;
      if (!ov.strategies.length) {
        p.innerHTML = `<div class="verdict bad"><p>No cached found model. Run <span class="mono">${esc(ov.command)}</span> (about 2 minutes, single-threaded).</p></div>`;
        return;
      }
      p.innerHTML = `<p class="what"><b>The idea</b> (OPERATIONALIZATION.md, ideas 42-43): before deploying an AI agent, state how it should change the system, as an edit to the system's model.
        After deploying it, check through the model whether it did. Here the system is not a system dynamics model at all: it is a discrete-event simulation, so the model discovered from its counts is only a best-effort guess.
        Because the simulation keeps a log of every event, the true effect is known exactly and the page can show how far the model's view was off.</p>
        <div class="hint small"><b>The system</b> (a discrete-event simulation made for this demo: a heap of timed events, one entity per item, seeded random draws; ${ov.days} days, sampled every ${ov.every_hours * 60} minutes):
          alerts and tickets arrive at random (about ${fmt(S.arrivals_mean)} an hour on weekdays, more by day, ${pc(S.weekend)} of that at weekends); on-call engineers (${esc(ov.shifts)}) triage one item at a time, oldest first (lognormal, ${fmt(S.triage_mean * 60)} minutes on average);
          ${pc(S.fix_share)} need a fix, which the dev team works in parallel (about ${fmt(S.fix_mean)} hours); ${pc(S.reopen_share)} of resolved items reopen about ${fmt(S.reopen_mean)} hours later.
          Monitoring sees only the counts: items waiting, in triage, in fix, resolved, plus new items and engineers on shift.
          <br><b>The agent</b> joins on day ${ov.deploy_day}. It is a separate program: the simulation tells it about new items, and it decides by its own rules and schedules its own events.
          It takes each new item while it has a free slot (${D.slots} at a time, about ${fmt(D.handle_hours * 60)} minutes each), then resolves it, closes it wrongly (the item reopens hours later), or hands it to the humans with a triage note.</div>
        <div class="verdict"><p><b>The design says</b> the agent resolves <b>${pc(D.resolve_share)}</b> of new items itself, its notes make the humans' triage of the rest <b>${pc(1 - D.note_factor)}</b> shorter, and it closes at most <b>${pc(D.misroute_max)}</b> wrongly.
          So the items waiting for triage should fall by about <b>${pc(-D.targets.queue)}</b>, the hours an item is open by about <b>${pc(-D.targets.hours_open)}</b>, and reopens should barely rise.</p></div>
        <div class="controls"><label style="max-width:100%">The agent as it really behaves <select id="av-variant" style="max-width:100%">${Object.entries(ov.variants).map(([k, v]) => `<option value="${esc(k)}">${esc(k)}: ${esc(v)}</option>`).join("")}</select></label>
          <label>Found model <select id="av-strategy">${ov.strategies.map((s) => `<option>${esc(s)}</option>`).join("")}</select></label></div>
        <div id="av-out"></div>`;
      q("#av-variant").onchange = run;
      q("#av-strategy").onchange = run;
      run();
    }

    async function run() {
      const out = q("#av-out");
      out.innerHTML = `<p class="busy">Reading the cached analysis…</p>`;
      let r;
      try { r = await get(`${API}/verify?strategy=${encodeURIComponent(q("#av-strategy").value)}&variant=${encodeURIComponent(q("#av-variant").value)}`); }
      catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const v = r.verdict, tr = r.true, C = r.charts, ov = st.ov;
      const by = Object.fromEntries(v.claims.map((c) => [c.key, c]));
      const side = tr.reopens_per_day.extra > v.allowance
        ? ` Side effect: <b>${fmt(tr.reopens_per_day.extra)} more reopened items a day</b> (${fmt(tr.reopens_per_day.without)} → ${fmt(tr.reopens_per_day.with)}), because it closed ${pc(tr.misroute_share, 1)} of new items wrongly.` : "";
      const same = v.word === v.model_word;
      const days = C.t_days.map((x) => Math.floor(x)), dep = ov.deploy_day;
      const marks = [{ t: dep, label: "agent on" }];
      const n = days.length, at = C.after_start;
      const chart = (s) => h.chart(days, [
        { ys: C.observed[s], color: "var(--faint)", label: "measured (the run with the agent)" },
        { ys: C.true_counterfactual[s].map((y, i) => (i >= at ? y : null)), color: "var(--fg)", dash: "4 3", label: "true counterfactual (the run without the agent)" },
        { ys: pad(C.before_fit[s], 0, n), color: "var(--eq)", label: "found model run free (fit)" },
        { ys: pad(C.counterfactual[s], at, n), color: "var(--accent2)", dash: "2 2", label: "found model's counterfactual" },
        { ys: pad(C.predicted[s], at, n), color: "var(--good)", label: "prediction: found model + the design's edit" },
      ], { h: 140, zero: true, marks, label: STOCK[s] });
      out.innerHTML = `<div class="verdict ${CLS[v.word]}">
          <p><b>Did the agent have the intended effect? ${WORD[v.word]}</b> (the truth, from the event log: ${v.n_met} of ${v.n} claims met).
            Items waiting for triage ${sg(tr.queue.change)} (intended ${sg(ov.design.targets.queue)}), hours open per item ${sg(tr.hours_open.change)} (intended ${sg(ov.design.targets.hours_open)});
            it resolved ${pc(tr.resolve_share, 1)} of new items itself (intended ${pc(ov.design.resolve_share)}).${side}</p>
          <p><b>Through the model: ${WORD[v.model_word]}</b>, ${same ? "the same verdict" : `<b>a different verdict</b>`}. The model agrees with the truth on ${v.model_agrees} of the ${v.model_judged} claims it can judge;
            ${v.n - v.model_judged} it cannot see at all (wrong closes, reopens, the notes' speed-up).${!same && v.word === "no" ? " It misses the harm: a wrong close looks like a resolution in the counts." : ""}</p></div>
        <div class="tablewrap"><table><thead><tr><th>the design's claim</th><th class="num">intended</th><th class="num">predicted<br><span class="small">model + edit</span></th>
          <th class="num">through the model<br><span class="small">after deployment</span></th><th class="num">true<br><span class="small">event log</span></th><th>notes</th></tr></thead><tbody>
          ${v.claims.map((c) => `<tr><td>${esc(c.claim)}</td><td class="num">${val(c, c.intended)}</td><td class="num">${c.predicted === null ? "–" : val(c, c.predicted)}</td>
            <td class="num">${val(c, c.model)}${mark(c.met_model)}</td><td class="num"><b>${val(c, c.true)}</b>${mark(c.met_true)}</td><td class="small muted">${esc(c.note || "")}</td></tr>`).join("")}
          </tbody></table></div>
        <p class="small muted">✓ / ✗: the claim met or not (a share within 10% of the plan, a cut at least 80% of the target, wrong closes at most 1.25× the limit). The overall word: yes when every claim is met; no when the queue or the hours open moved less than half the target, or reopens rose more than 3× the allowance; partly otherwise.
          The prediction and the model's view of the outcomes use the model's own counterfactual as the baseline; the truth compares the run with the agent to the same run without it (the same arrivals, the same items' random draws).</p>
        <h3 style="margin:16px 0 4px">The counts, before and after</h3>
        <div class="legend"><span><span class="key" style="border-color:var(--faint)"></span>measured</span><span><span class="key" style="border-color:var(--fg);border-top-style:dashed"></span>true counterfactual (no agent)</span>
          <span><span class="key" style="border-color:var(--eq)"></span>found model run free (days 0-21)</span><span><span class="key" style="border-color:var(--accent2);border-top-style:dotted"></span>found model's counterfactual</span>
          <span><span class="key" style="border-color:var(--good)"></span>predicted: model + the design's edit</span><span>x: day; daily means</span></div>
        <div class="grid">${Object.keys(STOCK).map((s) => `<div class="panel"><h3>${STOCK[s]} <span class="tag">items</span></h3>${chart(s)}</div>`).join("")}</div>
        <div class="grid" style="margin-top:10px">
          <div class="panel"><h3>How wrong the model is <span class="tag">days 0-21, before the agent</span></h3>
            <div class="tablewrap"><table><thead><tr><th></th><th class="num">measured mean</th><th class="num">model run free: mean</th><th class="num">free-run error</th><th class="num">one-step error</th></tr></thead><tbody>
            ${Object.keys(STOCK).map((s) => { const f = r.fit[s]; return `<tr><td>${STOCK[s]}</td><td class="num">${fmt(f.mean)}</td><td class="num">${fmt(f.free_mean)}</td><td class="num">${fmt(f.free_rmse)}</td><td class="num">${fmt(f.one_step_rmse)}</td></tr>`; }).join("")}
            </tbody></table></div>
            <p class="small muted">Errors are root-mean-square, in items. After deployment, the model's counterfactual puts ${fmt(r.stats.counterfactual.queue)} items waiting on average where the true counterfactual has ${fmt(r.stats.true_counterfactual.queue)},
              and ${fmt(r.stats.counterfactual.hours_open)} hours open per item where the truth has ${fmt(r.stats.true_counterfactual.hours_open)} (Little's law). Its effects are measured against its own baseline, so part of this bias cancels.</p></div>
          <div class="panel"><h3>The design as an edit of the model</h3>
            <div class="tablewrap"><table><thead><tr><th>flow</th><th>number</th><th class="num">from</th><th class="num">to</th></tr></thead><tbody>
            ${r.edits.map((e) => `<tr><td class="mono small">${esc(e.ends)}</td><td class="mono small">${esc(e.label)}</td><td class="num">${e.from === null ? "–" : fmt(e.from, 4)}</td><td class="num mono small">${typeof e.to === "number" ? fmt(e.to, 4) : esc(e.to)}</td></tr>`).join("")}
            </tbody></table></div>
            <p class="small muted">A new flow for the agent's resolutions, capped by its slots, and the humans' triage numbers (what the model multiplies the engineers by, and the share of in-triage items that leave a step) divided by the note factor ${fmt(ov.design.note_factor)}.</p></div>
        </div>
        <details style="margin-top:10px"><summary class="small muted">the found model (${esc(r.strategy)}): every flow</summary>
          <p class="src">Discovered once by <b>${esc(r.strategy)}</b> (code ${esc(r.found.commit)}${r.found.dirty ? ", uncommitted changes" : ""}, ${fmt(r.found.seconds)} s, ${esc(r.found.at)}) from the first 21 days' counts, the new items and the engineers on shift; cached in <span class="mono">~/.cache/sdlab/demos/agent-verify/</span>${r.found.stale ? ` <b style="color:var(--bad)">(stale: the simulation changed since; re-run precompute)</b>` : ""}.
            There is no true SD model to hold it against: the true process is the event simulation. Items in the simulation always pass through triage; flows straight from the queue are the model's way of writing triage that starts and ends within one quarter hour.</p>
          <div class="tablewrap"><table><tbody>${r.found.flows.map((f) => `<tr><td class="mono small">${esc(f.ends)}</td><td class="mono small">${esc(f.rate)}</td></tr>`).join("")}</tbody></table></div></details>
        <details><summary class="small muted">the event log from deployment on (the first 60 events) and the agent's counts</summary>
          <p class="small">From day ${dep} to ${ov.days}: ${fmt(tr.new_items)} new items; the agent took ${fmt(tr.agent.takes)}, resolved ${fmt(tr.agent.resolves)}, closed ${fmt(tr.agent.misroutes)} wrongly and handed ${fmt(tr.agent.hands_off)} to the humans.
            Reopened items a day: ${fmt(tr.reopens_per_day.without)} without the agent, ${fmt(tr.reopens_per_day.with)} with it. ${tr.still_open ? `${tr.still_open} items opened in those weeks were still open 3 days after the end.` : ""}</p>
          <div class="tablewrap"><table><thead><tr><th class="num">hour</th><th>who</th><th>what</th><th class="num">item</th></tr></thead><tbody>
          ${r.log.map((e) => `<tr><td class="num">${fmt(e[0], 6)}</td><td>${esc(e[1])}</td><td${e[2] === "misroutes" ? ` style="color:var(--bad)"` : ""}>${esc(e[2])}</td><td class="num">#${e[3]}</td></tr>`).join("")}</tbody></table></div></details>
        <h3 style="margin:16px 0 4px">The found model against the counts and the event log</h3>
        <p class="small muted">There is no true SD model here, so the "true" flows are what the event log moves between the sampled states each quarter hour:
          new items (outside → queued), triage starting (queued → in triage), sent to fix (in triage → in fix), resolved at triage (in triage → resolved), fixed (in fix → resolved), reopened (resolved → queued), and from day ${dep} the agent's closes, right or wrong (queued → resolved).
          These add up exactly to the sampled counts. What has no true counterpart: the found model's equations (the truth is events, not rates); its flows between stocks no event links (marked "found only", e.g. a flow straight from the queue to a fix: triage that starts and ends inside one quarter hour); and the agent's takes and hand-offs, which happen inside "queued" (an item the agent reads is counted as waiting).
          Before day ${dep} there is no agent, so a found queued → resolved flow is "found only" there.</p>
        <div class="controls"><label>Period <select id="av-period"><option value="before">days 0-${dep}: before the agent (what discovery saw)</option><option value="after">days ${dep}-${ov.days}: with the agent</option><option value="all">all ${ov.days} days</option></select></label></div>
        <div id="av-view"></div>`;
      const ps = q("#av-period");
      ps.value = st.period || "before";
      const view = () => { st.period = ps.value; const el = q("#av-view"); el.innerHTML = ""; h.modelView(el, { source: "agent-verify", strategy: r.strategy, variant: r.variant, period: ps.value }); };
      ps.onchange = view;
      view();
    }
    function pad(ys, at, n) { const out = new Array(n).fill(null); (ys || []).forEach((y, i) => { if (at + i < n) out[at + i] = y; }); return out; }

    start();
  }

  function register() { window.SDDemos.register({ tab: "agent-verify", title: "16. Verify an AI agent's effect", ui }); }
  if (window.SDDemos) register(); else window.addEventListener("load", register);
})();
