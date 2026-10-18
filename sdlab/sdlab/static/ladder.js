// SD Lab ladder page (/ladder): read only. Four views over the ladder's read API (/api/ladder):
//   Now      what the ladder is running (polled every second), and one result: the true model's
//            diagram beside the found one, laid out the same, flows coloured by verdict; the
//            equations side by side and the scores. Follows the run until the user picks something.
//   Matrix   strategies x cases, four squares per cell (one per variant); totals, per-tag summary
//   History  a case and strategy's results over time; each strategy's totals per version
//   Cases    every case: what it tests, its true model and equations, and its data
(function () {
  "use strict";
  const D = window.SDDiagram, L = window.SDLadder, fmt = L.fmt;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v) => (v === null || v === undefined || !Number.isFinite(+v) ? "–" : `${(100 * v).toFixed(1)}%`);
  const ci = (c) => (Array.isArray(c) && c.length === 2 && c.every((x) => x !== null) ? ` <span class="muted">[${(100 * c[0]).toFixed(1)}, ${(100 * c[1]).toFixed(1)}]</span>` : "");
  const when = (iso) => { if (!iso) return "–"; const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
  const short = (h) => (h ? String(h).slice(0, 7) : "–");
  const BOX = { w: 96, h: 46 };
  const LAYOUT = { box: BOX, colw: BOX.w + 150, rowh: BOX.h + 100 };
  const STATUS_LETTER = { pass: "P", equivalent: "E", fail: "F", error: "X", timeout: "T" };
  const STATUS_WORD = { pass: "pass", equivalent: "equivalent", fail: "fail", error: "error", timeout: "timeout" };
  const CLS_COLOR = { ok: "var(--good)", wrong: "var(--warn)", missing: "var(--bad)", spurious: "var(--bad)", equiv: "var(--eq)", small: "var(--muted)", unscored: "var(--muted)", plain: "var(--fg)" };
  const CLS_WORD = { ok: "found, right", wrong: "found, a number off", missing: "missing", spurious: "spurious", equiv: "equivalent", small: "too small to count", unscored: "not scored" };
  const SERIES = 8;                                      // categorical slots --c1..--c8 (style.css)

  const S = {
    view: "now", cases: [], byId: {}, strategies: [], summary: null, progress: null,
    sel: { case: null, variant: null, strategy: null, id: null }, follow: true, shown: null,
    hsel: { case: null, strategy: null }, csel: { case: null, variant: null, fresh: false }, cache: {},
  };

  function setStatus(t, err) { $("status").textContent = t; $("status").classList.toggle("error", !!err); }
  async function get(url) {
    const r = await fetch(url);
    if (!r.ok) throw Object.assign(new Error(`${url}: ${r.status}`), { status: r.status });
    return r.json();
  }
  async function cached(url) { return S.cache[url] || (S.cache[url] = await get(url)); }
  const enc = encodeURIComponent;

  // ---------- URL ----------
  function remember() {
    const u = new URL(location.href), p = u.searchParams;
    [...p.keys()].forEach((k) => p.delete(k));
    p.set("view", S.view);
    if (S.view === "now" && !S.follow) {
      ["case", "variant", "strategy"].forEach((k) => S.sel[k] && p.set(k, S.sel[k]));
      if (S.sel.id) p.set("result", S.sel.id);
    }
    if (S.view === "history") ["case", "strategy"].forEach((k) => S.hsel[k] && p.set(k, S.hsel[k]));
    if (S.view === "cases" && S.csel.case) p.set("case", S.csel.case);
    history.replaceState(null, "", u);
  }

  // ---------- tooltips: any element with data-tip ----------
  const tip = $("tip");
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest && e.target.closest("[data-tip]");
    if (!t) { tip.hidden = true; return; }
    tip.innerHTML = t.getAttribute("data-tip");
    tip.hidden = false;
  });
  document.addEventListener("mousemove", (e) => {
    if (tip.hidden) return;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = `${Math.max(4, Math.min(innerWidth - w - 8, e.clientX + 14))}px`;
    tip.style.top = `${e.clientY + h + 24 > innerHeight ? e.clientY - h - 10 : e.clientY + 16}px`;
  });

  // ---------- views ----------
  function setView(v) {
    S.view = v;
    document.querySelectorAll(".ltabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === v)));
    document.querySelectorAll(".lview").forEach((s) => { s.hidden = s.dataset.view !== v; });
    remember();
    if (v === "now") showCompare();
    if (v === "matrix") loadSummary().then(renderMatrix);
    if (v === "history") renderHistory();
    if (v === "cases") renderCases();
  }
  document.querySelectorAll(".ltabs [role=tab]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  async function loadSummary() {
    try { S.summary = await get("/api/ladder/summary"); } catch (e) { setStatus(String(e.message), true); }
    return S.summary;
  }
  const cellOf = (c, v, s) => S.summary && S.summary.cells.find((x) => x.case === c && x.variant === v && x.strategy === s);
  function squares(caseId, strategy, opts = {}) {
    const c = S.byId[caseId];
    return `<span class="sq4">${c.variants.map((v) => {
      const cell = cellOf(caseId, v.name, strategy) || {}, st = cell.status, stale = st && cell.stale;
      const tipTxt = `<b>${esc(caseId)}</b> · ${esc(v.name)} · ${esc(strategy)}<br>${st ? esc(STATUS_WORD[st]) : "not run"}${stale ? ` (stale: ${esc(cell.stale)})` : ""}${st && cell.recall !== null && cell.recall !== undefined ? `<br>recall ${pct(cell.recall)}, ${cell.right}/${cell.of} parts right${cell.spurious ? `, ${cell.spurious} spurious` : ""}<br>skill@20 ${pct(cell.skill20)}, fresh ${pct(cell.fresh20)}` : ""}${cell.error ? `<br>${esc(String(cell.error).slice(0, 200))}` : ""}`;
      const on = opts.current === v.name ? " on" : "";
      return `<button class="sq st-${st || "none"}${stale ? " stale" : ""}${on}" data-case="${esc(caseId)}" data-variant="${esc(v.name)}" data-strategy="${esc(strategy)}" data-tip="${esc(tipTxt)}" aria-label="${esc(`${caseId} ${v.name} ${strategy}: ${st || "not run"}${stale ? ", stale" : ""}`)}">${st ? STATUS_LETTER[st] : "·"}</button>`;
    }).join("")}</span>`;
  }

  // ---------- Now: live strip ----------
  function liveFocus(p) {
    const items = (p && p.items) || [];
    const done = items.filter((i) => i.state === "done" && i.finished).sort((a, b) => (a.finished < b.finished ? 1 : -1));
    const running = items.filter((i) => i.state === "running");
    return done[0] || running[0] || null;
  }
  function renderLive() {
    const p = S.progress, box = $("live");
    if (!p || !p.run) { box.innerHTML = `<p class="note">No ladder run yet. Start one with <code>uv run sdlab-ladder sync</code>; it shows here as it goes.</p>`; return; }
    const r = p.run, active = !r.finished, items = p.items || [];
    const counts = p.counts || {};
    const running = items.filter((i) => i.state === "running");
    const bar = ["pass", "equivalent", "fail", "error", "timeout"].map((k) => counts[k] ? `<span class="seg st-${k}" style="flex:${counts[k]}" data-tip="${counts[k]} ${k}"></span>` : "").join("")
      + (running.length ? `<span class="seg running" style="flex:${running.length}" data-tip="${running.length} running"></span>` : "")
      + (p.queued ? `<span class="seg queued" style="flex:${p.queued}" data-tip="${p.queued} queued"></span>` : "");
    const tally = Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(", ") || "nothing finished yet";
    box.innerHTML = `<div class="livehead">
        <span class="livedot${active ? " on" : ""}" aria-hidden="true"></span>
        <b>${active ? "Running" : "Last run"}</b> <code>${esc(r.command || "sdlab-ladder")}</code>
        <span class="muted small">${r.done}/${r.total} done${active ? `, ${r.running} running` : ""} · ${esc(tally)} · ${active ? `started ${esc(when(r.started))}` : `finished ${esc(when(r.finished))}`}</span>
        <label class="follow" title="Show each result as the run finishes it"><input type="checkbox" id="follow" ${S.follow ? "checked" : ""}> follow the run</label>
      </div>
      <div class="pbar" role="progressbar" aria-valuemin="0" aria-valuemax="${r.total}" aria-valuenow="${r.done}">${bar}</div>
      ${running.length ? `<div class="chips running-now"><span class="muted small">running now:</span>${running.slice(0, 6).map((i) => `<button class="chip" data-case="${esc(i.case)}" data-variant="${esc(i.variant)}" data-strategy="${esc(i.strategy)}">${esc(i.case)} · ${esc(i.variant)} · ${esc(i.strategy)}</button>`).join("")}${running.length > 6 ? `<span class="muted small">+${running.length - 6}</span>` : ""}</div>` : ""}`;
    $("follow").addEventListener("change", (e) => { S.follow = e.target.checked; if (S.follow) followTick(true); remember(); });
    box.querySelectorAll(".chip[data-case]").forEach((b) => b.addEventListener("click", () => pick({ case: b.dataset.case, variant: b.dataset.variant, strategy: b.dataset.strategy })));
  }
  function followTick(force) {
    if (!S.follow) return;
    const f = liveFocus(S.progress);
    if (!f) { if (force || !S.sel.case) defaultSel(); return; }
    const key = `${f.case}|${f.variant}|${f.strategy}|${f.state}|${f.finished}`;
    if (!force && key === S.focusKey) return;
    S.focusKey = key;
    S.sel = { case: f.case, variant: f.variant, strategy: f.strategy, id: null };
    S.focusRunning = f.state !== "done";
    if (S.view === "now") showCompare();
  }
  function defaultSel() {
    const c = S.sel.case || (S.cases[0] || {}).id;
    S.sel = { case: c, variant: S.sel.variant || ((S.byId[c] || {}).variants || [{}])[0].name, strategy: S.sel.strategy || defaultStrategy(), id: null };
    if (S.view === "now") showCompare();
  }
  const defaultStrategy = () => ((S.strategies.find((s) => s.name === "matrix") || S.strategies.find((s) => s.available) || S.strategies[0]) || {}).name;

  // the user picks: stop following
  function pick(sel) {
    S.follow = false; S.focusRunning = false;
    S.sel = { ...S.sel, id: null, ...sel };
    if (S.view !== "now") setView("now"); else { remember(); showCompare(); }
    const f = $("follow"); if (f) f.checked = false;
  }

  // ---------- Now: picker ----------
  function renderPick() {
    const c = S.byId[S.sel.case]; if (!c) return;
    const i = S.cases.indexOf(c);
    $("pick").innerHTML = `
      <span class="stepper"><button class="btn" id="prev" ${i <= 0 ? "disabled" : ""} title="The case before (←)" aria-label="Previous case">&#9664;</button>
      <select id="p-case" aria-label="Case">${S.cases.map((x) => `<option value="${esc(x.id)}" ${x.id === c.id ? "selected" : ""}>${esc(x.id)}</option>`).join("")}</select>
      <button class="btn" id="next" ${i >= S.cases.length - 1 ? "disabled" : ""} title="The case after (→)" aria-label="Next case">&#9654;</button></span>
      <span class="seg-btns" role="group" aria-label="Variant">${c.variants.map((v) => `<button class="btn${v.name === S.sel.variant ? " on" : ""}" data-v="${esc(v.name)}" title="${esc(`${v.noise === "none" ? "no noise" : "whole things (Poisson)"}, ${v.steps} steps`)}">${esc(v.name)}</button>`).join("")}</span>
      <label>Strategy <select id="p-strat" aria-label="Strategy">${S.strategies.map((s) => `<option value="${esc(s.name)}" ${s.name === S.sel.strategy ? "selected" : ""} ${s.available ? "" : "disabled"}>${esc(s.name)}${s.available ? "" : " (unavailable)"}</option>`).join("")}</select></label>
      ${S.sel.id ? `<span class="badge">result #${esc(S.sel.id)} from history</span> <button class="btn" id="latest">latest</button>` : ""}
      <span class="sqwrap muted small">${squares(c.id, S.sel.strategy, { current: S.sel.id ? null : S.sel.variant })}</span>`;
    const step = (d) => { const n = S.cases[i + d]; if (n) pick({ case: n.id }); };
    $("prev").onclick = () => step(-1);
    $("next").onclick = () => step(1);
    $("p-case").onchange = (e) => pick({ case: e.target.value });
    $("p-strat").onchange = (e) => pick({ strategy: e.target.value });
    $("pick").querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => pick({ variant: b.dataset.v })));
    $("pick").querySelectorAll(".sq").forEach((b) => (b.onclick = () => pick({ variant: b.dataset.variant })));
    if ($("latest")) $("latest").onclick = () => pick({});
  }
  document.addEventListener("keydown", (e) => {
    if (S.view !== "now" || e.target.closest("input, select, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
    const i = S.cases.findIndex((c) => c.id === S.sel.case);
    if (e.key === "ArrowLeft" && i > 0) pick({ case: S.cases[i - 1].id });
    if (e.key === "ArrowRight" && i >= 0 && i < S.cases.length - 1) pick({ case: S.cases[i + 1].id });
  });

  // ---------- Now: the comparison ----------
  let token = 0;
  async function showCompare() {
    const sel = { ...S.sel }, my = ++token;
    if (!sel.case || !S.byId[sel.case]) return;
    if (!S.byId[sel.case].variants.some((v) => v.name === sel.variant)) S.sel.variant = sel.variant = S.byId[sel.case].variants[0].name;
    if (!sel.strategy) S.sel.strategy = sel.strategy = defaultStrategy();
    renderPick();
    remember();
    let r = null, err = null;
    try {
      r = sel.id ? await get(`/api/ladder/result/${enc(sel.id)}`) : await get(`/api/ladder/results/${enc(sel.case)}/${enc(sel.variant)}/${enc(sel.strategy)}`);
    } catch (e) { if (e.status !== 404) err = e; }
    if (my !== token) return;
    if (r && sel.id && (r.case !== sel.case || r.variant !== sel.variant || r.strategy !== sel.strategy)) {
      S.sel = { case: r.case, variant: r.variant, strategy: r.strategy, id: sel.id };
      renderPick();
    }
    S.shown = r;
    renderCompare(S.byId[S.sel.case], r, err);
  }

  function scoreTable(r) {
    const s = (r && r.scores) || {}, b = s.behaviour || {};
    const sk = (where, h) => (b[where] || {})[String(h)] || {};
    const st = r ? r.status : null;
    return `<div class="scores">
      <span class="stbadge st-${st || "none"}">${st ? esc(STATUS_WORD[st]) : "not run"}</span>
      ${s.recall !== undefined ? `<span data-tip="Share of true parts whose key the found model has (right kind and ends, whatever the number)">recall <b>${pct(s.recall)}</b></span>
      <span data-tip="Share of found parts (at least as large as the spurious threshold) that are true">precision <b>${pct(s.precision)}</b></span>
      <span data-tip="True parts found with the right number in every window">right <b>${s.right}/${s.of}</b></span>
      <span>spurious <b>${(s.spurious || []).length}</b></span>
      <span data-tip="Skill of the found model's forecasts 20 steps ahead from about 150 moments of the run discovery saw, with its 95% bootstrap interval">skill@20 <b>${pct(sk("in_sample", 20).skill)}</b>${ci(sk("in_sample", 20).ci)}</span>
      <span data-tip="The same, 100 steps ahead">skill@100 <b>${pct(sk("in_sample", 100).skill)}</b>${ci(sk("in_sample", 100).ci)}</span>
      <span data-tip="Skill on a fresh run (the next seed), which discovery did not see">fresh@20 <b>${pct(sk("fresh", 20).skill)}</b>${ci(sk("fresh", 20).ci)}</span>
      <span>fresh@100 <b>${pct(sk("fresh", 100).skill)}</b>${ci(sk("fresh", 100).ci)}</span>` : ""}
      ${r ? `<span class="muted small">${r.seconds !== null && r.seconds !== undefined ? `${fmt(r.seconds)} s · ` : ""}${esc(when(r.at))} · strategy ${esc(short(r.strategy_hash))} · scorer ${esc(short(r.score_hash))}</span>` : ""}
    </div>`;
  }

  // the two diagrams' models, from the comparison
  function diagrams(c, cmp, found) {
    const truth = c.model, measured = new Set(cmp.measured);
    const readsOf = (f, extra) => [...L.readers(f)].filter((x) => x !== "const" && x !== f.from).map((stock) => ({ stock })).concat(extra || []);
    const tD = {
      stocks: truth.stocks.map((s) => ({ id: s.id, name: s.id, dashed: !measured.has(s.id), sub: measured.has(s.id) ? "" : "not measured", title: `${s.id}: starts at ${fmt(s.initial)}${measured.has(s.id) ? "" : ", not measured"}` })),
      flows: cmp.truth.map((t) => ({
        from: t.flow.from, to: t.flow.to, cls: t.cls, dashed: t.cls === "missing", label: t.flow.id,
        label2: `${short2(L.rateText(t.flow.rate))}${t.badge ? ` · ${t.badge}` : ""}`,
        title: `${t.flow.id}: ${t.equation}\n${CLS_WORD[t.cls] || t.cls}${t.notes.length ? "\n" + t.notes.join("\n") : ""}`,
        reads: readsOf(t.flow, t.reads.map((x) => ({ stock: x.stock, label: x.kind === "uses" ? `uses ${fmt(x.per)}` : "effect", dash: x.kind === "uses" ? "1 3" : "5 4", cls: x.cls || "plain" }))),
      })),
    };
    // a stock only the found model names (an inferred one) may have a long id: short names in the drawing
    const alias = {};
    cmp.extraStocks.forEach((id, i) => { alias[id] = id.length <= 6 ? id : `h${i + 1}`; });
    const al = (t) => cmp.extraStocks.reduce((acc, id) => acc.split(id).join(alias[id]), t);
    const fStocks = truth.stocks.filter((s) => measured.has(s.id)).map((s) => ({ id: s.id, name: s.id }))
      .concat(cmp.extraStocks.map((id) => ({ id, name: alias[id], dashed: true, sub: "inferred", title: `${alias[id]}: ${id}, a stock the found model infers (not measured)` })));
    const fFlows = [], vias = {};
    cmp.found.forEach((x, k) => {
      const f = x.flow;
      const common = { cls: x.cls, thin: x.cls === "small", label: short2(al(f.inflow && f.inflow.length > 1 ? L.equation(f).split(" on average")[0] : f.byTime && f.byTime.length > 1 ? `${L.rateText(f.rate)} (by time)` : L.rateText(f.rate))),
        label2: x.badge || (x.cls === "spurious" ? "not in the truth" : x.cls === "equiv" ? "equivalent" : ""),
        title: `${L.equation(f)}\n${CLS_WORD[x.cls] || x.cls}${x.notes.length ? "\n" + x.notes.join("\n") : ""}${f.note ? "\n" + f.note : ""}` };
      if (f.via) {
        const id = `via:${k}`;
        vias[id] = { from: f.from, to: f.to };
        fStocks.push({ id, name: "hidden", dashed: true, sub: `delay ${fmt(+f.via.delay)}`, cls: x.cls });
        fFlows.push({ ...common, from: f.from || f.via.echo, to: id, reads: [] }, { ...common, label: "", label2: "", from: id, to: f.to, reads: [] });
      } else {
        fFlows.push({ ...common, from: f.from, to: f.to,
          reads: readsOf(f, [...(f.effects || []).map((e) => ({ stock: e.stock, label: "effect", dash: "5 4" })), ...(f.uses || []).map((u) => ({ stock: u.stock, label: `uses ${fmt(+u.per)}`, dash: "1 3" }))]) });
      }
    });
    return { tD, fD: { stocks: fStocks, flows: fFlows }, vias, alias };
  }
  const short2 = (s) => (s.length > 30 ? s.slice(0, 29) + "…" : s);

  function maxCols() { return innerWidth >= 1150 ? 3 : innerWidth >= 600 ? 2 : 1; }
  // one layout for both sides, made from the truth alone (so a case always looks the same); a stock
  // only the found model names (an inferred hidden stock, or a flow's hidden stock) sits where the
  // true hidden stock between the same two stocks sits, or below the stocks it connects
  function sharedLayout(c, found, vias) {
    const pos = D.layout(c.model.stocks.map((s) => s.id), c.model.flows, { ...LAYOUT, maxCols: maxCols() });
    const truthIds = new Set(c.model.stocks.map((s) => s.id)), taken = new Set();
    const between = (a, b) => c.model.stocks.find((s) => s.measured === false && !taken.has(s.id) && c.model.flows.some((f) => f.to === s.id && f.from === a) && c.model.flows.some((f) => f.from === s.id && f.to === b));
    let k = 0;
    const place = (id, a, b) => {
      const h = between(a, b);
      if (h && pos[h.id]) { taken.add(h.id); pos[id] = { ...pos[h.id] }; return; }
      const pa = pos[a] || pos[b], pb = pos[b] || pa;
      if (!pa) { pos[id] = { x: k * LAYOUT.colw, y: -LAYOUT.rowh }; k++; return; }
      pos[id] = { x: Math.round((pa.x + pb.x) / 2 + (k % 2 ? 40 : 0)), y: Math.max(pa.y, pb.y) + LAYOUT.rowh * (1 + Math.floor(k / 2)) }; k++;
    };
    const extras = [...new Set(found.filter((f) => !f.via).flatMap((f) => [f.from, f.to]).filter((x) => x && !truthIds.has(x)))];
    extras.forEach((id) => {
      const a = (found.find((f) => f.to === id && f.from && truthIds.has(f.from)) || {}).from;
      const b = (found.find((f) => f.from === id && f.to && truthIds.has(f.to)) || {}).to;
      place(id, a, b);
    });
    Object.entries(vias || {}).forEach(([id, v]) => place(id, v.from, v.to));
    return pos;
  }

  function renderCompare(c, r, err) {
    const found = (r && r.found) || [];
    const cmp = L.compare(c.model, found, r && r.scores);
    $("cmp-head").innerHTML = `<div class="casehead">
        <h2 class="ctitle2">${esc(c.id)} <span>${esc(c.title)}</span></h2>
        <span class="muted small">level ${esc(c.level)} · ${c.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join(" ")}</span>
        <p class="tests">Tests: ${esc(c.tests)}</p>
      </div>
      ${S.focusRunning && S.follow ? `<p class="note discrunning">Running now: ${r ? "showing its previous result until it finishes." : "no earlier result."}</p>` : ""}
      ${err ? `<p class="note error">${esc(err.message)}</p>` : ""}
      ${scoreTable(r)}`;
    $("found-cap").textContent = r ? `Found by ${r.strategy}` : `Found by ${S.sel.strategy}: not run yet`;
    const { tD, fD, vias, alias } = diagrams(c, cmp, found);
    const pos = sharedLayout(c, found, vias);
    const b1 = D.bounds(pos, tD.flows, BOX), b2 = D.bounds(pos, r ? fD.flows : [], BOX);
    const x0 = Math.min(b1.x, b2.x), y0 = Math.min(b1.y, b2.y);
    const vb = { x: x0, y: y0, w: Math.max(b1.x + b1.w, b2.x + b2.w) - x0, h: Math.max(b1.y + b1.h, b2.y + b2.h) - y0 };
    const color = (cls) => CLS_COLOR[cls] || "var(--fg)";
    D.draw($("d-true"), tD, pos, { box: BOX, viewBox: vb, color, maxScale: 1.3 });
    D.draw($("d-found"), r ? fD : { stocks: fD.stocks, flows: [] }, pos, { box: BOX, viewBox: vb, color, maxScale: 1.3 });
    $("dpair").classList.toggle("stack", vb.w / vb.h < 1.05 || innerWidth < 900);
    const used = new Set([...cmp.truth.map((t) => t.cls), ...cmp.found.map((x) => x.cls)]);
    $("dlegend").innerHTML = ["ok", "wrong", "missing", "spurious", "equiv", "small", "unscored"].filter((k) => used.has(k)).map((k) =>
      `<span><span class="lsw ${k === "missing" ? "dash" : ""}" style="background:${CLS_COLOR[k]}"></span>${esc(CLS_WORD[k])}</span>`).join("")
      + `<span><span class="lsw link"></span>reads a stock</span>`
      + Object.entries(alias).filter(([id, n]) => id !== n).map(([id, n]) => `<span class="mono">${esc(n)} = ${esc(id)}</span>`).join("")
      + (cmp.equivalent ? `<span class="eqnote">Equivalent: the found flows make the same linear system as the truth, so the data cannot tell them apart. Not a pass.</span>` : "");
    $("cmp-body").innerHTML = equationsHtml(c, cmp, r);
  }

  function equationsHtml(c, cmp, r) {
    const s = (r && r.scores) || {};
    const rows = cmp.rows.map((row) => `<tr class="cls-${row.cls}">
      <td class="mono">${esc(row.ends)}</td>
      <td>${row.truth.map((t) => `<div><b>${esc(t.flow.id)}</b> <span class="mono">${esc(t.equation)}</span></div>`).join("") || `<span class="muted">–</span>`}</td>
      <td>${row.found.map((x) => `<div class="mono">${esc(x.equation)}</div>`).join("") || `<span class="muted">–</span>`}</td>
      <td><span class="vdot" style="background:${CLS_COLOR[row.cls]}"></span>${esc(CLS_WORD[row.cls] || row.cls)}${[...row.truth, ...row.found].flatMap((x) => x.notes).filter((v, i, a) => a.indexOf(v) === i).map((n) => `<div class="small muted">${esc(n)}</div>`).join("")}</td></tr>`).join("");
    const parts = (s.parts || []).map((p) => `<tr class="cls-${p.ok ? "ok" : p.found ? "wrong" : "missing"}">
      <td class="mono">${esc(p.key)}</td><td>${esc(p.kind)}</td><td class="num">${esc(fmt(p.true))}</td><td class="num">${esc(fmt(p.found_value))}</td>
      <td class="num">${p.error === null || p.error === undefined ? "–" : pct(p.error)}</td><td class="num">${p.se && typeof p.se === "object" ? esc(fmt(p.se.mean)) : esc(fmt(p.se))}</td>
      <td>${p.ok ? "right" : p.found ? "off" : "not found"}${p.compared ? ` <span class="muted small">(${esc(p.compared)})</span>` : ""}</td></tr>`).join("");
    const spur = (s.spurious || []).map((p) => `<tr class="cls-spurious"><td class="mono">${esc(p.key)}</td><td>${esc(p.kind)}</td><td class="num">–</td><td class="num">${esc(fmt(p.value))}</td><td class="num" colspan="2">size ${esc(fmt(p.size))}</td><td>spurious</td></tr>`).join("");
    const tol = s.tolerance ? Object.entries(s.tolerance).map(([k, v]) => `${k} ${fmt(v)}`).join(", ") : "";
    const inj = (c.model.injections || []).length ? `<p class="note">Announced injections: ${c.model.injections.slice(0, 6).map((j) => `${esc(j.stock)} +${esc(fmt(j.amount))} at ${esc(j.t)}`).join(", ")}${c.model.injections.length > 6 ? "…" : ""}</p>` : "";
    return `<h3>Equations, true and found</h3>
      <div class="tablewrap"><table class="rtable eqtable"><thead><tr><th>ends</th><th>true</th><th>found</th><th>verdict</th></tr></thead><tbody>${rows || `<tr><td colspan="4" class="muted">nothing</td></tr>`}</tbody></table></div>
      ${inj}
      ${r ? `<details class="parts"${(s.parts || []).length <= 8 ? " open" : ""}><summary>Every part: the numbers compared${s.windows > 1 ? ` (${s.windows} windows; values per window)` : ""}${tol ? ` <span class="muted small">tolerance ${esc(tol)}</span>` : ""}</summary>
        <div class="tablewrap"><table class="rtable"><thead><tr><th>part</th><th>kind</th><th class="num">true</th><th class="num">found</th><th class="num">error</th><th class="num">oracle SE</th><th>verdict</th></tr></thead><tbody>${parts}${spur}</tbody></table></div>
        ${(s.notes || []).length ? `<p class="note">${s.notes.map(esc).join("<br>")}</p>` : ""}
        ${r.error ? `<pre class="err">${esc(r.error)}</pre>` : ""}
      </details>` : `<p class="note">${esc(S.sel.strategy || "This strategy")} has not run on ${esc(c.id)} ${esc(S.sel.variant)} yet: <code>uv run sdlab-ladder run --strategies ${esc(S.sel.strategy || "")} --cases ${esc(c.id.slice(0, 3))} --variants ${esc(S.sel.variant)}</code></p>`}`;
  }

  // ---------- Matrix ----------
  function renderMatrix() {
    const sm = S.summary; if (!sm) return;
    const strats = matrixStrategies(sm);
    renderMatrixControls(sm, strats);
    $("matrix-note").innerHTML = `Each cell has one square per variant, in the order ${S.cases[0] ? S.cases[0].variants.map((v) => `<code>${esc(v.name)}</code>`).join(", ") : ""}. Click a square (or a cell) to open it in <a href="#" data-goto="now">Now</a>. Hover a case for what it tests.`;
    $("mlegend").innerHTML = [["pass", "P pass"], ["equivalent", "E equivalent"], ["fail", "F fail"], ["error", "X error"], ["timeout", "T timeout"], ["none", "· not run"]].map(([k, w]) => `<span><span class="sq st-${k} demo">${w[0]}</span>${esc(w.slice(2))}</span>`).join("")
      + `<span><span class="sq st-pass stale demo">P</span>stale (a sync would run it again)</span>`;
    let lvl = null, body = "";
    S.cases.forEach((c) => {
      if (c.level !== lvl) { lvl = c.level; body += `<tr class="lvl"><th colspan="${strats.length + 1}">Level ${esc(lvl)}</th></tr>`; }
      body += `<tr><th class="cname" data-tip="${esc(`<b>${esc(c.title)}</b><br>${esc(c.tests)}<br><span>${c.tags.map(esc).join(", ")}</span>`)}"><a href="#" data-case="${esc(c.id)}">${esc(c.id)}</a><span class="muted small ctl">${esc(c.title)}</span></th>`
        + strats.map((s) => `<td class="mcell" data-case="${esc(c.id)}" data-strategy="${esc(s.name)}">${squares(c.id, s.name)}</td>`).join("") + `</tr>`;
    });
    const tot = strats.map((s) => {
      const t = sm.totals[s.name] || {};
      return `<td class="num"><b>${(t.pass || 0) + (t.equivalent || 0)}</b>/${t.total || 0}<div class="small muted">${t.pass || 0} P · ${t.equivalent || 0} E · ${t.fail || 0} F${t.error ? ` · ${t.error} X` : ""}${t.timeout ? ` · ${t.timeout} T` : ""}${t.missing ? ` · ${t.missing} not run` : ""}${t.stale ? ` · ${t.stale} stale` : ""}</div>${stackBar(t)}</td>`;
    }).join("");
    $("matrix").innerHTML = `<thead><tr><th>case</th>${strats.map((s) => `<th title="${esc(s.available ? `${s.name}: hash ${s.hash}` : `${s.name}: ${s.reason || "unavailable"}`)}"><span class="vh">${esc(s.name)}${s.available ? "" : " (unavailable)"}</span></th>`).join("")}</tr></thead>
      <tbody>${body}</tbody><tfoot><tr><th>pass + equivalent</th>${tot}</tr></tfoot>`;
    const tags = Object.keys(sm.by_tag).sort();
    $("tags").innerHTML = `<thead><tr><th>tag</th><th class="num">cases</th>${strats.map((s) => `<th>${esc(s.name)}</th>`).join("")}</tr></thead><tbody>${tags.map((tag) =>
      `<tr><th><a href="#" data-tag="${esc(tag)}">${esc(tag)}</a></th><td class="num">${S.cases.filter((c) => c.tags.includes(tag)).length}</td>${strats.map((s) => {
        const g = sm.by_tag[tag][s.name] || {};
        return `<td class="num" data-tip="${esc(`${tag} · ${s.name}: ${g.pass || 0} pass, ${g.equivalent || 0} equivalent, ${g.fail || 0} fail${g.error ? `, ${g.error} error` : ""}${g.timeout ? `, ${g.timeout} timeout` : ""}${g.missing ? `, ${g.missing} not run` : ""}`)}">${(g.pass || 0) + (g.equivalent || 0)}/${g.total || 0}${stackBar(g)}</td>`;
      }).join("")}</tr>`).join("")}</tbody>`;
    $("view-matrix").querySelectorAll(".sq[data-case]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); pick({ case: b.dataset.case, variant: b.dataset.variant, strategy: b.dataset.strategy }); }));
    $("view-matrix").querySelectorAll(".mcell").forEach((td) => (td.onclick = () => pick({ case: td.dataset.case, strategy: td.dataset.strategy })));
    $("view-matrix").querySelectorAll("a[data-case]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); S.csel.case = a.dataset.case; setView("cases"); }));
    $("view-matrix").querySelectorAll("a[data-tag]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); S.ctag = a.dataset.tag; setView("cases"); }));
    $("view-matrix").querySelectorAll("a[data-goto]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); setView(a.dataset.goto); }));
  }
  // which strategies are columns: a filter (names or parts of names, comma separated; "all" or empty
  // for every one), ordered by name or by how many pass or are equivalent; kept in the browser
  try { S.mfilter = localStorage.getItem("sdlab.ladder.mfilter") || ""; S.morder = localStorage.getItem("sdlab.ladder.morder") || "best"; } catch { S.mfilter = ""; S.morder = "best"; }
  const good = (sm, n) => { const t = sm.totals[n] || {}; return (t.pass || 0) * 2 + (t.equivalent || 0); };
  function matrixStrategies(sm) {
    const words = S.mfilter.split(",").map((w) => w.trim().toLowerCase()).filter((w) => w && w !== "all");
    const exact = new Set(sm.strategies.map((s) => s.name.toLowerCase()));
    const hit = (name) => words.some((w) => (exact.has(w) ? name.toLowerCase() === w : name.toLowerCase().includes(w)));
    const list = sm.strategies.filter((s) => !words.length || hit(s.name));
    return S.morder === "best" ? [...list].sort((a, b) => good(sm, b.name) - good(sm, a.name) || a.name.localeCompare(b.name)) : [...list].sort((a, b) => a.name.localeCompare(b.name));
  }
  function renderMatrixControls(sm, strats) {
    const box = $("mcontrols");
    if (!box.firstChild) {
      box.innerHTML = `<label>Strategies <input id="m-filter" type="search" list="m-names" placeholder="all (or names, comma separated)" aria-label="Which strategies to show"></label>
        <datalist id="m-names"></datalist>
        <label>Order <select id="m-order"><option value="best">most passing first</option><option value="name">by name</option></select></label>
        <span class="chips" id="m-quick"></span><span class="muted small" id="m-count"></span>`;
      $("m-filter").value = S.mfilter;
      $("m-order").value = S.morder;
      const save = () => { try { localStorage.setItem("sdlab.ladder.mfilter", S.mfilter); localStorage.setItem("sdlab.ladder.morder", S.morder); } catch { /* not kept */ } };
      $("m-filter").addEventListener("input", (e) => { S.mfilter = e.target.value; save(); renderMatrix(); });
      $("m-order").addEventListener("change", (e) => { S.morder = e.target.value; save(); renderMatrix(); });
      box.addEventListener("click", (e) => {
        const b = e.target.closest("[data-quick]"); if (!b) return;
        S.mfilter = b.dataset.quick; $("m-filter").value = S.mfilter; save(); renderMatrix();
      });
    }
    $("m-names").innerHTML = sm.strategies.map((s) => `<option value="${esc(s.name)}">`).join("");
    const best = [...sm.strategies].sort((a, b) => good(sm, b.name) - good(sm, a.name)).slice(0, 5).map((s) => s.name).join(", ");
    $("m-quick").innerHTML = `<button class="chip" data-quick="">all</button><button class="chip" data-quick="${esc(best)}" title="${esc(best)}">best 5</button>${sm.strategies.some((s) => s.name === "matrix") ? '<button class="chip" data-quick="matrix">matrix</button>' : ""}`;
    $("m-count").textContent = `${strats.length} of ${sm.strategies.length} strategies`;
  }
  function stackBar(t) {
    const total = t.total || 0; if (!total) return "";
    return `<div class="sbar">${["pass", "equivalent", "fail", "error", "timeout"].map((k) => t[k] ? `<span class="st-${k}" style="flex:${t[k]}"></span>` : "").join("")}${t.missing ? `<span class="st-none" style="flex:${t.missing}"></span>` : ""}</div>`;
  }

  // ---------- History ----------
  async function renderHistory() {
    if (!S.hsel.case) S.hsel.case = S.sel.case || (S.cases[0] || {}).id;
    if (!S.hsel.strategy) S.hsel.strategy = S.sel.strategy || defaultStrategy();
    const c = S.byId[S.hsel.case]; if (!c) return;
    $("hpick").innerHTML = `<label>Case <select id="h-case">${S.cases.map((x) => `<option value="${esc(x.id)}" ${x.id === c.id ? "selected" : ""}>${esc(x.id)}</option>`).join("")}</select></label>
      <label>Strategy <select id="h-strat">${S.strategies.map((s) => `<option ${s.name === S.hsel.strategy ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
      <label>Plot <select id="h-metric">${[["recall", "recall"], ["precision", "precision"], ["skill20", "skill@20"], ["skill100", "skill@100"], ["fresh20", "fresh skill@20"]].map(([k, w]) => `<option value="${k}" ${k === (S.hmetric || "recall") ? "selected" : ""}>${w}</option>`).join("")}</select></label>`;
    $("h-case").onchange = (e) => { S.hsel.case = e.target.value; remember(); renderHistory(); };
    $("h-strat").onchange = (e) => { S.hsel.strategy = e.target.value; remember(); renderHistory(); };
    $("h-metric").onchange = (e) => { S.hmetric = e.target.value; renderHistory(); };
    remember();
    const strat = S.hsel.strategy;
    let hs;
    try { hs = await Promise.all(c.variants.map((v) => get(`/api/ladder/results/${enc(c.id)}/${enc(v.name)}/${enc(strat)}/history`))); } catch (e) { setStatus(e.message, true); return; }
    const metric = S.hmetric || "recall";
    const val = (r) => {
      const s = r.scores || {}, b = s.behaviour || {};
      if (metric === "recall" || metric === "precision") return s[metric];
      const where = metric.startsWith("fresh") ? "fresh" : "in_sample", h = metric.endsWith("100") ? "100" : "20";
      return ((b[where] || {})[h] || {}).skill;
    };
    const rows = [];
    c.variants.forEach((v, vi) => {
      const list = [...hs[vi]].reverse();                                   // oldest first
      list.forEach((r, i) => {
        const prev = list[i - 1];
        const good = (st) => st === "pass" || st === "equivalent";
        r._change = !prev ? "first run" : prev.status === r.status ? "" : good(r.status) && !good(prev.status) ? `started ${r.status === "pass" ? "passing" : "being equivalent"}` : !good(r.status) && good(prev.status) ? `started ${r.status === "fail" ? "failing" : r.status}` : `${prev.status} → ${r.status}`;
        r._codeChange = prev && prev.strategy_hash !== r.strategy_hash ? "strategy changed" : prev && prev.score_hash !== r.score_hash ? "scorer changed" : prev && prev.case_hash !== r.case_hash ? "case changed" : "";
        r._vi = vi;
        rows.push(r);
      });
    });
    const strips = c.variants.map((v, vi) => {
      const list = [...hs[vi]].reverse();
      const last = list[list.length - 1];
      return `<tr><th class="mono">${esc(v.name)}</th><td><span class="strip">${list.map((r) => `<button class="sq st-${r.status}" data-id="${r.id}" data-tip="${esc(`#${r.id} · ${when(r.at)}<br>${r.status}${r._change ? ` (${r._change})` : ""}<br>recall ${pct((r.scores || {}).recall)} · strategy ${short(r.strategy_hash)}`)}">${STATUS_LETTER[r.status]}</button>`).join("") || '<span class="muted small">never run</span>'}</span></td>
        <td class="small">${last ? `${list.length} result${list.length === 1 ? "" : "s"}; now <b>${esc(last.status)}</b>${sinceText(list)}` : ""}</td></tr>`;
    }).join("");
    $("hbody").innerHTML = `<p class="tests">${esc(c.title)}: ${esc(c.tests)}</p>
      <div class="tablewrap"><table class="rtable strips"><tbody>${strips}</tbody></table></div>
      <div class="chartbox" id="hchart"></div><div class="legend" id="hlegend"></div>
      <h3>Every result <span class="muted small">newest first; click one to see its found model</span></h3>
      <div class="tablewrap"><table class="rtable"><thead><tr><th>#</th><th>when</th><th>variant</th><th>status</th><th class="num">recall</th><th class="num">precision</th><th class="num">right</th><th class="num">skill@20</th><th class="num">fresh@20</th><th class="num">s</th><th>strategy</th><th>scorer</th><th></th></tr></thead><tbody>
      ${[...rows].sort((a, b) => b.id - a.id).map((r) => { const s = r.scores || {}, b = s.behaviour || {}; return `<tr>
        <td class="num">${r.id}</td><td class="small">${esc(when(r.at))}</td><td class="mono">${esc(r.variant)}</td>
        <td><span class="stbadge st-${r.status} small">${esc(r.status)}</span>${r._change && r._change !== "first run" ? ` <span class="small change">${esc(r._change)}</span>` : ""}${r._codeChange ? ` <span class="small muted">${esc(r._codeChange)}</span>` : ""}</td>
        <td class="num">${pct(s.recall)}</td><td class="num">${pct(s.precision)}</td><td class="num">${s.right ?? "–"}/${s.of ?? "–"}</td>
        <td class="num">${pct(((b.in_sample || {})["20"] || {}).skill)}</td><td class="num">${pct(((b.fresh || {})["20"] || {}).skill)}</td><td class="num">${r.seconds !== null && r.seconds !== undefined ? fmt(r.seconds) : "–"}</td>
        <td class="mono">${esc(short(r.strategy_hash))}</td><td class="mono">${esc(short(r.score_hash))}</td>
        <td><button class="btn small" data-id="${r.id}">view</button></td></tr>`; }).join("") || `<tr><td colspan="13" class="muted">${esc(strat)} has never run on ${esc(c.id)}.</td></tr>`}
      </tbody></table></div>`;
    $("hbody").querySelectorAll("[data-id]").forEach((b) => (b.onclick = () => { const r = rows.find((x) => String(x.id) === b.dataset.id); pick({ case: r.case, variant: r.variant, strategy: r.strategy, id: r.id }); }));
    historyChart($("hchart"), $("hlegend"), c.variants.map((v, vi) => ({ name: v.name, pts: rows.filter((r) => r._vi === vi).map((r) => ({ t: Date.parse(r.at), y: val(r), r })) })), metric);
    renderTimelines();
  }
  function sinceText(list) {
    const last = list[list.length - 1]; let i = list.length - 1;
    while (i > 0 && list[i - 1].status === last.status) i--;
    return list.length > 1 ? `, since ${esc(when(list[i].at))}${i > 0 ? ` (was ${esc(list[i - 1].status)})` : ""}` : "";
  }

  // a line per variant over time (time axis; one point per result); hover for the result, click to open
  function historyChart(box, legend, series, metric) {
    const all = series.flatMap((s) => s.pts).filter((p) => p.y !== null && p.y !== undefined && Number.isFinite(+p.y));
    if (!all.length) { box.innerHTML = `<p class="note">Nothing to plot yet.</p>`; legend.innerHTML = ""; return; }
    const W = Math.max(320, box.clientWidth || 800), H = 220, m = { l: 48, r: 16, t: 12, b: 28 };
    let t0 = Math.min(...all.map((p) => p.t)), t1 = Math.max(...all.map((p) => p.t));
    if (t1 - t0 < 1000) { t0 -= 30000; t1 += 30000; }
    const lo = Math.min(0, ...all.map((p) => +p.y)), hi = Math.max(1, ...all.map((p) => +p.y));
    const X = (t) => m.l + (t - t0) / (t1 - t0) * (W - m.l - m.r), Y = (y) => m.t + (1 - (y - lo) / (hi - lo)) * (H - m.t - m.b);
    const grid = [0, 0.25, 0.5, 0.75, 1].map((g) => lo + g * (hi - lo)).map((y) => `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(y)}" y2="${Y(y)}"/><text class="axis" x="${m.l - 6}" y="${Y(y) + 4}" text-anchor="end">${Math.round(y * 100)}%</text>`).join("");
    const ticks = [t0, (t0 + t1) / 2, t1].map((t, i) => `<text class="axis" x="${X(t)}" y="${H - 8}" text-anchor="${["start", "middle", "end"][i]}">${esc(new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }))}</text>`).join("");
    const lines = series.map((s, i) => {
      const pts = s.pts.filter((p) => p.y !== null && p.y !== undefined && Number.isFinite(+p.y));
      return `<path class="ln c${i + 1}" d="${pts.map((p, k) => `${k ? "L" : "M"}${X(p.t)} ${Y(+p.y)}`).join("")}"/>`
        + pts.map((p) => `<circle class="pt c${i + 1}" cx="${X(p.t)}" cy="${Y(+p.y)}" r="5" data-id="${p.r.id}" data-tip="${esc(`${s.name} · #${p.r.id}<br>${when(p.r.at)}<br>${p.r.status} · ${metric} ${pct(p.y)}`)}"/>`).join("");
    }).join("");
    box.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(metric)} over time per variant">${grid}${ticks}${lines}</svg>`;
    legend.innerHTML = series.map((s, i) => `<span><span class="sw c${i + 1}"></span>${esc(s.name)}</span>`).join("");
    box.querySelectorAll("circle[data-id]").forEach((c) => (c.onclick = () => { const p = all.find((x) => String(x.r.id) === c.dataset.id); pick({ case: p.r.case, variant: p.r.variant, strategy: p.r.strategy, id: p.r.id }); }));
  }

  // one row per strategy (most passing first): a small stacked bar per version, the ladder's state
  // just after that version ran; hover a bar for its counts
  async function renderTimelines() {
    const box = $("timeline");
    const avail = S.strategies.filter((s) => s.available);
    let tls;
    try { tls = await Promise.all(avail.map((s) => get(`/api/ladder/strategies/${enc(s.name)}/timeline`))); } catch (e) { box.innerHTML = `<p class="note error">${esc(e.message)}</p>`; return; }
    const good = (tl) => (tl.length ? tl[tl.length - 1].totals.pass * 2 + tl[tl.length - 1].totals.equivalent : -1);
    const order = avail.map((s, i) => ({ s, tl: tls[i] })).sort((a, b) => good(b.tl) - good(a.tl) || a.s.name.localeCompare(b.s.name));
    const H = 30, bw = 12, gap = 4;
    box.innerHTML = `<table class="rtable tltable"><thead><tr><th>strategy</th><th class="num">now</th><th>versions, oldest first</th></tr></thead><tbody>${order.map(({ s, tl }) => {
      if (!tl.length) return `<tr><th class="mono">${esc(s.name)}</th><td class="num muted">–</td><td class="muted small">never run</td></tr>`;
      const W = tl.length * (bw + gap);
      const bars = tl.map((v, k) => {
        let y = H; const x = k * (bw + gap);
        const segs = ["pass", "equivalent", "fail", "error", "timeout"].map((st) => {
          const n = v.totals[st] || 0; if (!n) return "";
          const h = n / v.of * H; y -= h;
          return `<rect class="st-${st}" x="${x}" y="${y.toFixed(1)}" width="${bw}" height="${Math.max(0, h - 0.5).toFixed(1)}"/>`;
        }).join("");
        const missing = v.of - Object.values(v.totals).reduce((a, b) => a + b, 0);
        const tipTxt = `<b>${esc(s.name)}</b> version ${k + 1}: strategy ${esc(short(v.strategy_hash))}, scorer ${esc(short(v.score_hash))}<br>first ran ${esc(when(v.first))}, ${v.ran} result${v.ran === 1 ? "" : "s"}<br>after it: ${v.totals.pass} pass, ${v.totals.equivalent} equivalent, ${v.totals.fail} fail${v.totals.error ? `, ${v.totals.error} error` : ""}${v.totals.timeout ? `, ${v.totals.timeout} timeout` : ""}${missing ? `, ${missing} not run` : ""} of ${v.of}`;
        return `<g data-tip="${esc(tipTxt)}"><rect x="${x}" y="0" width="${bw}" height="${H}" fill="var(--rule)" opacity=".35"/>${segs}</g>`;
      }).join("");
      const last = tl[tl.length - 1];
      return `<tr><th class="mono">${esc(s.name)}</th><td class="num">${last.totals.pass + last.totals.equivalent}/${last.of}</td>
        <td><svg class="tlbars" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(s.name)}: totals per version">${bars}</svg></td></tr>`;
    }).join("")}</tbody></table>`;
  }

  // ---------- Cases ----------
  function renderCases() {
    const tags = [...new Set(S.cases.flatMap((c) => c.tags))].sort();
    const q = (S.cfilter || "").toLowerCase();
    const list = S.cases.filter((c) => (!S.ctag || c.tags.includes(S.ctag)) && (!q || `${c.id} ${c.title} ${c.tests} ${c.tags.join(" ")}`.toLowerCase().includes(q)));
    if (!S.csel.case || !S.byId[S.csel.case]) S.csel.case = (list[0] || S.cases[0] || {}).id;
    $("clist").innerHTML = `<input id="cfind" type="search" placeholder="Find a case" value="${esc(S.cfilter || "")}" aria-label="Find a case">
      <div class="chips tagchips"><button class="chip${S.ctag ? "" : " on"}" data-tag="">all</button>${tags.map((t) => `<button class="chip${S.ctag === t ? " on" : ""}" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}</div>
      <div class="ccards">${list.map((c) => `<button class="card ccard${c.id === S.csel.case ? " on" : ""}" data-case="${esc(c.id)}">
        <span class="ctitle">${esc(c.id)} <span class="muted">· level ${esc(c.level)}</span></span><span class="cverdict">${esc(c.title)}</span><span class="cstatus">${esc(c.tags.join(", "))}</span></button>`).join("") || '<p class="empty">No case matches.</p>'}</div>`;
    $("cfind").oninput = (e) => { S.cfilter = e.target.value; renderCases(); const f = $("cfind"); f.focus(); f.setSelectionRange(f.value.length, f.value.length); };
    $("clist").querySelectorAll("[data-tag]").forEach((b) => (b.onclick = () => { S.ctag = b.dataset.tag || null; renderCases(); }));
    $("clist").querySelectorAll("[data-case]").forEach((b) => (b.onclick = () => { S.csel.case = b.dataset.case; remember(); renderCases(); }));
    remember();
    renderCase();
  }
  async function renderCase() {
    const c = S.byId[S.csel.case]; if (!c) { $("cdetail").innerHTML = ""; return; }
    if (!S.summary) await loadSummary();
    if (!c.variants.some((v) => v.name === S.csel.variant)) S.csel.variant = c.variants[0].name;
    const measured = new Set(c.model.stocks.filter((s) => s.measured !== false).map((s) => s.id));
    const flows = c.model.flows.map((f) => ({ flow: f, eq: L.equation(f, c.model.schedule) }));
    $("cdetail").innerHTML = `<div class="casehead"><h2 class="ctitle2">${esc(c.id)} <span>${esc(c.title)}</span></h2>
        <span class="muted small">level ${esc(c.level)} · ${c.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join(" ")} · hash ${esc(short(c.hash))}</span>
        <p class="tests">Tests: ${esc(c.tests)}</p></div>
      <div class="cstrats">${S.strategies.map((s) => `<span class="cst"><span class="small">${esc(s.name)}</span> ${squares(c.id, s.name)}</span>`).join("")}</div>
      <figure class="dpanel single"><figcaption>True model</figcaption><svg id="c-diagram" role="img" aria-label="The case's true model"></svg></figure>
      <div class="tablewrap"><table class="rtable"><thead><tr><th>flow</th><th>from → to</th><th>equation</th></tr></thead><tbody>
        ${flows.map((x) => `<tr><td><b>${esc(x.flow.id)}</b></td><td class="mono">${esc(x.flow.from || "outside")} → ${esc(x.flow.to || "outside")}</td><td class="mono">${esc(x.eq)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="note">Stocks: ${c.model.stocks.map((s) => `${esc(s.id)} starts at ${esc(fmt(s.initial))}${measured.has(s.id) ? "" : " (not measured)"}`).join("; ")}.
        ${(c.model.injections || []).length ? `Injections: ${c.model.injections.length} announced.` : ""}
        ${Object.keys(c.tolerance || {}).length ? `Tolerance overrides: ${esc(JSON.stringify(c.tolerance))}.` : ""}</p>
      <h3>Its data <span class="muted small">what discovery sees: the measured stocks' levels${measured.size < c.model.stocks.length ? "; dashed: not measured, for reference" : ""}</span></h3>
      <div class="rcontrols"><span class="seg-btns" role="group" aria-label="Variant">${c.variants.map((v) => `<button class="btn${v.name === S.csel.variant ? " on" : ""}" data-v="${esc(v.name)}">${esc(v.name)}</button>`).join("")}</span>
        <label><input type="checkbox" id="c-fresh" ${S.csel.fresh ? "checked" : ""}> fresh run (next seed)</label></div>
      <div class="chartbox" id="c-plot"></div><div class="legend" id="c-legend"></div>`;
    const pos = D.layout(c.model.stocks.map((s) => s.id), c.model.flows, { ...LAYOUT, maxCols: maxCols() });
    D.draw($("c-diagram"), {
      stocks: c.model.stocks.map((s) => ({ id: s.id, name: s.id, dashed: !measured.has(s.id), sub: measured.has(s.id) ? "" : "not measured" })),
      flows: c.model.flows.map((f) => ({ from: f.from, to: f.to, cls: "plain", label: f.id, label2: short2(L.rateText(f.rate)), title: `${f.id}: ${L.equation(f, c.model.schedule)}`,
        reads: [...L.readers(f)].filter((x) => x !== "const" && x !== f.from).map((stock) => ({ stock }))
          .concat((f.effects || []).map((e) => ({ stock: e.stock, label: "effect", dash: "5 4", cls: "plain" })), (f.uses || []).map((u) => ({ stock: u.stock, label: `uses ${fmt(+u.per)}`, dash: "1 3", cls: "plain" }))) })),
    }, pos, { box: BOX, color: (k) => CLS_COLOR[k] || "var(--fg)", maxScale: 1.3 });
    $("cdetail").querySelectorAll(".sq[data-case]").forEach((b) => (b.onclick = () => pick({ case: b.dataset.case, variant: b.dataset.variant, strategy: b.dataset.strategy })));
    $("cdetail").querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => { S.csel.variant = b.dataset.v; renderCase(); }));
    $("c-fresh").onchange = (e) => { S.csel.fresh = e.target.checked; renderCase(); };
    const my = (S.ctoken = (S.ctoken || 0) + 1);
    $("c-plot").innerHTML = `<p class="note">Loading the data…</p>`;
    try {
      const d = await cached(`/api/ladder/cases/${enc(c.id)}/data/${enc(S.csel.variant)}${S.csel.fresh ? "?fresh=true" : ""}`);
      if (my === S.ctoken) plotLevels($("c-plot"), $("c-legend"), d, c);
    } catch (e) { $("c-plot").innerHTML = `<p class="note error">${esc(e.message)}</p>`; }
  }

  // levels over time, one line per stock (categorical colours in fixed order), eras shaded,
  // injections ticked; hover for the values at a step
  function plotLevels(box, legend, d, c) {
    const ids = c.model.stocks.map((s) => s.id), measured = new Set(d.measured);
    const W = Math.max(320, box.clientWidth || 800), H = 260, m = { l: 52, r: 56, t: 14, b: 26 };
    const t = d.t, n = t.length, stride = Math.max(1, Math.ceil(n / 900));
    const series = ids.map((id) => ({ id, ys: (measured.has(id) ? d.levels[id] : d.all_levels[id]) || [], hidden: !measured.has(id) }));
    const hi = Math.max(1e-9, ...series.flatMap((s) => s.ys)), lo = Math.min(0, ...series.flatMap((s) => s.ys));
    const X = (i) => m.l + (t[i] - t[0]) / Math.max(1, t[n - 1] - t[0]) * (W - m.l - m.r), Y = (y) => m.t + (1 - (y - lo) / (hi - lo)) * (H - m.t - m.b);
    const ticks = [0, 0.25, 0.5, 0.75, 1].map((g) => lo + g * (hi - lo));
    const eras = (d.eras || []).length > 1 ? d.eras.map((e, k) => {
      const i0 = Math.max(0, t.indexOf(e.start)), next = d.eras[k + 1], i1 = next ? Math.max(0, t.indexOf(next.start)) : n - 1;
      return k % 2 ? `<rect x="${X(i0)}" y="${m.t}" width="${Math.max(0, X(i1) - X(i0))}" height="${H - m.t - m.b}" fill="var(--era)"/>` : "";
    }).join("") + d.eras.map((e) => { const i = t.indexOf(e.start); return i >= 0 ? `<text class="axis" x="${X(i) + 3}" y="${m.t + 10}">${esc(e.label || "")}</text>` : ""; }).join("") : "";
    const inj = (d.injections || []).map((j) => { const i = t.indexOf(j.t); return i >= 0 ? `<line x1="${X(i)}" x2="${X(i)}" y1="${H - m.b}" y2="${H - m.b - 6}" stroke="var(--fg)" stroke-width="1.5"/>` : ""; }).join("");
    // end labels, pushed apart so lines that end together stay readable
    const ends = series.map((s, k) => ({ k, y: Y(s.ys[n - 1] || 0) })).sort((a, b) => a.y - b.y);
    ends.forEach((e, i) => { if (i && e.y - ends[i - 1].y < 12) e.y = ends[i - 1].y + 12; });
    const endY = Object.fromEntries(ends.map((e) => [e.k, e.y]));
    const lines = series.map((s, k) => {
      let p = "";
      for (let i = 0; i < n; i += stride) p += `${p ? "L" : "M"}${X(i).toFixed(1)} ${Y(s.ys[i] || 0).toFixed(1)}`;
      return `<path class="ln c${(k % SERIES) + 1}${s.hidden ? " hid" : ""}" d="${p}"/><text class="dl c${(k % SERIES) + 1}" x="${W - m.r + 6}" y="${endY[k] + 4}">${esc(s.id)}</text>`;
    }).join("");
    box.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Levels over time">
      ${eras}${ticks.map((y) => `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(y)}" y2="${Y(y)}"/><text class="axis" x="${m.l - 6}" y="${Y(y) + 4}" text-anchor="end">${esc(fmt(y))}</text>`).join("")}
      <text class="axis" x="${m.l}" y="${H - 6}">${t[0]}</text><text class="axis" x="${W - m.r}" y="${H - 6}" text-anchor="end">step ${t[n - 1]}</text>
      ${inj}${lines}<line id="xhair" class="xhair" y1="${m.t}" y2="${H - m.b}" x1="-10" x2="-10"/><rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent" id="hit"/></svg>`;
    legend.innerHTML = series.map((s, k) => `<span><span class="sw c${(k % SERIES) + 1}${s.hidden ? " hid" : ""}"></span>${esc(s.id)}${s.hidden ? " (not measured)" : ""}</span>`).join("");
    const hit = box.querySelector("#hit"), xh = box.querySelector("#xhair");
    hit.addEventListener("mousemove", (e) => {
      const r = box.querySelector("svg").getBoundingClientRect(), x = (e.clientX - r.left) * W / r.width;
      const i = Math.max(0, Math.min(n - 1, Math.round((x - m.l) / (W - m.l - m.r) * (n - 1))));
      xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i));
      tip.innerHTML = `step ${t[i]}<br>${series.map((s, k) => `<span class="sw c${(k % SERIES) + 1}"></span>${esc(s.id)} ${esc(fmt(s.ys[i]))}`).join("<br>")}`;
      tip.hidden = false;
    });
    hit.addEventListener("mouseleave", () => { tip.hidden = true; xh.setAttribute("x1", -10); xh.setAttribute("x2", -10); });
  }

  // ---------- polling ----------
  let lastDone = null;
  async function poll() {
    let active = false;
    try {
      S.progress = await get("/api/ladder/progress?recent=20");
      active = !!(S.progress.run && !S.progress.run.finished);
      if (S.view === "now") renderLive();
      followTick(false);
      const done = S.progress.run ? `${S.progress.run.id}:${S.progress.run.done}` : null;
      if (done !== lastDone) {
        lastDone = done;
        if (S.view === "matrix" || S.view === "cases" || (S.view === "now" && S.sel.case)) {
          await loadSummary();
          if (S.view === "matrix") renderMatrix();
          if (S.view === "now") renderPick();
        }
      }
      setStatus(active ? `running: ${S.progress.run.done}/${S.progress.run.total}` : "");
    } catch (e) { setStatus(`progress: ${e.message}`, true); }
    setTimeout(poll, active || S.view === "now" ? 1000 : 3000);
  }

  let resizeT;
  addEventListener("resize", () => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => {
      if (S.view === "now" && S.shown !== undefined && S.sel.case) renderCompare(S.byId[S.sel.case], S.shown);
      if (S.view === "cases") renderCase();
      if (S.view === "history") renderHistory();
    }, 200);
  });

  // ---------- start ----------
  (async function start() {
    try {
      [S.cases, S.strategies] = await Promise.all([get("/api/ladder/cases"), get("/api/ladder/strategies")]);
    } catch (e) { setStatus(e.message, true); return; }
    S.cases.forEach((c) => { S.byId[c.id] = c; });
    const p = new URLSearchParams(location.search);
    const view = ["now", "matrix", "history", "cases"].includes(p.get("view")) ? p.get("view") : "now";
    if (view === "now" && p.get("case") && S.byId[p.get("case")]) {
      S.follow = false;
      S.sel = { case: p.get("case"), variant: p.get("variant"), strategy: p.get("strategy"), id: p.get("result") ? +p.get("result") : null };
    }
    if (view === "history") S.hsel = { case: S.byId[p.get("case")] ? p.get("case") : null, strategy: p.get("strategy") };
    if (view === "cases" && S.byId[p.get("case")]) S.csel.case = p.get("case");
    await loadSummary();
    try { S.progress = await get("/api/ladder/progress?recent=20"); } catch { S.progress = null; }
    if (S.follow) followTick(true);
    setView(view);
    renderLive();
    lastDone = S.progress && S.progress.run ? `${S.progress.run.id}:${S.progress.run.done}` : null;
    setTimeout(poll, 1000);
  })();
})();
