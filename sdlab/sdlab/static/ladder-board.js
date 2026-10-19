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
  const B = { strategy: null, variant: "counts-long", set: "tests", status: "", level: "", tag: "", sort: "level", data: null, tab: {}, loading: null };
  const isReal = (c) => !!(c.example || (c.tags || []).includes("realistic"));   // a realistic case: an example by reference (realistic.py)
  const isPhys = (c) => !!c.physics;                                                 // a physics case: an ODE solved in continuous time (physics/)
  const kindOf = (c) => (isReal(c) ? "realistic" : isPhys(c) ? "physics" : "tests");
  // a physics case runs none and meas (no counting noise): the counts variant picked reads as its meas variant
  const caseVariants = (c) => (isPhys(c) ? (c.variants || []).map((v) => v.name || v) : VARIANTS);
  const variantOf = (c, v) => (isPhys(c) && v !== "all" ? v.replace(/^counts-/, "meas-") : v);
  const PHYS = "Physics view: the found model's couplings (which stocks and inputs each stock's change reads, with sign and shape, from its Jacobian on the run) against the physics', and its fresh-run skill against the reference, the best model SD Lab's forms can write. Pass: the coupling graph and signs agree and fresh skill@20 is within 5 points of the reference's.";
  function physHtml(c, r) {
    const Ph = c.physics, ph = r && r.scores && r.scores.physics;
    const head = `<p class="tests"><b>Physics</b>: ${esc(Ph.about)}${Ph.differs ? ` <span class="muted">SD vs physics: ${esc(Ph.differs)}</span>` : ""}</p>`;
    if (!ph) return head;
    const shp = (x) => esc(x || "–");
    const rows = ph.couplings.map((x) => `<tr><td class="mono">${esc(x.key)}</td><td>${esc(x.sign_true)} ${shp(x.shape_true)}</td><td>${x.present ? `${esc(x.sign_found)} ${shp(x.shape_found)}` : "missing"}</td><td>${x.sign_ok ? "✓" : "✗"}${x.present && !x.shape_ok ? " <span class=\"muted\">shape</span>" : ""}</td></tr>`).join("")
      + ph.spurious.map((x) => `<tr><td class="mono">${esc(x.key)}</td><td>none</td><td>${esc(x.sign)} ${shp(x.shape)} (${pct(x.rel)} of the strongest)</td><td>✗ invented</td></tr>`).join("")
      + (ph.sampling || []).map((x) => `<tr><td class="mono">${esc(x.key)}</td><td>sampling only</td><td>${esc(x.sign)} ${shp(x.shape)}</td><td class="muted">allowed: the exact one-step map has it</td></tr>`).join("");
    const rb = (ph.reference || {}).behaviour || {}, sk = (b, h) => (((b || {}).fresh || {})[String(h)] || {}).skill;
    const lr = ph.longrun || {}, rl = (ph.reference || {}).longrun || {};
    return `${head}<table class="small" data-tip="${esc(PHYS)}"><tr><th>coupling</th><th>physics</th><th>found</th><th></th></tr>${rows}</table>
      <p class="small">fresh skill@20 <b>${pct(sk(r.scores.behaviour, 20))}</b> vs the reference's ${pct(sk(rb, 20))}; @100 <b>${pct(sk(r.scores.behaviour, 100))}</b> vs ${pct(sk(rb, 100))};
      long-run error (5,000 steps free) <b>${lr.diverges ? "diverges" : pct(lr.err)}</b> vs ${pct(rl.err)} <span class="muted">· reference: ${esc((ph.reference || {}).how || "")}</span></p>`;
  }
  const GOAL = "Meets the goal (as on the examples' bench): skill@20 at least 90% and skill@100 at least 80%; an error or timeout never does.";
  const meets = (r) => !!r && r.status !== "error" && r.status !== "timeout" && (() => { const m = L.measures(r.scores); return m.skill20 != null && m.skill100 != null && m.skill20 >= 0.9 && m.skill100 >= 0.8; })();
  try { Object.assign(B, JSON.parse(localStorage.getItem("sdlab.ladder.board") || "{}"), { data: null, tab: {}, loading: null }); } catch { /* defaults */ }
  {                                                        // a link (e.g. from the leaderboard): /ladder?view=now&strategy=S[&variant=V]
    const q = new URLSearchParams(location.search);
    if ((q.get("view") || "now") === "now" && !q.get("case") && q.get("strategy")) {
      Object.assign(B, { strategy: q.get("strategy"), variant: q.get("variant") || "all", set: q.get("set") || "tests", status: "", level: "", tag: "" });
    }
  }
  const save = () => { try { localStorage.setItem("sdlab.ladder.board", JSON.stringify({ strategy: B.strategy, variant: B.variant, set: B.set, status: B.status, level: B.level, tag: B.tag, sort: B.sort })); } catch { /* fine */ } };
  let P = null;                                            // the page's helpers
  let aboutOpen = false;                                   // the strategy explanation's "how it works" expanded

  // the selected strategy in plain language (explanations.yaml, via /api/ladder/strategies' "about")
  function aboutHtml(s) {
    const a = s && s.about;
    if (!a) return `<div class="babout muted">No explanation of ${esc(B.strategy)} yet. <a href="/ladder/glossary">Glossary</a></div>`;
    return `<div class="babout"><p><b>${esc(s.name)}</b> <span class="muted">(${esc(a.status)})</span>: ${esc(a.idea)}</p>
      <details${aboutOpen ? " open" : ""}><summary>How it works</summary><p>${esc(a.how)}</p>
        <p><span class="muted">Meant for:</span> ${esc(a.helps_with)}</p><p><span class="muted">Builds on:</span> ${esc(a.builds_on)}</p>
        ${a.note ? `<p class="muted">${esc(a.note)}</p>` : ""}</details>
      <a href="/ladder/glossary#s-${encodeURIComponent(s.name)}" title="Every strategy and the words the ladder uses, in plain language">Glossary</a></div>`;
  }
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
      <label data-tip="Tests: the ladder's tiny true models. Realistic: SD Lab's example models (sdlab/examples/sd-*), as on the examples' bench, where behaviour (skill, the goal) is the headline. Physics: physical systems solved in continuous time (no SD truth), against their physics and the best SD model; their counts variants read as meas.">Set <select id="b-set">${[["tests", "tests"], ["realistic", "realistic examples"], ["physics", "physics"], ["all", "all"]].map(([v, w]) => opt(v, w, B.set)).join("")}</select></label>
      <label>Verdict <select id="b-status">${[["", "any"], ["pass", "pass"], ["equivalent", "equivalent"], ["fail", "fail"], ["error", "error / timeout"], ["none", "not run"]].map(([v, w]) => opt(v, w, B.status)).join("")}</select></label>
      <label>Level <select id="b-level">${opt("", "any", B.level)}${levels.map((l) => opt(l, `level ${l}`, B.level)).join("")}</select></label>
      <label>Tag <select id="b-tag">${opt("", "any", B.tag)}${tags.map((t) => opt(t, t, B.tag)).join("")}</select></label>
      <label>Sort <select id="b-sort">${[["level", "by level"], ["status", "worst verdict first"], ["error", "largest error first"]].map(([v, w]) => opt(v, w, B.sort)).join("")}</select></label>
      <a class="btn" href="/ladder/strategy?name=${encodeURIComponent(B.strategy || "")}" title="How this strategy behaves: its history, and per case what would make its model right">Strategy page</a>
      <a class="btn" href="/ladder/leaderboard" title="Every strategy ranked by pass rate, recall, precision and skill">&#127942; Leaderboard</a>
      ${aboutHtml(strats.find((s) => s.name === B.strategy))}`;
    const det = $("board-controls").querySelector(".babout details");
    if (det) det.ontoggle = () => { aboutOpen = det.open; };
    const on = (id, k, reload) => ($(id).onchange = (e) => { B[k] = e.target.value; save(); if (reload) B.tab = {}; render(reload); });
    on("b-strat", "strategy", true); on("b-var", "variant", true); on("b-set", "set"); on("b-status", "status"); on("b-level", "level"); on("b-tag", "tag"); on("b-sort", "sort");
  }

  // the result a card shows: its variant, or with all four, the tab picked (default: the worst)
  function shown(c, d) {
    const rs = d.by[c.id] || {};
    if (B.variant !== "all") return rs[variantOf(c, B.variant)] || null;
    const pickV = B.tab[c.id] || [...caseVariants(c)].filter((v) => rs[v]).sort((a, b) => (RANK[rs[a].status] ?? 9) - (RANK[rs[b].status] ?? 9))[0];
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
        ${rows.some(({ c }) => isReal(c)) ? `<span data-tip="${esc(GOAL)}">goals met <b>${rows.filter(({ c, r }) => isReal(c) && meets(r)).length}</b> of ${rows.filter(({ c }) => isReal(c)).length}</span>` : ""}
        ${rows.some(({ c }) => isPhys(c)) ? `<span data-tip="${esc(PHYS)}">physics structure agrees <b>${rows.filter(({ c, r }) => isPhys(c) && r && r.scores && r.scores.physics && r.scores.physics.structure_ok).length}</b> of ${rows.filter(({ c }) => isPhys(c)).length}</span>` : ""}
      </div><div class="pbar">${bar}</div>`;
  }

  function cardHtml(c, r, d) {
    const m = r ? L.measures(r.scores) : null, st = r ? r.status : null;
    const rs = d.by[c.id] || {};
    const tabs = B.variant === "all" ? `<span class="btabs" role="tablist" aria-label="Variant">${caseVariants(c).map((v) => {
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
        <div data-tip="The true and found models run free from the start to t = 100,000 (no re-anchoring): line graphs per stock, equilibrium, time constants, divergence." class="wide"><dt>long run</dt><dd><a href="/ladder/run?id=${r.id}" style="color:inherit">&#128200; true vs found, far ahead</a></dd></div>
      </dl>` : "";
    return `<article class="bcard st-${st || "none"}" data-case="${esc(c.id)}">
      <header class="bhead">
        <button class="btitle" data-open title="Open the full comparison: every part, the equations side by side"><span class="mono">${esc(isReal(c) || isPhys(c) ? c.id : c.id.slice(0, 3))}</span> ${esc(c.title)}</button>
        <span class="stbadge st-${st || "none"}">${st ? esc(st) : "not run"}</span>
        ${isReal(c) && r ? `<span class="stbadge st-${meets(r) ? "pass" : "fail"}" data-tip="${esc(GOAL)}">${meets(r) ? "meets the goal" : "short of the goal"}</span>` : ""}
        ${m && m.errorScore !== null && !isPhys(c) ? `<span class="berr" data-tip="${esc(DEF.error)}"><b>${pct(m.errorScore)}</b><small>equation error${m.of ? ` · ${m.missing + m.off + m.spurious} of ${m.of}` : ""}</small></span>` : ""}
      </header>
      <p class="tests">Tests: ${esc(c.tests)} <span class="muted small">level ${esc(c.level)} · ${esc(c.tags.join(", "))}</span></p>
      ${isPhys(c) ? physHtml(c, r) : ""}
      ${P.drawHtml(c)}
      ${tabs}
      <div class="bdiag" data-draw="${esc(c.id)}"><figure class="dpanel"><figcaption>${isPhys(c) ? "Best SD model (reference)" : "True model"}</figcaption><svg role="img" aria-label="The true model"></svg></figure><figure class="dpanel"><figcaption>${r ? `Found by ${esc(r.strategy)} · ${esc(r.variant)}` : "Not run"}</figcaption><svg role="img" aria-label="The found model"></svg></figure><figure class="dpanel"><figcaption>Differences</figcaption><svg role="img" aria-label="The differences"></svg><p class="dcap">${P.legend()}</p></figure></div>
      ${r && r.found && !isPhys(c) ? P.diffHtml(c, r) : ""}
      ${r ? `<p class="bexplain">${esc((isPhys(c) && r.scores && r.scores.physics ? `${r.scores.physics.structure_ok ? "The coupling graph and signs agree with the physics" : "The coupling graph or signs differ from the physics"}; fresh skill@20 is ${r.scores.physics.near_reference ? "within 5 points of" : "more than 5 points below"} the reference's. ${(r.scores.notes || []).join(" ")}` : L.explain(r.scores)) || (r.error ? `Error: ${String(r.error).slice(0, 200)}` : ""))}</p>` : `<p class="bexplain muted">${esc(B.strategy)} has not run on this case${B.variant === "all" ? "" : ` in ${esc(B.variant)}`} yet.</p>`}
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
    rows = rows.filter(({ c, r }) => (B.set === "all" || B.set === kindOf(c)) && (!B.level || String(c.level) === String(B.level)) && (!B.tag || c.tags.includes(B.tag))
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
