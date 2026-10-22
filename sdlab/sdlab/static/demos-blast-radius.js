// Demo 12, blast radius across services (docs/demos/blast-radius.md; ideas 22 and 33): slow one service of a
// multi-service case from step T, in a copy of the true model and in a stored found model, and see where the effect
// spreads and when; then rank the services by how far a slowdown at each one spreads. Read only.
(function () {
  "use strict";
  if (!window.SDDemos) return;
  const API = "/api/demos/blast-radius";

  window.SDDemos.register({ tab: "blast-radius", title: "12. Blast radius", ui });

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
    const { get, esc } = h;
    const S = { setup: null };
    const $ = (s) => p.querySelector(s);
    const big = (x) => (x === null || x === undefined || !isFinite(x) ? "–" : x >= 10 ? `${Math.round(100 * x).toLocaleString()}%` : `${(100 * x).toFixed(x < 0.1 ? 1 : 0)}%`);
    const when = (n, m) => (n === null || n === undefined ? "–" : n === 0 ? "at once" : `+${n} step${n === 1 ? "" : "s"} (${n * m} min)`);

    p.innerHTML = `<style>[data-panel="blast-radius"] select { max-width: 100%; } [data-panel="blast-radius"] .controls label { max-width: 100%; }</style><p class="what"><b>The idea:</b> when one service slows down, which others feel it, how much, and how soon?
      A model of several services together can answer that before an incident, for triage during one, and to find the services whose trouble spreads furthest (dependency risk).
      Here one service is slowed from a chosen step, in the found model and, for comparison, in the true model of the same simulated system. Each model is compared with its own run without the fault;
      a stock has <i>moved</i> once it is more than 5% away from where it would have been.</p>
      <div id="b-intro" class="busy">Loading…</div>
      <div class="controls">
        <label>System <select id="b-case"></select></label>
        <label>Found model <select id="b-model"></select></label>
      </div>
      <div class="controls">
        <label>Slow down <select id="b-svc"></select></label>
        <label>what <select id="b-kind"></select></label>
        <label>to <select id="b-factor"><option value="0.75">75%</option><option value="0.5" selected>50%</option><option value="0.25">25%</option><option value="0">0% (stopped)</option></select></label>
        <label>from step <input id="b-t" type="number" value="1000" min="10" step="10" style="width:6em"></label>
        <button class="primary" id="b-run">Break it</button>
      </div>
      <div id="b-out"></div>
      <h3 style="margin:18px 0 6px">Dependency risk: which service's slowdown spreads furthest?</h3>
      <p class="what">Each service is slowed in turn (the same kind of slowdown, from the same step); its <i>spread</i> is the sum of the other services' largest moves. The found model's ranking beside the true model's.</p>
      <div class="controls"><button id="b-rank">Rank the services</button><span class="muted small">uses the system, model and slowdown chosen above</span></div>
      <div id="b-rank-out"></div>`;

    (async function start() {
      try { S.setup = await get(`${API}/setup`); } catch (e) { $("#b-intro").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      $("#b-case").innerHTML = S.setup.cases.map((c) => `<option value="${esc(c.key)}">${esc(c.title)}</option>`).join("");
      $("#b-kind").innerHTML = Object.entries(S.setup.kinds).map(([k, v]) => `<option value="${k}"${k === "completion" ? " selected" : ""}>${esc(v)}</option>`).join("");
      $("#b-case").onchange = () => { fillCase(); run(); };
      $("#b-model").onchange = () => { intro(); run(); };
      $("#b-run").onclick = run;
      $("#b-rank").onclick = rank;
      fillCase();
      run();
    })();

    const cs = () => S.setup.cases.find((c) => c.key === $("#b-case").value);
    const cell = () => { const [v, s] = $("#b-model").value.split("|"); return cs().models.find((m) => m.variant === v && m.strategy === s); };

    function fillCase() {
      const c = cs();
      $("#b-model").innerHTML = c.models.map((m) => {
        const bad = m.false_links.length + m.missed_links.length;
        return `<option value="${m.variant}|${m.strategy}">${esc(m.strategy)} on ${esc(m.variant)} (#${m.result}${bad ? `, ${bad} link${bad > 1 ? "s" : ""} wrong` : ""})</option>`;
      }).join("");
      $("#b-svc").innerHTML = c.services.map((s) => `<option${s === "catalog" ? " selected" : ""}>${esc(s)}</option>`).join("");
      $("#b-t").max = c.steps - 10;
      intro();
    }

    function intro() {
      const c = cs(), m = cell();
      if (!m) { $("#b-intro").innerHTML = `<p class="bad">No stored passing found model for this system.</p>`; p.querySelector(":scope > details.mview")?.remove(); return; }
      mview(p, h, { case: c.case, variant: m.variant, strategy: m.strategy, result: m.result });
      const wrong = m.false_links.map((e) => `a false link <span class="mono">${esc(e.join(" → "))}</span>`).concat(m.missed_links.map((e) => `a missed link <span class="mono">${esc(e.join(" → "))}</span>`));
      $("#b-intro").className = "";
      $("#b-intro").innerHTML = `<p class="src">System: <span class="mono">${esc(c.case)}</span>, ${c.steps} steps of ${S.setup.step_minutes} minutes; every service has a queue, requests in flight and a counter of responses; a caller's requests in flight make calls into its callees' queues.
        The found model: <b>${esc(m.strategy)}</b>'s stored result #${m.result} on ${esc(m.variant)} (${esc(m.status)}, code ${esc(m.commit)}), discovered from the measured levels alone${m.variant.startsWith("counts") ? " (counted, noisy measurements)" : " (noise-free measurements)"}.
        ${wrong.length ? `Its call graph has ${wrong.join(" and ")}.` : "Its call graph is the true one."}</p>`;
    }

    // ---------- the diagram: services as boxes, calls as arrows, coloured by how far each moved ----------
    function diagram(r, side, id) {
      const L = r.layout, sv = r.services[side], E = r.edges[side], T = r.edges.true, F = r.edges.found;
      const W = 360, bw = 96, bh = 46, ncol = Math.max(...Object.values(L).map((x) => x.col)) + 1, nrow = Math.max(...Object.values(L).map((x) => x.rows));
      const H = 30 + nrow * 74;
      const pos = {};
      for (const [s, x] of Object.entries(L)) {
        const cx = ncol === 1 ? W / 2 : 8 + bw / 2 + (x.col * (W - 16 - bw)) / (ncol - 1);
        const cy = 22 + ((x.row + 0.5) * (H - 30)) / x.rows;
        pos[s] = { x: cx, y: cy };
      }
      const has = (list, a, b) => list.some((e) => e[0] === a && e[1] === b);
      const edges = E.map((e) => ({ a: e[0], b: e[1], cls: side === "found" && !has(T, e[0], e[1]) ? "false" : "ok" }));
      if (side === "found") T.filter((e) => !has(F, e[0], e[1])).forEach((e) => edges.push({ a: e[0], b: e[1], cls: "missed" }));
      const col = { ok: "var(--faint)", false: "var(--bad)", missed: "var(--warn)" };
      const arrows = edges.map((e) => {
        const A = pos[e.a], B = pos[e.b];
        let d;
        if (L[e.b].col > L[e.a].col) d = `M${A.x + bw / 2},${A.y} C${(A.x + B.x) / 2},${A.y} ${(A.x + B.x) / 2},${B.y} ${B.x - bw / 2 - 3},${B.y}`;
        else { const up = Math.min(A.y, B.y) - bh / 2 - 16; d = `M${A.x},${A.y - bh / 2} C${A.x},${up} ${B.x},${up} ${B.x + 6},${B.y - bh / 2 - 3}`; }
        return `<path d="${d}" fill="none" stroke="${col[e.cls]}" stroke-width="${e.cls === "ok" ? 1.5 : 2}" ${e.cls === "ok" ? "" : `stroke-dasharray="${e.cls === "false" ? "5 3" : "2 3"}"`} marker-end="url(#${id}-${e.cls})"><title>${esc(e.a)} → ${esc(e.b)}${e.cls === "false" ? ": a link the true model does not have" : e.cls === "missed" ? ": a true link the found model misses" : ""}</title></path>`;
      }).join("");
      const marks = Object.entries(col).map(([k, c]) => `<marker id="${id}-${k}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" style="fill:${c}"/></marker>`).join("");
      const boxes = Object.keys(L).map((s) => {
        const P = pos[s], x = sv ? sv[s] : null, fault = s === r.fault.service;
        const pk = x ? x.peak : 0, op = !x || !x.reached ? 0 : pk < 0.25 ? 0.22 : pk < 1 ? 0.45 : 0.8;
        const txt = op > 0.6 ? "#fff" : "var(--fg)";
        const line2 = !x ? "not run" : x.reached ? `${big(pk)} · ${x.after === 0 ? "at once" : `+${x.after * r.step_minutes} min`}` : pk > 0.0005 ? `${big(pk)} (under 5%)` : "no change";
        return `<g><title>${esc(s)}${x ? `: largest move ${big(pk)} on ${esc(x.stock)}${x.reached ? `, first past 5% ${when(x.after, r.step_minutes)} after the fault${x.lasting ? ", still off at the end" : ", back by the end"}` : ""}` : ""}</title>
          <rect x="${P.x - bw / 2}" y="${P.y - bh / 2}" width="${bw}" height="${bh}" rx="7" style="fill:var(--surface)" stroke="${fault ? "var(--fg)" : "var(--rule)"}" stroke-width="${fault ? 2.5 : 1}"/>
          <rect x="${P.x - bw / 2}" y="${P.y - bh / 2}" width="${bw}" height="${bh}" rx="7" style="fill:var(--bad)" fill-opacity="${op}"/>
          <text x="${P.x}" y="${P.y - 4}" text-anchor="middle" style="fill:${txt};font-size:12px;font-weight:600">${esc(s)}${fault ? " ⚡" : ""}</text>
          <text x="${P.x}" y="${P.y + 12}" text-anchor="middle" style="fill:${txt};font-size:10px">${esc(line2)}</text></g>`;
      }).join("");
      return `<svg class="zp" viewBox="0 0 ${W} ${H}" role="img" aria-label="${side} model: services coloured by impact"><defs>${marks}</defs>${arrows}${boxes}</svg>`;
    }

    async function run() {
      const m = cell(), out = $("#b-out");
      if (!m) return;
      const svc = $("#b-svc").value, kind = $("#b-kind").value, factor = $("#b-factor").value, T = $("#b-t").value;
      out.innerHTML = `<p class="busy">Slowing ${esc(svc)} in both models…</p>`;
      let r;
      try { r = await get(`${API}/spread?case=${cs().key}&variant=${m.variant}&strategy=${m.strategy}&service=${encodeURIComponent(svc)}&kind=${kind}&factor=${factor}&t=${T}`); } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const f = r.fault, sm = r.step_minutes, st = r.services.true, sf = r.services.found;
      const reach = (sv) => (sv ? Object.entries(sv).filter(([s, x]) => s !== f.service && x.reached).sort((a, b) => a[1].after - b[1].after) : []);
      const words = (sv) => { const x = reach(sv); return x.length ? x.map(([s, v]) => `<b>${esc(s)}</b> ${when(v.after, sm)} (${big(v.peak)})`).join(", ") : "no other service"; };
      const D = r.differences, reachBad = D.some((d) => (d.kind === "false" || d.kind === "missed") && d.about === "service"), anyBad = D.length > 0;
      const cls = !sf ? "bad" : reachBad ? "bad" : anyBad ? "warn" : "good";
      const head = !sf ? `<b>Cannot compare:</b> the found model has no flow <span class="mono">${esc(f.ends.join(" → "))}</span>, so the slowdown cannot be applied to it (a missed flow).`
        : reachBad ? `<b>The found model gets the blast radius wrong.</b>` : anyBad ? `<b>The found model gets who is hit right, with differences:</b>` : `<b>The found model's blast radius matches the truth's</b>: the same services, at the same times, by about as much.`;
      out.innerHTML = `<div class="verdict ${cls}"><p>${head}</p>
          <p>The fault: from step ${f.t}, <b>${esc(f.service)}</b>: ${esc(f.label)} ${Math.round(100 * f.factor)}% (true flow <span class="mono">${esc(f.true_flow || "none")}</span>; ${f.found_flows} found flow${f.found_flows === 1 ? "" : "s"} <span class="mono">${esc(f.ends.join(" → "))}</span> scaled alike).</p>
          <p>True model: it reaches ${words(st)}. Found model: ${sf ? `it reaches ${words(sf)}` : "not run"}.</p>
          ${D.length ? `<ul class="flat">${D.map((d) => `<li><span style="color:var(--${d.kind === "false" || d.kind === "missed" ? "bad" : "warn"});font-weight:600">${d.kind}</span>: ${esc(d.text)}</li>`).join("")}</ul>` : ""}
          ${reach(st).length === 0 && f.service !== "frontend" ? `<p class="muted small">In this system a slowdown spreads only to the services a service calls: callers do not wait on their callees here (no backpressure), so nothing upstream moves in the true model.</p>` : ""}</div>
        <div class="legend"><span>box colour: the service's largest move (none under 5%, light under 25%, mid under 100%, dark above); ⚡ the slowed service; time: when it first moved past 5%</span>
          <span><span class="key" style="border-color:var(--bad);border-top-style:dashed"></span>a false link</span><span><span class="key" style="border-color:var(--warn);border-top-style:dotted"></span>a missed link</span></div>
        <div class="grid"><div class="panel"><h3>Found model <span class="tag">${esc(r.source.strategy)} #${r.source.result}</span></h3>${diagram(r, "found", "bf")}</div>
          <div class="panel"><h3>True model <span class="tag">the simulation</span></h3>${diagram(r, "true", "bt")}</div></div>
        ${stockTable(r)}
        ${charts(r)}`;
    }

    function stockTable(r) {
      const sm = r.step_minutes, T = r.stocks.true, F = r.stocks.found;
      const rows = Object.keys(r.series).map((s) => {
        const t = T && T[s], f = F && F[s];
        const off = t && f && ((t.after === null) !== (f.after === null) || (t.after !== null && Math.abs(t.after - f.after) > 1));
        const sgn = (x) => (x && x.peak > 0.0005 ? (x.sign > 0 ? "+" : "−") : "");
        return `<tr${off ? ` style="color:var(--bad)"` : ""}><td class="mono small">${esc(s)}${r.series[s].counter ? " <span class=\"muted\">(per step)</span>" : ""}</td>
          <td class="num">${f ? sgn(f) + big(f.peak) : "–"}</td><td class="num">${t ? sgn(t) + big(t.peak) : "–"}</td>
          <td class="num">${f ? when(f.after, sm) : "–"}</td><td class="num">${t ? when(t.after, sm) : "–"}</td></tr>`;
      }).join("");
      return `<div class="panel tablewrap" style="margin:10px 0"><table><thead><tr><th>stock</th><th class="num">found: largest move</th><th class="num">true: largest move</th><th class="num">found: past 5%</th><th class="num">true: past 5%</th></tr></thead><tbody>${rows}</tbody></table>
        <p class="muted small" style="margin:4px 0 0">Moves are relative to the stock's typical level after the fault, without it; a counter is read as its increase per step (responses per step). Red rows: the found model is wrong on whether or when the stock moves.</p></div>`;
    }

    function charts(r) {
      const moved = Object.keys(r.series).filter((s) => [r.stocks.true, r.stocks.found].some((x) => x && x[s].peak > 0.01));
      const still = Object.keys(r.series).filter((s) => !moved.includes(s));
      return `<div class="legend"><span><span class="key" style="border-color:var(--faint)"></span>found, no fault</span><span><span class="key" style="border-color:var(--accent)"></span>found, with the fault</span>
          <span><span class="key" style="border-color:var(--faint);border-top-style:dashed"></span>true, no fault</span><span><span class="key" style="border-color:var(--accent2);border-top-style:dashed"></span>true, with the fault</span></div>
        <div class="grid">${moved.map((s) => {
          const x = r.series[s];
          return `<div class="panel"><h3>${esc(s)} <span class="tag">${x.counter ? "responses per step" : "requests"}</span></h3>
            ${h.chart(r.t, [{ ys: x.found_base, color: "var(--faint)", label: "found, no fault" }, { ys: x.found, color: "var(--accent)", label: "found, with the fault" },
              { ys: x.true_base, color: "var(--faint)", dash: "4 3", label: "true, no fault" }, { ys: x.true, color: "var(--accent2)", dash: "4 3", label: "true, with the fault" }],
              { h: 110, marks: [{ t: r.fault.t, label: "fault" }], label: s })}</div>`;
        }).join("")}</div>
        ${still.length ? `<p class="muted small">Moved less than 1% in both models: ${still.map((s) => `<span class="mono">${esc(s)}</span>`).join(", ")}.</p>` : ""}`;
    }

    async function rank() {
      const m = cell(), out = $("#b-rank-out");
      if (!m) return;
      out.innerHTML = `<p class="busy">Slowing each service in turn, in both models…</p>`;
      let r;
      try { r = await get(`${API}/ranking?case=${cs().key}&variant=${m.variant}&strategy=${m.strategy}&kind=${$("#b-kind").value}&factor=${$("#b-factor").value}&t=${$("#b-t").value}`); } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const ok = r.same_order && r.same_reach;
      const cellTxt = (x) => (x ? `${x.spread > 0.0005 ? big(x.spread) : "none"}${x.reached.length ? ` <span class="muted small">(${x.reached.map(esc).join(", ")})</span>` : ""}` : "<span class=\"muted\">cannot apply</span>");
      out.innerHTML = `<div class="verdict ${ok ? "good" : r.same_order ? "warn" : "bad"}"><p>${ok ? "<b>The same ranking and the same reach</b> in both models." : r.same_order ? "<b>The same order, but not the same reach:</b> the found model says some slowdowns hit services that the truth leaves alone, or the other way round (rows in red)." : "<b>A different ranking</b> from the truth's (rows in red)."}</p>
          <p class="muted small">Slowdown: ${esc(r.label)} ${Math.round(100 * r.factor)}% from step ${r.t}; services past 5% in brackets. Services nothing depends on spread nothing, so they tie at the bottom.</p></div>
        <div class="panel tablewrap"><table><thead><tr><th>slowed service</th><th class="num">true rank</th><th>true spread (who is hit)</th><th class="num">found rank</th><th>found spread (who is hit)</th></tr></thead><tbody>
        ${r.rows.map((x) => { const bad = !x.true || !x.found || x.true.rank !== x.found.rank || x.true.reached.join() !== x.found.reached.join();
          return `<tr${bad ? ` style="color:var(--bad)"` : ""}><td class="mono">${esc(x.service)}</td><td class="num">${x.true ? x.true.rank : "–"}</td><td>${cellTxt(x.true)}</td><td class="num">${x.found ? x.found.rank : "–"}</td><td>${cellTxt(x.found)}</td></tr>`; }).join("")}
        </tbody></table></div>`;
    }
  }
})();
