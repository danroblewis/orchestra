// The strategy page (/ladder/strategy?name=S): how one strategy behaves, from the models it produced.
// Read only, over /api/ladder/strategy/{name} (strategy_view.py):
//   header     its explanation, pass rate, coverage, Occam, err@100k, the commit of its latest result
//   history    pass rate / coverage per version (code changes marked), and code changes per day; time per
//              cell per version and set (/api/ladder/timing/{name}, timing.py)
//   cards      one per case, many on screen: variant chips, the repairs that would make it right
//              (repairs.py), a diagram of only what matters, and each stock's normalised long-run error;
//              found flows and error series are fetched only for the cards on screen
//   full view  click a card: the true / found / differences diagrams, every repair, the long-run lines
(function () {
  "use strict";
  const D = window.SDDiagram, L = window.SDLadder, G = window.SDLadderDraw, fmt = L.fmt;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v, d = 1) => (v == null || !Number.isFinite(+v) ? "–" : `${(100 * v).toFixed(d)}%`);
  const enc = encodeURIComponent;
  const VARIANTS = ["none-short", "none-long", "counts-short", "counts-long"];
  const RANK = { fail: 0, error: 1, timeout: 1, equivalent: 2, pass: 3 };
  const WORD = { number: ["number", "numbers"], add: ["add", "add"], remove: ["remove", "remove"], form: ["change form", "change form"] };
  const CARD_LAYOUT = { box: { w: 64, h: 34 }, colw: 64 + 112, rowh: 34 + 74 };
  const when = (iso) => { const d = new Date(iso); return isNaN(d) ? "–" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); };
  const day = (iso) => String(iso || "").slice(0, 10);

  const q = new URLSearchParams(location.search);
  const S = { name: q.get("name") || "", data: null, cases: {}, cells: {}, details: {}, models: {}, errors: {}, tab: {}, rerun: {},
    f: { status: q.get("status") || "", variant: q.get("variant") || "", kind: q.get("kind") || "tests", level: "", tag: "", sort: q.get("sort") || "wrong", text: "" } };
  try { const t = localStorage.getItem("sdlab.theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* fine */ }
  $("theme").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("sdlab.theme", document.documentElement.dataset.theme); } catch { /* fine */ }
  };

  // ---------- tooltips: any element with data-tip ----------
  const tip = $("tip");
  const showTip = (html, e) => {
    tip.innerHTML = html; tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = `${Math.max(4, Math.min(innerWidth - w - 8, e.clientX + 14))}px`;
    tip.style.top = `${e.clientY + h + 24 > innerHeight ? e.clientY - h - 10 : e.clientY + 16}px`;
  };
  document.addEventListener("mousemove", (e) => {
    const t = e.target.closest && e.target.closest("[data-tip]");
    if (t) showTip(t.getAttribute("data-tip"), e); else if (!e.target.closest || !e.target.closest("svg[data-hover]")) tip.hidden = true;
  });

  async function get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: ${r.status} ${(await r.json().catch(() => ({}))).detail || ""}`);
    return r.json();
  }

  // ---------- header ----------
  function header(d) {
    const s = d.strategy, a = s.about, t = d.totals.tests, rt = d.totals.realistic, lt = d.latest;
    document.title = `${s.name}: strategy behaviour`;
    $("title").textContent = s.name;
    $("nowlink").href = `/ladder?view=now&strategy=${enc(s.name)}&variant=all`;
    const tile = (v, label, tipText) => `<div class="tile"${tipText ? ` data-tip="${esc(tipText)}"` : ""}><b>${v}</b><span>${label}</span></div>`;
    const commit = lt ? `${esc((lt.code_commit || "").slice(0, 10) || "unknown commit")}${lt.code_dirty ? ` + uncommitted patch ${esc(lt.code_dirty.slice(0, 8))}` : ""}` : "–";
    $("head").innerHTML = `
      <div class="about">${a ? `<p><b>${esc(a.idea)}</b> <span class="muted small">(${esc(a.status)})</span></p>
        <details><summary>How it works</summary><p>${esc(a.how)}</p><p>Meant for: ${esc(a.helps_with)} · Builds on: ${esc(a.builds_on)}</p>${a.note ? `<p>${esc(a.note)}</p>` : ""}</details>`
        : `<p class="muted">No explanation yet (sdlab/ladder/explanations.yaml).</p>`}${s.available === false ? `<p class="err small">Not available: ${esc(s.reason || "")}</p>` : ""}</div>
      <p class="prov">Latest result ${lt ? `#${lt.id}, ${esc(when(lt.at))}` : "–"} · commit <span class="mono">${commit}</span> · strategy hash <span class="mono">${esc((s.hash || "").slice(0, 10))}</span>
        ${d.behind ? ` · <span class="err">${d.behind} result${d.behind === 1 ? "" : "s"} from older code</span> (the watcher re-runs them; the board mixes versions)` : ""}
        ${t.stale ? ` · ${t.stale} to re-run or re-score` : ""}</p>
      <div class="tiles">
        ${tile(pct(t.pass_rate), `pass rate · ${t.pass} of ${t.ran} run`, "Tests (fixed cases and random draws): passes over the cells this strategy has run.")}
        ${tile(pct(t.strict_rate), `strict pass · ${t.strict} of ${t.strict_known} known`, `${STRICT_TIP} Over the cells with a strict verdict (${t.strict_known} of ${t.ran} run); a pass not computed yet is left out, never a fail.`)}
        ${tile(pct(t.achievable_rate), `pass where achievable · ${t.achievable_pass}/${t.achievable}`, "Passes over the cells whose data allow a pass (analysis.py: achievable).")}
        ${tile(`${t.ran}/${t.of}`, `coverage (${pct(t.of ? t.ran / t.of : null, 0)})`, "Cells run out of all test cells (cases × variants).")}
        ${tile(`${t.equivalent} / ${t.fail}`, "equivalent / fail")}
        ${tile(pct(t.occam), "Occam score", "Accuracy × parsimony, per run: fit (1 for pass or equivalent, else the share of true numbers right) × min(1, true ÷ found complexity).")}
        ${tile(pct(t.far), `err@100k (${t.far_n} runs)`, "Both models run free to t = 100,000: the gap as a share of the truth's range, capped at 100%; a run that runs away counts 100%.")}
        ${tile(t.repairs == null ? "–" : t.repairs.toFixed(1), "repairs per run (mean)")}
        ${tile(rt.of ? `${rt.ran}/${rt.of}` : "–", rt.of ? `realistic run · ${rt.pass} pass` : "realistic", "SD Lab's example models (realistic cases): run / all, and passes.")}
      </div>`;
  }

  // ---------- history ----------
  function rateChart(tl) {
    const box = $("h-rate");
    if (!tl.length) { box.innerHTML = `<p class="muted small">Never run.</p>`; return; }
    const W = Math.max(300, box.clientWidth || 600), H = 150, m = { l: 34, r: 8, t: 8, b: 20 };
    const n = tl.length, X = (i) => m.l + (n === 1 ? (W - m.l - m.r) / 2 : i / (n - 1) * (W - m.l - m.r)), Y = (v) => m.t + (1 - v) * (H - m.t - m.b);
    const pts = tl.map((v, i) => {
      const ran = Object.values(v.totals).reduce((a, b) => a + b, 0);
      return { i, v, ran, rate: ran ? v.totals.pass / ran : null, pe: ran ? (v.totals.pass + v.totals.equivalent) / ran : null, cov: v.of ? ran / v.of : null };
    });
    const line = (k, col, w, dash) => `<path d="${pts.filter((p) => p[k] != null).map((p, j) => `${j ? "L" : "M"}${X(p.i).toFixed(1)} ${Y(p[k]).toFixed(1)}`).join("")}" fill="none" stroke="${col}" stroke-width="${w}" ${dash ? `stroke-dasharray="${dash}"` : ""} stroke-linejoin="round"/>`;
    const grid = [0, 0.5, 1].map((g) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(g)}" y2="${Y(g)}" stroke="var(--grid)"/><text x="${m.l - 4}" y="${Y(g) + 3}" text-anchor="end">${g * 100}%</text>`).join("");
    const xt = [0, n - 1].filter((i, k, a) => a.indexOf(i) === k).map((i, k) => `<text x="${X(i)}" y="${H - 5}" text-anchor="${k ? "end" : "start"}">${esc(day(tl[i].first).slice(5))}</text>`).join("");
    const marks = pts.map((p) => p.rate == null ? "" : p.v.code_changed || p.i === 0 ? `<circle cx="${X(p.i)}" cy="${Y(p.rate)}" r="3.5" fill="var(--fg)" stroke="var(--surface)" stroke-width="1.5"/>`
      : `<circle cx="${X(p.i)}" cy="${Y(p.rate)}" r="3" fill="var(--surface)" stroke="var(--muted)" stroke-width="1.5"/>`).join("");
    box.innerHTML = `<svg width="100%" viewBox="0 0 ${W} ${H}" data-hover role="img" aria-label="pass rate per version">${grid}${xt}${line("cov", "var(--faint)", 1.5, "4 3")}${line("pe", "var(--c3)", 1.5)}${line("rate", "var(--c1)", 2)}${marks}
      <line class="cross" y1="${m.t}" y2="${H - m.b}" stroke="var(--muted)" stroke-dasharray="2 2" visibility="hidden"/><rect x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent"/></svg>`;
    const svg = box.querySelector("svg"), cross = svg.querySelector(".cross");
    svg.onpointermove = (e) => {
      const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W;
      const i = Math.max(0, Math.min(n - 1, Math.round(n === 1 ? 0 : (x - m.l) / (W - m.l - m.r) * (n - 1)))), p = pts[i], v = p.v, tt = v.totals;
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
      showTip(`<b>version ${i + 1} of ${n}</b>${v.code_changed ? " · code changed" : i ? " · scorer changed" : ""}<br>strategy <span class="mono">${esc(v.strategy_hash)}</span>, scorer <span class="mono">${esc(v.score_hash)}</span><br>commit${v.commits.length > 1 ? "s" : ""} <span class="mono">${esc(v.commits.join(", ") || "–")}</span><br>${esc(when(v.first))} – ${esc(when(v.last))}, ${v.ran} results<br>after it: ${tt.pass} pass, ${tt.equivalent} equivalent, ${tt.fail} fail${tt.error + tt.timeout ? `, ${tt.error + tt.timeout} error/timeout` : ""} of ${p.ran} run (${v.of} cells)<br>pass rate ${pct(p.rate)} · coverage ${pct(p.cov)}`, e);
    };
    svg.onpointerleave = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  }

  function changesChart(tl) {
    const box = $("h-changes");
    if (!tl.length) { box.innerHTML = ""; return; }
    const days = {};
    tl.forEach((v, i) => { const k = day(v.first); (days[k] || (days[k] = { code: [], scorer: [] }))[v.code_changed || i === 0 ? "code" : "scorer"].push({ v, i }); });
    const d0 = new Date(Object.keys(days).sort()[0]), d1 = new Date(Object.keys(days).sort().slice(-1)[0]);
    const all = []; for (let d = new Date(d0); d <= d1; d.setUTCDate(d.getUTCDate() + 1)) all.push(d.toISOString().slice(0, 10));
    const W = Math.max(260, box.clientWidth || 400), H = 150, m = { l: 26, r: 6, t: 8, b: 20 };
    const max = Math.max(1, ...all.map((k) => (days[k] ? days[k].code.length + days[k].scorer.length : 0)));
    const bw = Math.max(2, Math.min(22, (W - m.l - m.r) / all.length - 2)), X = (i) => m.l + (i + 0.5) * (W - m.l - m.r) / all.length, Y = (v) => m.t + (1 - v / max) * (H - m.t - m.b);
    const bars = all.map((k, i) => {
      const x = days[k]; if (!x) return "";
      const c = x.code.length, sc = x.scorer.length;
      const tipText = `<b>${esc(k)}</b>: ${c} code change${c === 1 ? "" : "s"}${sc ? `, ${sc} scorer change${sc === 1 ? "" : "s"}` : ""}<br>${[...x.code, ...x.scorer].slice(0, 8).map(({ v, i: j }) => `v${j + 1} <span class="mono">${esc(v.strategy_hash)}</span> ${esc(v.commits[0] || "")}`).join("<br>")}`;
      return `<g data-tip="${esc(tipText)}"><rect x="${X(i) - bw / 2}" y="${m.t}" width="${bw}" height="${H - m.t - m.b}" fill="transparent"/>
        ${c ? `<rect x="${X(i) - bw / 2}" y="${Y(c)}" width="${bw}" height="${Math.max(1, H - m.b - Y(c))}" rx="2" fill="var(--c7)"/>` : ""}
        ${sc ? `<rect x="${X(i) - bw / 2}" y="${Y(c + sc)}" width="${bw}" height="${Math.max(1, Y(c) - Y(c + sc) - 2)}" rx="2" fill="var(--faint)"/>` : ""}</g>`;
    }).join("");
    const grid = [0, max].map((g) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(g)}" y2="${Y(g)}" stroke="var(--grid)"/><text x="${m.l - 4}" y="${Y(g) + 3}" text-anchor="end">${g}</text>`).join("");
    const xt = `<text x="${m.l}" y="${H - 5}">${esc(all[0].slice(5))}</text>${all.length > 1 ? `<text x="${W - m.r}" y="${H - 5}" text-anchor="end">${esc(all[all.length - 1].slice(5))}</text>` : ""}`;
    const code = tl.filter((v, i) => v.code_changed || i === 0).length;
    box.innerHTML = `<svg width="100%" viewBox="0 0 ${W} ${H}" role="img" aria-label="code changes per day">${grid}${xt}${bars}</svg>
      <div class="muted small">${code} code version${code === 1 ? "" : "s"}, ${tl.length - code} scorer change${tl.length - code === 1 ? "" : "s"}, over ${all.length} day${all.length === 1 ? "" : "s"}</div>`;
  }

  // ---------- time per cell per version (/api/ladder/timing/{name}) ----------
  const TSETS = ["tests", "noisy", "canonical", "realistic", "physics", "real"];
  const secs = (v) => (v == null ? "–" : v < 1 ? v.toFixed(2) : v < 100 ? v.toFixed(1) : v.toFixed(0));
  async function loadTime() {
    let t;
    try { t = await get(`/api/ladder/timing/${enc(S.name)}`); } catch (e) { $("h-time").innerHTML = `<p class="err small">${esc(e.message)}</p>`; return; }
    if (t.pending) { setTimeout(loadTime, 3000); return; }
    S.time = t; timeChart(t);
  }
  function timeChart(t) {
    const box = $("h-time"), vs = (t.versions || []).filter((v) => v.all), st = t.stats || { sets: {}, score: {} };
    const now = TSETS.filter((s) => st.sets[s]).map((s) => `${s} ${secs(st.sets[s][0])} s (p95 ${secs(st.sets[s][1])}, ${st.sets[s][2]} cells${st.score[s] ? `; scoring ${secs(st.score[s][0])} s` : ""})`).join(" · ");
    const tr = st.trend ? `latest version ×${st.trend.ratio.toFixed(2)} the one before over the ${st.trend.n} cells both ran` : "";
    $("h-time-legend").innerHTML = TSETS.map((s, k) => `<span><i class="key" style="background:var(--c${k + 1})"></i>${s}</span>`).join("");
    if (!vs.length) { box.innerHTML = `<p class="muted small">No timed results yet.</p>`; return; }
    const W = Math.max(300, box.clientWidth || 600), H = 150, m = { l: 40, r: 8, t: 8, b: 20 }, n = vs.length;
    const vals = vs.flatMap((v) => TSETS.map((s) => v.sets[s] && v.sets[s][0]).filter((x) => x != null)).map((x) => Math.max(x, 0.001));
    const lo = Math.floor(Math.log10(Math.min(...vals))), hi = Math.max(lo + 1, Math.ceil(Math.log10(Math.max(...vals))));
    const X = (i) => m.l + (n === 1 ? (W - m.l - m.r) / 2 : i / (n - 1) * (W - m.l - m.r)), Y = (x) => m.t + (hi - Math.log10(Math.max(x, 0.001))) / (hi - lo) * (H - m.t - m.b);
    const grid = Array.from({ length: hi - lo + 1 }, (_, k) => lo + k).map((e) => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(10 ** e)}" y2="${Y(10 ** e)}" stroke="var(--grid)"/><text x="${m.l - 4}" y="${Y(10 ** e) + 3}" text-anchor="end">${secs(10 ** e)}s</text>`).join("");
    const lines = TSETS.map((s, k) => {
      const pts = vs.map((v, i) => (v.sets[s] ? [i, v.sets[s][0]] : null)).filter(Boolean);
      if (!pts.length) return "";
      return `<path d="${pts.map(([i, x], j) => `${j ? "L" : "M"}${X(i).toFixed(1)} ${Y(x).toFixed(1)}`).join("")}" fill="none" stroke="var(--c${k + 1})" stroke-width="1.6" stroke-linejoin="round"/>`
        + pts.map(([i, x]) => `<circle cx="${X(i)}" cy="${Y(x)}" r="2.4" fill="var(--c${k + 1})"/>`).join("");
    }).join("");
    const xt = [0, n - 1].filter((i, k, a) => a.indexOf(i) === k).map((i, k) => `<text x="${X(i)}" y="${H - 5}" text-anchor="${k ? "end" : "start"}">${esc(day(vs[i].at).slice(5))}</text>`).join("");
    box.innerHTML = `<svg width="100%" viewBox="0 0 ${W} ${H}" data-hover role="img" aria-label="time per cell per version">${grid}${xt}${lines}
      <line class="cross" y1="${m.t}" y2="${H - m.b}" stroke="var(--muted)" stroke-dasharray="2 2" visibility="hidden"/><rect x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent"/></svg>
      <div class="muted small">Now: ${esc(now) || "–"}${tr ? ` · ${esc(tr)}` : ""}. What re-testing costs: <span class="mono">uv run sdlab-ladder cost --strategies ${esc(S.name)}</span></div>`;
    const svg = box.querySelector("svg"), cross = svg.querySelector(".cross");
    svg.onpointermove = (e) => {
      const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) / r.width * W;
      const i = Math.max(0, Math.min(n - 1, Math.round(n === 1 ? 0 : (x - m.l) / (W - m.l - m.r) * (n - 1)))), v = vs[i];
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("visibility", "visible");
      showTip(`<b>version ${i + 1} of ${n}</b> <span class="mono">${esc(v.hash)}</span><br>from ${esc(when(v.at))}, ${v.n} cells<br>`
        + TSETS.filter((s) => v.sets[s]).map((s) => `${s}: median ${secs(v.sets[s][0])} s, p95 ${secs(v.sets[s][1])} s (${v.sets[s][2]})`).join("<br>"), e);
    };
    svg.onpointerleave = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  }

  // ---------- filters and the grid ----------
  const cellOf = (cid, v) => S.cells[`${cid}|${v}`] || null;
  function shown(c) {
    if (S.tab[c.id]) return cellOf(c.id, S.tab[c.id]);
    const vs = c.variants.filter((v) => !S.f.variant || v === S.f.variant).map((v) => cellOf(c.id, v)).filter((x) => x && x.status);
    if (!vs.length) return S.f.variant ? cellOf(c.id, S.f.variant) : null;
    return vs.sort((a, b) => (RANK[a.status] ?? 9) - (RANK[b.status] ?? 9) || (b.n || 0) - (a.n || 0) || (b.far || 0) - (a.far || 0))[0];
  }
  const headline = (x) => {
    if (!x || !x.status) return "not run";
    if (x.n == null) return x.status;
    if (!x.n) return "no repairs";
    return `${x.n} repair${x.n === 1 ? "" : "s"}: ` + ["remove", "add", "form", "number"].filter((t) => x.by[t]).map((t) => `${x.by[t]} ${WORD[t][x.by[t] === 1 ? 0 : 1]}`).join(", ");
  };

  function controls(d) {
    const levels = [...new Set(d.cases.map((c) => c.level))].sort((a, b) => a - b), tags = [...new Set(d.cases.flatMap((c) => c.tags))].sort();
    const o = (v, w, cur) => `<option value="${esc(v)}"${String(v) === String(cur) ? " selected" : ""}>${esc(w)}</option>`;
    const f = S.f;
    $("controls").innerHTML = `
      <label>Verdict <select data-f="status">${[["", "any"], ["fail", "fail"], ["equivalent", "equivalent"], ["pass", "pass"], ["error", "error / timeout"], ["none", "not run"]].map(([v, w]) => o(v, w, f.status)).join("")}</select></label>
      <label>Variant <select data-f="variant">${o("", "worst of four", f.variant)}${VARIANTS.map((v) => o(v, v, f.variant)).join("")}</select></label>
      <label>Cases <select data-f="kind">${[["tests", "tests (fixed + draws)"], ["test", "fixed cases"], ["draw", "random draws"], ["realistic", "realistic"], ["physics", "physics"], ["all", "all"]].map(([v, w]) => o(v, w, f.kind)).join("")}</select></label>
      <label>Level <select data-f="level">${o("", "any", f.level)}${levels.map((l) => o(l, `level ${l}`, f.level)).join("")}</select></label>
      <label>Tag <select data-f="tag">${o("", "any", f.tag)}${tags.map((t) => o(t, t, f.tag)).join("")}</select></label>
      <label>Sort <select data-f="sort">${[["wrong", "most wrong (verdict, repairs, err@100k)"], ["repairs", "most repairs"], ["far", "worst err@100k"], ["level", "by level"]].map(([v, w]) => o(v, w, f.sort)).join("")}</select></label>
      <input data-f="text" placeholder="case id or title" value="${esc(f.text)}" style="width:150px" aria-label="Find a case">
      <span class="count" id="count"></span>`;
    $("controls").querySelectorAll("[data-f]").forEach((el) => {
      el[el.tagName === "INPUT" ? "oninput" : "onchange"] = () => {
        S.f[el.dataset.f] = el.value; if (el.dataset.f === "variant") S.tab = {};
        const u = new URL(location.href); ["status", "variant", "kind", "sort"].forEach((k) => (S.f[k] ? u.searchParams.set(k, S.f[k]) : u.searchParams.delete(k))); history.replaceState(null, "", u);
        grid();
      };
    });
  }

  function rows() {
    const f = S.f, txt = f.text.trim().toLowerCase();
    let out = S.data.cases.filter((c) => (f.kind === "all" || (f.kind === "tests" ? c.kind !== "realistic" && c.kind !== "physics" : c.kind === f.kind))
      && (!f.level || String(c.level) === f.level) && (!f.tag || c.tags.includes(f.tag)) && (!txt || c.id.toLowerCase().includes(txt) || c.title.toLowerCase().includes(txt)))
      .map((c) => ({ c, x: shown(c) }))
      .filter(({ x }) => !f.status || (f.status === "none" ? !x || !x.status : f.status === "error" ? x && (x.status === "error" || x.status === "timeout") : x && x.status === f.status));
    const wrong = (x) => (!x || !x.status ? -1 : (3 - (RANK[x.status] ?? 0)) * 1000 + (x.n || 0) * 10 + (x.far || 0) * 9);
    if (f.sort === "wrong") out.sort((a, b) => wrong(b.x) - wrong(a.x) || a.c.level - b.c.level);
    else if (f.sort === "repairs") out.sort((a, b) => ((b.x && b.x.n) ?? -1) - ((a.x && a.x.n) ?? -1) || a.c.level - b.c.level);
    else if (f.sort === "far") out.sort((a, b) => ((b.x && b.x.far) ?? -1) - ((a.x && a.x.far) ?? -1));
    else out.sort((a, b) => a.c.level - b.c.level || a.c.id.localeCompare(b.c.id));
    return out;
  }

  // strict pass (strict.py), shown on a pass: strict, not strict (why), or not computed yet
  const STRICT_WHY = { extra: "more complexity than the truth", longrun: "long-run error above what the refitted truth reaches (or it diverges)", fresh: "fresh-run skill@100 below what the refitted truth reaches" };
  const STRICT_TIP = "Strict pass: a pass with no more complexity than the truth, whose long-run error (10 × the truth's slowest time constant) and fresh-run skill@100 are as good as the truth's own structure refitted on the same kind of data achieves (strict.py).";
  function strictChip(x) {
    if (!x || x.status !== "pass") return "";
    const why = x.strict_why || "";
    if (x.strict === 1) return `<span class="badge b-pass" data-tip="${esc(STRICT_TIP + (why ? ` Not applied here (${why}).` : ""))}">strict</span>`;
    if (x.strict === 0) return `<span class="badge b-fail" data-tip="${esc(`${STRICT_TIP} Fails: ${why.split(",").map((w) => STRICT_WHY[w] || w).join("; ")}.`)}">not strict: ${esc(why.replace(/,/g, ", "))}</span>`;
    return `<span class="badge b-lim" data-tip="${esc(`${STRICT_TIP} Not computed yet (${why.replace("pending: ", "") || "pending"}): sdlab-ladder strict.`)}">strict: not computed</span>`;
  }

  function cardHtml(c, x) {
    const st = x && x.status ? x.status : "none";
    const chips = c.variants.map((v) => { const y = cellOf(c.id, v), on = x && x.variant === v; return `<button class="chip st-${y && y.status ? y.status : "none"}${on ? " on" : ""}" data-v="${esc(v)}" title="${esc(v)}: ${esc(y && y.status ? `${y.status}, ${headline(y)}` : "not run")}"><i></i>${esc(v.replace("counts-", "c-").replace("none-", "n-"))}</button>`; }).join("");
    const lab = x && x.analysis && x.analysis !== "achievable" ? `<span class="badge b-lim" data-tip="${esc(`analysis.py: ${x.analysis}. Achievable = the data allow a pass with p ≥ 0.5; data-limited = even the best estimator usually misses; unidentifiable = only an equivalent model is possible.`)}">${esc(x.analysis)}</span>` : "";
    const strict = strictChip(x);
    const far = x && x.far != null ? `<span class="muted small" data-tip="Both models run free to t = 100,000: the gap as a share of the truth's range (capped at 100%)">err@100k ${pct(x.far, 0)}${x.flag ? ` · <span class="err">${esc(x.flag)}</span>` : ""}</span>` : "";
    return `<article class="card st-${st}" data-case="${esc(c.id)}" tabindex="0" aria-label="${esc(c.id)} ${esc(c.title)}">
      <div class="chead"><span class="cid">${esc(c.kind === "realistic" ? "" : c.id.slice(0, 3))}${c.kind === "draw" ? esc(c.id.slice(3)) : ""}</span><span class="ctitle" title="${esc(c.id)}: ${esc(c.tests)}">${esc(c.title)}</span>
        <button class="rerun" data-rerun title="Re-run ${esc(c.id)} for ${esc(S.name)} now: every variant, at the top of the CPU pool's queue, at the latest committed code">↻ Re-run</button></div>
      <div class="rr-status small muted" aria-live="polite">${esc(S.rerun[c.id] || "")}</div>
      <div class="chips">${chips}</div>
      <div class="headline"><span class="badge b-${st}">${esc(st === "none" ? "not run" : st)}</span><b>${esc(headline(x))}</b>${strict}${lab}${far}</div>
      <div class="dg"><svg role="img" aria-label="What would make it right"></svg></div>
      <ul class="reps"></ul>
      <div class="spark"></div>
    </article>`;
  }

  let observer = null;
  function grid() {
    const rs = rows(), box = $("grid");
    $("count").textContent = `${rs.length} case${rs.length === 1 ? "" : "s"}`;
    box.innerHTML = rs.map(({ c, x }) => cardHtml(c, x)).join("") || `<p class="muted">No case matches.</p>`;
    if (observer) observer.disconnect();
    observer = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { observer.unobserve(e.target); fill(e.target); } }), { rootMargin: "300px 0px" });
    box.querySelectorAll(".card").forEach((el) => observer.observe(el));
  }

  // ---------- lazy filling: details (found flows, repairs) and error series, in batches ----------
  const want = { details: new Set(), errors: new Set() }, waiting = new Map();
  let timer = null;
  function fill(el) {
    const c = S.cases[el.dataset.case], x = shown(c);
    if (!x || !x.id) { el.querySelector(".dg").innerHTML = `<span class="muted small">${x && x.status ? "" : "not run yet"}</span>`; return; }
    el.dataset.id = x.id;
    if (!waiting.has(x.id)) waiting.set(x.id, new Set());
    waiting.get(x.id).add(el);
    if (!S.details[x.id]) want.details.add(x.id);
    if (!(x.id in S.errors) && x.status !== "error" && x.status !== "timeout") want.errors.add(x.id);
    paint(x.id);
    clearTimeout(timer); timer = setTimeout(flush, 30);
  }
  async function batch(kind, size, done) {
    while (want[kind].size) {
      const ids = [...want[kind]].slice(0, size); ids.forEach((i) => want[kind].delete(i));
      try {
        const r = await get(`/api/ladder/strategy/${enc(S.name)}/${kind}?ids=${ids.join(",")}`);
        done(r, ids);
      } catch (e) { $("status").textContent = e.message; }
      ids.forEach(paint);
    }
  }
  let busy = { details: false, errors: false };
  function flush() {
    if (!busy.details) { busy.details = true; batch("details", 24, (r, ids) => { Object.assign(S.models, r.models); ids.forEach((i) => { S.details[i] = r.results[i] || { missing: true }; }); }).finally(() => { busy.details = false; if (want.details.size) flush(); }); }
    for (let k = 0; k < 2; k++) if (!busy["errors" + k]) {     // two error streams: the series cost up to a second each, cold
      busy["errors" + k] = true;
      batch("errors", 4, (r, ids) => ids.forEach((i) => { S.errors[i] = r[i] ?? null; })).finally(() => { busy["errors" + k] = false; if (want.errors.size) flush(); });
    }
  }
  function paint(id) {
    const els = waiting.get(+id) || waiting.get(String(id)); if (!els) return;
    els.forEach((el) => {
      if (!el.isConnected || String(el.dataset.id) !== String(id)) return;
      const det = S.details[id], c = S.cases[el.dataset.case];
      if (det && !det.missing && !el.dataset.drawn && S.models[det.case]) {
        el.dataset.drawn = "1";
        try { G.drawRepairs({ ...c, model: S.models[det.case] }, det, el.querySelector(".dg svg"), det.repairs, { layout: CARD_LAYOUT, cols: 3, maxScale: 1, pad: 16 }); } catch (e) { el.querySelector(".dg").innerHTML = `<span class="err small">${esc(e.message)}</span>`; }
        el.querySelector(".reps").innerHTML = repList(det, 3);
      } else if (det && det.error && !el.dataset.drawn) { el.dataset.drawn = "1"; el.querySelector(".dg").innerHTML = `<span class="err small">${esc(det.error.slice(0, 160))}</span>`; }
      if (id in S.errors && !el.dataset.sparked) { el.dataset.sparked = "1"; el.querySelector(".spark").innerHTML = spark(S.errors[id], { h: 44 }); hoverSpark(el.querySelector(".spark svg"), S.errors[id]); }
    });
  }

  function limTag(it) {
    if (it.limit === "data-limited") return ` <span class="lim data" data-tip="${esc(`The miss is ${it.z.toFixed(1)} standard errors of the best estimate the data allow (${it.se_source === "bound" ? "Cramér–Rao bound" : "the scorer's oracle"}, SE ${fmt(it.se)}): the data cannot do much better.`)}">data-limited</span>`;
    if (it.limit === "method error") return ` <span class="lim method" data-tip="${esc(`The miss is ${it.z > 1e4 ? "over 10,000" : it.z.toFixed(0)} standard errors of the best estimate the data allow (${it.se_source === "bound" ? "Cramér–Rao bound" : "the scorer's oracle"}, SE ${fmt(it.se)}${it.allowed != null ? `; the scorer allows ±${fmt(it.allowed)}` : ""}): the method, not the data.`)}">method error</span>`;
    if (it.limit === "equivalent") return ` <span class="lim data">equivalent reading</span>`;
    return "";
  }
  function repList(det, max) {
    const rp = det.repairs;
    if (!rp) return det.error ? `<li class="err">${esc(det.error.slice(0, 200))}</li>` : "";
    const items = rp.items;
    const lis = items.slice(0, max || items.length).map((it) => `<li class="r-${it.type}">${esc(it.text)}${limTag(it)}</li>`).join("");
    const eq = rp.equivalence ? `<li class="muted" style="text-indent:0;padding:0">${esc(max ? (rp.equivalence.unidentifiable ? "Equivalent: the data cannot tell it from the truth." : "Equivalent: the same equations for every stock.") : rp.equivalence.text)}</li>` : "";
    return lis + (max && items.length > max ? `<li class="more" style="text-indent:0;padding:0">+${items.length - max} more</li>` : "") + eq;
  }

  // the normalised error per stock over log time: (found − true) ÷ the truth's range, as %
  function spark(e, { h = 44, w = 320, axis = false } = {}) {
    if (e === null) return `<div class="sl"><span>long run: no found model</span></div>`;
    if (!e) return "";
    if (e.error) return `<div class="sl"><span class="err">long run: ${esc(e.error)}</span></div>`;
    const lt = e.t.map((t) => Math.log10(t)), x0 = lt[0], x1 = lt[lt.length - 1] || x0 + 1;
    const vals = e.err.flat().filter((v) => v != null);
    const peak = Math.max(0.01, ...vals.map(Math.abs)), lim = Math.min(peak, 1.5);
    const m = axis ? { l: 40, r: 8, t: 6, b: 18 } : { l: 2, r: 2, t: 3, b: 3 };
    const X = (v) => m.l + (v - x0) / ((x1 - x0) || 1) * (w - m.l - m.r), Y = (v) => m.t + (1 - (Math.max(-lim, Math.min(lim, v)) + lim) / (2 * lim)) * (h - m.t - m.b);
    const paths = e.err.map((row, k) => { let d = "", pen = false; row.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${X(lt[i]).toFixed(1)} ${Y(v).toFixed(1)}`; pen = true; }); return `<path d="${d}" fill="none" stroke="var(--c${(k % 8) + 1})" stroke-width="${axis ? 2 : 1.5}" stroke-linejoin="round"/>`; }).join("");
    const runX = X(Math.log10(e.run_end));
    const ax = axis ? [lim, 0, -lim].map((v) => `<text x="${m.l - 4}" y="${Y(v) + 3}" text-anchor="end">${v > 0 ? "+" : ""}${(100 * v).toFixed(0)}%</text>`).join("")
      + [1, 2, 3, 4, 5].filter((p) => p >= x0 && p <= x1).map((p) => `<text x="${X(p)}" y="${h - 4}" text-anchor="middle">${p >= 3 ? 10 ** (p - 3) + "k" : 10 ** p}</text>`).join("") : "";
    const worst = e.err.map((row, k) => ({ k, v: Math.max(0, ...row.filter((v) => v != null).map(Math.abs)), last: row[row.length - 1] })).sort((a, b) => b.v - a.v);
    const n = e.stocks.length;
    const label = `<div class="sl"><span>long-run error${n > 1 ? `, ${n} stocks` : ""}: worst ${pct(worst[0].v, 0)} (${esc(e.stocks[worst[0].k])})</span><span>${e.flag ? `<span class="err">${esc(e.flag)}</span> · ` : ""}at 100k ${worst[0].last == null ? "runaway" : pct(Math.abs(worst[0].last), 0)}</span></div>`;
    return `${axis ? "" : label}<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" data-hover role="img" aria-label="long-run error per stock" style="${axis ? "height:auto" : ""}">
      <line x1="${m.l}" x2="${w - m.r}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--rule)"/>${axis ? `<line x1="${m.l}" x2="${w - m.r}" y1="${Y(lim)}" y2="${Y(lim)}" stroke="var(--grid)"/><line x1="${m.l}" x2="${w - m.r}" y1="${Y(-lim)}" y2="${Y(-lim)}" stroke="var(--grid)"/>` : ""}
      <line x1="${runX}" x2="${runX}" y1="${m.t}" y2="${h - m.b}" stroke="var(--faint)" stroke-dasharray="2 2"/>${ax}${paths}
      <line class="cross" y1="${m.t}" y2="${h - m.b}" stroke="var(--muted)" visibility="hidden" vector-effect="non-scaling-stroke"/></svg>${axis ? label : ""}`;
  }
  function hoverSpark(svg, e) {
    if (!svg || !e || !e.t) return;
    const vb = svg.viewBox.baseVal, lt = e.t.map((t) => Math.log10(t)), cross = svg.querySelector(".cross");
    const axis = vb.height > 60, m = axis ? { l: 40, r: 8 } : { l: 2, r: 2 };
    svg.onpointermove = (ev) => {
      const r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width * vb.width;
      const target = lt[0] + (x - m.l) / (vb.width - m.l - m.r) * (lt[lt.length - 1] - lt[0]);
      let i = 0, best = Infinity; lt.forEach((v, j) => { const d = Math.abs(v - target); if (d < best) { best = d; i = j; } });
      const px = m.l + (lt[i] - lt[0]) / ((lt[lt.length - 1] - lt[0]) || 1) * (vb.width - m.l - m.r);
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("visibility", "visible");
      showTip(`t = ${e.t[i].toLocaleString()}${e.t[i] <= e.run_end ? " (recorded run)" : " (beyond the run)"}<br>${e.stocks.map((s, k) => `<span style="color:var(--c${(k % 8) + 1})">■</span> ${esc(s)} ${e.err[k][i] == null ? "runaway" : `${e.err[k][i] > 0 ? "+" : ""}${(100 * e.err[k][i]).toFixed(1)}%`}`).slice(0, 12).join("<br>")}${e.stocks.length > 12 ? `<br>… ${e.stocks.length - 12} more` : ""}`, ev);
    };
    svg.onpointerleave = () => { cross.setAttribute("visibility", "hidden"); tip.hidden = true; };
  }

  // ---------- the full view ----------
  async function openFull(cid, id) {
    const c = S.cases[cid], ov = $("overlay");
    ov.hidden = false; document.body.style.overflow = "hidden";
    ov.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-label="${esc(cid)}"><button class="close" id="close" aria-label="Close">✕ Close</button><p class="muted">Loading…</p></div>`;
    $("close").onclick = closeFull;
    if (!S.details[id]) { const r = await get(`/api/ladder/strategy/${enc(S.name)}/details?ids=${id}`); Object.assign(S.models, r.models); S.details[id] = r.results[id]; }
    const det = S.details[id], cc = { ...c, model: S.models[det.case] }, x = cellOf(cid, det.variant);
    const a = det.analysis;
    ov.querySelector(".sheet").innerHTML = `<button class="close" id="close" aria-label="Close">✕ Close</button>
      <h2>${esc(c.id)} <span class="muted">${esc(c.title)}</span></h2>
      <p class="small muted">Tests: ${esc(c.tests)} · level ${esc(c.level)} · ${esc(c.tags.join(", "))}</p>
      <div class="headline"><span class="badge b-${det.status}">${esc(det.status)}</span><b>${esc(det.variant)}</b> · <b>${esc(det.repairs ? det.repairs.headline : "no model")}</b>
        ${a ? `<span class="badge b-lim" data-tip="${esc((a.why || []).join("; ") || "")}">${esc(a.label)}${a.p != null ? ` · p ${a.p.toFixed(2)}` : ""}</span>` : ""}
        <a href="/ladder?view=now&case=${enc(c.id)}&variant=${enc(det.variant)}&strategy=${enc(S.name)}">equations, every part</a> · <a href="/ladder/run?id=${id}">long run, full page</a> · result #${id}</div>
      <h3>What would make it right</h3>
      <ul class="reps fullreps">${repList(det, 0) || "<li>Nothing: it is right.</li>"}</ul>
      ${a && a.equivalences && a.equivalences.length && det.status !== "pass" ? `<details class="small muted"><summary>Equivalent structures for this case (analysis)</summary><ul>${a.equivalences.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></details>` : ""}
      <div class="three">
        <figure><figcaption>What to change</figcaption><svg id="f-rep"></svg></figure>
        <figure><figcaption>True model</figcaption><svg id="f-true"></svg></figure>
        <figure><figcaption>Found by ${esc(S.name)}</figcaption><svg id="f-found"></svg></figure>
        <figure><figcaption>Differences (${G.LEGEND})</figcaption><svg id="f-diff"></svg></figure>
      </div>
      <h3>Long run: (found − true) ÷ the truth's range, per stock</h3>
      <div id="f-err"><p class="muted small">Loading…</p></div>
      <h3>Each stock, true vs found (log time, to the far end)</h3>
      <div id="f-stocks" class="stockcharts"><p class="muted small">Loading…</p></div>`;
    $("close").onclick = closeFull;
    try {
      G.drawRepairs(cc, det, $("f-rep"), det.repairs, { full: true, cols: innerWidth >= 900 ? 3 : 1, pad: 24 });
    } catch (e) { $("f-rep").outerHTML = `<p class="err">${esc(e.message)}</p>`; }
    try {
      const cmp = await G.compareOf(cc, { strategy: S.name, ...det });     // the verdicts from the server's diff (diff.py)
      if ($("f-diff")) G.drawPair(cc, det, $("f-true"), $("f-found"), cmp, innerWidth >= 900 ? 3 : 1, $("f-diff"));
    } catch (e) { if ($("f-true")) $("f-true").outerHTML = `<p class="err">${esc(e.message)}</p>`; }
    if (!(id in S.errors)) { const r = await get(`/api/ladder/strategy/${enc(S.name)}/errors?ids=${id}`).catch(() => ({})); S.errors[id] = r[id] ?? null; }
    $("f-err").innerHTML = spark(S.errors[id], { h: 200, w: 900, axis: true }) + (S.errors[id] && S.errors[id].stocks ? `<div class="legend small">${S.errors[id].stocks.slice(0, 16).map((s, k) => `<span><i class="key" style="background:var(--c${(k % 8) + 1})"></i>${esc(s)}</span>`).join(" ")}</div>` : "");
    hoverSpark($("f-err").querySelector("svg"), S.errors[id]);
    if (x && x.status !== "error" && x.status !== "timeout") {
      get(`/api/ladder/longrun/${id}`).then((g) => {
        $("f-stocks").innerHTML = g.stocks.map((s, k) => `<div class="panel"><h2>${esc(s)}</h2>${lines(g.overview.t, g.overview.truth[k], g.overview.found[k])}</div>`).join("")
          + `<p class="muted small">Blue: the true model; orange: the found one. <a href="/ladder/run?id=${id}">Every window and the recorded data</a>.</p>`;
      }).catch((e) => { $("f-stocks").innerHTML = `<p class="err small">${esc(e.message)}</p>`; });
    } else $("f-stocks").innerHTML = "";
  }
  function lines(t, truth, found) {
    const W = 320, H = 120, m = { l: 40, r: 6, t: 6, b: 16 }, lt = t.map((v) => Math.log10(v));
    const all = [...truth, ...found].filter((v) => v != null && Number.isFinite(v));
    const lo = Math.min(0, ...all), hi = Math.max(lo + 1e-9, ...all);
    const X = (v) => m.l + (v - lt[0]) / ((lt[lt.length - 1] - lt[0]) || 1) * (W - m.l - m.r), Y = (v) => m.t + (1 - (Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * (H - m.t - m.b);
    const p = (vs) => { let d = "", pen = false; vs.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${X(lt[i]).toFixed(1)} ${Y(v).toFixed(1)}`; pen = true; }); return d; };
    return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto"><line x1="${m.l}" x2="${W - m.r}" y1="${Y(lo)}" y2="${Y(lo)}" stroke="var(--grid)"/><line x1="${m.l}" x2="${W - m.r}" y1="${Y(hi)}" y2="${Y(hi)}" stroke="var(--grid)"/>
      <text x="${m.l - 4}" y="${Y(hi) + 3}" text-anchor="end">${fmt(hi)}</text><text x="${m.l - 4}" y="${Y(lo) + 3}" text-anchor="end">${fmt(lo)}</text>
      <text x="${m.l}" y="${H - 3}">${t[0]}</text><text x="${W - m.r}" y="${H - 3}" text-anchor="end">${t[t.length - 1].toLocaleString()}</text>
      <path d="${p(truth)}" fill="none" stroke="var(--c1)" stroke-width="2"/><path d="${p(found)}" fill="none" stroke="var(--c2)" stroke-width="2" stroke-dasharray="5 3"/></svg>`;
  }
  function closeFull() { $("overlay").hidden = true; $("overlay").innerHTML = ""; document.body.style.overflow = ""; }
  $("overlay").onclick = (e) => { if (e.target === $("overlay")) closeFull(); };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("overlay").hidden) closeFull(); });

  // the re-run button: one case for this strategy, every variant, at the top of the pool's queue; its
  // progress shows on the card, and the card redraws with the new results when the job is done
  async function rerun(c) {
    const say = (t) => { S.rerun[c.id] = t; const el = $("grid").querySelector(`[data-case="${CSS.escape(c.id)}"] .rr-status`); if (el) el.textContent = t; };
    say("submitting…");
    let j;
    try {
      const r = await fetch("/api/pool/rerun", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case: c.id, strategy: S.name }) });
      const d = await r.json();
      if (!r.ok) { say(`not submitted: ${d.error || r.status}`); return; }
      j = d.job;
    } catch (e) { say(`not submitted: ${e.message}`); return; }
    for (;;) {
      const n = j.counts || {}, fin = (n.done || 0) + (n.reused || 0) + (n.skipped || 0) + (n.error || 0);
      if (["done", "cancelled", "failed", "error"].includes(j.state)) break;
      say(`job ${j.id}: ${j.state === "planning" ? "planning" : `${fin} of ${j.total || "?"} done, ${n.leased || 0} running`}`);
      await new Promise((ok) => setTimeout(ok, 4000));
      try { j = (await get(`/api/pool/jobs/${j.id}`)).job; } catch { /* the server restarts: keep asking */ }
    }
    const st = Object.entries(j.statuses || {}).map(([k, v]) => `${v} ${k}`).join(", ");
    say(`job ${j.id} ${j.state}${st ? `: ${st}` : ""} (refreshing…)`);
    for (let i = 0; i < 6; i++) {                                // the new results reach the summary within seconds
      await new Promise((ok) => setTimeout(ok, 3000));
      try {
        const d = await get(`/api/ladder/strategy/${enc(S.name)}?fresh=${Date.now()}`);
        d.cells.filter((x) => x.case === c.id).forEach((x) => { S.cells[`${x.case}|${x.variant}`] = x; });
        delete S.details[c.id]; Object.keys(S.details).forEach((k) => { if (String(k).startsWith(c.id)) delete S.details[k]; });
      } catch { continue; }
      const el = $("grid").querySelector(`[data-case="${CSS.escape(c.id)}"]`);
      if (el) { el.outerHTML = cardHtml(c, shown(c)); fill($("grid").querySelector(`[data-case="${CSS.escape(c.id)}"]`)); }
    }
    say(`job ${j.id} ${j.state}${st ? `: ${st}` : ""}`);
  }

  $("grid").onclick = (e) => {
    const card = e.target.closest(".card"); if (!card) return;
    const chip = e.target.closest("[data-v]"), c = S.cases[card.dataset.case];
    if (e.target.closest("[data-rerun]")) { e.stopPropagation(); rerun(c); return; }
    if (chip) {
      S.tab[c.id] = chip.dataset.v;
      card.outerHTML = cardHtml(c, shown(c));
      const el = $("grid").querySelector(`[data-case="${CSS.escape(c.id)}"]`); fill(el);
      return;
    }
    if (card.dataset.id) openFull(c.id, +card.dataset.id);
  };
  $("grid").onkeydown = (e) => { if (e.key === "Enter" && e.target.classList.contains("card") && e.target.dataset.id) openFull(e.target.dataset.case, +e.target.dataset.id); };

  // ---------- start ----------
  async function strategies() {
    try {
      const ss = await get("/api/ladder/strategies");
      $("pick").innerHTML = ss.map((s) => `<option${s.name === S.name ? " selected" : ""}>${esc(s.name)}</option>`).join("");
      if (!S.name) { S.name = ss.find((s) => s.available)?.name || ss[0].name; start(); }
    } catch { /* the picker stays empty */ }
  }
  $("pick").onchange = (e) => { location.href = `/ladder/strategy?name=${enc(e.target.value)}`; };

  async function start() {
    if (!S.name) return;
    const t0 = performance.now();
    let d;
    try { d = await get(`/api/ladder/strategy/${enc(S.name)}`); } catch (e) { $("head").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    S.data = d;
    d.cases.forEach((c) => { S.cases[c.id] = c; });
    d.cells.forEach((x) => { S.cells[`${x.case}|${x.variant}`] = x; });
    header(d);
    $("hist").hidden = false; $("controls").hidden = false; $("legend").hidden = false;
    controls(d);
    grid();
    rateChart(d.timeline); changesChart(d.timeline);
    loadTime();
    $("status").textContent = `${Math.round(performance.now() - t0)} ms`;
  }
  start();
  strategies();
  let rw = innerWidth;
  addEventListener("resize", () => { if (Math.abs(innerWidth - rw) > 60 && S.data) { rw = innerWidth; rateChart(S.data.timeline); changesChart(S.data.timeline); if (S.time) timeChart(S.time); } });
})();
