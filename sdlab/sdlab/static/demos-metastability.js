// Demo 6, metastability scan (docs/demos/metastability.md): load spikes swept over a kubernetes case, through the
// true model and the stored found models of several strategies; each run recovers or stays stuck. Read only.
(function () {
  "use strict";
  if (!window.SDDemos) return;
  const API = "/api/demos/metastability";
  const DUR = (steps) => { const m = 5 * steps; return m < 60 ? `${m} min` : m % 60 ? `${Math.floor(m / 60)} h ${m % 60}` : `${m / 60} h`; };
  const BAND_CLS = { "within 1 h": "b1", "within 6 h": "b2", "within a day": "b3", stuck: "b4" };

  function css() {
    if (document.getElementById("ms-css")) return;
    const st = document.createElement("style");
    st.id = "ms-css";
    st.textContent = `
      .ms-ctl label { max-width: 100%; }
      .ms-ctl select { max-width: 100%; }
      .ms-grid table { font-size: 11px; table-layout: fixed; }
      .ms-grid th, .ms-grid td { padding: 3px 2px; text-align: center; border-bottom: 0; }
      .ms-grid th.rowh { text-align: right; padding-right: 6px; white-space: nowrap; width: 3.6em; }
      .ms-grid td.cell { cursor: pointer; border: 1px solid var(--surface); border-radius: 3px; font-variant-numeric: tabular-nums; }
      .ms-grid td.cell:hover { outline: 2px solid var(--fg); }
      .ms-grid td.b1 { background: color-mix(in srgb, var(--good) 30%, transparent); }
      .ms-grid td.b2 { background: color-mix(in srgb, var(--warn) 18%, transparent); }
      .ms-grid td.b3 { background: color-mix(in srgb, var(--warn) 50%, transparent); }
      .ms-grid td.b4 { background: color-mix(in srgb, var(--bad) 55%, transparent); color: var(--fg); font-weight: 600; }
      .ms-grid td.miss { outline: 2px dashed var(--bad); outline-offset: -2px; }
      .ms-grid td.diff { box-shadow: inset 0 0 0 2px var(--fg); }
      .ms-grid td.on { outline: 2px solid var(--accent); outline-offset: -1px; }
      .ms-grid .gsum { font-size: 12px; margin: 4px 0 0; }
      .ms-sw { display: inline-block; width: 12px; height: 12px; border-radius: 2px; vertical-align: -2px; margin-right: 4px; }
      .ms-ex { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 10px; }
      .ms-ex h3 { flex-wrap: wrap; }
      .ms-ex .panel p { margin: 0 0 4px; font-size: 13px; }
    `;
    document.head.appendChild(st);
  }

  // the shared model view (demos.js modelView) for the found model shown, at the end of the tab; replaced when the model changes
  function mview(p, h, s) {
    const key = [s.case, s.variant, s.strategy, s.result || ""].join("|"), old = p.querySelector(":scope > details.mview");
    if (old && old.dataset.key === key) return;
    if (old) old.remove();
    if (!h.modelView) return;
    const box = h.modelView(p, { case: s.case, variant: s.variant, strategy: s.strategy, ...(s.result ? { result: s.result } : {}) });
    box.dataset.key = key;
  }

  function ui(p, h) {
    css();
    const { get, esc, fmt, chart } = h;
    const S = { opts: null, scan: null, strategy: "milp", pick: null, seq: 0, exSeq: 0 };

    function cellText(c) {
      if (c.recovery === null) return c.growing ? "stuck ↑" : "stuck";
      return c.recovery === 0 ? "0" : DUR(c.recovery).replace(" min", "m").replace(" h ", "h").replace(" h", "h");
    }
    function gridHTML(title, sub, g, truthGrid, who, foot = "") {
      const head = `<tr><th class="rowh"></th>${S.scan.heights.map((x) => `<th>+${x}</th>`).join("")}</tr>`;
      const rows = g.map((row, i) => `<tr><th class="rowh">${DUR(row[0].width)}</th>${row.map((c, j) => {
        const t = truthGrid ? truthGrid[i][j] : null;
        const cls = [BAND_CLS[c.band]];
        if (t && t.band === "stuck" && c.band !== "stuck") cls.push("miss");
        else if (t && t.band !== c.band) cls.push("diff");
        const tip = `+${c.height} requests a step for ${DUR(c.width)}: ${c.recovery === null ? `not back within a day${c.growing ? " (the queue is still growing)" : " (still draining)"}` : `back to normal ${DUR(c.recovery)} after the spike`}; the queue peaked at ${fmt(c.peak_queue)}` +
          (t ? `. True model: ${t.recovery === null ? "stuck" : DUR(t.recovery)}` : "");
        return `<td class="cell ${cls.join(" ")}" data-who="${esc(who)}" data-h="${c.height}" data-w="${c.width}" title="${esc(tip)}">${esc(cellText(c))}</td>`;
      }).join("")}</tr>`).join("");
      return `<div class="panel ms-grid"><h3>${title}</h3>${sub}<div class="tablewrap"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>${foot}</div>`;
    }

    p.innerHTML = `<p class="what"><b>The idea:</b> a <i>metastable failure</i> (Bronson et al., HotOS 2021) starts with a trigger, such as a load spike, and is kept going by a reinforcing loop
      (timeouts → retries → more load → more timeouts) after the trigger is gone. Here load spikes of many sizes and lengths are pushed through the true model and through each strategy's found model;
      each run either gets back to its normal queue or stays stuck. The grid of answers is the <b>safe-load envelope</b>. The spike is added to the traffic of an in-memory copy of the true model, and the same traffic is fed to the found models.</p>
      <div class="controls ms-ctl">
        <label>Service <select id="ms-case"></select></label>
        <label>Retry behaviour <select id="ms-mech"></select></label>
        <label>Spike starts <select id="ms-start"></select></label>
        <label>Examples from <select id="ms-strat"></select></label>
      </div>
      <div id="ms-out"><p class="busy">Loading…</p></div>`;
    const $ = (s) => p.querySelector(s);

    (async function start() {
      try { S.opts = await get(`${API}/options`); } catch (e) { $("#ms-out").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const o = S.opts;
      $("#ms-case").innerHTML = Object.entries(o.cases).map(([k, v]) => `<option value="${esc(k)}">${esc(v.label)}</option>`).join("");
      $("#ms-mech").innerHTML = Object.entries(o.mechanisms).map(([k, v]) => `<option value="${esc(k)}">${esc(v.label)}</option>`).join("");
      $("#ms-start").innerHTML = Object.entries(o.starts).map(([k, v]) => `<option value="${esc(k)}"${k === "ramp" ? " selected" : ""}>${esc(k === "ramp" ? "as traffic rises" : k === "peak" ? "at the daily peak" : "at the night's low")} (step ${v})</option>`).join("");
      $("#ms-strat").innerHTML = o.strategies.map((s) => `<option>${esc(s)}</option>`).join("");
      for (const id of ["#ms-case", "#ms-mech", "#ms-start"]) $(id).onchange = runScan;
      $("#ms-strat").onchange = () => { S.strategy = $("#ms-strat").value; examples(); };
      runScan();
    })();

    async function runScan() {
      const out = $("#ms-out");
      out.innerHTML = `<p class="busy">Sweeping ${S.opts.heights.length * S.opts.widths.length} spikes through the true model and ${S.opts.strategies.length} found models (seconds when cached, about 10 s the first time)…</p>`;
      const q = `case=${encodeURIComponent($("#ms-case").value)}&mechanism=${encodeURIComponent($("#ms-mech").value)}&start=${encodeURIComponent($("#ms-start").value)}`;
      const my = ++S.seq;
      let r;
      try { r = await get(`${API}/scan?${q}`); } catch (e) { if (my === S.seq) out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      if (my !== S.seq) return;                                   // a newer choice is on its way
      S.scan = r; S.pick = null;
      const cells = r.truth.grid.flat(), n = cells.length;
      const stuck = cells.filter((c) => c.band === "stuck"), growing = stuck.filter((c) => c.growing);
      const rec = cells.filter((c) => c.recovery !== null), slow = rec.reduce((a, c) => (c.recovery > (a ? a.recovery : -1) ? c : a), null);
      const k = r.mechanism.k, amp = 0.6 + k, cov = r.coverage;
      let cls, head;
      if (r.truth.base_stuck) { cls = "bad"; head = `<b>Broken with no spike at all:</b> with this retry behaviour the true system's own daily peak tips it over; the queue grows without end (to ${fmt(r.truth.base_peak)}) even when nothing extra arrives. The grid below is meaningless here: every run, spike or not, is broken.`; }
      else if (growing.length) { cls = "bad"; head = `<b>The true system has a metastable region:</b> ${growing.length} of ${n} spikes leave it broken: the queue is still growing a day after the spike ended, though traffic is back to normal. Smaller spikes recover; the boundary between them is the safe-load envelope.`; }
      else if (stuck.length) { cls = "warn"; head = `<b>No metastable region, but ${stuck.length} of ${n} spikes are not back within a day:</b> the queue is still draining, slowly, a day later (not growing).`; }
      else { cls = "good"; head = `<b>The true system has no metastable region here:</b> every one of the ${n} spikes recovers. The nearest real effect is a <b>long recovery</b>: the slowest, +${slow.height} requests a step for ${DUR(slow.width)}, takes ${DUR(slow.recovery)} to get back to normal.`; }
      const why = k === 0
        ? `Why: a request that times out comes back only ${fmt(0.6)} times (40% of clients give up). Below the dispatch cap the queue loses ${fmt(100 * r.loop.loss_below_cap)}% a step; at the cap (<span class="mono">${esc(r.truth.dispatch)}</span>) it still loses ${fmt(100 * r.loop.loss_at_cap, 2)}% a step to clients giving up, so a backlog always drains, but slowly once the cap binds.`
        : `The change (in-memory copies of the true model and of each found model alike): a second retry layer adds ${fmt(k)} × <span class="mono">retries</span> to the queue each step, so a timed-out request comes back ${fmt(amp)} times. ${amp > 1 ? "Above 1, once the dispatch cap binds the retry loop feeds itself: the queue grows unless the pods catch up, and the autoscaler is capped too (16 pods; 12 on 311's node pool)." : "Below 1 the loop cannot feed itself, but each backlog drains more slowly."}`;
      const covText = cov.bound_steps ? `In the measured data discovery saw, the dispatch cap bound on <b>${cov.bound_steps}</b> of ${cov.steps} steps (queue up to ${fmt(cov.max_queue)}).`
        : `In the measured data discovery saw, the dispatch cap <b>never bound</b>: dispatch reached at most ${fmt(100 * cov.max_ratio)}% of it (queue up to ${fmt(cov.max_queue)}).`;
      const nocap = r.found.filter((f) => !f.missing && !f.cap).map((f) => f.strategy), withcap = r.found.filter((f) => !f.missing && f.cap).map((f) => f.strategy);
      const lesson = nocap.length
        ? `<p><b>A model is only valid where the data has been.</b> ${nocap.length === r.found.length ? "None" : "Some"} of the found models (${nocap.map(esc).join(", ")}) have the cap: they write dispatch as <span class="mono">${esc(r.found.find((f) => f.strategy === nocap[0]).dispatch)}</span>, which fits every measured step exactly because the cap never bound there. So they drain any backlog at 60% a step and say every spike recovers within minutes. They cannot show the tipping point.</p>`
        : `<p><b>Every found model has the cap</b> (${withcap.map(esc).join(", ")}): the data showed it binding, so they can show where spikes tip the system over.</p>`;
      out.innerHTML = `<div class="verdict ${cls}"><p>${head}</p><p class="small">${why}</p></div>
        <div class="verdict ${nocap.length ? "warn" : "good"}"><p>${covText}</p>${lesson}</div>
        <div class="legend"><span><span class="ms-sw" style="background:color-mix(in srgb, var(--good) 30%, transparent)"></span>back within 1 h</span>
          <span><span class="ms-sw" style="background:color-mix(in srgb, var(--warn) 18%, transparent)"></span>within 6 h</span>
          <span><span class="ms-sw" style="background:color-mix(in srgb, var(--warn) 50%, transparent)"></span>within a day</span>
          <span><span class="ms-sw" style="background:color-mix(in srgb, var(--bad) 55%, transparent)"></span>not back within a day (↑ still growing)</span>
          <span>dashed red: the found model says safe where the truth is stuck; black frame: another band than the truth</span></div>
        <p class="muted small">Columns: extra requests a step (normal traffic is 180-620 a step); rows: how long the spike lasts. A cell is the time from the spike's end until the queue is within ${fmt(100 * r.tolerance.relative)}% (or ${fmt(r.tolerance.absolute)} requests) of the same model's run without the spike and stays there for 2 hours; a day is watched. Click a cell to see that run.</p>
        <div class="grid">${gridHTML("True model", `<p class="small muted">case <span class="mono">${esc(r.case)}</span> ${esc(r.variant)}, noise-free, in the truth engine</p>`, r.truth.grid, null, "truth")}
        ${r.found.map((f) => f.missing ? `<div class="panel"><h3>${esc(f.strategy)}</h3><p class="muted">${esc(f.missing)}</p></div>` : gridHTML(
          `${esc(f.strategy)} <span class="tag">${f.cap ? "has the cap" : "no cap"}</span>`,
          `<p class="small muted">stored result #${esc(f.source.result)} (${esc(f.source.status)}, code ${esc(f.source.commit)}); dispatch <span class="mono">${esc(f.dispatch)}</span></p>`, f.grid, r.truth.grid, f.strategy,
          `<p class="gsum">${agreeText(f.agreement)}</p>`)).join("")}</div>
        <h3 style="margin:16px 0 6px">Two runs, the true model beside <span id="ms-exname"></span></h3>
        <div id="ms-examples"></div>`;
      out.querySelectorAll("td.cell").forEach((td) => (td.onclick = () => {
        if (td.dataset.who !== "truth") { S.strategy = td.dataset.who; $("#ms-strat").value = S.strategy; }
        S.pick = { height: +td.dataset.h, width: +td.dataset.w };
        examples();
      }));
      examples();
    }

    function agreeText(a) {
      if (!a) return "";
      const bits = [`<b>${a.same_band}/${a.cells}</b> cells in the truth's band`];
      if (a.missed_stuck) bits.push(`<span style="color:var(--bad)">calls ${a.missed_stuck} stuck spike${a.missed_stuck === 1 ? "" : "s"} safe</span>`);
      if (a.false_stuck) bits.push(`calls ${a.false_stuck} safe spike${a.false_stuck === 1 ? "" : "s"} stuck`);
      if (a.worst_underestimate !== null && a.worst_underestimate < -6) bits.push(`recovery up to ${DUR(-a.worst_underestimate)} too fast`);
      return bits.join("; ") + ".";
    }

    function defaults() {
      const cells = S.scan.truth.grid.flat();
      const area = (c) => c.height * c.width;
      const stuck = cells.filter((c) => c.band === "stuck").sort((a, b) => area(a) - area(b));
      const rec = cells.filter((c) => c.recovery !== null);
      const first = stuck.length ? stuck[0] : rec.slice().sort((a, b) => b.recovery - a.recovery)[0];
      const quick = rec.filter((c) => c.recovery <= 12 && c !== first).sort((a, b) => area(b) - area(a))[0] || rec[0];
      return [first, quick].filter(Boolean);
    }

    async function examples() {
      const box = $("#ms-examples");
      $("#ms-exname").textContent = S.strategy + "'s found model";
      const fm = S.scan.found.find((f) => f.strategy === S.strategy && !f.missing);
      if (fm) mview(p, h, { case: S.scan.case, variant: S.scan.variant, strategy: S.strategy, result: fm.source.result });
      else p.querySelector(":scope > details.mview")?.remove();
      if (S.scan.truth.base_stuck) { box.innerHTML = `<p class="muted">With this retry behaviour the true system breaks without a spike; pick another to see runs.</p>`; return; }
      const picks = S.pick ? [S.pick] : defaults();
      p.querySelectorAll("td.cell.on").forEach((x) => x.classList.remove("on"));
      if (S.pick) p.querySelectorAll(`td.cell[data-h="${S.pick.height}"][data-w="${S.pick.width}"]`).forEach((x) => x.classList.add("on"));
      box.innerHTML = `<p class="busy">Running…</p>`;
      const q = (c) => `case=${encodeURIComponent(S.scan.case)}&mechanism=${encodeURIComponent(S.scan.mechanism.key)}&start=${encodeURIComponent(S.scan.start.key)}&strategy=${encodeURIComponent(S.strategy)}&height=${c.height}&width=${c.width}`;
      const my = ++S.exSeq;
      let rs;
      try { rs = await Promise.all(picks.map((c) => get(`${API}/example?${q(c)}`))); } catch (e) { if (my === S.exSeq) box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      if (my !== S.exSeq || !box.isConnected) return;
      box.innerHTML = (S.pick ? "" : `<p class="muted small">${rs.length > 1 ? "The smallest spike that leaves the true system stuck (or its slowest recovery), and the largest one it recovers from within an hour." : ""} Click any cell above to see its run.</p>`) +
        `<div class="ms-ex">${rs.map(exampleHTML).join("")}</div>`;
    }

    function outcome(o) {
      if (o.recovery === null) return o.growing ? `<b style="color:var(--bad)">stuck</b>: the queue is still growing a day later` : `<b style="color:var(--warn)">not back within a day</b>, still draining`;
      return `<b style="color:var(--good)">recovers</b> ${o.recovery ? `${DUR(o.recovery)} after the spike` : "as soon as the spike ends"}`;
    }

    function exampleHTML(r) {
      const t = r.t, T0 = r.start, T1 = r.start + r.width;
      const marks = [{ t: T0, label: "spike", color: "var(--fg)" }, { t: T1, label: "", color: "var(--fg)" }];
      if (r.truth.recovery !== null) marks.push({ t: T1 + r.truth.recovery, label: "true: back", color: "var(--good)" });
      if (r.truth.first_capped) marks.push({ t: r.truth.first_capped, label: "", color: "var(--bad)" });
      const q = r.stocks.queue, rd = r.stocks.ready;
      const clipped = q.truth.some((v) => v >= r.clip) || q.found.some((v) => v >= r.clip);
      const agree = (r.truth.recovery === null) === (r.found.recovery === null);
      return `<div class="panel"><h3>+${r.height} requests a step for ${DUR(r.width)}</h3>
        <p>True model: ${outcome(r.truth)}. ${esc(r.strategy)}: ${outcome(r.found)}${agree ? "" : ` <b style="color:var(--bad)">(wrong)</b>`}.</p>
        <p class="small muted">${r.truth.capped_steps ? `The true dispatch was at its cap for ${r.truth.capped_steps} steps (red line: the first): from there the queue drains only as fast as the pods and the give-ups allow${r.mechanism.k > 0.4 ? ", and the retry loop, now feeding itself, dominates" : ""}.` : "The true dispatch never reached its cap in this run."}
          ${r.found.cap ? "" : ` ${esc(r.strategy)}'s model has no cap, so its dispatch keeps growing with the queue.`}</p>
        <div class="legend"><span><span class="key" style="border-color:var(--accent2)"></span>true, with spike</span><span><span class="key" style="border-color:var(--faint);border-top-style:dashed"></span>true, no spike</span>
          <span><span class="key" style="border-color:var(--accent)"></span>${esc(r.strategy)}, with spike</span><span><span class="key" style="border-color:var(--accent);border-top-style:dotted"></span>${esc(r.strategy)}, no spike</span></div>
        <p class="small"><b>queue</b> (requests)${clipped ? ` <span class="muted">drawn up to ${fmt(r.clip)}</span>` : ""}</p>
        ${chart(t, [{ ys: q.truth_base, color: "var(--faint)", dash: "4 3", label: "true, no spike" }, { ys: q.found_base, color: "var(--accent)", dash: "1 2", label: "found, no spike" },
          { ys: q.truth, color: "var(--accent2)", width: 2, label: "true, with spike" }, { ys: q.found, color: "var(--accent)", label: "found, with spike" }], { h: 130, zero: true, marks, label: "queue" })}
        <p class="small"><b>retries</b> waiting (requests)</p>
        ${chart(t, [{ ys: r.stocks.retries.truth_base, color: "var(--faint)", dash: "4 3" }, { ys: r.stocks.retries.truth, color: "var(--accent2)", width: 2 }, { ys: r.stocks.retries.found, color: "var(--accent)" }], { h: 80, zero: true, marks: marks.slice(0, 2), label: "retries" })}
        <p class="small"><b>ready pods</b>${rd.room ? " (dotted: room on the nodes)" : ""}</p>
        ${chart(t, [{ ys: rd.truth_base, color: "var(--faint)", dash: "4 3" }, { ys: rd.truth, color: "var(--accent2)", width: 2 }, { ys: rd.found, color: "var(--accent)" }].concat(rd.room ? [{ ys: rd.room, color: "var(--muted)", dash: "1 2" }] : []), { h: 80, zero: true, marks: marks.slice(0, 2), label: "ready pods" })}
        <p class="small muted">${esc(r.strategy)}: result #${esc(r.source.result)}, ${esc(r.source.status)}, code ${esc(r.source.commit)}.</p></div>`;
    }
  }

  window.SDDemos.register({ tab: "metastability", title: "6. Metastability scan", ui });
})();
