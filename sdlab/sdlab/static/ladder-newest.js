// The newest cases page (/ladder/new): reads /api/ladder/newest (newest.py) once, then filters in the page.
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const md = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  const enc = encodeURIComponent;
  const pct = (v) => (v == null || Number.isNaN(v) ? "–" : (100 * v).toFixed(1) + "%");
  const TESTS = new Set(["test", "distilled", "noisy", "canonical"]);
  const SET = { test: "tests", distilled: "tests", noisy: "tests", canonical: "tests", realistic: "realistic", physics: "physics", particles: "physics", real: "real" };
  const WORD = { P: "pass", E: "equivalent", "~": "fits", F: "fail", X: "error", T: "timeout", ".": "not run" };
  let D = null;
  const F = { win: "h6", kind: "", everyone: false, q: "" };
  try { Object.assign(F, JSON.parse(localStorage.getItem("sdlab.newest") || "{}")); } catch { /* defaults */ }
  const save = () => { try { localStorage.setItem("sdlab.newest", JSON.stringify(F)); } catch { /* fine */ } };

  function when(iso) {
    if (!iso) return "–";
    const d = new Date(iso), h = (Date.now() - d) / 3.6e6;
    const ago = h < 1 ? `${Math.max(1, Math.round(h * 60))} min ago` : h < 48 ? `${h.toFixed(h < 10 ? 1 : 0)} h ago` : `${Math.round(h / 24)} days ago`;
    return `${d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} (${ago})`;
  }
  // the commits that added cases, newest first: {commit, at, subject, n}
  function batches() {
    const by = new Map();
    for (const r of D.rows) {
      const k = r.added.commit || "uncommitted";
      const b = by.get(k) || { commit: r.added.commit, at: r.added.at, subject: r.added.subject, n: 0 };
      b.n += 1; if (r.added.at && (!b.at || r.added.at < b.at)) b.at = r.added.at;
      by.set(k, b);
    }
    return [...by.values()].sort((a, b) => (b.at || "").localeCompare(a.at || ""));
  }
  // the newest commit that added Tests cases (the batch most likely behind a pass-rate drop)
  function latestTests() {
    const r = D.rows.filter((x) => x.added.commit && TESTS.has(x.kind)).sort((a, b) => b.added.at.localeCompare(a.added.at))[0];
    return r ? batches().find((b) => b.commit === r.added.commit) : null;
  }
  function cutoff() {
    if (F.win === "all") return null;
    if (F.win === "latest") { const b = latestTests(); return b ? b.at : null; }
    if (F.win.startsWith("h")) return new Date(Date.now() - +F.win.slice(1) * 3.6e6).toISOString().replace(/\.\d+Z$/, "Z");
    if (F.win.startsWith("c:")) return F.win.slice(2);
    return null;
  }
  const winText = () => $("win").selectedOptions[0] ? $("win").selectedOptions[0].textContent : "";
  const isNew = (r, cut) => cut != null && !!r.added.at && r.added.at >= cut;

  function fillWindows() {
    const lt = latestTests();
    const opts = [...(lt ? [["latest", `with the latest Tests batch (${lt.commit.slice(0, 7)}: ${(lt.subject || "").slice(0, 50)})`]] : []), ["h3", "in the last 3 h"], ["h6", "in the last 6 h"], ["h24", "in the last 24 h"], ["h168", "in the last 7 days"], ["all", "at any time"]];
    for (const b of batches().slice(0, 40)) if (b.at) opts.push([`c:${b.at}`, `since ${b.commit ? b.commit.slice(0, 7) : "now"}: ${(b.subject || "not committed yet").slice(0, 60)}`]);
    $("win").innerHTML = opts.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
    if (![...$("win").options].some((o) => o.value === F.win)) F.win = "h6";
    $("win").value = F.win;
  }

  function impact() {
    const cut = cutoff(), rows = D.rows.filter((r) => TESTS.has(r.kind));
    const fresh = rows.filter((r) => isNew(r, cut));
    const line = (name, get) => {
      const a = [0, 0], o = [0, 0], n = [0, 0];
      for (const r of rows) {
        const x = get(r); if (!x) continue;
        a[0] += x[0]; a[1] += x[1];
        const t = isNew(r, cut) ? n : o; t[0] += x[0]; t[1] += x[1];
      }
      const all = a[1] ? a[0] / a[1] : NaN, old = o[1] ? o[0] / o[1] : NaN, nw = n[1] ? n[0] / n[1] : NaN;
      return { name, all, old, nw, a, o, n, delta: all - old };
    };
    const ls = D.leaders.map((l) => line(l.name, (r) => (r.leaders[l.name] ? [r.leaders[l.name].p, r.leaders[l.name].n] : null)));
    const pooled = line("every strategy (pooled)", (r) => [r.all.cells_pass, r.all.cells_run]);
    const meanOld = ls.map((x) => x.old).filter((v) => !Number.isNaN(v)), meanNew = ls.map((x) => x.nw).filter((v) => !Number.isNaN(v));
    const avg = (v) => (v.length ? v.reduce((p, q) => p + q, 0) / v.length : NaN);
    const reg = D.regressions;
    const verdict = cut == null ? "Pick a window to split the Tests cases into new and old."
      : !fresh.length ? `No Tests case was added ${esc(winText())}.`
      : `<b>${fresh.length}</b> of ${rows.length} Tests cases were added ${esc(winText())}. The leaders pass <b>${pct(avg(meanNew))}</b> of their cells on them
         and <b>${pct(avg(meanOld))}</b> on the older cases. ` + (reg == null ? "Regressions are still being computed."
         : reg.n_fail ? `<b class="down">${reg.n_fail} cell${reg.n_fail > 1 ? "s" : ""} regressed</b> (a strategy now fails a cell its previous version passed; see below).`
         : "No strategy fails a cell its previous version passed, so the drop is the new cases, not a regression.");
    const tr = (x, cls = "") => `<tr class="${cls}"><td class="l">${D.leaders.some((l) => l.name === x.name) ? `<a href="/ladder/strategy?name=${enc(x.name)}&kind=tests">${esc(x.name)}</a>` : esc(x.name)}</td>
      <td class="num" title="${x.a[0]} of ${x.a[1]} cells run">${pct(x.all)}</td>
      <td class="num" title="${x.o[0]} of ${x.o[1]} cells run">${pct(x.old)}</td>
      <td class="num" title="${x.n[0]} of ${x.n[1]} cells run">${pct(x.nw)} <span class="muted small hide-sm">(${x.n[0]}/${x.n[1]})</span></td>
      <td class="num ${x.delta < -0.0005 ? "down" : ""}">${Number.isNaN(x.delta) ? "–" : (x.delta >= 0 ? "+" : "") + (100 * x.delta).toFixed(1)}</td></tr>`;
    $("impact").innerHTML = `<div class="callout">${verdict}</div>
      <div class="wrap"><table><thead><tr><th class="l">strategy (the ${D.leaders.length} best by Tests pass rate)</th><th>Tests pass rate</th>
        <th title="The same rate without the cases added in the window">without new cases</th><th>on new cases only</th>
        <th title="Points the new cases take off the pass rate">change from new cases</th></tr></thead>
      <tbody>${ls.map((x) => tr(x)).join("")}${tr(pooled, "muted")}</tbody></table></div>
      <p class="note small">Rates are over the cells each strategy has run (as on the leaderboard); hover for counts. Tests = the kinds test, distilled, noisy
      and canonical (realistic, physics, particles and real data are never in it).</p>`;
  }

  function regressions() {
    const r = D.regressions;
    if (r == null) { $("reg").innerHTML = `<p class="note">Being computed in the background (one pass over the result store); reload in a few seconds.</p>`; return; }
    const head = `<p class="note">A regression is a cell (case × variant) where a strategy's latest result is worse than its previous version's
      (a different strategy hash) on the same case (same case hash): pass → anything else, equivalent → fits, fail, error or timeout, or fits → fail, error or timeout. Checked over every
      strategy, ${esc(when(r.computed))}.</p>`;
    if (!r.n) { $("reg").innerHTML = head + `<div class="callout up">None: no strategy fails a cell that its previous version passed.</div>`; return; }
    const rows = r.items.map((x) => `<tr><td class="l"><a href="/ladder/strategy?name=${enc(x.strategy)}">${esc(x.strategy)}</a></td>
      <td class="l"><a href="/ladder?view=history&case=${enc(x.case)}&strategy=${enc(x.strategy)}">${esc(x.case)}</a></td><td class="l">${esc(x.variant)}</td>
      <td class="l">${esc(x.from)} → <b class="${x.to === "error" || x.to === "timeout" ? "" : "down"}">${esc(x.to)}</b></td>
      <td class="l small muted hide-sm">${esc(x.prev_hash)} → ${esc(x.hash)}</td><td class="l small">${x.scorer_changed ? "scorer changed between them" : x.to === "error" || x.to === "timeout" ? "error / timeout (may be load)" : "same scorer"}</td></tr>`).join("");
    $("reg").innerHTML = head + `<div class="callout"><b>${r.n}</b> regressed cell${r.n > 1 ? "s" : ""}: ${r.n_fail} now fail (${r.n_clean} with the same scorer),
      ${r.n - r.n_fail} now error or time out.</div>
      <div class="wrap"><table><thead><tr><th class="l">strategy</th><th class="l">case (history)</th><th class="l">variant</th><th class="l">before → now</th>
      <th class="l hide-sm">version</th><th class="l">note</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${r.truncated ? `<p class="note">and ${r.truncated} more (/api/ladder/newest/regressions)</p>` : ""}`;
  }

  function card(r) {
    const vs = r.variants;
    const lead = D.leaders.map((l) => {
      const x = r.leaders[l.name];
      if (!x) return "";
      const sq = x.v != null ? [...x.v].map((ch, i) => `<a class="sq s-${ch === "." ? "_" : ch === "~" ? "fits" : ch}" href="/ladder?view=now&case=${enc(r.id)}&variant=${enc(vs[i])}&strategy=${enc(l.name)}" title="${esc(`${l.name}, ${vs[i]}: ${WORD[ch]}`)}">${ch === "." ? "·" : ch}</a>`).join("")
        : `<span class="small muted">${r.n_draws} draws × ${vs.length} variants</span>`;
      return `<tr><td><a href="/ladder/strategy?name=${enc(l.name)}&kind=${SET[r.kind] === "tests" ? "tests" : SET[r.kind]}">${esc(l.name)}</a></td><td>${sq}</td>
        <td class="small muted num">${x.p}/${x.n} pass${x.e ? `, ${x.e} eq` : ""}${x.n < x.of ? `, ${x.of - x.n} not run` : ""}</td>
        <td class="small hide-sm"><a href="/ladder?view=now&strategy=${enc(l.name)}&variant=all&set=${SET[r.kind]}" class="muted">now</a></td></tr>`;
    }).join("");
    const f = r.from;
    return `<article class="case${r.fails_everyone ? " everyone" : ""}">
      <div class="chead"><a class="id" href="/ladder?view=cases&case=${enc(r.n_draws ? r.id + "#1" : r.id)}">${esc(r.id)}</a><span class="t">${esc(r.title)}</span>
        <span class="badge k-${esc(r.kind)}">${esc(r.kind)}</span><span class="badge">level ${esc(r.level)}</span>
        ${r.n_draws ? `<span class="badge">${r.n_draws} draws</span>` : ""}${r.fails_everyone ? `<span class="badge bad">fails for every strategy (${r.all.ran} ran)</span>` : ""}</div>
      <div class="small muted">added ${esc(when(r.added.at))} · ${r.added.committed ? `<code>${esc((r.added.commit || "").slice(0, 7))}</code> ${esc(r.added.subject || "")}` : "not committed yet (the file's time)"}</div>
      <div class="chips" title="Capabilities tested (motif tags)">${r.capabilities.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
      <p class="tests"><span class="muted">Tests:</span> ${esc(r.tests)}</p>
      ${f ? `<div class="from"><p><span class="muted">Distilled from:</span> ${md(f.hard)}</p><p><span class="muted">The mistake it reproduces:</span> ${md(f.mistake)}</p>
        <p class="small muted">From docs/LADDER.md, "Distilled cases"</p></div>` : ""}
      <table class="lead">${lead}</table>
      <div class="small muted">every strategy: ${r.all.passing} of ${r.all.ran} that ran pass at least one cell; ${r.all.cells_pass} of ${r.all.cells_run} cells pass</div>
    </article>`;
  }

  function list() {
    const cut = cutoff(), q = F.q.trim().toLowerCase();
    const rows = D.rows.filter((r) => (cut == null || isNew(r, cut))
      && (!F.kind || (F.kind === "tests" ? TESTS.has(r.kind) : r.kind === F.kind))
      && (!F.everyone || r.fails_everyone)
      && (!q || `${r.id} ${r.title} ${r.tests} ${r.tags.join(" ")}`.toLowerCase().includes(q)));
    $("count").textContent = `${rows.length} case file${rows.length === 1 ? "" : "s"} added ${winText()}${rows.filter((r) => r.fails_everyone).length ? `, ${rows.filter((r) => r.fails_everyone).length} failing for every strategy` : ""}`;
    let html = "", last = null;
    for (const r of rows) {
      const k = r.added.commit || "uncommitted";
      if (k !== last) {
        const n = rows.filter((x) => (x.added.commit || "uncommitted") === k).length;
        html += `<div class="batch">${r.added.commit ? `<code>${esc(r.added.commit.slice(0, 7))}</code> <b>${esc(r.added.subject || "")}</b>` : "<b>Not committed yet</b>"}
          <span class="muted small">· ${esc(when(r.added.at))} · ${n} case${n > 1 ? "s" : ""}</span></div>`;
        last = k;
      }
      html += card(r);
    }
    $("list").innerHTML = html || `<p class="note">No case matches.</p>`;
  }

  function render() { impact(); regressions(); list(); }

  async function load() {
    const res = await fetch("/api/ladder/newest");
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    D = await res.json();
    fillWindows();
    $("kind").value = F.kind; $("everyone").checked = !!F.everyone; $("q").value = F.q;
    render();
  }
  $("win").onchange = (e) => { F.win = e.target.value; save(); render(); };
  $("kind").onchange = (e) => { F.kind = e.target.value; save(); list(); };
  $("everyone").onchange = (e) => { F.everyone = e.target.checked; save(); list(); };
  $("q").oninput = (e) => { F.q = e.target.value; list(); };
  load().catch((e) => { $("impact").innerHTML = `<p class="note down">Could not load: ${esc(e.message)}</p>`; });
  setInterval(() => load().catch(() => {}), 60000);
})();
