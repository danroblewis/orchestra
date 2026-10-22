// Demo 2, daily model diff (docs/demos/daily-diff.md): day 1's found model against day 2's, both found by the same
// strategy, as a git-style diff and a diagram, beside the true change. API: /api/demos/daily-diff/{changes,diff}.
(function () {
  "use strict";
  const KIND = {
    changed: { sign: "~", color: "var(--warn)", word: "a number changed" },
    added: { sign: "+", color: "var(--good)", word: "added" },
    removed: { sign: "−", color: "var(--bad)", word: "removed" },
    redrawn: { sign: "=", color: "var(--eq)", word: "written differently, same amounts" },
    same: { sign: " ", color: "var(--faint)", word: "same" },
  };
  const VERDICT = { right: ["✓ right", "var(--good)"], false: ["✗ false", "var(--bad)"], missed: ["✗ missed", "var(--bad)"] };

  // where each scenario's stocks sit in the diagram (column, row); any other stock goes in the spare cells below
  const PLACES = {
    "memory-oom": { retries: [0, 0], queue: [1, 0], inflight: [2, 0], responses_total: [3, 0], cpu: [2, 1], errors_total: [3, 1],
      desired: [0, 2], pending: [1, 2], ready: [2, 2], oom_kills_total: [3, 2], leak: [1, 3], mem: [2, 3] },
    "two-services": { frontend_queue: [0, 0], frontend_inflight: [1, 0], frontend_responses_total: [2, 0],
      catalog_queue: [0, 1], catalog_inflight: [1, 1], catalog_responses_total: [2, 1] },
  };

  function diagram(r, esc) {
    const BW = 150, BH = 34, CW = 190, RH = 96, X0 = 30, Y0 = 34, PLACE = PLACES[r.scenario] || {};
    const stocks = [...r.measured, ...r.hidden_stocks.map((h) => (r.hidden_truth[h] || h))];
    const named = (s) => (s && r.hidden_truth[s]) || s;          // a found hidden stock drawn in the truth's place
    const pos = {}, used = new Set();
    stocks.forEach((s) => { const p = PLACE[s]; if (p && !used.has(p.join())) { pos[s] = p; used.add(p.join()); } });
    let spare = 0;
    stocks.forEach((s) => { if (pos[s]) return; while (used.has([spare % 4, 4 + Math.floor(spare / 4)].join())) spare++; pos[s] = [spare % 4, 4 + Math.floor(spare / 4)]; used.add(pos[s].join()); });
    const rows = Math.max(...Object.values(pos).map((p) => p[1])) + 1, cols = Math.max(...Object.values(pos).map((p) => p[0])) + 1;
    const W = X0 * 2 + CW * (cols - 1) + BW, H = Y0 + RH * (rows - 1) + BH + 40;
    const box = (s) => ({ x: X0 + pos[s][0] * CW, y: Y0 + pos[s][1] * RH });
    const mid = (s) => { const b = box(s); return { x: b.x + BW / 2, y: b.y + BH / 2 }; };
    const edgeOf = (p, q) => {                                     // from the centre of p toward q, cut at p's box
      const dx = q.x - p.x, dy = q.y - p.y, k = Math.min(dx ? (BW / 2 + 3) / Math.abs(dx) : 1e9, dy ? (BH / 2 + 3) / Math.abs(dy) : 1e9);
      return { x: p.x + dx * k, y: p.y + dy * k };
    };
    let defs = "", lines = "", labels = "";
    Object.entries(KIND).forEach(([k, v]) => { defs += `<marker id="dd-arrow-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${v.color}"/></marker>`; });
    const outN = {};
    r.edges.forEach((e) => {
      const fr = named(e.from), to = named(e.to), K = KIND[e.kind], strong = e.kind !== "same";
      const w = strong ? 2.4 : 1.2, op = strong ? 1 : 0.55;
      const tip = esc(`${e.ends}: ${K.word}${e.verdict ? ` (${e.verdict})` : ""}\nday 1: ${e.a.join(" + ") || "none"}\nday 2: ${e.b.join(" + ") || "none"}`);
      let d, lx, ly;
      if (fr && to && pos[fr] && pos[to]) {
        const p = mid(fr), q = mid(to), dx = q.x - p.x, dy = q.y - p.y, L = Math.hypot(dx, dy) || 1;
        const bend = Math.abs(dy) < 1 && Math.abs(dx) > CW + 1 ? 46 : 16;      // a long straight run clears the boxes between
        const c = { x: (p.x + q.x) / 2 - (dy / L) * bend, y: (p.y + q.y) / 2 + (dx / L) * bend };
        const a = edgeOf(p, c), b = edgeOf(q, c);
        d = `M${a.x.toFixed(1)},${a.y.toFixed(1)} Q${c.x.toFixed(1)},${c.y.toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)}`;
        lx = (a.x + 2 * c.x + b.x) / 4; ly = (a.y + 2 * c.y + b.y) / 4;
      } else {
        const s = fr || to;
        if (!pos[s]) return;
        const bx = box(s), n = (outN[s + (fr ? "o" : "i")] = (outN[s + (fr ? "o" : "i")] || 0) + 1) - 1;
        const x = fr ? bx.x + BW - 14 - n * 12 : bx.x + 14 + n * 12;
        const [y1, y2] = fr ? [bx.y + BH + 2, bx.y + BH + 22] : [bx.y - 22, bx.y - 2];
        d = `M${x},${y1} L${x},${y2}`;
        lines += `<circle cx="${x}" cy="${fr ? y2 + 3 : y1 - 3}" r="3" fill="none" stroke="${K.color}" opacity="${op}"/>`;
        lx = x + 4; ly = (y1 + y2) / 2 + 3;
      }
      const vd = e.verdict && VERDICT[e.verdict];
      if (e.verdict === "missed") lines += `<path d="${d}" fill="none" stroke="var(--bad)" stroke-width="7" opacity="0.25"/>`;
      lines += `<path d="${d}" fill="none" stroke="${K.color}" stroke-width="${w}" opacity="${op}" marker-end="url(#dd-arrow-${e.kind})"><title>${tip}</title></path>`;
      if (strong || vd) labels += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" style="fill:${vd ? vd[1] : K.color};font-weight:600;font-size:11px">${esc(K.sign.trim() || "")}${vd ? " " + vd[0].split(" ")[0] : ""}</text>`;
    });
    const drawn = new Set(r.edges.map((e) => `${named(e.from)}|${named(e.to)}`));
    r.verdict.missed.filter((x) => !drawn.has(`${x.from}|${x.to}`) && x.from && x.to && pos[x.from] && pos[x.to]).forEach((x) => {
      const p = mid(x.from), q = mid(x.to), dx = q.x - p.x, dy = q.y - p.y, L = Math.hypot(dx, dy) || 1;
      const c = { x: (p.x + q.x) / 2 - (dy / L) * 16, y: (p.y + q.y) / 2 + (dx / L) * 16 }, a = edgeOf(p, c), b = edgeOf(q, c);
      const d = `M${a.x.toFixed(1)},${a.y.toFixed(1)} Q${c.x.toFixed(1)},${c.y.toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)}`;
      lines += `<path d="${d}" fill="none" stroke="var(--bad)" stroke-width="7" opacity="0.25"/><path d="${d}" fill="none" stroke="var(--bad)" stroke-width="1.4" stroke-dasharray="4 3" marker-end="url(#dd-arrow-removed)"><title>${esc(`${x.ends}: the true change, missed (in neither found model)`)}</title></path>`;
      labels += `<text x="${((a.x + 2 * c.x + b.x) / 4).toFixed(1)}" y="${((a.y + 2 * c.y + b.y) / 4).toFixed(1)}" style="fill:var(--bad);font-weight:600;font-size:11px">✗ missed</text>`;
    });
    const boxes = stocks.map((s) => {
      const b = box(s), hid = !r.measured.includes(s);
      return `<rect x="${b.x}" y="${b.y}" width="${BW}" height="${BH}" rx="5" fill="var(--surface)" stroke="var(--muted)" ${hid ? 'stroke-dasharray="4 3"' : ""}/>
        <text x="${b.x + BW / 2}" y="${b.y + BH / 2 + 4}" text-anchor="middle" style="fill:var(--fg);font-size:12px">${esc(s)}${hid ? " (hidden)" : ""}</text>`;
    }).join("");
    return `<svg class="zp" viewBox="0 0 ${W} ${H}" role="img" aria-label="the diff of day 1's and day 2's found models"><defs>${defs}</defs>${lines}${boxes}${labels}</svg>`;
  }

  function ui(el, h) {
    const { get, esc, fmt, pct } = h;
    el.innerHTML = `<p class="what"><b>The idea:</b> rediscover the model every day and diff today's against yesterday's, like a code review of the system.
      Both models come from the same strategy, so its habits cancel out; what is left is what changed. Here day 2 is a simulated day with other traffic and, on top, a real change made to a copy of the true model.
      The diff is worked out from the two <i>found</i> models only; then it is held beside the true change: each edit is <b>right</b> (the true change found), <b>false</b> (an edit where nothing really changed), or the true change is <b>missed</b>.</p>
      <div class="controls"><label style="max-width:100%">Service <select id="dd-scen" style="max-width:100%"></select></label><label style="max-width:100%">Day 2's change <select id="dd-change" style="max-width:100%"></select></label><button class="primary" id="dd-run">Diff the two days</button></div>
      <div id="dd-out"><p class="busy">Loading…</p></div>`;
    const out = el.querySelector("#dd-out"), sel = el.querySelector("#dd-change"), scenSel = el.querySelector("#dd-scen");
    let C = null;
    const fill = () => {
      const sc = C.scenarios.find((x) => x.key === scenSel.value);
      sel.innerHTML = sc.changes.filter((x) => x.key !== "quiet").concat(sc.changes.filter((x) => x.key === "quiet"))
        .map((x) => `<option value="${esc(x.key)}"${x.ready ? "" : " disabled"}>${esc(x.label)}${x.ready ? "" : " (not discovered yet)"}</option>`).join("");
      return sc;
    };
    get("/api/demos/daily-diff/changes").then((c) => {
      C = c;
      scenSel.innerHTML = c.scenarios.map((x) => `<option value="${esc(x.key)}">${esc(x.title)}</option>`).join("");
      scenSel.onchange = () => { fill(); run(); };
      const sc = fill();
      el.querySelector("#dd-run").onclick = run;
      if (!sc.changes.some((x) => x.ready)) { out.innerHTML = `<div class="verdict warn"><p>Day 2 has not been discovered yet${sc.source.error ? ` (${esc(sc.source.error)})` : ""}. Run, in the sdlab checkout:</p><p class="mono small">${esc(c.command)} ${esc(sc.key)}</p></div>`; return; }
      run();
    }).catch((e) => { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; });

    const pc = (x) => (x < 1e-5 ? "under 0.001%" : x >= 10 ? `${Math.round(100 * x).toLocaleString()}%` : `${+(100 * x).toPrecision(2)}%`);
    const flowText = (xs) => (xs.length ? xs.map((x) => `<span class="mono">${esc(x)}</span>`).join(" + ") : `<span class="muted">none</span>`);
    async function run() {
      out.innerHTML = `<p class="busy">Diffing day 1's model against day 2's…</p>`;
      let r;
      try { r = await get(`/api/demos/daily-diff/diff?scenario=${encodeURIComponent(scenSel.value)}&change=${encodeURIComponent(sel.value)}`); } catch (e) { out.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
      const v = r.verdict, s = r.source, quiet = r.change.key === "quiet";
      const nEdits = v.right.length + v.false.length;
      const cls = quiet ? (nEdits ? "bad" : "good") : (v.missed.length || v.false.length ? (v.right.length ? "warn" : "bad") : "good");
      const head = quiet
        ? (nEdits ? `<b>${nEdits} false edit${nEdits === 1 ? "" : "s"}</b> on a day where nothing changed.` : `<b>No edits:</b> nothing changed, and the diff says so (only the traffic was different).`)
        : `<b>${v.right.length} right</b>, <b>${v.false.length} false</b>, <b>${v.missed.length} missed</b> (${r.truth.length} true change${r.truth.length === 1 ? "" : "s"}).`;
      const tol = r.tolerance;
      const again = r.day1_again, failed = r.day2.status !== "pass" && r.day2.status !== "equivalent";
      const warn = failed || r.quiet_status !== "pass"
        ? `<p><b>Read this diff with care:</b> ${failed ? `day 2's discovery <b>failed</b> against day 2's own true model (${esc(r.day2.status)}), so some edits are the strategy's mistakes, not changes in the service.` : ""}
           ${r.quiet_status !== "pass" ? ` The quiet day's discovery failed too (${esc(r.quiet_status)}), so the tolerance it sets is loose (${tol.quiet_edits} edit${tol.quiet_edits === 1 ? "" : "s"} on a day where nothing changed).` : ""}
           A diff is only as good as both days' discovery.</p>` : "";
      out.innerHTML = `<div class="verdict ${cls}"><p>${head}</p>${warn}
          <p>What really changed on day 2: <b>${esc(r.change.label)}</b>${r.truth.length ? ": " + r.truth.map((t) => `<span class="mono">${esc(t.ends)}</span> ${t.before ? `${esc(t.before)} → ${esc(t.after)}` : `new, ${esc(t.after)}`}`).join("; ") : ""}. Also ${esc(r.day2_about)}.</p>
          <p class="small">An edge counts as changed when its amounts on the two days' states differ, relative to its size, by more than ${fmt(tol.times)}× what they differ on the quiet day (same service, other traffic, no change), and never less than ${pct(tol.floor).replace("+", "")}.
            On the quiet day the largest such difference is ${pc(tol.quiet_worst)}${tol.quiet_worst < 1e-4 ? " (the data are noise-free and the strategy finds the same numbers, so the 2% floor sets the tolerance)" : ""}.</p>
          <p class="src">Day 1: <b>${esc(s.strategy)}</b>'s stored result #${esc(s.result)} on <span class="mono">${esc(s.case)}</span> ${esc(s.variant)} (${esc(s.status)}, code ${esc(s.commit)}).
            Day 2: the same strategy run once on day 2's data (code ${esc((r.day2.commit || "").slice(0, 9))}${r.day2.dirty ? " with local changes" : ""}, ${fmt(r.day2.seconds)} s; against day 2's true model it scores <b>${esc(r.day2.status)}</b>).
            ${again ? `Day 1 re-run at that code: ${again.same_as_stored ? `largest edge difference from the stored model ${fmt(100 * again.same_as_stored.worst, 2)}%` : "no model"} (${esc(again.status)}).` : ""}</p></div>
        <div class="legend">${Object.entries(KIND).map(([k, x]) => `<span><span class="key" style="border-color:${x.color}"></span>${x.sign.trim() ? esc(x.sign) + " " : ""}${esc(x.word)}</span>`).join("")}
          <span>✓ right, ✗ false / missed (against the true change)</span></div>
        <div class="panel" style="max-width:900px;margin:0 0 10px">${diagram(r, esc)}<p class="small muted">Arrows are edges (all flows between two ends); short stubs are flows to or from outside (in from above, out below). Hover an arrow for both days' equations. A wide pale red line marks a true change the diff missed.</p></div>
        <div class="panel tablewrap"><table><thead><tr><th></th><th>edge</th><th>day 1</th><th>day 2</th><th class="num">difference</th><th>against the truth</th></tr></thead><tbody>
        ${r.edges.filter((e) => e.kind !== "same" || e.verdict).map((e) => row(e)).join("")}
        </tbody></table>
        <details><summary class="small muted">${r.edges.filter((e) => e.kind === "same" && !e.verdict).length} edges the same on both days</summary><table><tbody>
        ${r.edges.filter((e) => e.kind === "same" && !e.verdict).map((e) => row(e)).join("")}</tbody></table></details></div>
        ${Object.keys(r.hidden).length ? `<p class="small muted">Day 2's hidden stock ${Object.entries(r.hidden).map(([b, a]) => `<span class="mono">${esc(b)}</span>`).join(", ")} is matched to day 1's by what it touches (no truth needed); both are drawn in the place of the truth's <span class="mono">${esc(Object.values(r.hidden_truth)[0] || "")}</span>, which the scorer matched day 1's to.</p>` : ""}
        <div class="dd-mv"><h3 style="margin:0 0 4px">Each day's model on its own day's data</h3>
        <p class="small muted">Day 1's stored model on day 1's data, then day 2's model on day 2's data (true amounts: each day's own simulation, with day 2's change).</p></div>`;
      const mv = { source: "daily-diff", scenario: r.scenario, change: r.change.key };
      const host = out.querySelector(".dd-mv");
      h.modelView(host, { ...mv, day: "2" });
      h.modelView(host, { ...mv, day: "1" });                       // each view goes first in its host: day 1 above day 2
      host.querySelectorAll(":scope > h3, :scope > p").forEach((x) => host.insertBefore(x, host.firstChild));
      host.insertBefore(host.querySelector(":scope > p"), host.querySelector("details.mview"));
      if (h.toTop) h.toTop(host, "dd-mv");
    }
    function row(e) {
      const K = KIND[e.kind], vd = e.verdict && VERDICT[e.verdict];
      const nums = (e.numbers || []).filter((n) => Math.abs(n.b - n.a) > 1e-3 * Math.max(Math.abs(n.a), 1e-9));
      const diff = e.rel === null || e.rel === undefined ? (e.kind === "added" ? `new, ${fmt(e.size_b)} a step` : e.kind === "removed" ? `was ${fmt(e.size_a)} a step` : "")
        : `${pc(e.rel)} <span class="muted small">(tolerance ${pc(e.tol)})</span>`;
      return `<tr><td class="mono" style="color:${K.color};font-weight:700">${esc(K.sign)}</td><td class="mono small">${esc(e.ends)}</td>
        <td class="small">${flowText(e.a)}</td><td class="small">${flowText(e.b)}${nums.length && e.kind === "changed" ? `<div class="muted small">${nums.map((n) => `${esc(n.label)}: ${fmt(n.a, 4)} → ${fmt(n.b, 4)}`).join("; ")}</div>` : ""}${e.note ? `<div class="muted small">${esc(e.note)}</div>` : ""}</td>
        <td class="num small">${diff}</td><td class="small" style="color:${vd ? vd[1] : "var(--muted)"}">${vd ? vd[0] : ""}${e.near ? `<div class="muted small">shares a stock with the missed change at ${e.near.map(esc).join(", ")}</div>` : ""}</td></tr>`;
    }
  }

  window.SDDemos.register({ tab: "daily-diff", title: "2. Daily model diff", ui });
})();
