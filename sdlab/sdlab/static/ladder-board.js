// The ladder page's all-cases view (the Now tab's default): every case on one page, the true model
// beside what one strategy found, with the error measures, a plain-language explanation and the
// verdict, for one variant or all four. ladder.js hands it its helpers (window.SDLadderPage).
(function () {
  "use strict";
  const L = window.SDLadder, D = window.SDDiagram, fmt = L.fmt;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v) => (v === null || v === undefined || !Number.isFinite(+v) ? "–" : `${(100 * v).toFixed(1)}%`);
  const ci = (c) => (Array.isArray(c) && c.length === 2 && c.every((x) => x !== null) ? ` <span class="muted">[${(100 * c[0]).toFixed(0)}, ${(100 * c[1]).toFixed(0)}]</span>` : "");
  const VARIANTS = ["none-short", "none-long", "counts-short", "counts-long"];
  const RANK = { fail: 0, error: 1, timeout: 1, equivalent: 2, pass: 3 };
  const DEF = {
    error: "Equation error: the share of the equations' numbers that are wrong: (true numbers missing + true numbers off + invented numbers) ÷ true numbers. 0% = the true equations, within tolerance.",
    recall: "Recall: true numbers the found model has (right kind and ends, whatever the value) ÷ all true numbers.",
    precision: "Precision: found numbers (large enough to count) that are true ÷ all of them.",
    rate: "Rate error: for the true numbers that were found, how far off the found value is, |found − true| ÷ |true|: the mean, and the worst.",
    spurious: "Spurious: found numbers the truth does not have (larger than 5% of a typical true flow), and their total size in things per step.",
    skill20: "Skill@20: how much of the true model's movement 20 steps ahead the found model predicts, from about 150 starting moments on the run it saw (100% = as good as the truth), with its 95% bootstrap interval.",
    skill100: "Skill@100: the same, 100 steps ahead.",
    fresh20: "Fresh skill@20: skill@20 on a fresh run (the next seed), which discovery never saw.",
    complexity: "Complexity: flows + the numbers needed to write their rates over the run (every piece of a rate that changes, effects' numbers, co-flows, hidden stocks), counted the same way for the true and the found model. Extra = found − true, by where it comes from.",
  };
  const cxText = (x) => !x ? "–" : `${x.true} → ${x.found}` + (x.extra ? ` (${x.extra > 0 ? "+" : ""}${x.extra}: ${Object.entries(x.by).filter(([, v]) => v).map(([k, v]) => `${v > 0 ? "+" : ""}${v} ${k}`).join(", ")})` : " (same)");
  const B = { strategy: null, variant: "counts-long", status: "", level: "", tag: "", sort: "level", data: null, tab: {}, loading: null };
  try { Object.assign(B, JSON.parse(localStorage.getItem("sdlab.ladder.board") || "{}"), { data: null, tab: {}, loading: null }); } catch { /* defaults */ }
  const save = () => { try { localStorage.setItem("sdlab.ladder.board", JSON.stringify({ strategy: B.strategy, variant: B.variant, status: B.status, level: B.level, tag: B.tag, sort: B.sort })); } catch { /* fine */ } };
  let P = null;                                            // the page's helpers
  let observer = null;

  async function load(force) {
    const q = `strategy=${encodeURIComponent(B.strategy || "")}&variant=${encodeURIComponent(B.variant)}`;
    if (!force && B.data && B.data.q === q) return B.data;
    const my = (B.loading = q);
    const r = await fetch(`/api/ladder/board?${B.strategy ? q : `variant=${encodeURIComponent(B.variant)}`}`);
    if (!r.ok) throw Object.assign(new Error(`board: ${r.status}`), { status: r.status });
    const d = await r.json();
    if (B.loading !== my) return B.data;
    if (!B.strategy) B.strategy = d.strategy;
    d.q = q;
    d.by = {};
    d.results.forEach((x) => { (d.by[x.case] || (d.by[x.case] = {}))[x.variant] = x; });
    B.data = d;
    return d;
  }

  function controls(d) {
    const strats = P.strategies().filter((s) => s.available);
    const levels = [...new Set(d.cases.map((c) => c.level))].sort((a, b) => a - b);
    const tags = [...new Set(d.cases.flatMap((c) => c.tags))].sort();
    const opt = (v, w, cur) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${esc(w)}</option>`;
    $("board-controls").innerHTML = `
      <label>Strategy <select id="b-strat">${strats.map((s) => opt(s.name, s.name === d.best ? `${s.name} (best pass rate)` : s.name, B.strategy)).join("")}</select></label>
      <label>Variant <select id="b-var">${[...VARIANTS.map((v) => [v, v]), ["all", "all four (tabs)"]].map(([v, w]) => opt(v, w, B.variant)).join("")}</select></label>
      <label>Verdict <select id="b-status">${[["", "any"], ["pass", "pass"], ["equivalent", "equivalent"], ["fail", "fail"], ["error", "error / timeout"], ["none", "not run"]].map(([v, w]) => opt(v, w, B.status)).join("")}</select></label>
      <label>Level <select id="b-level">${opt("", "any", B.level)}${levels.map((l) => opt(l, `level ${l}`, B.level)).join("")}</select></label>
      <label>Tag <select id="b-tag">${opt("", "any", B.tag)}${tags.map((t) => opt(t, t, B.tag)).join("")}</select></label>
      <label>Sort <select id="b-sort">${[["level", "by level"], ["status", "worst verdict first"], ["error", "largest error first"]].map(([v, w]) => opt(v, w, B.sort)).join("")}</select></label>
      <a class="btn" href="/ladder/leaderboard" title="Every strategy ranked by pass rate, recall, precision and skill">&#127942; Leaderboard</a>`;
    const on = (id, k, reload) => ($(id).onchange = (e) => { B[k] = e.target.value; save(); if (reload) B.tab = {}; render(reload); });
    on("b-strat", "strategy", true); on("b-var", "variant", true); on("b-status", "status"); on("b-level", "level"); on("b-tag", "tag"); on("b-sort", "sort");
  }

  // the result a card shows: its variant, or with all four, the tab picked (default: the worst)
  function shown(c, d) {
    const rs = d.by[c.id] || {};
    if (B.variant !== "all") return rs[B.variant] || null;
    const pickV = B.tab[c.id] || [...VARIANTS].filter((v) => rs[v]).sort((a, b) => (RANK[rs[a].status] ?? 9) - (RANK[rs[b].status] ?? 9))[0];
    return pickV ? rs[pickV] : null;
  }

  function summary(rows) {
    const rs = rows.map((x) => x.r).filter(Boolean), n = rows.length;
    const count = (st) => rs.filter((r) => r.status === st).length;
    const ms = rs.map((r) => L.measures(r.scores));
    const mean = (k) => { const v = ms.map((m) => m[k]).filter((x) => x !== null && Number.isFinite(x)); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    const clipMean = (k) => { const v = ms.map((m) => m[k]).filter((x) => x !== null && Number.isFinite(x)).map((x) => Math.max(-1, x)); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
    const bar = ["pass", "equivalent", "fail", "error", "timeout"].map((k) => count(k) ? `<span class="seg st-${k}" style="flex:${count(k)}" data-tip="${count(k)} ${k}"></span>` : "").join("")
      + (n - rs.length ? `<span class="seg queued" style="flex:${n - rs.length}" data-tip="${n - rs.length} not run"></span>` : "");
    $("board-sum").innerHTML = `<div class="bsum">
        <span class="bsum-v"><span class="stbadge st-pass">${count("pass")} pass</span> <span class="stbadge st-equivalent">${count("equivalent")} equivalent</span> <span class="stbadge st-fail">${count("fail")} fail</span>${count("error") + count("timeout") ? ` <span class="stbadge st-error">${count("error") + count("timeout")} error</span>` : ""}${n - rs.length ? ` <span class="stbadge st-none">${n - rs.length} not run</span>` : ""} <span class="muted small">of ${n} shown</span></span>
        <span data-tip="${esc(DEF.error)}">equation error <b>${pct(mean("errorScore"))}</b></span>
        <span data-tip="${esc(DEF.recall)}">recall <b>${pct(mean("recall"))}</b></span>
        <span data-tip="${esc(DEF.precision)}">precision <b>${pct(mean("precision"))}</b></span>
        <span data-tip="${esc(DEF.rate)}">rate error <b>${pct(mean("rateMean"))}</b></span>
        <span data-tip="${esc(DEF.skill20)} Means clip each run at −100%.">skill@20 <b>${pct(clipMean("skill20"))}</b></span>
        <span data-tip="${esc(DEF.fresh20)}">fresh@20 <b>${pct(clipMean("fresh20"))}</b></span>
      </div><div class="pbar">${bar}</div>`;
  }

  function cardHtml(c, r, d) {
    const m = r ? L.measures(r.scores) : null, st = r ? r.status : null;
    const rs = d.by[c.id] || {};
    const tabs = B.variant === "all" ? `<span class="btabs" role="tablist" aria-label="Variant">${VARIANTS.map((v) => {
      const x = rs[v], on = r && r.variant === v;
      return `<button role="tab" aria-selected="${on}" class="btab${on ? " on" : ""}" data-tab="${esc(v)}"><span class="sq st-${x ? x.status : "none"}">${x ? x.status[0].toUpperCase() : "·"}</span>${esc(v)}</button>`;
    }).join("")}</span>` : "";
    const worst = m && m.rateWorst ? `, ${pct(m.rateMax)} at worst (${esc(m.rateWorst)})` : "";
    const meas = m ? `<dl class="bmeas">
        <div data-tip="${esc(DEF.recall)}"><dt>recall</dt><dd>${pct(m.recall)}</dd></div>
        <div data-tip="${esc(DEF.precision)}"><dt>precision</dt><dd>${pct(m.precision)}</dd></div>
        <div data-tip="${esc(DEF.rate)}" class="wide"><dt>rate error</dt><dd>${m.rateMean === null ? "–" : `${pct(m.rateMean)} on average${worst}`}</dd></div>
        <div data-tip="${esc(DEF.spurious)}"><dt>spurious</dt><dd>${m.spurious}${m.spurious ? `, ${fmt(m.spuriousSize)}/step` : ""}</dd></div>
        <div data-tip="${esc(DEF.skill20)}"><dt>skill@20</dt><dd>${pct(m.skill20)}${ci(m.skill20ci)}</dd></div>
        <div data-tip="${esc(DEF.skill100)}"><dt>skill@100</dt><dd>${pct(m.skill100)}${ci(m.skill100ci)}</dd></div>
        <div data-tip="${esc(DEF.fresh20)}"><dt>fresh@20</dt><dd>${pct(m.fresh20)}</dd></div>
        <div data-tip="${esc(DEF.complexity)}" class="wide"><dt>complexity true → found</dt><dd>${esc(cxText(r.complexity))}</dd></div>
      </dl>` : "";
    return `<article class="bcard st-${st || "none"}" data-case="${esc(c.id)}">
      <header class="bhead">
        <button class="btitle" data-open title="Open the full comparison: every part, the equations side by side"><span class="mono">${esc(c.id.slice(0, 3))}</span> ${esc(c.title)}</button>
        <span class="stbadge st-${st || "none"}">${st ? esc(st) : "not run"}</span>
        ${m && m.errorScore !== null ? `<span class="berr" data-tip="${esc(DEF.error)}"><b>${pct(m.errorScore)}</b><small>equation error${m.of ? ` · ${m.missing + m.off + m.spurious} of ${m.of}` : ""}</small></span>` : ""}
      </header>
      <p class="tests">Tests: ${esc(c.tests)} <span class="muted small">level ${esc(c.level)} · ${esc(c.tags.join(", "))}</span></p>
      ${tabs}
      <div class="bdiag" data-draw="${esc(c.id)}"><figure class="dpanel"><figcaption>True model</figcaption><svg role="img" aria-label="The true model"></svg></figure><figure class="dpanel"><figcaption>${r ? `Found by ${esc(r.strategy)} · ${esc(r.variant)}` : "Not run"}</figcaption><svg role="img" aria-label="The found model"></svg></figure><figure class="dpanel"><figcaption>Differences</figcaption><svg role="img" aria-label="The differences"></svg><p class="dcap">${P.legend()}</p></figure></div>
      ${r && r.found ? P.diffHtml(c, r) : ""}
      ${r ? `<p class="bexplain">${esc(L.explain(r.scores) || (r.error ? `Error: ${String(r.error).slice(0, 200)}` : ""))}</p>` : `<p class="bexplain muted">${esc(B.strategy)} has not run on this case${B.variant === "all" ? "" : ` in ${esc(B.variant)}`} yet.</p>`}
      ${meas}
    </article>`;
  }

  function draw(el) {
    const d = B.data, c = d && d.cases.find((x) => x.id === el.dataset.draw); if (!c) return;
    const r = shown(c, d);
    const svgs = el.querySelectorAll("svg");
    P.drawPair(c, r, svgs[0], svgs[1], null, 2, svgs[2]);     // compact: two columns, wrapped
    el.dataset.drawn = "1";
  }

  async function render(reload) {
    const box = $("board");
    if (!B.data || reload) box.innerHTML = `<p class="note">Loading every case…</p>`;
    let d;
    try { d = await load(!!reload); } catch (e) {
      box.innerHTML = `<p class="note error">Could not load the cases: ${esc(e.message)}</p>`;
      return false;
    }
    controls(d);
    let rows = d.cases.map((c) => ({ c, r: shown(c, d) }));
    rows = rows.filter(({ c, r }) => (!B.level || String(c.level) === String(B.level)) && (!B.tag || c.tags.includes(B.tag))
      && (!B.status || (B.status === "none" ? !r : B.status === "error" ? r && (r.status === "error" || r.status === "timeout") : r && r.status === B.status)));
    const err = (r) => { const m = r && L.measures(r.scores); return m && m.errorScore !== null ? m.errorScore : -1; };
    if (B.sort === "status") rows.sort((a, b) => (a.r ? RANK[a.r.status] ?? 9 : 10) - (b.r ? RANK[b.r.status] ?? 9 : 10) || a.c.level - b.c.level);
    else if (B.sort === "error") rows.sort((a, b) => err(b.r) - err(a.r) || a.c.level - b.c.level);
    else rows.sort((a, b) => a.c.level - b.c.level || a.c.id.localeCompare(b.c.id));
    summary(rows);
    box.innerHTML = rows.map(({ c, r }) => cardHtml(c, r, d)).join("") || `<p class="note">No case matches.</p>`;
    if (observer) observer.disconnect();
    const els = [...box.querySelectorAll("[data-draw]")];
    if ("IntersectionObserver" in window) {
      observer = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { observer.unobserve(e.target); draw(e.target); } }), { rootMargin: "400px 0px" });
      els.forEach((el) => observer.observe(el));
    } else els.forEach(draw);
    box.onclick = (e) => {                                   // one listener: cards are replaced in place
      const card = e.target.closest("[data-case]"); if (!card) return;
      const id = card.dataset.case, c = d.cases.find((x) => x.id === id);
      const tab = e.target.closest("[data-tab]");
      if (tab) {
        B.tab[id] = tab.dataset.tab;
        card.outerHTML = cardHtml(c, shown(c, d), d);
        draw(box.querySelector(`[data-case="${CSS.escape(id)}"] [data-draw]`));
        return;
      }
      if (e.target.closest("[data-open]")) {
        const r = shown(c, d);
        P.open({ case: id, variant: r ? r.variant : (B.variant === "all" ? "counts-long" : B.variant), strategy: B.strategy });
      }
    };
    return true;
  }

  window.SDLadderBoard = {
    init(page) { P = page; },
    render,
    // during a run: fetch again, and redraw only when this strategy's results changed
    async refresh() {
      const sig = (d) => (d ? d.results.map((r) => r.id).join() : "");
      const before = sig(B.data);
      try { await load(true); } catch { return false; }
      return sig(B.data) === before ? true : render(false);
    },
    redraw() { document.querySelectorAll("#board [data-draw][data-drawn]").forEach(draw); },
    get strategy() { return B.strategy; },
  };
})();
