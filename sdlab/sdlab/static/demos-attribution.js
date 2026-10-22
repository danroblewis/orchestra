// Demo 10, before/after attribution (docs/demos/attribution.md): a simulated SRE project lands at step T; the
// "before" model (the found structure, its numbers refitted on the steps before T) run on the after-period's traffic
// is the counterfactual; measured minus counterfactual is the project's effect, beside the true effect. The numbers
// refitted after T show which one the project moved. API: /api/demos/attribution/{projects,run,seeds}.
(function () {
  "use strict";
  if (!window.SDDemos) return;
  const ival = (h, x, d = 3) => `${h.fmt(x.value, d)} <span class="muted small">[${h.fmt(x.lo, d)}, ${h.fmt(x.hi, d)}]</span>`;
  const signed = (h, x, d = 3) => (x === null || x === undefined || !isFinite(x) ? "–" : `${x > 0 ? "+" : ""}${h.fmt(x, d)}`);

  // the shared model view (demos.js modelView) for the found model shown, at the end of the tab; replaced when the model changes
  function mview(p, h, s) {
    const key = [s.case, s.variant, s.strategy, s.result || ""].join("|"), old = p.querySelector(":scope > details.mview");
    if (old && old.dataset.key === key) return;
    if (old) old.remove();
    if (!h.modelView) return;
    const box = h.modelView(p, { case: s.case, variant: s.variant, strategy: s.strategy, ...(s.result ? { result: s.result } : {}) });
    box.dataset.key = key;
  }

  window.SDDemos.register({
    tab: "attribution",
    title: "10. Before/after attribution",
    async ui(p, h) {
      p.innerHTML = `<p class="busy">Loading…</p>`;
      let o;
      try { o = await h.get("/api/demos/attribution/projects"); } catch (e) { p.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
      p.innerHTML = `<p class="what"><b>The idea:</b> an SRE project ships at step ${o.t}. Did it work, and by how much?
        Keep the found model's structure and refit only its numbers on the steps <i>before</i> the project: that "before" model, run on the traffic that came <i>after</i>, says what would have happened without the project (the counterfactual).
        Measured minus counterfactual is the project's effect. Refitting the numbers on the steps after the project shows which number it moved.
        The simulation knows the true effect (the true model run with and without the project), so the two can be compared.</p>
        <div class="controls"><label>The project <select id="a-project" style="max-width:calc(100vw - 48px)">${Object.entries(o.projects).map(([k, v]) => `<option value="${h.esc(k)}">${h.esc(v)}</option>`).join("")}</select></label>
        <label><input type="checkbox" id="a-counts"> counted noise (flows move whole requests)</label>
        <label>seed <select id="a-seed" disabled>${[1, 2, 3, 4, 5, 6, 7, 8].map((s) => `<option>${s}</option>`).join("")}</select></label>
        <button class="primary" id="a-run">Measure the effect</button></div>
        <div id="a-out"></div><div id="a-seeds"></div>`;
      const q = (s) => p.querySelector(s);
      q("#a-counts").onchange = () => { q("#a-seed").disabled = !q("#a-counts").checked; };
      q("#a-run").onclick = () => go();
      go();

      async function go() {
        const out = q("#a-out"), counts = q("#a-counts").checked, project = q("#a-project").value;
        out.innerHTML = `<p class="busy">Refitting the numbers before and after, and running the counterfactual (a few seconds)…</p>`;
        q("#a-seeds").innerHTML = "";
        let r;
        try { r = await h.get(`/api/demos/attribution/run?project=${encodeURIComponent(project)}&counts=${counts}&seed=${q("#a-seed").value}`); } catch (e) { out.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
        out.innerHTML = view(r);
        mview(p, h, r.source);
        if (counts) seeds(project);
      }

      function view(r) {
        const pj = r.project, src = r.source, oc = r.outcomes;
        const hitRow = r.numbers.find((x) => x.ends === pj.ends);
        const found = hitRow && hitRow.moved, others = r.numbers.filter((x) => x.moved && x.ends !== pj.ends);
        const cls = found && !others.length ? "good" : found ? "warn" : "bad";
        const trueNew = pj.rate.k;
        const head = `<div class="verdict ${cls}">
          <p><b>The project</b> (at step ${pj.t}): ${h.esc(pj.label)}: the true flow <span class="mono">${h.esc(pj.ends)}</span>.</p>
          <p><b>Which number moved:</b> ${found ? `the refit finds <span class="mono">${h.esc(pj.ends)} ${h.esc(hitRow.label)}</span> going ${ival(h, hitRow.before)} → <b>${ival(h, hitRow.after)}</b> (true: ${h.fmt(hitRow.stored)} → ${h.fmt(trueNew)}${hitRow.after.lo <= trueNew && trueNew <= hitRow.after.hi ? ", inside the interval" : ", <b>outside</b> the interval"}).`
            : `<b>missed</b>: the number on <span class="mono">${h.esc(pj.ends)}</span> did not move significantly${hitRow ? ` (${ival(h, hitRow.before)} → ${ival(h, hitRow.after)})` : ""}.`}
            ${others.length ? `Also moved (false): ${others.map((x) => `<span class="mono small">${h.esc(x.ends)} ${h.esc(x.label)}</span>`).join(", ")}.` : "No other number moved."}</p>
          <p class="src">Found model: <b>${h.esc(src.strategy)}</b>'s stored result #${h.esc(src.result)} on <span class="mono">${h.esc(src.case)}</span> ${h.esc(src.variant)} (${h.esc(src.status)}, code ${h.esc(src.commit)}); its structure kept, its ${r.numbers.length} proportional and linear numbers refitted
            on ${r.refit.before_steps} steps before and ${r.refit.after_steps} after (one-step least squares). Intervals: 2.5–97.5% of a block bootstrap (${r.refit.boot} draws, blocks of ${r.refit.block} steps). "Moved": |z| &gt; ${r.z} (z divided by its spread on ${r.placebo_runs} placebo run(s) with no project) and by more than ${Math.round(100 * r.rel)}%.
            ${r.counts ? `Counted noise, seed ${r.seed}.` : "Noise-free data."}</p></div>`;
        const rows = Object.entries(oc).map(([s, x]) => {
          const m = x.summary, what = x.how === "total" ? "total since the project" : "mean change";
          return `<tr><td>${h.esc(x.label)} <span class="muted small">${what}</span></td>
            <td class="num">${signed(h, m.estimate)}</td><td class="num">${signed(h, m.corrected)} <span class="muted small">[${signed(h, m.lo)}, ${signed(h, m.hi)}]</span></td>
            <td class="num">${signed(h, m.truth)}</td><td class="num">${signed(h, m.predicted)}</td><td class="num muted">${signed(h, m.placebo)}</td>
            <td>${m.inside ? `<span style="color:var(--good)">inside</span>` : `<span style="color:var(--bad)">outside</span>`}</td></tr>`;
        }).join("");
        const table = `<div class="panel tablewrap"><table><thead><tr><th>outcome (over the ${r.refit.after_steps} steps after)</th><th class="num">measured − counterfactual</th><th class="num" title="${r.counts ? "the estimate minus the median placebo 'effect' (what the method reports when nothing changed)" : "noise-free: no placebo correction is needed"}">${r.counts ? "less the placebo [band]" : "[band]"}</th><th class="num">true effect</th>
          <th class="num" title="the before model with the moved numbers set to their after values, minus the before model">predicted from the moved number</th>
          <th class="num" title="the same measurement on run(s) of the service with no project: it should be 0">with no project (placebo)</th><th>truth in band?</th></tr></thead><tbody>${rows}</tbody></table>
          <p class="muted small">${r.band === "bootstrap" ? `The band is the spread over ${r.cf_draws} counterfactuals from bootstrap draws of the before refit (noise-free data: the refit's uncertainty is all there is).`
            : `The band is the spread of the same measurement on ${r.placebo_runs} placebo runs (the service with no project, on their own seeds): it holds the service's own randomness and the model's misfit, which the refit's bootstrap alone misses. The table below shows how often it holds across seeds.`}
          The placebo column is what the method reports when nothing changed (it should be 0)${r.counts ? "; its median is taken off the estimate" : ""}.
          "Predicted from the moved number" checks idea 36: did the outcome follow the number that moved?</p></div>`;
        const charts = `<div class="legend"><span><span class="key" style="border-color:var(--accent)"></span>measured − counterfactual (the estimated effect)</span>
            <span><span class="key" style="border-color:var(--accent);border-top-style:dotted"></span>its band</span>
            <span><span class="key" style="border-color:var(--accent2);border-top-style:dashed"></span>the true effect</span></div>
          <div class="grid">${Object.entries(oc).map(([s, x]) => `<div class="panel"><h3>${h.esc(s)} <span class="tag">${h.esc(x.unit || "")}</span></h3>
            ${h.chart(r.t, [{ ys: x.lo, color: "var(--accent)", dash: "1 2", width: 1, label: "band low" }, { ys: x.hi, color: "var(--accent)", dash: "1 2", width: 1, label: "band high" },
              { ys: x.effect, color: "var(--accent)", width: 1.8, label: "estimated effect" }, { ys: x.true_effect, color: "var(--accent2)", dash: "5 3", width: 1.6, label: "true effect" }], { h: 110, zero: true, label: `${s} effect` })}
            <details><summary class="small muted">measured, counterfactual, true counterfactual</summary>
            ${h.chart(r.t, [{ ys: x.actual, color: "var(--faint)", label: "measured (with the project)" }, { ys: x.counterfactual, color: "var(--accent)", dash: "3 2", label: "counterfactual (before model)" },
              { ys: x.true_counterfactual, color: "var(--accent2)", dash: "5 3", label: "true run without the project" }], { h: 100, label: `${s} levels` })}
            <p class="small muted">grey: measured; blue dashed: the before model's counterfactual; orange dashed: the true run without the project.</p></details></div>`).join("")}</div>`;
        const nums = r.numbers.filter((x) => x.identified).sort((a, b) => (b.moved - a.moved) || (Math.abs(b.z || 0) - Math.abs(a.z || 0)));
        const hidden = r.numbers.length - nums.length;
        const numTable = `<details class="panel" style="margin-top:10px"><summary><b>Every refitted number</b>, before and after the project</summary><div class="tablewrap"><table>
          <thead><tr><th>flow</th><th>term</th><th class="num">stored</th><th class="num">before [interval]</th><th class="num">after [interval]</th><th class="num">z</th><th>moved?</th></tr></thead><tbody>
          ${nums.map((x) => `<tr${x.ends === pj.ends ? ` style="font-weight:600"` : ""}><td class="mono small">${h.esc(x.ends)}</td><td class="mono small">${h.esc(x.label)}</td><td class="num">${h.fmt(x.stored, 4)}</td>
            <td class="num">${ival(h, x.before, 4)}</td><td class="num">${ival(h, x.after, 4)}</td><td class="num">${h.fmt(x.z, 3)}</td><td>${x.moved ? `<span style="color:${x.ends === pj.ends ? "var(--good)" : "var(--bad)"}">moved</span>` : ""}</td></tr>`).join("")}
          </tbody></table></div>${hidden ? `<p class="muted small">${hidden} number(s) not shown: their flow moved nothing on enough steps of one window (e.g. a scale-down that never happened), so the data there cannot say what they are.</p>` : ""}
          <p class="muted small">Bold: the flow the project really changed. Expressions, effect tables and constants are kept as found (not refitted).</p></details>`;
        return head + table + charts + numTable;
      }

      async function seeds(project) {
        const el = q("#a-seeds");
        el.innerHTML = `<p class="busy">Loading the same measurement over 8 seeds (cached; the first time takes about a minute)…</p>`;
        let s;
        try { s = await h.get(`/api/demos/attribution/seeds?project=${encodeURIComponent(project)}`); } catch (e) { el.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
        const keys = ["errors_total", "queue", "retries"];
        const inside = (k) => s.rows.filter((r) => r.outcomes[k].inside).length;
        const numIn = s.rows.filter((r) => r.number && r.number.inside).length, numMoved = s.rows.filter((r) => r.number && r.number.moved).length;
        el.innerHTML = `<div class="panel tablewrap" style="margin-top:12px"><h3>Counted noise across seeds: how often does the band hold?</h3>
          <table><thead><tr><th>seed</th>${keys.map((k) => `<th class="num">${h.esc(k)}: less the placebo [band]</th><th class="num">true</th>`).join("")}<th class="num">changed number after [interval]</th><th>numbers found moved</th></tr></thead><tbody>
          ${s.rows.map((r) => `<tr><td>${r.seed}</td>${keys.map((k) => { const m = r.outcomes[k]; return `<td class="num"${m.inside ? "" : ` style="color:var(--bad)"`}>${signed(h, m.corrected)} <span class="muted small">[${signed(h, m.lo)}, ${signed(h, m.hi)}]</span></td><td class="num">${signed(h, m.truth)}</td>`; }).join("")}
            <td class="num"${r.number && r.number.inside ? "" : ` style="color:var(--bad)"`}>${r.number ? `${ival(h, r.number.after)}${r.number.moved ? "" : " <span class='small'>(not moved)</span>"}` : "–"}</td>
            <td class="small mono">${h.esc((r.moved || []).join(", "))}</td></tr>`).join("")}
          </tbody></table>
          <p class="small">The truth inside the band: ${keys.map((k) => `${h.esc(k)} ${inside(k)} of ${s.rows.length}`).join("; ")}. The changed number found moved in ${numMoved} of ${s.rows.length} seeds, its true new value inside the after interval in ${numIn}.
          Red: the truth is outside. Bands come from 12 placebo runs, so they are rough; a counterfactual that is biased (the model's misfit under counted noise) shifts the estimate without widening the band: see docs/demos/attribution.md.</p></div>`;
      }
    },
  });
})();
