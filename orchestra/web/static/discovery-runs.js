// What rediscovering costs, on the Dynamics page: the discovery line beside the rediscover button
// ("last run: 3 m 12 s · 41 requests · saved v7", with the job's health as a dot, and the phase and
// elapsed time live while a run is going), and the drawer it opens: the health in words, the last
// run's phases as a bar, its cost per source and outcome, trend lines of duration and requests per
// run over the last day, and the recent runs with the inference rounds interleaved and marked.
// The records are sd/runs.py's, the health sd/runhealth.py's, served by /api/dynamics/runs.
// Pure functions but `open`, `start` and `paintLine`: tests/discovery_runs/discovery-runs.test.mjs.
const DiscoveryRuns = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const PHASES = [["reads", "store reads", "#3987e5"], ["inference", "inference (survey, probes)", "#d95926"], ["fit", "the strategy's fit", "#199e70"], ["saving", "saving", "#c98500"]];
  const LEVEL = { green: ["●", "healthy"], amber: ["▲", "needs a look"], red: ["■", "failing"], none: ["○", "no runs yet"] };
  const DAY = 86400;
  function dur(s) {
    if (s == null || !isFinite(s)) return "—";
    s = Math.max(0, +s);
    if (s < 10) return `${s.toFixed(1)} s`;
    if (s < 60) return `${Math.round(s)} s`;
    if (s < 3600) return `${Math.floor(s / 60)} m ${Math.floor(s % 60)} s`;
    if (s < DAY) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} m`;
    return `${(s / DAY).toFixed(1)} d`;
  }
  const num = (n) => (n == null ? "—" : Math.round(n).toLocaleString("en"));
  const bytes = (b) => (b == null ? "—" : b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`);
  const plural = (n, w) => `${num(n)} ${n === 1 ? w : w + "s"}`;
  const sum = (r, k) => Object.values((r && r.cost) || {}).reduce((a, c) => a + (+(c && c[k]) || 0), 0);
  const requests = (r) => sum(r, "requests");
  const points = (r) => sum(r, "points");
  const clock = (t) => { const d = new Date(t * 1000); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
  const outcomeClass = (o) => (/^failed/.test(o || "") ? "dr-bad" : o === "timed out" ? "dr-warn" : /^saved/.test(o || "") ? "dr-good" : "");
  const lastDiscovery = (v) => [...((v && v.runs) || [])].reverse().find((r) => r.kind === "discovery") || null;
  // the health dot: a shape and a word beside the colour, never colour alone
  function dot(h) {
    const lv = (h && h.level) || "none", [shape, word] = LEVEL[lv] || LEVEL.none;
    return `<span class="dr-dot dr-${esc(lv)}" title="${esc(((h && h.reasons) || []).join("; "))}" aria-label="discovery ${esc(word)}">${shape}</span>`;
  }
  // the run going now, its phase and how long it has run (``extra``: seconds since it was read)
  function liveText(run, extra = 0) {
    const ph = (PHASES.find((p) => p[0] === run.phase) || [null, run.phase || "starting"])[1];
    return `${run.trigger === "button" ? "rediscovering" : "discovering"}: ${esc(ph)}${run.what ? ` (${esc(run.what)})` : ""} · ${dur((+run.elapsed_s || 0) + extra)}`;
  }
  // the discovery line: health, and the last run as a link to the drawer (or the run going now)
  function lineHtml(v, extra = 0) {
    if (!v || !v.ok) return "";
    const last = lastDiscovery(v), h = v.health || {};
    const live = v.running ? `<span class="dr-live">${liveText(v.running, extra)}</span> · ` : "";
    const lastText = last ? `last run: ${dur(last.duration_s)} · ${plural(requests(last), "request")} · ${esc(last.outcome)}` : "no run recorded yet";
    return `${dot(h)} ${live}<a href="#" class="dr-link" onclick="DiscoveryRuns.open();return false" title="what discovery runs cost, and how healthy the job is">${lastText}</a>`;
  }
  // the phases of one run as a bar, each labelled with its seconds
  function phaseBar(r) {
    const ph = r.phases || {}, total = PHASES.reduce((a, [k]) => a + (+ph[k] || 0), 0) || 1;
    const segs = PHASES.filter(([k]) => ph[k] > 0).map(([k, label, c]) => `<div class="dr-seg" style="flex:${(ph[k] / total).toFixed(4)} 1 0;background:${c}" title="${esc(label)}: ${dur(ph[k])}"></div>`).join("");
    const key = PHASES.filter(([k]) => ph[k] > 0).map(([k, label, c]) => `<span class="dr-key"><i style="background:${c}"></i>${esc(label)} <b>${dur(ph[k])}</b></span>`).join("");
    return `<div class="dr-bar" role="img" aria-label="phases: ${esc(PHASES.filter(([k]) => ph[k] > 0).map(([k, l]) => `${l} ${dur(ph[k])}`).join(", "))}">${segs || '<div class="dr-seg" style="flex:1;background:var(--border2)"></div>'}</div><div class="dr-keys">${key}</div>`;
  }
  // the store cost of one run, a row per source
  function costTable(r) {
    const rows = Object.entries(r.cost || {});
    if (!rows.length) return '<div class="muted">No other store was read: the own metrics store only, which costs no request.</div>';
    return `<table class="dt dr-cost"><tr><th>source</th><th class="num">requests</th><th class="num">whole</th><th class="num">incremental</th><th class="num">inference</th><th class="num">series</th><th class="num">points</th><th class="num">bytes</th><th class="num">waiting</th><th class="num">refused</th><th class="num">today / cap</th></tr>`
      + rows.map(([name, c]) => `<tr><td>${esc(name)}</td><td class="num">${num(c.requests)}</td><td class="num">${num(c.whole)}</td><td class="num">${num(c.incremental)}</td><td class="num">${num(c.inference)}</td><td class="num">${num(c.series)}</td><td class="num">${num(c.points)}</td><td class="num">${bytes(c.bytes)}</td><td class="num">${dur((c.wait_ms || 0) / 1000)}</td><td class="num${c.refused ? " dr-bad" : ""}">${num(c.refused)}</td><td class="num${c.per_day && c.today >= c.per_day ? " dr-bad" : ""}">${num(c.today)}${c.per_day ? ` / ${num(c.per_day)}` : ""}</td></tr>`).join("")
      + "</table>";
  }
  // one trend line over the last day: a value per run, its points titled for hover
  function trend(runs, value, label, fmt, w = 300, h = 44) {
    const pts = runs.map((r) => [r.ended, value(r)]).filter(([t, y]) => t != null && y != null && isFinite(y));
    if (pts.length < 2) return `<div class="dr-trend"><div class="dr-tl">${esc(label)}</div><div class="muted">too few runs in the last day for a line</div></div>`;
    const t0 = Math.min(...pts.map((p) => p[0])), t1 = Math.max(...pts.map((p) => p[0])), hi = Math.max(...pts.map((p) => p[1])) || 1;
    const x = (t) => 4 + ((t - t0) / (t1 - t0 || 1)) * (w - 8), y = (v) => h - 4 - (v / hi) * (h - 8);
    const line = pts.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const hits = pts.map(([t, v]) => `<circle cx="${x(t).toFixed(1)}" cy="${y(v).toFixed(1)}" r="6" fill="transparent"><title>${clock(t)}: ${esc(fmt(v))}</title></circle>`).join("");
    const lastP = pts[pts.length - 1];
    return `<div class="dr-trend"><div class="dr-tl">${esc(label)} <span class="muted">· last ${esc(fmt(lastP[1]))}, at most ${esc(fmt(hi))}</span></div>`
      + `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" role="img" aria-label="${esc(label)} over the last day, ${pts.length} runs, at most ${esc(fmt(hi))}">`
      + `<line x1="0" x2="${w}" y1="${h - 4}" y2="${h - 4}" stroke="var(--border2)" stroke-width="1" vector-effect="non-scaling-stroke"/>`
      + `<polyline fill="none" stroke="#3987e5" stroke-width="2" vector-effect="non-scaling-stroke" points="${line}"/>`
      + `<circle cx="${x(lastP[0]).toFixed(1)}" cy="${y(lastP[1]).toFixed(1)}" r="3" fill="#3987e5"/>${hits}</svg></div>`;
  }
  // the recent runs, newest first, the inference rounds interleaved and marked
  function history(runs, n = 40) {
    const rows = [...runs].reverse().slice(0, n).map((r) => {
      const inf = r.kind === "inference";
      return `<tr class="${inf ? "dr-inf" : ""}"><td class="num">${esc(clock(r.started))}</td><td>${inf ? `<span class="tag dr-itag">inference</span> ${esc(r.source || "")}` : esc(r.trigger)}</td><td class="num">${dur(r.duration_s)}</td><td class="num">${num(requests(r))}</td><td class="num">${num(points(r))}</td><td class="${outcomeClass(r.outcome)}">${esc(r.outcome)}${r.partial ? ' <span class="dr-warn" title="' + esc(r.partial) + '">(partial)</span>' : ""}</td></tr>`;
    }).join("");
    return `<table class="dt dr-hist"><tr><th>time</th><th>trigger</th><th class="num">duration</th><th class="num">requests</th><th class="num">points</th><th>outcome</th></tr>${rows}</table>`;
  }
  function drawerHtml(v) {
    const h = v.health || {}, last = lastDiscovery(v), runs = v.runs || [], now = v.now || Date.now() / 1000;
    const day = runs.filter((r) => r.kind === "discovery" && (r.ended || 0) >= now - DAY);
    const head = `<h3 data-drawer-key="runs">Discovery runs <span class="tag">${esc((LEVEL[h.level] || LEVEL.none)[1])}</span></h3>`
      + `<div class="dr-health dr-h-${esc(h.level || "none")}">${dot(h)} <div>${(h.reasons || []).map((w) => `<div>${esc(w)}</div>`).join("")}</div></div>`
      + (v.running ? `<div class="dr-live" style="margin-top:6px">${liveText(v.running)}</div>` : "");
    if (!last) return head + '<div class="muted" style="margin-top:8px">No discovery run is recorded yet. The host runs one every ' + esc(dur(v.every_s)) + "; the rediscover button runs one now.</div>";
    const st = last.strategy || {}, res = last.result || {};
    const facts = `<div class="def"><div>when</div><div>${esc(new Date(last.started * 1000).toLocaleString())} · ${esc(last.trigger)}</div>`
      + `<div>outcome</div><div class="${outcomeClass(last.outcome)}"><b>${esc(last.outcome)}</b>${last.partial ? ` · <span class="dr-warn">partial: ${esc(last.partial)}</span>` : ""}</div>`
      + `<div>took</div><div>${dur(last.duration_s)}</div>`
      + `<div>strategy</div><div>${esc(st.ran || st.asked || st.configured || "—")}${st.configured && st.ran && st.configured !== st.ran ? ` <span class="muted">(configured: ${esc(st.configured)})</span>` : ""}</div>`
      + `<div>window</div><div>${dur(last.window_s)} in ${dur(last.step_s)} steps</div>`
      + `<div>model</div><div>${plural(res.stocks || 0, "stock")}, ${plural(res.flows || 0, "flow")}, ${num(res.left_out || 0)} series left out</div></div>`;
    return head + `<h4>The last run</h4>${phaseBar(last)}${facts}<h4>What it cost the stores</h4>${costTable(last)}`
      + `<h4>The last day <span class="muted" style="text-transform:none;letter-spacing:0">· ${plural(day.length, "discovery run")}</span></h4><div class="dr-trends">${trend(day, (r) => r.duration_s, "duration per run", dur)}${trend(day, requests, "requests per run", (n) => num(n))}</div>`
      + `<h4>Recent runs</h4>${history(runs)}`;
  }
  // the page side: the line kept fresh (every 2 s while a run is going, else every 15 s) and the drawer
  let VIEW = null, READ_AT = 0, TIMER = null;
  async function fetchView() {
    try { VIEW = await (await fetch("/api/dynamics/runs")).json(); READ_AT = Date.now() / 1000; } catch (e) { VIEW = null; }
    return VIEW;
  }
  function paintLine() {
    const el = typeof document !== "undefined" && document.getElementById("disc-runs");
    if (el && VIEW) el.innerHTML = lineHtml(VIEW, VIEW.running ? Date.now() / 1000 - READ_AT : 0);
  }
  async function tick() {
    await fetchView(); paintLine();
    const dr = document.getElementById("drawer");
    if (dr && dr.dataset.key === "runs" && document.getElementById("overlay").classList.contains("open") && VIEW) openDrawer(drawerHtml(VIEW), { key: "runs" });
    clearTimeout(TIMER); TIMER = setTimeout(tick, VIEW && VIEW.running ? 2000 : 15000);
  }
  function start() { tick(); setInterval(() => { if (VIEW && VIEW.running) paintLine(); }, 1000); }
  async function open() { if (!VIEW) await fetchView(); if (VIEW) openDrawer(drawerHtml(VIEW), { key: "runs" }); }
  // a run asked for from this page: look again soon, so the line goes live at once
  function soon() { clearTimeout(TIMER); TIMER = setTimeout(tick, 400); }
  return { dur, dot, liveText, lineHtml, phaseBar, costTable, trend, history, drawerHtml, requests, points, open, start, soon, paintLine };
})();
if (typeof module !== "undefined") module.exports = DiscoveryRuns;
