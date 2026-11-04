// What discovery read and tried for one series, in a drawer (the Dynamics page's left-out rows and
// its stocks): the sparkline of what came back, the exact query (copyable, with a link to the Core
// page's External stores box), the kind it was taken for and on what evidence, the balances tried,
// every net-flow form tried with its inputs, R² and why it lost, how it fared as an input or a move,
// and the verdict in words with what would help. The record is sd/explain.py's
// (discovery.explain[key], served one series at a time by /api/dynamics/explain).
// Pure functions but `open`: tests/explain/explain-drawer.test.mjs.
const Explain = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => (v == null ? "—" : Math.abs(v) >= 1000 || Number.isInteger(v) ? Math.round(v).toLocaleString("en") : (+v).toPrecision(3));
  const r2 = (v) => (v == null ? "—" : (+v).toFixed(2));
  const dur = (s) => (s == null ? "?" : s < 120 ? `${Math.round(s)} s` : s < 7200 ? `${Math.round(s / 60)} min` : s < 172800 ? `${+(s / 3600).toFixed(1)} h` : `${+(s / 86400).toFixed(1)} d`);
  const plural = (n, w) => `${n} ${n === 1 || /series$/.test(w) ? w : /(s|ch)$/.test(w) ? w + "es" : w + "s"}`;
  // the sparkline: a polyline over the window, gaps where nothing came back
  function spark(values, w = 520, h = 56) {
    const vs = (values || []).filter((v) => v != null);
    if (!vs.length) return '<div class="muted">nothing came back in the window</div>';
    const lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1, n = values.length;
    const x = (i) => ((i + 0.5) / n) * w, y = (v) => h - 4 - ((v - lo) / span) * (h - 8);
    const runs = []; let cur = [];
    values.forEach((v, i) => { if (v == null) { if (cur.length) runs.push(cur); cur = []; } else cur.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`); });
    if (cur.length) runs.push(cur);
    return `<svg class="xp-spark" viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" role="img" aria-label="what came back, ${n} points over the window, from ${num(lo)} to ${num(hi)}">`
      + runs.map((r) => (r.length === 1 ? `<circle cx="${r[0].split(",")[0]}" cy="${r[0].split(",")[1]}" r="1.5" fill="var(--accent,#60a5fa)"/>` : `<polyline fill="none" stroke="var(--accent,#60a5fa)" stroke-width="1.5" vector-effect="non-scaling-stroke" points="${r.join(" ")}"/>`)).join("") + "</svg>";
  }
  // a series as the drawer names it: its title when the record has one, else its key
  const name = (k, titles) => esc((titles && titles[k]) || k);
  // the kind, in a sentence, with its evidence
  function kindText(k) {
    const e = k.evidence || {}, what = { counter: "a counter", gauge: "a gauge (a level)", indicator: "an indicator (only 0 and 1)" }[k.as] || k.as;
    const bits = [`${plural(e.points ?? 0, "point")}${e.interval_s ? `, one every ${dur(e.interval_s)}` : ""}`, `from ${num(e.min)} to ${num(e.max)}`,
      e.whole ? "whole numbers" : "", e.never_falls ? "never falls" : `falls ${plural(e.falls, "time")}${e.resets ? ` (${plural(e.resets, "reset")})` : ""}`,
      e.autocorr != null ? `lag-one autocorrelation ${(+e.autocorr).toFixed(2)}` : ""].filter(Boolean);
    return `Read as ${what}: ${k.why}. ${bits.join(", ")}.`;
  }
  // the story of what was tried, in plain sentences (the owner's question: what is it comparing to?)
  function story(rec, titles) {
    const out = [], k = rec.kind || {}, ro = rec.roles || {}, b = ro.balance, dv = ro.driven, inp = ro.input, mv = ro.move;
    if (k.reads_as === "rate") out.push(`It reads as a rate: ${k.reads_why}. A per-interval count (calls per scrape interval) says how fast something happens, not how much is held, so its changes are noise around a mean.`);
    else if (k.reads_as === "held") out.push(`It reads as a held quantity: ${k.reads_why}.`);
    if (b) {
      const n = (b.counters || {}).n || 0, apart = Object.entries(b.kept_apart || {}).map(([w, c]) => `${c} ${w}`).join(", ");
      if (!b.in_window) out.push(`Tried as a level to balance: there was no counter in the window at all, so nothing under the match could be its inflows and outflows. Its R² ${r2(b.r2)} is that of an empty balance, not a comparison with any other series.`);
      else if (!n) out.push(`Tried as a level to balance: of the ${plural(b.in_window, "counter")} in the window none could be its moves (${apart || "all kept apart"}), so nothing could balance it; R² ${r2(b.r2)} is that of an empty balance.`);
      else out.push(`Tried as a level to balance with ${plural(n, "counter")} as its possible moves${apart ? ` (kept apart: ${apart})` : ""}: ${(b.terms || []).length ? `the best balance, ${b.terms.map((t) => `${t.sign > 0 ? "+" : "−"} ${(titles && titles[t.series]) || t.series}`).join(" ")}, fits at R² ${r2(b.r2)}` : `no combination explained any share of its changes (R² ${r2(b.r2)})`}${b.outcome === "fits" ? "" : `, short of the ${b.min_r2 ?? 0.9} a stock needs`}.`);
    }
    if (dv) {
      const forms = (dv.forms || []).filter((f) => f.outcome !== "reference"), own = dv.own_name || [];
      const others = own.length ? ` The ${plural(own.length, "other series")} under the match share${own.length === 1 ? "s" : ""} its name, and a level is never driven by another of its own name (its part, its total, or another part).` : "";
      if (!dv.offered) out.push(`Tried as a level driven by other series: none could be offered.${others} So only a constant drift and its own pull toward a level could be tried (${plural(forms.length, "form")} beyond the constant)${forms.length ? `: ${forms.map((f) => `${f.form} ${f.outcome}${f.why ? `, ${f.why}` : ""}`).join("; ")}` : ""}.`);
      else {
        const best = forms.filter((f) => f.r2 != null).sort((a, c) => c.r2 - a.r2)[0];
        out.push(`Tried as a level driven by other series: ${plural(dv.offered, "series")} offered, ${plural(forms.length, "form")} tried beyond the constant${best ? `; the best fit, ${best.form} at R² ${r2(best.r2)}, ${best.outcome}${best.why ? `: ${best.why}` : ""}` : ""}.${others}`);
      }
    }
    if (inp) {
      const fl = inp.to_flows || [], lv = inp.to_levels || [];
      out.push(fl.length || lv.length ? `Offered as an input to ${plural(fl.length, "flow")}' rates${fl.some((f) => f.chosen) ? ` (chosen by ${fl.filter((f) => f.chosen).map((f) => f.flow).join(", ")})` : " (chosen by none)"} and to ${plural(lv.length, "other level")}' net flows.`
        : "Offered as an input to nothing: no flow's rate and no other level's net flow was there to read it.");
    }
    if (mv) {
      const n = (mv.offered_to || {}).n || 0;
      out.push(`As a move: offered to the balances of ${plural(n, "level")}${(mv.in_balances || []).length ? `, and in the balance of ${mv.in_balances.join(", ")}` : ", in none of them"}${mv.flow ? `; it measures the flow ${mv.flow}` : ""}.`);
    }
    return out;
  }
  // what would help, for this series; ``fallback`` the page's words for its left-out group (left-out.js)
  function help(rec, fallback) {
    if (rec.kept) return "";
    const k = rec.kind || {}, b = (rec.roles || {}).balance, dv = (rec.roles || {}).driven;
    const alone = (!b || !(b.counters || {}).n) && (!dv || !dv.offered);
    if (k.reads_as === "rate" && alone) return "What would help: a per-interval count is a rate, so it will not be a stock itself, and nothing else under the match could drive or balance it. Add a held quantity it fills or drains, such as calls in flight or a queue's depth, or widen the match to more families (what calls it, what it calls), so that something can be balanced or driven and this count read as a flow's rate.";
    if (alone) return "What would help: nothing else under the match could drive or balance it. Widen the match to more families: the counters that fill and drain it, or the series that move it.";
    return fallback || "";
  }
  function query(read, windowS, href) {
    const r = read || {}, own = r.source === "own", q = r.store_query || r.selector || r.query;
    const view = !own && href && q ? ` <a class="sv-view" href="${esc(href(r.source, q, windowS))}" onclick="event.stopPropagation()" title="open the Core page's External stores box with this query over the fitting window">view in ${esc(r.source)}</a>` : "";
    const line = (label, text, all) => (text ? `<div>${label}</div><div><code class="xp-q" style="user-select:all;overflow-wrap:anywhere;font-size:11.5px">${esc(text)}</code>${all || ""}</div>` : "");
    return `<div class="def">${line(own ? "read as" : "query", r.query, view)}${r.selector && r.selector !== r.query ? line("selector", r.selector) : ""}${r.store_query && r.store_query !== r.query && r.store_query !== r.selector ? line("view query", r.store_query) : ""}`
      + `${r.named_by ? `<div>named</div><div>“${esc(r.named_as || "")}”, by <code>${esc(r.named_by)}</code> in the source's names</div>` : ""}`
      + `${(r.summed || []).length ? `<div>split</div><div>summed by its split over ${esc(r.summed.join(", "))}</div>` : ""}`
      + `<div>window</div><div>${r.window ? `${dur(r.window[1] - r.window[0])} in ${dur(r.step)} steps` : "?"} from <b>${esc(r.source || "own")}</b>${r.instances ? ` · ${plural(r.instances, "instance")} summed` : ""}</div>`
      + `<div>came back</div><div>${plural(r.points ?? 0, "point")} over ${dur(r.span_s)}, from ${num(r.min)} to ${num(r.max)}</div></div>`;
  }
  function formsTable(dv, titles) {
    const forms = (dv && dv.forms) || [];
    if (!forms.length) return "";
    const rows = forms.map((f) => `<tr><td class="num">${esc(f.form)}</td><td>${f.inputs.length ? f.inputs.map((k) => name(k, titles)).join(", ") : f.own ? "its own level" : "none"}</td><td class="num">${r2(f.r2)}</td><td><b>${esc(f.outcome)}</b>${f.why ? `<div class="muted">${esc(f.why)}</div>` : ""}</td></tr>`).join("");
    const passed = (dv.passed_over || []).map((p) => `<div class="muted">passed over ${name(p.series, titles)}: ${esc(p.why)}</div>`).join("");
    const own = (dv.own_name || []).length ? `<div class="muted">never offered (its own name): ${dv.own_name.map((k) => name(k, titles)).join(", ")}</div>` : "";
    return `<h4>Forms tried as a driven level <span class="muted" style="text-transform:none;letter-spacing:0">· ${plural(dv.offered || 0, "input")} offered · ${plural(dv.stretches ?? 0, "stretch")} of ${dur(dv.stretch_s)}, the level changed in ${dv.changes ?? 0}</span></h4>`
      + `<table class="dt xp-forms"><tr><th>form</th><th>inputs</th><th>R²</th><th>outcome</th></tr>${rows}</table>${own}${passed}`;
  }
  function balanceBlock(b, titles) {
    if (!b) return "";
    const ks = (b.counters || {}).keys || [], more = ((b.counters || {}).n || 0) - ks.length;
    return `<h4>Balance tried</h4><div class="def"><div>counters</div><div>${b.in_window ? `${(b.counters || {}).n || 0} of the ${b.in_window} in the window offered as its moves${ks.length ? ": " + ks.map((k) => `<span class="ty">${name(k, titles)}</span>`).join(" ") + (more > 0 ? ` and ${more} more` : "") : ""}` : "none in the window"}</div>`
      + `${Object.keys(b.kept_apart || {}).length ? `<div>kept apart</div><div>${Object.entries(b.kept_apart).map(([w, c]) => `${c} ${esc(w)}`).join(", ")}</div>` : ""}`
      + `<div>best balance</div><div>${(b.terms || []).length ? b.terms.map((t) => `${t.sign > 0 ? "+" : "−"} ${name(t.series, titles)}`).join(" ") : "none"} · R² ${r2(b.r2)} against ${b.min_r2 ?? 0.9} needed · ${esc(b.outcome)}</div>`
      + `${b.declared ? `<div>declared</div><div>${esc(b.declared)}</div>` : ""}</div>`;
  }
  // the drawer: ``data`` is /api/dynamics/explain's answer; ``ctx``: {href(source, query, windowS), help (the group's words), titles}
  function html(key, data, ctx = {}) {
    const rec = data.explain, titles = ctx.titles || {}, w = data.window || {}, windowS = w.end != null && w.start != null ? w.end - w.start : null;
    const head = `<h3 data-drawer-key="xp:${esc(key)}">${esc(data.title || key)} <span class="tag">${rec.kept ? "stock" : "left out"}</span></h3>${data.title ? `<div class="muted num" style="font-size:11.5px">${esc(key)}</div>` : ""}`;
    const words = story(rec, titles), hp = help(rec, ctx.help);
    return head
      + `<h4>What came back</h4>${spark((rec.read || {}).spark)}`
      + query(rec.read, windowS, ctx.href)
      + `<h4>Kind</h4><div class="xp-kind">${esc(kindText(rec.kind || {}))}</div>`
      + `<h4>Verdict</h4><div class="xp-verdict"><b>${esc(rec.verdict)}</b></div>`
      + `<div class="xp-story">${words.map((s) => `<p style="margin:6px 0">${esc(s)}</p>`).join("")}</div>`
      + (hp ? `<div class="xp-help" style="margin-top:8px">${esc(hp)}</div>` : "")
      + balanceBlock((rec.roles || {}).balance, titles) + formsTable((rec.roles || {}).driven, titles);
  }
  // fetch one series' record and open its drawer (the page's openDrawer, app.js)
  async function open(key, ctx = {}) {
    const v = typeof VERSION !== "undefined" && VERSION != null ? `&version=${VERSION}` : "";
    let data;
    try { data = await (await fetch(`/api/dynamics/explain?key=${encodeURIComponent(key)}${v}`)).json(); } catch (e) { data = { ok: false, error: String(e) }; }
    if (!data.ok) return openDrawer(`<h3 data-drawer-key="xp:${esc(key)}">${esc(key)}</h3><div class="muted">${esc(data.error || "not recorded")}</div>${data.left_out ? `<h4>Verdict</h4><div>${esc(data.left_out)}</div>` : ""}`);
    openDrawer(html(key, data, ctx));
  }
  return { spark, kindText, story, help, html, open };
})();
if (typeof module !== "undefined") module.exports = Explain;
