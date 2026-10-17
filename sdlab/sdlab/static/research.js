// SD Lab research view: read only. The research topics (docs/research) as a board, each document
// rendered on click; the bench's saved runs over time; one run example by example; two runs compared.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v) => (v === null || v === undefined || !Number.isFinite(+v) ? "–" : `${(100 * v).toFixed(1)}%`);
  const sgn = (v) => (v > 0 ? "+" : v < 0 ? "−" : "");
  const pts = (d) => `${sgn(d)}${Math.abs(100 * d).toFixed(1)}`;
  const S = { runs: [], goal: { skill20: 0.9, skill100: 0.8 }, cache: {}, metric: "skill20", by: "branch", highlight: "", complete: true };
  const params = new URLSearchParams(location.search);
  function setStatus(t, err) { $("status").textContent = t; $("status").classList.toggle("error", !!err); }
  async function get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: ${r.status}`);
    return r.json();
  }
  function remember() {
    const u = new URL(location.href);
    [["run", $("run-a").value], ["a", $("cmp-a").value], ["b", $("cmp-b").value]].forEach(([k, v]) => (v ? u.searchParams.set(k, v) : u.searchParams.delete(k)));
    history.replaceState(null, "", u);
  }

  // ---------- markdown, rendered safely: everything is escaped first, then only known syntax becomes markup ----------
  function inline(text, base) {
    return text.split(/(`[^`]*`)/).map((part, i) => {
      if (i % 2) return `<code>${esc(part.slice(1, -1))}</code>`;
      let s = esc(part);
      s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
        const raw = url.replace(/&amp;/g, "&");
        if (/^https?:\/\//i.test(raw)) return `<a href="${esc(raw)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
        const doc = resolve(base, raw.split("#")[0]);
        if (doc && /\.md$/.test(doc)) return `<a href="#" data-doc="${esc(doc)}">${label}</a>`;
        return label;                                     // anything else stays text
      });
      s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>").replace(/(^|\W)_([^_\s][^_]*)_(?=\W|$)/g, "$1<i>$2</i>");
      return s;
    }).join("");
  }
  // a relative link inside docs/research ("frols.md", "literature/x.md", "../x.md" leaves it: null)
  function resolve(base, rel) {
    if (!rel || rel.startsWith("/")) return null;
    const parts = base.split("/").slice(0, -1);
    for (const p of rel.split("/")) {
      if (p === "..") { if (!parts.length) return null; parts.pop(); } else if (p && p !== ".") parts.push(p);
    }
    return parts.join("/");
  }
  function md(src, base) {
    const lines = src.replace(/\r/g, "").split("\n"), out = [];
    let i = 0;
    const para = [];
    const flush = () => { if (para.length) { out.push(`<p>${inline(para.join(" "), base)}</p>`); para.length = 0; } };
    const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
    while (i < lines.length) {
      const l = lines[i];
      if (/^```/.test(l)) {
        flush();
        const code = [];
        for (i++; i < lines.length && !/^```/.test(lines[i]); i++) code.push(lines[i]);
        out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); i++; continue;
      }
      const h = /^(#{1,6})\s+(.*)$/.exec(l);
      if (h) { flush(); out.push(`<h${h[1].length + 1}>${inline(h[2], base)}</h${h[1].length + 1}>`); i++; continue; }
      if (/^\s*\|/.test(l) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        flush();
        const head = cells(l), rows = [];
        for (i += 2; i < lines.length && /^\s*\|/.test(lines[i]); i++) rows.push(cells(lines[i]));
        out.push(`<div class="tablewrap"><table class="rtable"><thead><tr>${head.map((c) => `<th>${inline(c, base)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c, base)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      if (/^\s*([-*+]|\d+\.)\s+/.test(l)) {
        flush();
        const ordered = /^\s*\d+\./.test(l), items = [];
        while (i < lines.length && (/^\s*([-*+]|\d+\.)\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
          if (/^\s*([-*+]|\d+\.)\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ""));
          else items[items.length - 1] += " " + lines[i].trim();
          i++;
        }
        out.push(`<${ordered ? "ol" : "ul"}>${items.map((x) => `<li>${inline(x, base)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
        continue;
      }
      if (/^>\s?/.test(l)) {
        flush();
        const q = [];
        for (; i < lines.length && /^>\s?/.test(lines[i]); i++) q.push(lines[i].replace(/^>\s?/, ""));
        out.push(`<blockquote>${inline(q.join(" "), base)}</blockquote>`); continue;
      }
      if (/^\s*(---+|\*\*\*+)\s*$/.test(l)) { flush(); out.push("<hr>"); i++; continue; }
      if (!l.trim()) { flush(); i++; continue; }
      para.push(l.trim()); i++;
    }
    flush();
    return out.join("\n");
  }

  // ---------- topics ----------
  const KINDS = [["running", "Running"], ["done", "Done"], ["idea", "Ideas"], ["other", "Other"]];
  async function loadTopics() {
    const r = await get("/api/research/topics");
    $("topics-intro").innerHTML = inline(r.intro.split("\n")[0] || "", "README.md") + ` <a href="#" data-doc="README.md">The index</a>.`;
    $("board").innerHTML = KINDS.map(([k, name]) => {
      const list = r.topics.filter((t) => t.kind === k);
      if (!list.length) return "";
      return `<div class="bcol bcol-${k}"><h3>${name} <span class="muted small">${list.length}</span></h3>${list.map((t) => `
        <button class="card" ${t.file ? `data-doc="${esc(t.file)}"` : "disabled"} title="${esc(t.file ? "Open the topic's document" : "No document yet")}">
          <span class="ctitle">${esc(t.title)}</span>
          <span class="cstatus">${esc(t.status)}</span>
          ${t.verdict ? `<span class="cverdict">${esc(t.verdict)}</span>` : ""}
        </button>`).join("")}</div>`;
    }).join("");
    $("other-docs").innerHTML = r.documents.length ? `<h3>Other documents</h3><div class="chips">${r.documents.map((d) => `<button class="btn small" data-doc="${esc(d)}">${esc(d.replace(/\.md$/, ""))}</button>`).join("")}</div>` : "";
  }
  async function openDoc(name) {
    try {
      const r = await get(`/api/research/topics/${name.split("/").map(encodeURIComponent).join("/")}`);
      $("doc-name").textContent = `docs/research/${r.name}`;
      $("doc-body").innerHTML = md(r.markdown, r.name);
      $("doc").hidden = false; $("doc").scrollTop = 0; $("doc-close").focus();
    } catch (e) { setStatus(`Could not open ${name}`, true); }
  }
  document.addEventListener("click", (e) => {
    const d = e.target.closest("[data-doc]");
    if (d) { e.preventDefault(); openDoc(d.dataset.doc); }
  });
  $("doc-close").addEventListener("click", () => { $("doc").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("doc").hidden = true; });

  // ---------- bench history ----------
  const METRICS = [["skill20", "mean skill@20"], ["skill100", "mean skill@100"], ["fresh20", "fresh runs: mean skill@20"], ["fresh100", "fresh runs: mean skill@100"], ["meets", "runs meeting the goal"]];
  const groupOf = (r) => (S.by === "branch" ? r.branch : r.engine) || "(none)";
  const runName = (r) => `${(r.at || "").slice(0, 16).replace("T", " ")}${r.baseline ? ` [baseline ${r.baseline}]` : ""}${r.label ? ` ${r.label}` : ""}`;
  function usable() {
    const ok = S.runs.filter((r) => !r.broken);
    const full = Math.max(0, ...ok.map((r) => r.n));
    return S.complete ? ok.filter((r) => r.n === full) : ok;
  }
  function renderControls() {
    // groups by how many runs they have; the one with most (besides the main line) is highlighted first
    const count = {};
    usable().forEach((r) => { count[groupOf(r)] = (count[groupOf(r)] || 0) + 1; });
    const groups = Object.keys(count).sort((a, b) => count[b] - count[a] || (a < b ? -1 : 1));
    if (!groups.includes(S.highlight)) S.highlight = groups.find((g) => g !== main() && g !== "(none)") || "";
    $("history-controls").innerHTML = `
      <label>Show <select id="metric">${METRICS.map(([v, l]) => `<option value="${v}" ${v === S.metric ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label>Group by <select id="by"><option value="branch" ${S.by === "branch" ? "selected" : ""}>branch</option><option value="engine" ${S.by === "engine" ? "selected" : ""}>strategy</option></select></label>
      <label>Highlight <select id="hl">${groups.filter((g) => g !== main()).map((g) => `<option value="${esc(g)}" ${g === S.highlight ? "selected" : ""}>${esc(g)} (${count[g]})</option>`).join("")}</select></label>
      <label><input type="checkbox" id="complete" ${S.complete ? "checked" : ""}> only runs over every example and length</label>`;
    $("metric").addEventListener("change", (e) => { S.metric = e.target.value; renderHistory(); });
    $("by").addEventListener("change", (e) => { S.by = e.target.value; S.highlight = ""; renderControls(); renderHistory(); });
    $("hl").addEventListener("change", (e) => { S.highlight = e.target.value; renderHistory(); });
    $("complete").addEventListener("change", (e) => { S.complete = e.target.checked; renderControls(); renderHistory(); });
  }
  const main = () => (S.by === "branch" ? "sdlab" : "matrix");                // the main line of discovery
  function renderHistory() {
    const runs = usable().filter((r) => r.at), m = S.metric, isCount = m === "meets";
    const val = (r) => (isCount ? r.meets : r[m]);
    const shown = runs.filter((r) => val(r) !== null && val(r) !== undefined);
    const box = $("chart");
    if (!shown.length) { box.innerHTML = `<p class="note">No runs to show${S.complete ? " (try including runs over fewer examples)" : ""}.</p>`; $("legend").innerHTML = ""; return; }
    const W = Math.max(320, box.clientWidth || 800), H = 280, P = { l: 52, r: 16, t: 14, b: 34 };
    const ts = shown.map((r) => Date.parse(r.at)), t0 = Math.min(...ts), t1 = Math.max(...ts) || t0 + 1;
    const vs = shown.map(val), goal = isCount ? null : m.endsWith("100") ? S.goal.skill100 : S.goal.skill20;
    let lo = isCount ? 0 : Math.min(...vs, goal), hi = isCount ? Math.max(...vs, ...shown.map((r) => r.n)) : Math.max(...vs, goal, 1);
    if (hi - lo < 1e-9) hi = lo + 1;
    // round ticks: a step of 1, 2, 2.5 or 5 times a power of ten, about five of them
    const raw = (hi - lo) / 5, mag = 10 ** Math.floor(Math.log10(raw)), step = mag * [1, 2, 2.5, 5, 10].find((m) => m * mag >= raw);
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    const x = (t) => P.l + (W - P.l - P.r) * (t1 > t0 ? (t - t0) / (t1 - t0) : 0.5), y = (v) => P.t + (H - P.t - P.b) * (1 - (v - lo) / (hi - lo));
    const grid = [];
    for (let v = lo; v <= hi + step / 2; v += step) {
      grid.push(`<line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${P.l - 6}" y="${y(v) + 4}" class="axis" text-anchor="end">${isCount ? Math.round(v) : `${+(100 * v).toFixed(1)}%`}</text>`);
    }
    const days = [...new Set(shown.map((r) => r.at.slice(0, 10)))];
    const xt = (t1 > t0 ? [t0, (t0 + t1) / 2, t1] : [t0]).map((t) => `<text x="${x(t)}" y="${H - 10}" class="axis" text-anchor="middle">${new Date(t).toISOString().slice(days.length > 1 ? 5 : 11, 16).replace("T", " ")}</text>`);
    const cls = (r) => (groupOf(r) === main() ? "s1" : groupOf(r) === S.highlight ? "s2" : "s0");
    // the main line and the highlighted group are joined in time order; everything else is grey dots
    const line = (c) => { const p = shown.filter((r) => cls(r) === c).sort((a, b) => Date.parse(a.at) - Date.parse(b.at)); return p.length > 1 ? `<polyline class="ln ${c}" points="${p.map((r) => `${x(Date.parse(r.at))},${y(val(r))}`).join(" ")}"/>` : ""; };
    const order = ["s0", "s2", "s1"];
    const dots = order.flatMap((c) => shown.filter((r) => cls(r) === c).map((r) => {
      const cx = x(Date.parse(r.at)), cy = y(val(r));
      return r.baseline ? `<rect class="pt ${c} base" x="${cx - 5}" y="${cy - 5}" width="10" height="10" transform="rotate(45 ${cx} ${cy})" data-file="${esc(r.file)}"/>`
        : `<circle class="pt ${c}" cx="${cx}" cy="${cy}" r="4.5" data-file="${esc(r.file)}"/>`;
    }));
    const goalLine = goal !== null ? `<line class="goal" x1="${P.l}" x2="${W - P.r}" y1="${y(goal)}" y2="${y(goal)}"/><text class="axis" x="${W - P.r}" y="${y(goal) - 5}" text-anchor="end">goal ${Math.round(100 * goal)}% per run</text>` : "";
    box.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="${esc(METRICS.find((q) => q[0] === m)[1])} of each bench run over time">${grid.join("")}${xt.join("")}${goalLine}${line("s2")}${line("s1")}${dots.join("")}</svg>`;
    const count = (c) => shown.filter((r) => cls(r) === c).length;
    $("legend").innerHTML = `<span><i class="sw s1"></i>${esc(main())} (the main line, ${count("s1")})</span>${S.highlight ? `<span><i class="sw s2"></i>${esc(S.highlight)} (${count("s2")})</span>` : ""}<span><i class="sw s0"></i>other (${count("s0")})</span><span><i class="sw dia"></i>a named baseline</span>`;
    $("history-note").textContent = `${shown.length} of ${S.runs.length} saved runs${S.complete ? `, those over every example and length (${Math.max(0, ...usable().map((r) => r.n))} runs each)` : ""}. Mean skill is each example's skill clipped at −100%, averaged; the goal is skill@20 ≥ ${pct(S.goal.skill20)} and skill@100 ≥ ${pct(S.goal.skill100)} for every example at every length. Hover a point for the run; click it to see it example by example.`;
    box.querySelectorAll(".pt").forEach((p) => {
      const r = S.runs.find((q) => q.file === p.dataset.file);
      p.addEventListener("pointerenter", (e) => tip(e, `<b>${esc(r.label || r.file)}</b><br>${esc(r.at)}<br>${esc(r.branch)} · ${esc(r.engine)} · ${esc(r.commit)}${r.baseline ? `<br>baseline "${esc(r.baseline)}"` : ""}<br>skill@20 ${pct(r.skill20)}, @100 ${pct(r.skill100)}; meets ${r.meets} of ${r.n}${r.fresh20 !== null ? `<br>fresh: @20 ${pct(r.fresh20)}, @100 ${pct(r.fresh100)}; meets ${r.freshMeets}` : ""}`));
      p.addEventListener("pointerleave", () => tip());
      p.addEventListener("click", () => { $("run-a").value = r.file; renderRun(); remember(); $("run").scrollIntoView({ behavior: "smooth" }); });
    });
  }
  function tip(e, html) {
    const t = $("tip");
    if (!e) { t.hidden = true; return; }
    t.innerHTML = html; t.hidden = false;
    const x = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8), y = Math.min(e.clientY + 14, innerHeight - t.offsetHeight - 8);
    t.style.left = `${x}px`; t.style.top = `${y}px`;
  }
  function renderRunsTable() {
    const runs = [...S.runs].reverse();
    $("runs-count").textContent = `${runs.length} saved, newest first`;
    $("runs").innerHTML = `<thead><tr><th>when (UTC)</th><th>label</th><th>branch</th><th>strategy</th><th>commit</th><th>runs</th><th>skill@20</th><th>skill@100</th><th>meet goal</th><th>fresh @20</th><th>fresh @100</th><th>fresh meet</th><th></th></tr></thead><tbody>${runs.map((r) => r.broken
      ? `<tr><td colspan="13" class="muted">${esc(r.file)}: not a readable run</td></tr>`
      : `<tr><td class="mono">${esc((r.at || "").slice(0, 19).replace("T", " "))}</td><td>${r.baseline ? `<span class="chip">baseline ${esc(r.baseline)}</span> ` : ""}${esc(r.label)}</td><td>${esc(r.branch)}</td><td>${esc(r.engine)}</td><td class="mono">${esc(r.commit)}</td>
         <td class="num">${r.n}</td><td class="num">${pct(r.skill20)}</td><td class="num">${pct(r.skill100)}</td><td class="num">${r.meets} / ${r.n}</td>
         <td class="num">${pct(r.fresh20)}</td><td class="num">${pct(r.fresh100)}</td><td class="num">${r.freshMeets ?? "–"}</td>
         <td class="acts"><button class="btn small" data-show="${esc(r.file)}" title="See this run example by example">show</button><button class="btn small" data-cmp-a="${esc(r.file)}" title="Compare: use as the run before">A</button><button class="btn small" data-cmp-b="${esc(r.file)}" title="Compare: use as the run after">B</button></td></tr>`).join("")}</tbody>`;
    $("runs").querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => { $("run-a").value = b.dataset.show; renderRun(); remember(); $("run").scrollIntoView({ behavior: "smooth" }); }));
    $("runs").querySelectorAll("[data-cmp-a]").forEach((b) => b.addEventListener("click", () => { $("cmp-a").value = b.dataset.cmpA; renderCompare(); remember(); $("compare").scrollIntoView({ behavior: "smooth" }); }));
    $("runs").querySelectorAll("[data-cmp-b]").forEach((b) => b.addEventListener("click", () => { $("cmp-b").value = b.dataset.cmpB; renderCompare(); remember(); $("compare").scrollIntoView({ behavior: "smooth" }); }));
    const bases = S.runs.filter((r) => r.baseline);
    $("baselines").innerHTML = bases.length ? bases.map((r) => `<button class="btn small" data-show="${esc(r.file)}" title="${esc(`${r.label || ""} (${r.at}, ${r.branch} ${r.commit}): skill@20 ${pct(r.skill20)}, @100 ${pct(r.skill100)}, meets ${r.meets} of ${r.n}`)}"><b>${esc(r.baseline)}</b> <span class="muted">${pct(r.skill20)} / ${pct(r.skill100)} · ${r.meets}/${r.n}</span></button>`).join("")
      : `<p class="note">No named baselines (evaluate.py --save NAME).</p>`;
    $("baselines").querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => { $("run-a").value = b.dataset.show; renderRun(); remember(); $("run").scrollIntoView({ behavior: "smooth" }); }));
  }

  // ---------- one run, and two compared ----------
  async function runData(file) {
    if (!file) return null;
    if (!S.cache[file]) S.cache[file] = get(`/api/research/runs/${encodeURIComponent(file)}`);
    return S.cache[file];
  }
  const v = (x, key, h) => { const o = x && x[key]; const n = o && o[String(h)]; return Number.isFinite(n) ? n : null; };
  // a cell coloured by its distance to the goal: met, close (within 20 points), or far
  function goalCell(s, goal) {
    if (s === null) return `<td class="num muted">–</td>`;
    const d = s - goal, c = d >= 0 ? "met" : d > -0.2 ? "near" : d > -1 ? "far" : "vfar";
    return `<td class="num hc ${c}" title="${d >= 0 ? "meets the goal" : `${pts(d)} points from the goal (${pct(goal)})`}">${d >= 0 ? "✓ " : ""}${pct(s)}</td>`;
  }
  function deltaCell(d) {
    if (d === null) return `<td class="num muted">–</td>`;
    const c = Math.abs(d) < 0.0005 ? "same" : d > 0 ? (d > 0.02 ? "up" : "upish") : (d < -0.02 ? "down" : "downish");
    return `<td class="num hc ${c}">${Math.abs(d) < 0.0005 ? "0" : pts(d)}</td>`;
  }
  const lengthOrder = (a, b) => (a === b ? 0 : a === "default" ? -1 : b === "default" ? 1 : a === "long" ? 1 : b === "long" ? -1 : (+a || 0) - (+b || 0));
  async function renderRun() {
    const file = $("run-a").value, r = await runData(file).catch(() => null);
    if (!r || $("run-a").value !== file) { if (!r) $("heat").innerHTML = `<p class="note">Could not read that run.</p>`; return; }
    const res = r.results || [], lengths = [...new Set(res.map((x) => String(x.length)))].sort(lengthOrder);
    const examples = [...new Set(res.map((x) => x.example))].sort();
    const at = (e, l) => res.find((x) => x.example === e && String(x.length) === l);
    const hasFresh = res.some((x) => x.fresh);
    const cols = [["skill", 20, S.goal.skill20, "skill@20"], ["skill", 100, S.goal.skill100, "skill@100"], ...(hasFresh ? [["fresh", 20, S.goal.skill20, "fresh@20"], ["fresh", 100, S.goal.skill100, "fresh@100"]] : [])];
    const s = r.summary;
    $("heat").innerHTML = `<p class="note"><b>${esc(r.label || file)}</b> · ${esc(r.at)} · ${esc(r.branch)} · ${esc(r.engine)} · ${esc(r.commit)}. Mean skill@20 ${pct(s.skill20)}, @100 ${pct(s.skill100)}; ${s.meets} of ${s.n} meet the goal${s.fresh20 !== null ? `; on fresh runs ${pct(s.fresh20)}, ${pct(s.fresh100)}, ${s.freshMeets} meet it` : ""}. Cells: ✓ meets its goal (skill@20 ≥ ${pct(S.goal.skill20)}, skill@100 ≥ ${pct(S.goal.skill100)}); amber within 20 points; red further.</p>
      <div class="tablewrap"><table class="rtable heat"><thead><tr><th rowspan="2">example</th>${lengths.map((l) => `<th colspan="${cols.length + 1}" class="lenhead">${esc(l)}</th>`).join("")}</tr>
      <tr>${lengths.map(() => cols.map((c) => `<th class="num">${c[3]}</th>`).join("") + `<th class="num">parts</th>`).join("")}</tr></thead>
      <tbody>${examples.map((e) => `<tr><th>${esc(e)}</th>${lengths.map((l) => {
        const x = at(e, l);
        if (!x) return cols.map(() => `<td class="muted">–</td>`).join("") + `<td></td>`;
        const t = `${x.steps} steps, ${x.flows} flows, ${x.ms} ms${x.chosen ? `; ${x.chosen}` : ""}${x.error ? `; ERROR ${x.error}` : ""}`;
        return cols.map((c) => goalCell(v(x, c[0], c[1]), c[2])).join("") + `<td class="num muted" title="${esc(t)}">${x.error ? "error" : `${x.parts}/${x.of}`}</td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  async function renderCompare() {
    const fa = $("cmp-a").value, fb = $("cmp-b").value;
    const [a, b] = await Promise.all([runData(fa).catch(() => null), runData(fb).catch(() => null)]);
    if ($("cmp-a").value !== fa || $("cmp-b").value !== fb) return;
    if (!a || !b) { $("cmp").innerHTML = `<p class="note">Choose two runs.</p>`; return; }
    const key = (x) => `${x.example}\u0000${x.length}`;
    const ra = new Map((a.results || []).map((x) => [key(x), x])), rb = new Map((b.results || []).map((x) => [key(x), x]));
    const keys = [...new Set([...ra.keys(), ...rb.keys()])].sort((p, q) => { const [e1, l1] = p.split("\u0000"), [e2, l2] = q.split("\u0000"); return e1 === e2 ? lengthOrder(l1, l2) : e1 < e2 ? -1 : 1; });
    const both = keys.filter((k) => ra.has(k) && rb.has(k));
    const mean = (m, key2, h) => both.length ? both.reduce((s, k) => s + Math.max(-1, v(m.get(k), key2, h) ?? -1), 0) / both.length : null;
    const d = (p, q) => (p === null || q === null ? null : q - p);
    const head = [["skill", 20, "skill@20"], ["skill", 100, "skill@100"], ["fresh", 20, "fresh@20"], ["fresh", 100, "fresh@100"]];
    const meets = (x) => x && !x.error && v(x, "skill", 20) >= S.goal.skill20 && v(x, "skill", 100) >= S.goal.skill100;
    const gained = both.filter((k) => !meets(ra.get(k)) && meets(rb.get(k))).length, lost = both.filter((k) => meets(ra.get(k)) && !meets(rb.get(k))).length;
    $("cmp").innerHTML = `<p class="note">${both.length} example runs in both. Over those, mean skill@20 ${pct(mean(ra, "skill", 20))} → ${pct(mean(rb, "skill", 20))}, skill@100 ${pct(mean(ra, "skill", 100))} → ${pct(mean(rb, "skill", 100))}; ${gained} newly meet the goal, ${lost} no longer do. Deltas are in points; green better, red worse (pale under 2 points).</p>
      <div class="tablewrap"><table class="rtable heat"><thead><tr><th>example</th><th>length</th>${head.map((h) => `<th class="num">${h[2]} before</th><th class="num">after</th><th class="num">Δ</th>`).join("")}<th>goal</th></tr></thead>
      <tbody>${keys.map((k) => {
        const [e, l] = k.split("\u0000"), x = ra.get(k), y = rb.get(k);
        return `<tr><th>${esc(e)}</th><td>${esc(l)}</td>${head.map(([kk, h]) => { const p = v(x, kk, h), q = v(y, kk, h); return `<td class="num">${pct(p)}</td><td class="num">${pct(q)}</td>${deltaCell(d(p, q))}`; }).join("")}
          <td>${!x || !y ? (x ? "only before" : "only after") : meets(x) === meets(y) ? (meets(y) ? "✓ both" : "") : meets(y) ? "✓ now meets" : "no longer meets"}</td></tr>`;
      }).join("")}</tbody></table></div>`;
  }
  function fillSelects() {
    const opts = (sel) => [...S.runs].reverse().filter((r) => !r.broken).map((r) => `<option value="${esc(r.file)}" ${r.file === sel ? "selected" : ""}>${esc(runName(r))} — ${esc(r.branch)}, ${esc(r.engine)}, ${r.n} runs</option>`).join("");
    const ok = S.runs.filter((r) => !r.broken), latest = ok[ok.length - 1], has = (f) => ok.some((r) => r.file === f);
    const base = ok.find((r) => r.baseline === "v2.1") || [...ok].reverse().find((r) => r.baseline);
    const pick = (k, dflt) => (has(params.get(k)) ? params.get(k) : dflt && dflt.file);
    $("run-a").innerHTML = opts(pick("run", latest));
    $("cmp-a").innerHTML = opts(pick("a", base || ok[ok.length - 2]));
    $("cmp-b").innerHTML = opts(pick("b", latest));
    ["run-a"].forEach((id) => $(id).addEventListener("change", () => { renderRun(); remember(); }));
    ["cmp-a", "cmp-b"].forEach((id) => $(id).addEventListener("change", () => { renderCompare(); remember(); }));
  }

  async function start() {
    loadTopics().catch((e) => { $("board").innerHTML = `<p class="note">Could not read the research topics (${esc(e.message)}).</p>`; });
    try {
      const r = await get("/api/research/runs");
      S.runs = r.runs; S.goal = r.goal;
      if (!S.runs.length) {
        $("history-note").textContent = `No saved bench runs in ${r.folder} (tests/bench/evaluate.py saves them there).`;
        return;
      }
      renderControls(); renderHistory(); renderRunsTable(); fillSelects(); renderRun(); renderCompare();
      setStatus(`${S.runs.length} bench runs in ${r.folder}`);
    } catch (e) { setStatus(`Could not read the bench runs: ${e.message}`, true); }
    let w = innerWidth;
    addEventListener("resize", () => { if (Math.abs(innerWidth - w) > 20) { w = innerWidth; if (S.runs.length) renderHistory(); } });
  }
  start();
})();
