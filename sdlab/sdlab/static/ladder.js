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
  const { BOX, LAYOUT, CLS_COLOR, CLS_WORD, LEGEND, short2, maxCols, drawPair, diffHtml, compareOf } = window.SDLadderDraw;
  const STATUS_LETTER = { pass: "P", equivalent: "E", fail: "F", error: "X", timeout: "T" };
  const STATUS_WORD = { pass: "pass", equivalent: "equivalent", fail: "fail", error: "error", timeout: "timeout" };
  const SERIES = 8;                                      // categorical slots --c1..--c8 (style.css)

  const S = {
    view: "now", cases: [], byId: {}, strategies: [], summary: null, progress: null,
    sel: { case: null, variant: null, strategy: null, id: null }, follow: false, shown: null, nowMode: "board",
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
    if (S.view === "now" && !S.follow && S.nowMode === "one") {
      ["case", "variant", "strategy"].forEach((k) => S.sel[k] && p.set(k, S.sel[k]));
      if (S.sel.id) p.set("result", S.sel.id);
    }
    if (S.view === "history") ["case", "strategy"].forEach((k) => S.hsel[k] && p.set(k, S.hsel[k]));
    if (S.view === "cases") {                       // the list's filters, so a refresh keeps them
      if (S.csel.case) p.set("case", S.csel.case);
      if (S.csel.run) p.set("run", `${S.csel.run.strategy}:${S.csel.run.variant}`);
      if (S.cfilter) p.set("q", S.cfilter);
      if ((S.ctags || []).length) p.set("tags", S.ctags.join(","));
      if (S.cstatus && S.cstatus !== "all") p.set("status", S.cstatus);
      if (S.cset && S.cset !== "all") p.set("set", S.cset);
      if (S.csort && S.csort !== "ladder") p.set("sort", S.csort);
    }
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
    if (v === "now") showNow();
    if (v === "matrix") loadSummary().then(renderMatrix);
    if (v === "history") renderHistory();
    if (v === "cases") renderCases();
  }
  document.querySelectorAll(".ltabs [role=tab]").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  // the matrix's cells (/api/ladder/matrix: only what a square shows): every case's for the matrix view,
  // one case's otherwise; fetched again only when the summary's version has changed
  async function loadSummary(caseId) {
    const cid = caseId !== undefined ? caseId : S.view === "matrix" ? null : S.view === "cases" ? S.csel.case : S.sel.case;
    if (!cid && S.view !== "matrix" && caseId === undefined) return S.summary;      // no case on screen: nothing to show
    const want = cid || "";
    try {
      if (S.summary && S.summary.key === want && (await get("/api/ladder/version")).version === S.summary.version) return S.summary;
      S.summary = expandCells(await get(`/api/ladder/matrix${cid ? `?case=${encodeURIComponent(cid)}` : ""}`), want);
    } catch (e) { setStatus(String(e.message), true); }
    return S.summary;
  }
  function expandCells(m, key) {
    const at = new Map();
    const cells = m.cells.map((r) => {
      const x = { case: m.cases[r[0]], variant: m.variants[r[1]], strategy: m.strategies[r[2]].name };
      m.fields.forEach((f, i) => { x[f] = r[i + 3]; });
      at.set(`${x.case}|${x.variant}|${x.strategy}`, x);
      return x;
    });
    return { ...m, key, cells, totals: m.totals || {}, by_tag: m.by_tag || {}, covers: (cid) => !key || key === cid, at: (c, v, s) => at.get(`${c}|${v}|${s}`) };
  }
  function wantCase(cid) {                                 // a case whose cells are not here yet: fetch them, then draw again
    if (S.wanting === cid) return;
    S.wanting = cid;
    loadSummary(cid).then(() => { S.wanting = null; if (S.view === "now" && S.sel.case === cid) renderPick(); if (S.view === "cases" && S.csel.case === cid) renderCase(); });
  }
  const cellOf = (c, v, s) => S.summary && S.summary.at(c, v, s);
  function squares(caseId, strategy, opts = {}) {
    const c = S.byId[caseId];
    if (S.view !== "matrix" && (!S.summary || !S.summary.covers(caseId))) wantCase(caseId);
    return `<span class="sq4">${c.variants.map((v) => {
      const cell = cellOf(caseId, v.name, strategy) || {}, st = cell.status, stale = st && cell.stale;
      const tipTxt = `<b>${esc(caseId)}</b> · ${esc(v.name)} · ${esc(strategy)}<br>${st ? esc(STATUS_WORD[st]) : "not run"}${stale ? ` (stale: ${esc(cell.stale)})` : ""}${st && cell.recall !== null && cell.recall !== undefined ? `<br>recall ${pct(cell.recall)}, ${cell.right}/${cell.of} parts right${cell.spurious ? `, ${cell.spurious} spurious` : ""}<br>skill@20 ${pct(cell.skill20)}, fresh ${pct(cell.fresh20)}` : ""}${cell.error ? `<br>${esc(String(cell.error).slice(0, 200))}` : ""}${cell.analysis && cell.analysis !== "achievable" ? `<br>the data: ${esc(cell.analysis)}${cell.achievable_p != null ? ` (p ${cell.achievable_p.toFixed(2)})` : ""} (sdlab-ladder analyse)` : ""}`;
      const on = opts.current === v.name ? " on" : "";
      return `<button class="sq st-${st || "none"}${stale ? " stale" : ""}${cell.analysis ? ` an-${cell.analysis.replace(" ", "-")}` : ""}${on}" data-case="${esc(caseId)}" data-variant="${esc(v.name)}" data-strategy="${esc(strategy)}" data-tip="${esc(tipTxt)}" aria-label="${esc(`${caseId} ${v.name} ${strategy}: ${st || "not run"}${stale ? ", stale" : ""}`)}">${st ? STATUS_LETTER[st] : "·"}</button>`;
    }).join("")}</span>`;
  }

  // ---------- Now: live strip ----------
  // the item to show: the one finished last (or one running), among the cases this page knows; a
  // case it does not know yet (added since the page loaded) makes it fetch the case list again
  function liveFocus(p) {
    const all = (p && p.items) || [];
    if (all.some((i) => !S.byId[i.case])) refreshCases();
    const items = all.filter((i) => S.byId[i.case]);
    const done = items.filter((i) => i.state === "done" && i.finished).sort((a, b) => (a.finished < b.finished ? 1 : -1));
    const running = items.filter((i) => i.state === "running");
    return done[0] || running[0] || null;
  }
  function renderLive() {
    const p = S.progress, box = $("live");
    if (!p || !p.run) { box.innerHTML = `<p class="note">No ladder run yet. Start one with <code>uv run sdlab-ladder sync</code>; it shows here as it goes.</p>`; return; }
    const r = p.run, active = !r.finished, items = p.items || [];   // the server reports a dead run as finished (aborted)
    const counts = p.counts || {};
    const running = items.filter((i) => i.state === "running");
    const bar = ["pass", "equivalent", "fail", "error", "timeout"].map((k) => counts[k] ? `<span class="seg st-${k}" style="flex:${counts[k]}" data-tip="${counts[k]} ${k}"></span>` : "").join("")
      + (running.length ? `<span class="seg running" style="flex:${running.length}" data-tip="${running.length} running"></span>` : "")
      + (p.queued ? `<span class="seg queued" style="flex:${p.queued}" data-tip="${p.queued} queued"></span>` : "");
    const tally = Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(", ") || "nothing finished yet";
    box.innerHTML = `<div class="livehead">
        <span class="livedot${active ? " on" : ""}" aria-hidden="true"></span>
        <b>${active ? "Running" : r.aborted ? "Last run (stopped before the end)" : "Last run"}</b> <code>${esc(r.command || "sdlab-ladder")}</code>
        <span class="muted small">${r.done}/${r.total} done${active ? `, ${r.running} running` : ""} · ${esc(tally)} · ${active ? `started ${esc(when(r.started))}` : `finished ${esc(when(r.finished))}`}</span>
        <label class="follow" title="Show each result as the run finishes it"><input type="checkbox" id="follow" ${S.follow ? "checked" : ""}> follow the run</label>
      </div>
      <div class="pbar" role="progressbar" aria-valuemin="0" aria-valuemax="${r.total}" aria-valuenow="${r.done}">${bar}</div>
      ${timingChart(p)}
      ${running.length ? `<div class="chips running-now"><span class="muted small">running now:</span>${running.slice(0, 6).map((i) => `<button class="chip" data-case="${esc(i.case)}" data-variant="${esc(i.variant)}" data-strategy="${esc(i.strategy)}">${esc(i.case)} · ${esc(i.variant)} · ${esc(i.strategy)}</button>`).join("")}${running.length > 6 ? `<span class="muted small">+${running.length - 6}</span>` : ""}</div>` : ""}`;
    $("follow").addEventListener("change", (e) => { S.follow = e.target.checked; if (S.follow) { S.nowMode = "one"; followTick(true); } remember(); });
    box.querySelectorAll(".chip[data-case]").forEach((b) => b.addEventListener("click", () => pick({ case: b.dataset.case, variant: b.dataset.variant, strategy: b.dataset.strategy })));
    const t = (p && p.times) || [];
    box.querySelectorAll(".tbar").forEach((b) => b.addEventListener("click", () => openTime(t[+b.dataset.ti])));
    const step = (d) => { const i = timesAt(t); openTime(t[i === -1 ? (d < 0 ? t.length - 1 : 0) : Math.max(0, Math.min(t.length - 1, i + d))]); renderLive(); };
    if ($("t-prev")) $("t-prev").onclick = () => step(-1);
    if ($("t-next")) $("t-next").onclick = () => step(1);
  }
  // the chart's bar for the result on screen (-1: none of them)
  function timesAt(t) {
    if (S.follow || S.nowMode !== "one") return -1;
    return t.findIndex((x) => (S.sel.id && x.id === S.sel.id) || (!S.sel.id && x.case === S.sel.case && x.variant === S.sel.variant && x.strategy === S.sel.strategy));
  }
  function openTime(x) { if (x) pick({ case: x.case, variant: x.variant, strategy: x.strategy, ...(x.id ? { id: x.id } : {}) }); }
  // how long the newest results took (the pool's last 120), one bar each, coloured by status, with each item's
  // timeout as a dashed tick: a run that bumps into its limit shows at once (the user, 2026-10-21)
  function timingChart(p) {
    const t = (p && p.times) || [];
    if (!t.length) return "";
    const W = 720, H = 70, n = t.length, bw = W / n, top = Math.max(...t.map((x) => Math.max(x.seconds || 0, x.timeout || 0)), 1);
    const y = (s) => H - (H - 4) * Math.sqrt(Math.max(0, s) / top);            // square-root scale: short runs stay visible
    const col = (st) => ({ pass: "var(--good)", equivalent: "var(--eq)", fail: "var(--bad)", error: "var(--bad)", timeout: "var(--warn)" }[st] || "var(--muted)");
    const cur = timesAt(t);
    const bars = t.map((x, i) => {
      const s = x.status === "timeout" ? x.timeout : x.seconds || 0;
      return `<rect class="tbar${i === cur ? " on" : ""}" data-ti="${i}" x="${(i * bw).toFixed(1)}" y="${y(s).toFixed(1)}" width="${Math.max(1, bw - 1).toFixed(1)}" height="${(H - y(s)).toFixed(1)}" fill="${col(x.status)}"><title>${esc(`${x.case} · ${x.variant} · ${x.strategy}: ${x.status}, ${x.status === "timeout" ? `stopped at its ${x.timeout} s limit` : `${(x.seconds || 0).toFixed(1)} s`} (limit ${x.timeout} s) — click to open`)}</title></rect>`
        + `<line x1="${(i * bw).toFixed(1)}" x2="${((i + 1) * bw - 1).toFixed(1)}" y1="${y(x.timeout).toFixed(1)}" y2="${y(x.timeout).toFixed(1)}" stroke="var(--fg)" stroke-dasharray="2 2" opacity="0.5"/>`;
    }).join("");
    const secs = t.map((x) => x.seconds || 0).sort((a, b) => a - b), med = secs[Math.floor(secs.length / 2)], p90 = secs[Math.floor(secs.length * 0.9)];
    const to = t.filter((x) => x.status === "timeout").length;
    return `<figure class="timing"><div class="tnav"><button class="btn" id="t-prev" ${cur <= 0 && cur !== -1 ? "disabled" : ""} title="The result finished before the one shown">◀ previous</button>
      <span class="small muted">${cur >= 0 ? `result ${cur + 1} of ${n}` : `newest of ${n}`}</span>
      <button class="btn" id="t-next" ${cur === -1 || cur >= n - 1 ? "disabled" : ""} title="The result finished after the one shown">next ▶</button></div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="How long the newest results took; click a bar to open it">${bars}</svg>
      <figcaption class="small muted">Run times of the last ${n} results (square-root scale; dashes: each one's time limit): median ${med.toFixed(1)} s, 90th percentile ${p90.toFixed(0)} s, longest ${secs[secs.length - 1].toFixed(0)} s${to ? `, <span class="err">${to} timed out</span>` : ""}</figcaption></figure>`;
  }
  // the runs panel (/api/ladder/runs, runs.py): the watcher's batch, pace, backlog and ETA, and the newest runs
  const hrs = (h) => (h == null ? "–" : h * 60 < 90 ? `${Math.round(h * 60)} min` : `${h.toFixed(1)} h`);
  const num = (x) => (x == null ? "–" : Number(x).toLocaleString());
  let runsOpen = false;
  function renderRuns(p) {
    const box = $("runs-panel");
    if (!p || p.pending) { box.hidden = false; box.innerHTML = `<p class="muted">Runs: being worked out…</p>`; return; }
    const w = p.watcher || {}, b = w.batch, pc = w.pace || {}, bl = w.backlog || {}, eta = w.eta || {};
    const left = b && b.done != null ? b.total - b.done : null;
    const batch = b ? `Watcher batch <b>#${b.id}</b> ${b.state === "running" ? `running since ${esc(when(b.started))}` : `${esc(b.state)} ${esc(when(b.finished || b.started))}`}`
      + (b.done != null ? `: <b>${num(b.done)}</b> of ${num(b.total)} done, ${num(left)} left${b.errors ? `, ${b.errors} errors` : ""}${b.timeouts ? `, ${b.timeouts} timeouts` : ""}` : ` (${num(b.total)} items; started before batches were counted)`)
      + (b.jobs ? ` on ${b.jobs} workers` : "") + (b.per_hour ? ` · ${num(Math.round(b.per_hour))} results/h` : "") + (w.alive === false ? ` · <span class="error">its process is gone</span>` : "")
      : "No watch batch recorded yet.";
    const how = Object.entries(bl.how || {}).map(([k, n]) => `${num(n)} ${k}`).join(", ");
    const sets = Object.entries(bl.by_set || {}).sort((a, c) => c[1][1] - a[1][1]).map(([k, [n, sec]]) => `${k} ${num(n)} (${hrs(sec / 3600)})`).join(", ");
    const etaText = eta.by_cost != null || eta.by_pace != null
      ? `ETA for the backlog: <b>${hrs(eta.by_cost != null ? eta.by_cost : eta.by_pace)}</b>${eta.at ? ` (${esc(when(eta.at))})` : ""}`
        + ` <span class="muted">· by pace ${hrs(eta.by_pace)}, by stored cost ${eta.by_cost != null ? hrs(eta.by_cost) : `– (efficiency not measured yet; ${hrs(eta.ideal)} if every worker is busy)`}</span>` : "ETA: –";
    const rows = (p.runs || []).map((r) => `<tr><td>#${r.id}</td><td class="l"><code>${esc(r.command)}</code></td><td class="l">${esc(when(r.started))}</td><td>${r.seconds != null ? hrs(r.seconds / 3600) : "–"}</td>`
      + `<td>${num(r.done)}/${num(r.total)}</td><td>${r.errors ?? "–"}</td><td>${r.timeouts ?? "–"}</td><td>${r.jobs ?? "–"}</td><td>${r.busy != null ? hrs(r.busy / 3600) : "–"}</td><td class="l">${esc(r.state)}</td></tr>`).join("");
    // the other machines (runs.remote: machines.yaml, as of their last export imported here)
    const others = (p.machines || []).map((m) => {
      const mb = m.backlog || {};
      const bs = (m.batches || []).map((r) => `batch #${r.id} ${esc(r.state)}${r.done != null ? ` ${num(r.done)}/${num(r.total)}` : ""}${r.backlog != null ? ` of a backlog of ${num(r.backlog)}` : ""}${r.jobs ? ` on ${r.jobs} workers` : ""}${r.errors ? `, ${r.errors} errors` : ""}${r.timeouts ? `, ${r.timeouts} timeouts` : ""}`).join("; ");
      return `<p><b>${esc(m.name)}</b>: ${m.imported_at ? `${num(m.results)} results imported, last sync ${esc(when(m.imported_at))}` : "never synced"}`
        + `${bs ? ` · its watchers: ${bs}` : ""} · stale in its share here: <b>${num(mb.items)}</b> (${num(mb.run)} to run, ${num(mb.rescore)} to re-score), about ${hrs((mb.seconds || 0) / 3600)} of work</p>`;
    }).join("");
    const me = p.machine && (p.machines || []).length ? ` on <b>${esc(p.machine)}</b>` : "";
    box.hidden = false;
    box.innerHTML = `<p>${batch}${me}</p>
      <p>Backlog${me}: <b>${num(bl.items)}</b> stale (${num(bl.run)} to run, ${num(bl.rescore)} to re-score), about ${hrs((bl.seconds || 0) / 3600)} of work <span class="muted" title="each item's cost from: ${esc(how)}">· ${esc(sets)}</span></p>
      <p>Pace: <b>${num(pc.per_hour != null ? Math.round(pc.per_hour) : null)}</b> results/h over the last ${pc.hours ?? "–"} h (${pc.batches || 0} batches)${pc.efficiency != null ? `, ${Math.round(100 * pc.efficiency)}% of the workers' time on items` : ""} · ${etaText}</p>${others}
      <details${runsOpen ? " open" : ""}><summary>Recent runs (every <code>sdlab-ladder run</code>, sync and watch batch)</summary><div class="tablewrap"><table><thead><tr><th>run</th><th class="l">command</th><th class="l">started</th><th>took</th><th>done</th><th>errors</th><th>timeouts</th><th>workers</th><th>busy</th><th class="l">state</th></tr></thead><tbody>${rows}</tbody></table></div></details>`;
    box.querySelector("details").addEventListener("toggle", (e) => { runsOpen = e.target.open; });
  }
  let runsAt = 0;
  async function pollRuns(force) {
    if (!force && (S.view !== "now" || Date.now() - runsAt < 15000)) return;
    runsAt = Date.now();
    try { const p = await get("/api/ladder/runs"); renderRuns(p); if (p.pending) runsAt = Date.now() - 12000; } catch { /* the next poll */ }
  }

  let casesAt = 0;
  async function refreshCases() {
    if (Date.now() - casesAt < 10000) return;
    casesAt = Date.now();
    try {
      S.cases = await get("/api/ladder/cases");
      S.byId = {}; S.cases.forEach((c) => { S.byId[c.id] = c; });
    } catch { /* the next poll tries again */ }
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
    S.nowMode = "one";
    if (S.view === "now") showNow();
  }
  function defaultSel() {
    const c = S.sel.case || (S.cases[0] || {}).id;
    S.sel = { case: c, variant: S.sel.variant || ((S.byId[c] || {}).variants || [{}])[0].name, strategy: S.sel.strategy || defaultStrategy(), id: null };
    if (S.view === "now") showNow();
  }
  const defaultStrategy = () => ((S.strategies.find((s) => s.name === "matrix") || S.strategies.find((s) => s.available) || S.strategies[0]) || {}).name;

  // the user picks: stop following
  function pick(sel) {
    S.follow = false; S.focusRunning = false; S.nowMode = "one";
    S.sel = { ...S.sel, id: null, ...sel };
    if (S.view !== "now") setView("now"); else { remember(); showNow(); }
    const f = $("follow"); if (f) f.checked = false;
  }

  // ---------- Now: every case (ladder-board.js), or one result ----------
  // The all-cases board is the default; picking a case (or following the run) shows one result.
  // If the board cannot load (an older server without /api/ladder/board), the single view stays.
  async function showNow() {
    const board = S.nowMode === "board" && window.SDLadderBoard;
    $("board-wrap").hidden = !board;
    $("one-wrap").hidden = !!board;
    remember();
    if (!board) return showCompare();
    const ok = await window.SDLadderBoard.render(false);
    if (!ok && S.nowMode === "board") { S.nowMode = "one"; if (!S.sel.case) defaultSel(); else showNow(); }
  }
  function toBoard() {
    S.follow = false; S.nowMode = "board";
    const f = $("follow"); if (f) f.checked = false;
    showNow();
  }

  // ---------- Now: picker ----------
  function renderPick() {
    const c = S.byId[S.sel.case]; if (!c) return;
    const i = S.cases.indexOf(c);
    $("pick").innerHTML = `${window.SDLadderBoard ? `<button class="btn" id="to-board" title="Every case on one page">&#8592; All cases</button>` : ""}
      <span class="stepper"><button class="btn" id="prev" ${i <= 0 ? "disabled" : ""} title="The case before (←)" aria-label="Previous case">&#9664;</button>
      <select id="p-case" aria-label="Case">${S.cases.map((x) => `<option value="${esc(x.id)}" ${x.id === c.id ? "selected" : ""}>${esc(x.id)}</option>`).join("")}</select>
      <button class="btn" id="next" ${i >= S.cases.length - 1 ? "disabled" : ""} title="The case after (→)" aria-label="Next case">&#9654;</button></span>
      <span class="seg-btns" role="group" aria-label="Variant">${c.variants.map((v) => `<button class="btn${v.name === S.sel.variant ? " on" : ""}" data-v="${esc(v.name)}" title="${esc(`${v.noise === "none" ? "no noise" : "whole things (Poisson)"}, ${v.steps} steps`)}">${esc(v.name)}</button>`).join("")}</span>
      <label>Strategy <select id="p-strat" aria-label="Strategy">${S.strategies.map((s) => `<option value="${esc(s.name)}" ${s.name === S.sel.strategy ? "selected" : ""} ${s.available ? "" : "disabled"}>${esc(s.name)}${s.available ? "" : " (unavailable)"}</option>`).join("")}</select></label>
      ${S.sel.id ? `<span class="badge">result #${esc(S.sel.id)} from history</span> <button class="btn" id="latest">latest</button>` : ""}
      <span class="sqwrap muted small">${squares(c.id, S.sel.strategy, { current: S.sel.id ? null : S.sel.variant })}</span>`;
    if ($("to-board")) $("to-board").onclick = toBoard;
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
    if (!S.sel.case || !S.byId[S.sel.case]) S.sel = { ...S.sel, case: (S.cases[0] || {}).id, id: null };   // never a blank page
    const sel = { ...S.sel }, my = ++token;
    if (!sel.case || !S.byId[sel.case]) { $("cmp-head").innerHTML = `<p class="note">No ladder cases found.</p>`; return; }
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
    $("dpair").hidden = false;
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
      ${r && r.complexity ? `<span data-tip="Complexity: flows + the numbers needed to write their rates over the run, the same count for the truth and the found model (extra by part: ${esc(Object.entries(r.complexity.by).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", "))})">complexity <b>${r.complexity.true} → ${r.complexity.found}</b>${r.complexity.extra ? ` <span class="muted">(${r.complexity.extra > 0 ? "+" : ""}${r.complexity.extra})</span>` : ""}</span>` : ""}
      ${r ? `<span class="muted small">${r.seconds !== null && r.seconds !== undefined ? `${fmt(r.seconds)} s · ` : ""}${esc(when(r.at))} · strategy ${esc(short(r.strategy_hash))} · scorer ${esc(short(r.score_hash))}</span>` : ""}
    </div>`;
  }

  if (window.SDLadderBoard) window.SDLadderBoard.init({ strategies: () => S.strategies, drawPair, diffHtml, compareOf, legend: () => LEGEND, open: (sel) => pick(sel), drawHtml });

  // the verdicts come from the server's diff (compareOf: diff.py), the page's own comparison only if that fails
  async function renderCompare(c, r, err) {
    const my = (S.rctoken = (S.rctoken || 0) + 1);
    const cmp = await compareOf(c, r);
    if (my !== S.rctoken) return;
    $("cmp-head").innerHTML = `<div class="casehead">
        <div class="nowstrat" title="The strategy whose result this is">${esc((r && r.strategy) || S.sel.strategy || "")}<span class="nowvar"> · ${esc((r && r.variant) || S.sel.variant || "")}</span></div>
        <h2 class="ctitle2">${esc(c.id)} <span>${esc(c.title)}</span></h2>
        <span class="muted small">level ${esc(c.level)} · ${c.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join(" ")}</span>
        <p class="tests">Tests: ${esc(c.tests)}</p>${drawHtml(c)}
      </div>
      ${S.focusRunning && S.follow ? `<p class="note discrunning">Running now: ${r ? "showing its previous result until it finishes." : "no earlier result."}</p>` : ""}
      ${err ? `<p class="note error">${esc(err.message)}</p>` : ""}
      ${scoreTable(r)}`;
    $("found-cap").textContent = r ? `Found by ${r.strategy}` : `Found by ${S.sel.strategy}: not run yet`;
    const { alias } = drawPair(c, r, $("d-true"), $("d-found"), cmp, innerWidth >= 900 ? 2 : null, $("d-diff"));
    $("dpair").classList.toggle("stack", innerWidth < 900);
    $("dlegend").innerHTML = LEGEND + Object.entries(alias).filter(([id, n]) => id !== n).map(([id, n]) => ` · <span class="mono">${esc(n)} = ${esc(id)}</span>`).join("");
    $("dlist").innerHTML = r ? `${diffHtml(cmp)}<p class="bexplain">${esc(L.explain(r.scores))}</p>` : "";
    $("cmp-body").innerHTML = equationsHtml(c, cmp, r);
  }

  function equationsHtml(c, cmp, r, sel = S.sel) {
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
      </details>` : `<p class="note">${esc(sel.strategy || "This strategy")} has not run on ${esc(c.id)} ${esc(sel.variant)} yet: <code>uv run sdlab-ladder run --strategies ${esc(sel.strategy || "")} --cases ${esc(c.id.slice(0, 3))} --variants ${esc(sel.variant)}</code></p>`}`;
  }

  // ---------- Matrix ----------
  function renderMatrix() {
    const sm = S.summary; if (!sm) return;
    const strats = matrixStrategies(sm);
    renderMatrixControls(sm, strats);
    $("matrix-note").innerHTML = `Each cell has one square per variant, in the order ${S.cases[0] ? S.cases[0].variants.map((v) => `<code>${esc(v.name)}</code>`).join(", ") : ""}. Click a square (or a cell) to open it in <a href="#" data-goto="now">Now</a>. Hover a case for what it tests.`;
    $("mlegend").innerHTML = [["pass", "P pass"], ["equivalent", "E equivalent"], ["fail", "F fail"], ["error", "X error"], ["timeout", "T timeout"], ["none", "· not run"]].map(([k, w]) => `<span><span class="sq st-${k} demo">${w[0]}</span>${esc(w.slice(2))}</span>`).join("")
      + `<span><span class="sq st-pass stale demo">P</span>stale (a sync would run it again)</span>`
      + `<span><span class="sq st-fail an-data-limited demo">F</span>data-limited (even the best method rarely meets the tolerance)</span>`
      + `<span><span class="sq st-fail an-unidentifiable demo">F</span>unidentifiable (only an equivalent model is possible)</span>`;
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

  // a draw of a parametric case: its drawn numbers, as the lines of the case they went into
  function drawHtml(c) {
    const d = c && c.draw; if (!d) return "";
    const lines = [...new Set((d.values || []).map((v) => v.line))];
    const tip = (d.values || []).map((v) => `${esc(v.label)}: ${esc(v.value)} (drawn from [${esc(v.lo)}, ${esc(v.hi)}]${v.log ? ", log" : ""}${v.int ? ", whole" : ""})`).join("<br>")
      + ((d.rejected || []).length ? `<br>${d.rejected.length} earlier attempt(s) failed the case checks and were drawn again` : "");
    return `<p class="drawn small" data-tip="${esc(tip)}"><b>Draw ${esc(d.i)} of ${esc(d.of)}</b> of ${esc(d.base)}: ${lines.map((l) => `<code>${esc(l)}</code>`).join(" ")} <span class="muted">(sdlab-ladder freeze ${esc(c.id)} makes it a fixed case)</span></p>`;
  }

  // ---------- Cases ----------
  // The list: each case coloured by how many strategies pass it (/api/ladder/casestats, case_stats.py: a
  // strategy passes a case when every variant it ran passes), filtered by text, tags (all of them),
  // status and set, sorted by the ladder's order, level or pass rate.
  const CSTATUS = [["all", "all"], ["pass", "passing"], ["mixed", "mixed"], ["fail", "failing"], ["none", "not run"]];
  const CSETS = [["all", "every set"], ["tests", "Tests"], ["kubernetes", "Kubernetes"], ["realistic", "Realistic"], ["physics", "Physics"], ["real", "Real data"]];
  const CSORTS = [["ladder", "ladder order"], ["level", "level"], ["rate-up", "pass rate, lowest first"], ["rate-down", "pass rate, highest first"]];
  async function loadCaseStats() {
    try {
      const v = (await get("/api/ladder/version")).version;
      if (S.cstats && S.cstats.version === v) return false;
      const m = await get("/api/ladder/casestats"), by = {};
      m.rows.forEach((r) => { const x = {}; m.fields.forEach((f, i) => { x[f] = r[i]; }); by[x.case] = x; });
      S.cstats = { version: m.version, strategies: m.strategies, by };
      return true;
    } catch (e) { setStatus(`case stats: ${e.message}`, true); return false; }
  }
  // green: at least half the strategies that ran it pass; amber: some (1-49%); red: none; grey: none ran it
  function caseClass(x) {
    if (!x || !x.ran) return "none";
    const r = x.pass / x.ran;
    return r >= 0.5 ? "pass" : r > 0 ? "mixed" : "fail";
  }
  function caseRate(x) { return x && x.ran ? x.pass / x.ran : null; }
  function caseSummary(x) {
    const n = S.cstats ? S.cstats.strategies : 0;
    if (!S.cstats) return `<span class="csum muted">…</span>`;
    if (!x || !x.ran) return `<span class="csum muted">not run by any of ${n} strategies</span>`;
    const t = { total: n, pass: x.pass, equivalent: x.equivalent, fail: x.fail, error: x.other, missing: n - x.ran };
    const tipTxt = `<b>${esc(x.case)}</b>: of the ${x.ran} strategies that ran it (of ${n}), ${x.pass} pass every variant they ran, ${x.equivalent} are equivalent, ${x.fail} fail, ${x.other} error or time out${n - x.ran ? `; ${n - x.ran} have not run it` : ""}<br>cells (variant × strategy): ${x.cells_pass} of ${x.cells_run} run pass, ${x.cells - x.cells_run} not run`;
    return `<span class="csum" data-tip="${esc(tipTxt)}"><span class="crate">${Math.round(100 * x.pass / x.ran)}% of ${x.ran} pass</span>${x.equivalent ? `<span class="muted"> · ${x.equivalent} ≈</span>` : ""}<span class="sbar">${["pass", "equivalent", "fail", "error"].map((k) => t[k] ? `<span class="st-${k}" style="flex:${t[k]}"></span>` : "").join("")}${t.missing ? `<span class="st-none" style="flex:${t.missing}"></span>` : ""}</span></span>`;
  }
  function caseList() {
    const q = (S.cfilter || "").toLowerCase(), tags = S.ctags || [], st = S.cstatus || "all", set = S.cset || "all";
    const by = (S.cstats && S.cstats.by) || {};
    const inSet = (c) => { const x = by[c.id]; return set === "all" || (x && (set === "kubernetes" ? x.kubernetes : x.set === set)); };
    const base = S.cases.filter((c) => tags.every((t) => c.tags.includes(t)) && inSet(c) && (!q || `${c.id} ${c.title} ${c.tests} ${c.tags.join(" ")}`.toLowerCase().includes(q)));
    const counts = { all: base.length, pass: 0, mixed: 0, fail: 0, none: 0 };
    base.forEach((c) => { counts[caseClass(by[c.id])] += 1; });
    let list = st === "all" ? base : base.filter((c) => caseClass(by[c.id]) === st);
    const order = new Map(S.cases.map((c, i) => [c.id, i]));
    const rate = (c) => caseRate(by[c.id]);
    if (S.csort === "level") list = [...list].sort((a, b) => a.level - b.level || order.get(a.id) - order.get(b.id));
    if (S.csort === "rate-up" || S.csort === "rate-down") {
      const d = S.csort === "rate-up" ? 1 : -1;
      list = [...list].sort((a, b) => (rate(a) === null) - (rate(b) === null) || d * ((rate(a) || 0) - (rate(b) || 0)) || a.level - b.level || order.get(a.id) - order.get(b.id));
    }
    return { list, counts };
  }
  function renderCases() {
    if (!S.cstats) loadCaseStats().then((changed) => { if (changed && S.view === "cases") renderCaseCards(); });
    if (S.ctag) { S.ctags = [S.ctag]; S.ctag = null; }                 // from the matrix's per-tag table
    if (!S.csel.case || !S.byId[S.csel.case]) S.csel.case = (caseList().list[0] || S.cases[0] || {}).id;
    const legend = `<div class="clegend small"><span><i class="cs-pass"></i>≥ 50% pass</span><span><i class="cs-mixed"></i>1–49%</span><span><i class="cs-fail"></i>0%</span><span><i class="cs-none"></i>not run</span>
      <span class="muted" data-tip="A strategy passes a case when every variant it ran passes. The rate is over the strategies that ran the case; equivalent (≈) is shown, not counted as a pass.">of the strategies that ran it ⓘ</span></div>`;
    $("clist").innerHTML = `<div class="cfilters">
      <input id="cfind" type="search" placeholder="Find a case" value="${esc(S.cfilter || "")}" aria-label="Find a case">
      <div class="tagpick" id="tagpick"><span id="tagchips"></span><input id="tagin" type="text" placeholder="Add a tag…" autocomplete="off" aria-label="Filter by tag" aria-autocomplete="list" aria-controls="tagsugg"><div class="tagsugg" id="tagsugg" role="listbox" hidden></div></div>
      <div class="chips cstatus-btns" role="group" aria-label="Status" id="cstatus"></div>
      <div class="cselects"><label class="small">Set <select id="cset">${CSETS.map(([k, w]) => `<option value="${k}" ${(S.cset || "all") === k ? "selected" : ""}>${w}</option>`).join("")}</select></label>
        <label class="small">Sort <select id="csort">${CSORTS.map(([k, w]) => `<option value="${k}" ${(S.csort || "ladder") === k ? "selected" : ""}>${w}</option>`).join("")}</select></label></div>
      ${legend}</div>
      <div class="ccards" id="ccards"></div>`;
    $("cfind").oninput = (e) => { S.cfilter = e.target.value; renderCaseCards(); };
    $("cset").onchange = (e) => { S.cset = e.target.value; renderCaseCards(); };
    $("csort").onchange = (e) => { S.csort = e.target.value; renderCaseCards(); };
    wireTagPick();
    renderCaseCards();
    remember();
    renderCase();
  }
  function renderCaseCards() {
    if (!$("ccards")) return;
    const { list, counts } = caseList(), by = (S.cstats && S.cstats.by) || {};
    if (S.view === "cases") remember();
    const head = document.querySelector("#cdetail .cdsum");               // the open case's line, once the numbers are here
    if (head && S.csel.case) { head.className = `cdsum cs-${caseClass(by[S.csel.case])}`; head.innerHTML = caseSummary(by[S.csel.case]); }
    $("cstatus").innerHTML = CSTATUS.map(([k, w]) => `<button class="chip${(S.cstatus || "all") === k ? " on" : ""}" data-cst="${k}" aria-pressed="${(S.cstatus || "all") === k}">${k !== "all" ? `<i class="cs-${k}"></i>` : ""}${w} <span class="muted">${counts[k]}</span></button>`).join("");
    $("cstatus").querySelectorAll("[data-cst]").forEach((b) => (b.onclick = () => { S.cstatus = b.dataset.cst; renderCaseCards(); }));
    $("tagchips").innerHTML = (S.ctags || []).map((t) => `<span class="tagchip">${esc(t)}<button data-untag="${esc(t)}" aria-label="Remove tag ${esc(t)}" title="Remove">×</button></span>`).join("");
    $("tagchips").querySelectorAll("[data-untag]").forEach((b) => (b.onclick = () => { S.ctags = (S.ctags || []).filter((t) => t !== b.dataset.untag); renderCaseCards(); }));
    $("ccards").innerHTML = list.map((c) => {
      const x = by[c.id];
      return `<button class="card ccard cs-${caseClass(x)}${c.id === S.csel.case ? " on" : ""}" data-case="${esc(c.id)}">
        <span class="ctitle">${esc(c.id)} <span class="muted">· level ${esc(c.level)}</span></span><span class="cverdict">${esc(c.title)}</span>${caseSummary(x)}<span class="cstatus">${esc(c.tags.join(", "))}</span></button>`;
    }).join("") || '<p class="empty">No case matches.</p>';
    $("ccards").querySelectorAll("[data-case]").forEach((b) => (b.onclick = () => {
      S.csel.case = b.dataset.case; S.csel.run = null; remember();
      $("ccards").querySelectorAll(".ccard.on").forEach((o) => o.classList.remove("on")); b.classList.add("on");
      renderCase();
    }));
  }
  // tags: type to get suggestions (with how many cases carry each), Enter or a click adds one, × or
  // Backspace in the empty box removes one; a case must carry every chosen tag
  function wireTagPick() {
    const inp = $("tagin"), box = $("tagsugg");
    let hits = [], at = 0, counts = {};
    const show = () => {
      counts = {};                                     // how many of the cases listed now carry each tag
      caseList().list.forEach((c) => c.tags.forEach((t) => { counts[t] = (counts[t] || 0) + 1; }));
      const q = inp.value.trim().toLowerCase(), have = new Set(S.ctags || []);
      hits = Object.keys(counts).filter((t) => !have.has(t) && (!q || t.toLowerCase().includes(q)))
        .sort((a, b) => (q ? (b.toLowerCase().startsWith(q) - a.toLowerCase().startsWith(q)) : 0) || counts[b] - counts[a] || a.localeCompare(b)).slice(0, 12);
      at = Math.min(at, Math.max(0, hits.length - 1));
      box.innerHTML = hits.map((t, i) => `<div role="option" class="tsug${i === at ? " on" : ""}" aria-selected="${i === at}" data-add="${esc(t)}">${esc(t)} <span class="muted">${counts[t]}</span></div>`).join("") || `<div class="tsug muted">no tag matches</div>`;
      box.hidden = false;
      box.querySelectorAll("[data-add]").forEach((d) => (d.onmousedown = (e) => { e.preventDefault(); add(d.dataset.add); }));
    };
    const add = (t) => { S.ctags = [...(S.ctags || []), t]; inp.value = ""; at = 0; renderCaseCards(); show(); };
    inp.onfocus = show;
    inp.oninput = () => { at = 0; show(); };
    inp.onblur = () => { box.hidden = true; };
    inp.onkeydown = (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); at = Math.max(0, Math.min(hits.length - 1, at + (e.key === "ArrowDown" ? 1 : -1))); show(); }
      else if (e.key === "Enter") { e.preventDefault(); if (hits[at]) add(hits[at]); }
      else if (e.key === "Escape") { box.hidden = true; inp.blur(); }
      else if (e.key === "Backspace" && !inp.value && (S.ctags || []).length) { S.ctags = S.ctags.slice(0, -1); renderCaseCards(); show(); }
    };
  }
  // the open case's strategies: the competing ones first; eliminated ones (for a kubernetes case) and
  // retired ones, which are not run on new cases, folded away with why
  function caseStrategies(c) {
    const k8s = c.tags.includes("kubernetes");
    const out = (s) => k8s && s.eliminated && s.eliminated.kubernetes;
    const run = S.csel.run;
    const cell = (s, note) => `<span class="cst${run && run.strategy === s.name ? " on" : ""}"${note ? ` data-tip="${esc(note)}"` : ""}><span class="small">${esc(s.name)}</span> ${squares(c.id, s.name, run && run.strategy === s.name ? { current: run.variant } : {})}</span>`;
    const live = S.strategies.filter((s) => s.standing !== "retired" && !out(s));
    const elim = S.strategies.filter((s) => s.standing !== "retired" && out(s));
    const gone = S.strategies.filter((s) => s.standing === "retired");
    const fold = (list, title, note) => list.length ? `<details class="cfold"><summary class="small muted">${list.length} ${title}</summary><div class="cstrats">${list.map((s) => cell(s, note(s))).join("")}</div></details>` : "";
    return `<div class="cstrats">${live.map((s) => cell(s, s.standing === "parked" ? `parked: ${s.why}` : "")).join("")}</div>`
      + fold(elim, "eliminated from the kubernetes competition (not run on later rungs)", (s) => { const e = s.eliminated.kubernetes; return `eliminated at rung ${e.rung} (${e.kind}): ${e.reason}`; })
      + fold(gone, "retired strategies (not run on new cases)", (s) => `retired: ${s.why}`);
  }
  // one run of the open case (a square clicked): true, found and differences, its scores and equations
  function caseRunHtml() {
    const run = S.csel.run; if (!run) return "";
    return `<section class="crun" id="c-run" aria-label="The chosen run">
      <div class="crunhead"><h3>${esc(run.strategy)} <span class="muted">· ${esc(run.variant)}</span></h3>
        <span><button class="btn" id="c-run-now" title="Open this run on the Now page">Open in Now</button> <button class="btn" id="c-run-close" aria-label="Close the run">✕ Close</button></span></div>
      <div id="c-run-scores"><p class="note">Loading the result…</p></div>
      <div class="dpair three" id="c-dpair">
        <figure class="dpanel"><figcaption>True model</figcaption><svg id="c-true" role="img" aria-label="The true model"></svg></figure>
        <figure class="dpanel"><figcaption>Found by ${esc(run.strategy)}</figcaption><svg id="c-found" role="img" aria-label="The found model"></svg></figure>
        <figure class="dpanel"><figcaption>Differences</figcaption><svg id="c-diff" role="img" aria-label="The differences"></svg><p class="dcap" id="c-dlegend"></p></figure>
      </div>
      <div id="c-dlist"></div><div id="c-eq"></div></section>`;
  }
  async function showCaseRun(c) {
    const run = S.csel.run; if (!run || !$("c-run")) return;
    const my = (S.crtoken = (S.crtoken || 0) + 1);
    let r = null, err = null;
    try { r = await get(`/api/ladder/results/${enc(c.id)}/${enc(run.variant)}/${enc(run.strategy)}`); } catch (e) { if (e.status !== 404) err = e; }
    if (my !== S.crtoken || !$("c-run")) return;
    const cmp = await compareOf(c, r);
    if (my !== S.crtoken || !$("c-run")) return;
    $("c-run-scores").innerHTML = `${err ? `<p class="note error">${esc(err.message)}</p>` : ""}${scoreTable(r)}`;
    const { alias } = drawPair(c, r, $("c-true"), $("c-found"), cmp, innerWidth >= 900 ? 2 : null, $("c-diff"));
    $("c-dpair").classList.toggle("stack", innerWidth < 900);
    $("c-dlegend").innerHTML = LEGEND + Object.entries(alias).filter(([id, n]) => id !== n).map(([id, n]) => ` · <span class="mono">${esc(n)} = ${esc(id)}</span>`).join("");
    $("c-dlist").innerHTML = r ? `${diffHtml(cmp)}<p class="bexplain">${esc(L.explain(r.scores))}</p>` : "";
    $("c-eq").innerHTML = equationsHtml(c, cmp, r, run);
  }
  // The case's declared boundary (2026-10-20): per measured stock, its outside inflows and outflows and
  // their kinds, as announced to discovery; undeclared: outside flows are allowed as boundary claims.
  function boundaryHtml(c, measured) {
    const b = c.boundary;
    if (b === undefined || b === null) return `<p class="note boundary"><b>Boundary:</b> not declared <span class="muted small">(outside flows are allowed, as boundary claims)</span></p>`;
    const kinds = (xs) => xs.map((k) => (k === "measured" ? "measured input" : "to estimate")).join(", ");
    const side = (xs, word) => (xs && xs.length ? `${xs.length} outside ${word}${xs.length > 1 ? "s" : ""} (${esc(kinds(xs))})` : "");
    const rows = [...measured].map((id) => {
      const e = b[id] || {};
      const parts = [side(e.in, "inflow"), side(e.out, "outflow")].filter(Boolean);
      return `<li><b>${esc(id)}</b>: ${parts.length ? parts.join("; ") : `<span class="muted">none</span>`}</li>`;
    });
    return `<div class="note boundary"><b>Boundary</b> <span class="muted small">declared, announced to discovery: an outside flow anywhere else fails as an invented boundary</span>
      <ul class="boundary-list" style="margin:4px 0 0;padding-left:18px">${rows.join("")}</ul></div>`;
  }
  async function renderCase() {
    const c = S.byId[S.csel.case]; if (!c) { $("cdetail").innerHTML = ""; return; }
    if (!S.summary || !S.summary.covers(c.id)) await loadSummary(c.id);
    if (!c.variants.some((v) => v.name === S.csel.variant)) S.csel.variant = c.variants[0].name;
    const measured = new Set(c.model.stocks.filter((s) => s.measured !== false).map((s) => s.id));
    const flows = c.model.flows.map((f) => ({ flow: f, eq: L.equation(f, c.model.schedule) }));
    $("cdetail").innerHTML = `<div class="casehead"><h2 class="ctitle2">${esc(c.id)} <span>${esc(c.title)}</span></h2>
        <span class="muted small">level ${esc(c.level)} · ${c.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join(" ")} · hash ${esc(short(c.hash))}</span>
        <p class="tests">Tests: ${esc(c.tests)}</p>${drawHtml(c)}
        <div class="cdsum cs-${caseClass(S.cstats && S.cstats.by[c.id])}">${caseSummary(S.cstats && S.cstats.by[c.id])}</div></div>
      ${caseStrategies(c)}
      ${caseRunHtml()}
      <figure class="dpanel single"${S.csel.run ? " hidden" : ""}><figcaption>True model</figcaption><svg id="c-diagram" role="img" aria-label="The case's true model"></svg></figure>
      ${boundaryHtml(c, measured)}
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
      flows: c.model.flows.map((f) => ({ from: f.from, to: f.to, cls: "plain", label: f.id,
        cloud: c.boundary && ((!f.from && f.to && ((c.boundary[f.to] || {}).in || [])[0]) || (f.from && !f.to && ((c.boundary[f.from] || {}).out || [])[0])) || undefined, label2: short2(L.rateText(f.rate)), title: `${f.id}: ${L.equation(f, c.model.schedule)}`,
        reads: [...L.readers(f)].filter((x) => x !== "const" && x !== f.from).map((stock) => ({ stock }))
          .concat((f.effects || []).map((e) => ({ stock: e.stock, label: "effect", dash: "5 4", cls: "plain" })), (f.uses || []).map((u) => ({ stock: u.stock, label: `uses ${fmt(+u.per)}`, dash: "1 3", cls: "plain" }))) })),
    }, pos, { box: BOX, color: (k) => CLS_COLOR[k] || "var(--fg)", maxScale: 1.3, outline: { label: c.boundary ? "system boundary" : "boundary not declared" } });
    $("cdetail").querySelectorAll(".sq[data-case]").forEach((b) => (b.onclick = () => {
      S.csel.run = { strategy: b.dataset.strategy, variant: b.dataset.variant };
      S.csel.variant = b.dataset.variant;                                     // the data below: the run's variant
      remember(); renderCase().then(() => { const x = $("c-run"); if (x) x.scrollIntoView({ behavior: "smooth", block: "start" }); });
    }));
    if ($("c-run-close")) $("c-run-close").onclick = () => { S.csel.run = null; remember(); renderCase(); };
    if ($("c-run-now")) $("c-run-now").onclick = () => pick({ case: c.id, ...S.csel.run });
    showCaseRun(c);
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
      pollRuns(false);
      followTick(false);
      const done = S.progress.run ? `${S.progress.run.id}:${S.progress.run.done}` : null;
      if (done !== lastDone) {
        lastDone = done;
        // the board shows new results as a run makes them, at most every 10 seconds
        if (S.view === "now" && S.nowMode === "board" && window.SDLadderBoard && Date.now() - (S.boardAt || 0) > 10000) {
          S.boardAt = Date.now();
          window.SDLadderBoard.refresh();
        }
        if (S.view === "cases") loadCaseStats().then((changed) => { if (changed && S.view === "cases") renderCaseCards(); });
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
      if (S.view === "now" && S.nowMode === "board" && window.SDLadderBoard) window.SDLadderBoard.redraw();
      else if (S.view === "now" && S.shown !== undefined && S.sel.case) renderCompare(S.byId[S.sel.case], S.shown);
      if (S.view === "cases") renderCase();
      if (S.view === "history") renderHistory();
    }, 200);
  });

  // ---------- start ----------
  (async function start() {
    try {
      [S.cases, S.strategies] = await Promise.all([get("/api/ladder/cases"), get("/api/ladder/strategies")]);
    } catch (e) { setStatus(e.message, true); $("cmp-head").innerHTML = `<p class="note error">Could not load the ladder: ${esc(e.message)}</p>`; return; }
    S.cases.forEach((c) => { S.byId[c.id] = c; });
    const p = new URLSearchParams(location.search);
    const view = ["now", "matrix", "history", "cases"].includes(p.get("view")) ? p.get("view") : "now";
    if (view === "now" && p.get("case") && S.byId[p.get("case")]) {
      S.follow = false; S.nowMode = "one";
      S.sel = { case: p.get("case"), variant: p.get("variant"), strategy: p.get("strategy"), id: p.get("result") ? +p.get("result") : null };
    }
    if (view === "history") S.hsel = { case: S.byId[p.get("case")] ? p.get("case") : null, strategy: p.get("strategy") };
    if (view === "cases") {
      if (S.byId[p.get("case")]) S.csel.case = p.get("case");
      const [rs, rv] = (p.get("run") || "").split(":");
      if (rs && rv && S.csel.case && S.byId[S.csel.case].variants.some((v) => v.name === rv)) { S.csel.run = { strategy: rs, variant: rv }; S.csel.variant = rv; }
      const pick = (k, opts) => (opts.some(([v]) => v === p.get(k)) ? p.get(k) : undefined);
      S.cfilter = p.get("q") || "";
      S.ctags = (p.get("tags") || "").split(",").filter(Boolean);
      S.cstatus = pick("status", CSTATUS); S.cset = pick("set", CSETS); S.csort = pick("sort", CSORTS);
    }
    try { S.progress = await get("/api/ladder/progress?recent=20"); } catch { S.progress = null; }
    // the matrix's numbers come in the background: the comparison does not wait for them
    if (view !== "matrix") loadSummary().then(() => { if (S.view === "now") renderPick(); });
    if (S.follow) followTick(true);
    setView(view);
    renderLive();
    pollRuns(true);
    lastDone = S.progress && S.progress.run ? `${S.progress.run.id}:${S.progress.run.done}` : null;
    setTimeout(poll, 1000);
  })();
})();
