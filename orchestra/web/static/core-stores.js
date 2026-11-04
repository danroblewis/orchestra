// The Core page's external stores ([[sources]]): what each row says, as pure functions of
// /api/core/stores (tests/core_stores/core-stores.test.mjs), and the per-store query box's
// completion cache, filled only from the bounded label endpoints (never /api/v1/series).
const CoreStores = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ago = (sec) => (sec < 60 ? `${Math.round(sec)}s` : sec < 3600 ? `${Math.round(sec / 60)}m` : sec < 2 * 86400 ? `${(sec / 3600).toFixed(1)}h` : `${(sec / 86400).toFixed(1)}d`);
  const when = (t, now) => (t ? `${ago(Math.max(0, now - t))} ago` : "never");
  const num = (n) => (n == null ? "—" : Number(n).toLocaleString("en-US"));
  const EMPTY = "This project reads no other store: its configuration declares no <code>[[sources]]</code> entry (SPEC §4.4). Series that live in another Prometheus-API store are read where they live through one, and listed here.";
  // the auth form: its kinds, and where each credential comes from and whether it is there; never a value
  function authText(a) {
    if (!a || !(a.kinds || []).length) return "none";
    const creds = (a.credentials || []).map((c) => `${c.what} from ${c.from}${c.user ? ` (user ${c.user})` : ""}${c.present ? "" : " · missing"}`);
    return `${a.kinds.join(" + ")}${creds.length ? ` · ${creds.join("; ")}` : ""}${a.insecure ? " · TLS not verified" : ""}`;
  }
  // today's requests against the daily cap: the store's (every reader on this machine) and the web server's share
  function capText(s) {
    const b = s.bucket || {}, st = b.store || {}, web = b.web || {};
    const share = b.web_share != null ? `${Math.round(b.web_share * 100)}%` : "a share";
    const held = st.held_s > 0 ? ` · held ${Math.round(st.held_s)} s (the store asked to wait)` : "";
    return `${num(st.today)} of ${num(st.per_day ?? s.per_day)} today (UTC), every reader of the store on this machine · this web server's ${share}: ${num(web.today)} of ${num(web.per_day)}${held}`;
  }
  function inferredText(inf, now) {
    if (!inf) return "none yet: the host's discovery infers what to read (orchestra sources infer)";
    return `${num(inf.definitions)} series definition${inf.definitions === 1 ? "" : "s"} kept (${num(inf.inferred)} inferred${inf.left_out ? `, ${num(inf.left_out)} left out` : ""}) · inferred ${when(inf.at, now)}`;
  }
  function rowHtml(s, now = Date.now() / 1000) {
    const err = s.last_error;
    return `<div class="kv st-kv">
      <div>backend</div><div><b>${esc(s.type)}</b> <span class="muted">prefix ${esc(s.prefix)}:</span></div>
      <div>at</div><div class="num mono">${esc(s.url)}</div>
      <div>auth</div><div>${esc(authText(s.auth))}</div>
      <div>match</div><div class="mono">${(s.match || []).map(esc).join(" or ")}</div>
      <div>caps</div><div class="num">${num(s.max_series)} series at most · ${s.rate} requests/s (bursts of ${s.burst}) · ${num(s.per_day)} a day</div>
      <div>requests</div><div class="num">${esc(capText(s))}</div>
      <div>last read</div><div>${when(s.last_ok, now)}</div>
      <div>last error</div><div>${err ? `<span class="stale">${esc(err.error)}</span> <span class="muted">(${esc(err.from)}, ${when(err.at, now)})</span>` : "none"}</div>
      <div>series</div><div>${esc(inferredText(s.inferred, now))}</div></div>`;
  }
  function refusedHtml(r) {
    return `<div class="probe bad"><b>${esc(r.name)}</b>: refused: ${esc(r.error)}</div>`;
  }
  // the whole section when it is not a list of stores: an error, or the empty state
  function stateHtml(d) {
    if (!d || !d.ok) return `<div class="probe bad">${esc((d && d.error) || "the external stores cannot be read")}</div>`;
    if (!(d.stores || []).length && !(d.refused || []).length) return `<div class="empty">${EMPTY}</div>`;
    return null;
  }
  const label = (lab) => {
    const name = lab.__name__ || "";
    const inner = Object.entries(lab).filter(([k]) => k !== "__name__").sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}="${v}"`).join(",");
    return inner ? `${name}{${inner}}` : name || "{}";
  };
  // an instant query's answer: one row per series, its value and when
  function instantHtml(d) {
    if (!d.lines.length) return `<div class="empty" style="margin-top:8px">no series at this instant</div>`;
    return `<table class="ct"><tr><th>series</th><th>value</th></tr>${d.lines.map((l) => {
      const p = l.points[l.points.length - 1] || [];
      return `<tr><td class="mono">${esc(label(l.labels))}</td><td class="num">${p.length ? esc(String(p[1])) : "—"}</td></tr>`;
    }).join("")}</table>`;
  }
  function noteText(d) {
    const cut = d.matched > d.lines.length ? `, the first ${d.lines.length} shown (limit ${d.limit})` : "";
    return `${d.matched} series${cut} · ${d.requests} request${d.requests === 1 ? "" : "s"} · sent: ${d.query}`;
  }
  // completion: what the bounded endpoints said, as PromEditor's catalogue reads it
  function cache() {
    const names = new Set(), labels = new Map();       // metric ("" for any) -> Map(label -> Set(values))
    const labelsOf = (metric) => {
      const out = new Map();
      for (const key of metric ? [metric, ""] : [...labels.keys()]) for (const [k, v] of labels.get(key) || []) {
        const cur = out.get(k) || new Set(); v.forEach((x) => cur.add(x)); out.set(k, cur);
      }
      return out;
    };
    return {
      names, labelsOf,
      catalog: () => ({ metrics: [...names].sort().map((n) => ({ name: n })) }),
      addNames(xs) { xs.forEach((x) => names.add(x)); },
      addLabels(metric, xs) { const m = labels.get(metric || "") || new Map(); xs.filter((k) => k !== "__name__").forEach((k) => m.has(k) || m.set(k, new Set())); labels.set(metric || "", m); },
      addValues(metric, label, xs) { const m = labels.get(metric || "") || new Map(); const s = m.get(label) || new Set(); xs.forEach((x) => s.add(x)); m.set(label, s); labels.set(metric || "", m); },
    };
  }
  // which bounded lookup a completion context needs: [path, params] or null
  function lookup(ctx) {
    if (!ctx) return null;
    if (ctx.kind === "name") return ["label/__name__/values", { selector: "" }];
    if (ctx.kind === "label") return ["labels", { selector: ctx.metric || "" }];
    if (ctx.kind === "value") return [`label/${encodeURIComponent(ctx.label)}/values`, { selector: ctx.metric || "" }];
    return null;
  }
  // the query's first vector selector (what the labels button narrows to): label lists, ranges,
  // function and aggregation names and keywords skipped; "" when it has none
  const WORDS = new Set(["by", "without", "on", "ignoring", "group_left", "group_right", "offset", "bool", "and", "or", "unless"]);
  function firstSelector(q) {
    const t = String(q || "").replace(/\b(by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)/g, " ").replace(/\[[^\]]*\]/g, " ");
    const re = /([a-zA-Z_:][\w:]*)?\s*(\{(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^}])*\})?/g;
    let m;
    while ((m = re.exec(t))) {
      if (!m[0]) { re.lastIndex++; continue; }
      if (!m[1] && !m[2]) continue;
      const after = t.slice(re.lastIndex).trimStart()[0];
      if (m[1] && !m[2] && (after === "(" || WORDS.has(m[1].toLowerCase()))) continue;
      if (m[1] && /^\d/.test(m[1])) continue;
      return m[0].trim();
    }
    return "";
  }
  return { EMPTY, firstSelector, authText, capText, inferredText, rowHtml, refusedHtml, stateHtml, instantHtml, noteText, label, cache, lookup };
})();
