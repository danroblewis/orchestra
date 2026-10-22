// Demo 11, canary guard (docs/demos/canary.md): a baseline and a canary copy of the service, the canary with one
// rate a little worse; the found model's numbers refitted on each, compared with intervals: stop or go. A table over
// sizes and seeds counts the decisions against the truth. API: /api/demos/canary/{options,run,table}.
(function () {
  "use strict";
  if (!window.SDDemos) return;
  const ival = (h, x, d = 4) => `${h.fmt(x.value, d)} <span class="muted small">±${h.fmt(1.96 * x.se, 2)}</span>`;
  const pc = (x) => `${Math.round(100 * x)}%`;

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
    tab: "canary",
    title: "11. Canary guard",
    async ui(p, h) {
      p.innerHTML = `<p class="busy">Loading…</p>`;
      let o;
      try { o = await h.get("/api/demos/canary/options"); } catch (e) { p.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
      p.innerHTML = `<p class="what"><b>The idea:</b> during a rollout, a canary (the new version) runs beside the baseline (the old one). Is it worse?
        Keep the found model's structure and refit its numbers on each copy's data; if a number differs between them by more than the noise allows, stop the rollout.
        Here the canary is a copy of the true model with one rate made a little worse (or not at all, to count false stops), and each copy runs on its own seed.</p>
        <div class="controls"><label>The canary is <select id="c-reg" style="max-width:calc(100vw - 48px)">${Object.entries(o.regressions).map(([k, v]) => `<option value="${h.esc(k)}">${h.esc(v)}</option>`).join("")}</select></label>
        <label>by <select id="c-size">${o.sizes.map((s) => `<option value="${s}"${s === 0.15 ? " selected" : ""}>${pc(s)}</option>`).join("")}</select></label>
        <label>seed <select id="c-seed">${o.seeds.map((s) => `<option>${s}</option>`).join("")}</select></label>
        <label>steps <select id="c-steps">${o.steps.map((s) => `<option${s === 1000 ? " selected" : ""}>${s}</option>`).join("")}</select></label>
        <label><input type="checkbox" id="c-counts" checked> counted noise (flows move whole requests)</label>
        <button class="primary" id="c-run">Compare the copies</button></div>
        <div id="c-out"></div><div id="c-table"></div>`;
      const q = (s) => p.querySelector(s);
      let lastTable = "";
      q("#c-run").onclick = () => go();
      go();

      async function go() {
        const out = q("#c-out"), reg = q("#c-reg").value, steps = q("#c-steps").value, counts = q("#c-counts").checked;
        out.innerHTML = `<p class="busy">Running both copies and refitting each (a second or two)…</p>`;
        let r;
        try { r = await h.get(`/api/demos/canary/run?regression=${encodeURIComponent(reg)}&size=${q("#c-size").value}&seed=${q("#c-seed").value}&steps=${steps}&counts=${counts}`); } catch (e) { out.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
        out.innerHTML = view(r);
        mview(p, h, r.source);
        const key = `${reg}|${steps}|${counts}`;
        if (key !== lastTable) { lastTable = key; table(reg, steps, counts); }
      }

      function view(r) {
        const rg = r.regression, src = r.source;
        const cls = r.verdict.startsWith("right") ? "good" : "bad";
        const worse = r.size > 0;
        const flaggedText = r.flagged.length ? r.flagged.map((f) => `<span class="mono small">${h.esc(f)}</span>`).join(", ") : "none";
        const head = `<div class="verdict ${cls}"><p style="font-size:16px"><b>${r.stop ? "STOP" : "GO"}</b>: ${r.stop ? `a number differs: ${flaggedText}` : "no number differs by more than the noise allows"}.</p>
          <p>The truth: the canary's <span class="mono">${h.esc(rg.ends)}</span> is ${worse ? `<b>${pc(r.size)} worse</b> (${h.esc(rg.label)})` : "<b>the same</b> as the baseline's"}, so this is a <b>${h.esc(r.verdict)}</b>${r.stop && worse ? (r.right_number ? ", and the flagged number is the one that changed" : ", but the flagged number is not the one that changed") : ""}.</p>
          <p class="src">Found model: <b>${h.esc(src.strategy)}</b>'s stored result #${h.esc(src.result)} on <span class="mono">${h.esc(src.case)}</span> ${h.esc(src.variant)} (${h.esc(src.status)}, code ${h.esc(src.commit)}); its structure kept, its proportional and linear numbers refitted on each copy's ${r.steps} steps
            (seeds ${r.seeds.baseline} and ${r.seeds.canary}${r.counts ? ", counted noise" : ", noise-free"}). A number is flagged when the two differ by more than ${r.z} standard errors and by more than ${Math.round(100 * r.rel)}%; a standard error is the block bootstrap's, widened by the number's spread over ${r.calibration.pairs} A/A pairs (identical copies on their own seeds), since the bootstrap within one run misses how the refit varies from run to run.
            ${r.stop_raw !== r.stop ? `Without that widening the decision would be <b>${r.stop_raw ? "stop" : "go"}</b>.` : ""}</p></div>`;
        const rows = r.rows.filter((x) => x.identified).sort((a, b) => (b.flag - a.flag) || (b.is_changed_flow - a.is_changed_flow) || Math.abs(b.z || 0) - Math.abs(a.z || 0));
        const numTable = `<div class="panel tablewrap"><table><thead><tr><th>flow</th><th>term</th><th class="num">baseline ±95%</th><th class="num">canary ±95%</th><th class="num">difference</th><th class="num" title="difference / its standard error, divided by the number's spread on A/A pairs">z</th><th class="num" title="difference / its bootstrap standard error, before the A/A calibration">z (bootstrap only)</th><th></th></tr></thead><tbody>
          ${rows.map((x) => `<tr${x.is_changed_flow ? ` style="font-weight:600"` : ""}><td class="mono small">${h.esc(x.ends)}</td><td class="mono small">${h.esc(x.label)}</td>
            <td class="num">${ival(h, x.baseline)}</td><td class="num">${ival(h, x.canary)}</td><td class="num">${h.pct(x.relative)}</td><td class="num">${h.fmt(x.z, 3)}</td><td class="num muted">${h.fmt(x.z_raw, 3)}</td>
            <td>${x.flag ? `<span style="color:${x.is_changed_flow ? "var(--good)" : "var(--bad)"}">flagged</span>` : ""}</td></tr>`).join("")}
          </tbody></table><p class="muted small">Bold: the flow made worse in the canary (when it is). Numbers whose flow moved nothing in a copy's run are left out (the data cannot say what they are).</p></div>`;
        const charts = `<div class="legend" style="margin-top:10px"><span><span class="key" style="border-color:var(--faint)"></span>baseline</span><span><span class="key" style="border-color:var(--accent2)"></span>canary</span>
            <span>what the two copies measured: a few percent is hard to see by eye</span></div>
          <div class="grid">${Object.entries(r.stocks).map(([s, x]) => `<div class="panel"><h3>${h.esc(s)} <span class="tag">${h.esc(x.unit || "")}</span></h3>
            ${h.chart(r.t, [{ ys: x.baseline, color: "var(--faint)", label: "baseline" }, { ys: x.canary, color: "var(--accent2)", label: "canary" }], { h: 100, label: s })}</div>`).join("")}</div>`;
        return head + numTable + charts;
      }

      async function table(reg, steps, counts) {
        const el = q("#c-table");
        el.innerHTML = `<p class="busy">Loading the decisions over every size and seed (cached; the first time takes about a minute)…</p>`;
        let t;
        try { t = await h.get(`/api/demos/canary/table?regression=${encodeURIComponent(reg)}&steps=${steps}&counts=${counts}`); } catch (e) { el.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
        const z = t.summary["0.0"] || t.summary["0"];
        const rows = t.sizes.map((s) => {
          const m = t.summary[String(s === 0 ? "0.0" : s)] || t.summary[String(s)];
          const cells = t.cells.filter((c) => c.size === s);
          return `<tr><td>${pc(s)}</td><td>${s ? "worse" : "the same"}</td>
            <td class="num">${s ? `<span style="color:var(--good)">${m.stops}</span> of ${m.runs}` : "–"}</td>
            <td class="num">${s ? `<span${m.runs - m.stops ? ` style="color:var(--bad)"` : ""}>${m.runs - m.stops}</span>` : "–"}</td>
            <td class="num">${s ? "–" : `<span${m.stops ? ` style="color:var(--bad)"` : ""}>${m.stops}</span> of ${m.runs}`}</td>
            <td class="num muted">${m.stops_raw} of ${m.runs}</td>
            <td class="num">${s ? `${m.right_number} of ${m.stops}` : "–"}</td>
            <td class="mono small">${cells.map((c) => `<span title="seed ${c.seed}: ${h.esc(c.verdict)}${c.flagged.length ? ": " + h.esc(c.flagged.join(", ")) : ""}" style="color:${c.verdict.startsWith("right") ? "var(--good)" : "var(--bad)"}">${c.stop ? "■" : "□"}</span>`).join("")}</td></tr>`;
        }).join("");
        el.innerHTML = `<div class="panel tablewrap" style="margin-top:12px"><h3>Decisions vs the truth: ${h.esc(reg)}, ${t.steps} steps, ${t.counts ? `counted noise, ${t.seeds.length} seeds` : "noise-free (every seed is the same run)"}</h3>
          <table><thead><tr><th>canary worse by</th><th>truth</th><th class="num">right stops</th><th class="num">missed</th><th class="num">false stops</th><th class="num" title="stops with the bootstrap's standard errors alone, without the A/A widening">stops, bootstrap only</th><th class="num">flagged the right number</th><th>each seed (■ stop, □ go; green right, red wrong)</th></tr></thead><tbody>${rows}</tbody></table>
          <p class="muted small">False stops at 0%: ${z ? `${z.stops} of ${z.runs}` : "–"} (the threshold aims at about 5%; with the bootstrap alone ${z ? `${z.stops_raw} of ${z.runs}` : "–"}). Hover a square for what was flagged.</p></div>`;
      }
    },
  });
})();
