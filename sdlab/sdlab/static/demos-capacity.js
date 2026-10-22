// SD Lab demo 4, capacity projection (docs/demos/capacity.md): traffic scaled up through a stored found model and
// the true model of ladder case 311 (a node pool); where each limit binds, the headroom, and whether the found model
// has each limit at all. Read only: /api/demos/capacity/*.
(function () {
  "use strict";
  if (!window.SDDemos) return;
  const num = (x) => (x === null || x === undefined || !isFinite(x) ? "–" : Math.abs(x) >= 100 ? Math.round(x).toLocaleString() : String(+(+x).toPrecision(3)));
  const LIMITS = { serving: "serving limit (40 requests a step per ready pod)", room: "node room (pods wait for a node)", hpa: "autoscaler maximum (16 pods)" };

  // a small x-y chart with a numeric x axis (the scale): series [{ys, color, dash, label}]
  function xy(h, xs, series, o = {}) {
    const W = 360, H = o.h || 130, m = { l: 44, r: 8, t: 8, b: 26 };
    const all = series.flatMap((s) => s.ys.filter((v) => v !== null && isFinite(v)));
    let lo = Math.min(0, ...all), hi = Math.max(...all, o.min_hi || 0);
    if (hi - lo < 1e-9) hi = lo + 1;
    const X = (x) => m.l + ((x - xs[0]) / (xs[xs.length - 1] - xs[0])) * (W - m.l - m.r);
    const Y = (y) => H - m.b - ((y - lo) / (hi - lo)) * (H - m.t - m.b);
    const lines = series.map((s) => `<polyline fill="none" stroke="${s.color}" stroke-width="${s.width || 1.6}" ${s.dash ? `stroke-dasharray="${s.dash}"` : ""} points="${s.ys.map((v, i) => (v === null ? "" : `${X(xs[i]).toFixed(1)},${Y(v).toFixed(1)}`)).join(" ")}"><title>${h.esc(s.label)}</title></polyline>`).join("");
    const ticks = [0.5, 1, 1.5, 2, 2.5].map((x) => `<line x1="${X(x)}" x2="${X(x)}" y1="${H - m.b}" y2="${H - m.b + 3}" stroke="var(--rule)"/><text x="${X(x)}" y="${H - m.b + 13}" text-anchor="middle">${x}×</text>`).join("");
    const today = `<line x1="${X(1)}" x2="${X(1)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--fg)" stroke-dasharray="2 3" opacity="0.5"/><text x="${X(1) + 3}" y="${m.t + 9}">today</text>`;
    const pick = o.pick ? `<line x1="${X(o.pick)}" x2="${X(o.pick)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--accent2)" opacity="0.6"/>` : "";
    const fmtY = o.pct ? (v) => `${Math.round(100 * v)}%` : (v) => num(v);
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${h.esc(o.label || "chart")}">
      <line x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}" stroke="var(--rule)"/>
      <text x="${m.l - 4}" y="${Y(hi) + 4}" text-anchor="end">${fmtY(hi)}</text><text x="${m.l - 4}" y="${Y(lo) + 3}" text-anchor="end">${fmtY(lo)}</text>
      <text x="${W - m.r}" y="${H - 2}" text-anchor="end">traffic scale</text>${ticks}${today}${pick}${lines}</svg>`;
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

  const room = (x) => (x === null || x === undefined ? "below 0.5×" : `${x}×`);
  function headText(hd, rows, k) {
    if (hd[k] === 2.5 && rows[rows.length - 1].binds[k] < 0.01) return "beyond 2.5×";
    return room(hd[k]);
  }

  function ui(p, h) {
    p.innerHTML = `<p class="what"><b>This demo uses ladder case 311</b> (a node pool: three nodes of 4 pods each; pending pods start only while there is room), not the 310 scenario above.
      <b>The idea:</b> how much more traffic can this service take, and which limit hits first?
      Scale the week's traffic (0.5× to 2.5×) and run it through the found model and through the true model. A limit <i>binds</i> when it, not the demand, decides a flow:
      ready pods serve at most 40 requests a step; a pending pod starts only while a node has room (4 pods a node); the autoscaler asks for at most 16 pods.
      <b>Headroom</b> is the largest scale where a limit binds in under 1% of the week. A projection past the data is only as good as the model's form there, so the demo also checks
      whether the found model <i>has</i> each limit, and whether the data ever reached it.</p>
      <div class="controls"><label>Found model <select id="cap-strat"></select></label>
        <label>Nodes <select id="cap-nodes"><option value="3">3 (today)</option><option value="4">4</option><option value="5">5</option><option value="6">6</option></select></label>
        <label><input type="checkbox" id="cap-fail" checked> the case's node failures (Mon, Wed, Fri)</label>
        <button class="primary" id="cap-run">Project</button></div>
      <div id="cap-out"></div>`;
    const sel = p.querySelector("#cap-strat");
    ["milp", "combined2", "kalman_lna", "structures", "engine_forms"].forEach((s) => sel.insertAdjacentHTML("beforeend", `<option>${s}</option>`));
    p.querySelector("#cap-run").onclick = () => run(p, h);
    run(p, h);
  }

  async function run(p, h) {
    const out = p.querySelector("#cap-out");
    out.innerHTML = `<p class="busy">Running 21 traffic scales through both models (the first time takes about 10 s; then it is cached)…</p>`;
    const q = `strategy=${encodeURIComponent(p.querySelector("#cap-strat").value)}&nodes=${p.querySelector("#cap-nodes").value}&failures=${p.querySelector("#cap-fail").checked}`;
    let r;
    try { r = await h.get(`/api/demos/capacity/projection?${q}`); } catch (e) { out.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
    const src = r.source, i1 = r.scales.indexOf(1), T = r.truth[i1], F = r.found[i1];
    const hdT = r.headroom.truth, hdF = r.headroom.found;
    const agree = (k) => hdT[k] === hdF[k];
    const allAgree = ["serving", "room", "hpa"].every(agree);
    const missing = r.caps.filter((c) => !c.has_min);
    const gap = Math.max(...r.scales.map((_, i) => Math.abs((r.found[i].queue_peak - r.truth[i].queue_peak) / Math.max(1, r.truth[i].queue_peak))));
    const cls = allAgree && gap < 0.1 ? (missing.length ? "warn" : "good") : "bad";
    out.innerHTML = `<div class="verdict ${cls}">
        <p>Today (1.0×, ${r.nodes} nodes): pods are short of node room in <b>${Math.round(100 * T.binds.room)}%</b> of the week's steps (found model: ${Math.round(100 * F.binds.room)}%),
          the serving limit binds in <b>${Math.round(100 * T.binds.serving)}%</b> (found ${Math.round(100 * F.binds.serving)}%); the queue peaks at <b>${num(T.queue_peak)}</b> requests (found ${num(F.queue_peak)}).</p>
        <table><thead><tr><th>headroom (limit binds in under 1% of the week)</th><th class="num">true model</th><th class="num">found model</th></tr></thead><tbody>
          ${Object.entries(LIMITS).map(([k, w]) => `<tr><td>${h.esc(w)}</td><td class="num">${headText(hdT, r.truth, k)}</td><td class="num"${agree(k) ? "" : ` style="color:var(--bad);font-weight:600"`}>${headText(hdF, r.found, k)}</td></tr>`).join("")}
        </tbody></table>
        <p>${allAgree ? "The found model gives the same headroom as the truth for every limit" : "<b>The found model's headroom differs from the truth's</b> (in red)"}; its peak queue is within ${Math.round(100 * gap)}% of the truth's at every scale.</p>
        ${missing.length ? `<p><b>Fits, not proven:</b> the found model has no ${missing.map((c) => h.esc(c.what.split(":")[0])).join(", ")}. ${missing.every((c) => !c.reached) ? "The data never reached it, so discovery could not see it; " : ""}its projection where that limit would bind is unsupported${r.nodes === 3 ? " (with 3 nodes it never binds: try 5 or 6 nodes)" : ""}.</p>` : ""}
      </div>
      <p class="src">Found model: <b>${h.esc(src.strategy)}</b>'s stored result #${h.esc(src.result)} on <span class="mono">${h.esc(src.case)}</span> ${h.esc(src.variant)} (${h.esc(src.status)}, code ${h.esc(src.commit)}). One simulated week (${r.steps} five-minute steps), every stock started where the case starts. Both models get the same traffic and node changes.</p>
      <div class="panel tablewrap" style="margin-bottom:10px"><table><thead><tr><th>limit</th><th>true flow</th><th>found flow (same stocks)</th><th class="num">data reached it</th><th>verdict</th></tr></thead><tbody>
        ${r.caps.map((c) => `<tr><td>${h.esc(c.what)}</td><td class="mono small">${h.esc(c.true_rate)}</td><td class="mono small">${h.esc(c.found_rate || "none")}</td><td class="num">${Math.round(100 * c.reached)}% of steps</td>
          <td style="color:var(--${c.class === "good" ? "good" : c.class === "bad" ? "bad" : "warn"})">${h.esc(c.verdict)}</td></tr>`).join("")}</tbody></table></div>
      <div class="legend"><span><span class="key" style="border-color:var(--accent)"></span>found model</span><span><span class="key" style="border-color:var(--accent2);border-top-style:dashed"></span>true model</span></div>
      <div class="grid">
        ${panelXY(h, r, "Peak queue (requests waiting)", (x) => x.queue_peak)}
        ${panelXY(h, r, "Share of the week pods wait for node room", (x) => x.binds.room, true)}
        ${panelXY(h, r, "Share of the week the serving limit binds", (x) => x.binds.serving, true)}
        ${panelXY(h, r, "Most pods wanted (desired)", (x) => x.desired_peak)}
        ${panelXY(h, r, "Most pods ready", (x) => x.ready_peak)}
        ${panelXY(h, r, "Requests that gave up (share of traffic)", (x) => x.lost_share, true)}
      </div>
      <h3 style="font-size:14px;margin:14px 0 6px">One week at a chosen scale</h3>
      <div class="controls"><label>Traffic <input type="range" id="cap-scale" min="0.5" max="2.5" step="0.1" value="2"> <b id="cap-scale-v">2.0×</b></label></div>
      <div id="cap-week"></div>`;
    const sl = out.querySelector("#cap-scale");
    sl.oninput = () => (out.querySelector("#cap-scale-v").textContent = `${(+sl.value).toFixed(1)}×`);
    sl.onchange = () => weekRun(p, h, q, +sl.value);
    mview(p, h, src);
    weekRun(p, h, q, 2.0);
  }

  function panelXY(h, r, title, f, pct) {
    return `<div class="panel"><h3>${h.esc(title)}</h3>${xy(h, r.scales, [
      { ys: r.found.map(f), color: "var(--accent)", label: "found model" },
      { ys: r.truth.map(f), color: "var(--accent2)", dash: "4 3", label: "true model" }], { pct, label: title, min_hi: pct ? 0.05 : 0 })}</div>`;
  }

  async function weekRun(p, h, q, scale) {
    const out = p.querySelector("#cap-week");
    out.innerHTML = `<p class="busy">Simulating the week at ${scale.toFixed(1)}×…</p>`;
    let r;
    try { r = await h.get(`/api/demos/capacity/week?${q}&scale=${scale}`); } catch (e) { out.innerHTML = `<p class="bad">${h.esc(e.message)}</p>`; return; }
    const marks = r.failures.map((t) => ({ t, label: "", color: "var(--bad)" }));
    out.innerHTML = `<p class="muted small">Five-minute steps; one day is 288 steps (step 1 is Monday 00:05; Saturday and Sunday are quieter). Red lines: node failures.</p>
      <div class="grid">${Object.entries(r.stocks).map(([s, x]) => `<div class="panel"><h3>${h.esc(s)} <span class="tag">${h.esc(x.unit || "")}</span></h3>
      ${h.chart(r.t, [{ ys: x.found, color: "var(--accent)", label: "found model" }, { ys: x.truth, color: "var(--accent2)", dash: "4 3", label: "true model" }], { h: 110, zero: true, marks, label: s })}</div>`).join("")}</div>`;
  }

  window.SDDemos.register({ tab: "capacity", title: "4. Capacity projection", ui });
})();
