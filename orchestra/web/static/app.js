// Shared helpers, nav, and drawers for the Orchestra UI.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const color = (s) => `var(--${s})`;
// How a machine was seen, one wording wherever it is shown: on the bus (first and last), by its
// counted traffic only, or not yet.
const seenText = (m, now = Date.now() / 1000) => (m.first_seen ? `first ${ago(now - m.first_seen)} ago, last ${ago(now - m.last_seen)} ago`
  : m.counted_only ? (m.last_seen ? `known by counts only; last counted ${ago(now - m.last_seen)} ago` : "known by counts only")
  : "no events yet");
// one colour per machine, the same every time for the same id, on every page (the Machines page,
// the Dashboard, Dynamics); no machine, or "none": grey
const MPAL = ["#60a5fa", "#f59e0b", "#e879f9", "#22c55e", "#f87171", "#38bdf8", "#facc15", "#a78bfa", "#fb923c", "#2dd4bf"];
const mcolor = (id) => { if (!id || id === "none") return "#94a3b8"; let h = 0; for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return MPAL[h % MPAL.length]; };
const ago = (sec) => (sec < 60 ? `${Math.round(sec)}s` : sec < 3600 ? `${Math.round(sec / 60)}m` : `${(sec / 3600).toFixed(1)}h`);
const fmtBytes = (b) => (b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(1)} GB` : `${Math.round(b / (1 << 20))} MB`);

window.Orchestra = window.Orchestra || {};
// One time formatter, with the zone, for every page (a plugin's pages delegate to it):
// "12:03 PST"; {seconds: true} "12:03:07 PST"; {date: true} "Nov 1, 12:03 PST".
// ``t`` in seconds since the epoch; none reads "—"
Orchestra.when = (t, o = {}) => (t == null ? "—" : new Date(t * 1000).toLocaleString(undefined, {
  ...(o.date ? { month: "short", day: "numeric" } : {}), hour: "2-digit", minute: "2-digit", ...(o.seconds ? { second: "2-digit" } : {}),
  hourCycle: "h23", timeZoneName: "short" }));
const hhmm = (t) => Orchestra.when(t);
// Whether a machine is active, said the same way everywhere (the Dashboard's row, a card's seen row,
// the map's tooltip, the dialog), with the rule the judgement used: heard within 2.5× its usual gap,
// at least 2 minutes; with no cadence yet, the 2-minute floor alone. The host's flag is the runtime
// record's (``active_by: "runtime"``): it publishes only when it starts and stops, so it has no
// rhythm to be in. A machine whose events never stop long enough to make a beat (orchestra/cadence.py:
// none more than BURST_S apart) has no cadence however long it is heard: it publishes continuously.
// {word, cls ("live" or "quiet"), detail, title}
Orchestra.BURST_S = 48;            // cadence.BURST_S: an event this soon after the last is the same burst
Orchestra.continuous = (x) => !x.cadence_s && x.first_seen != null && x.last_seen != null && x.last_seen - x.first_seen > Orchestra.BURST_S;
Orchestra.liveness = (m, now = Date.now() / 1000) => {
  if (m.active_by === "runtime") return { word: m.active ? "running" : "not running", cls: m.active ? "live" : "quiet", detail: "",
    title: "by the runtime record: the host process is in it; it publishes only when it starts and stops" };
  if (!m.last_seen) return { word: "never heard", cls: "quiet", detail: "", title: m.intent ? "declared: nothing on the bus under it" : "nothing on the bus under it yet" };
  const cads = [m.cadence_s, ...(m.instances || []).map((i) => i.cadence_s)].filter((g) => g), g = cads.length ? Math.min(...cads) : null;
  // events too close together to make beats: how often, on average, never "continuously" (beside an
  // announced "ad hoc" that would read as a contradiction)
  const n = (m.publishes || []).reduce((a, p) => a + (p.count || 0), 0), every = n > 1 ? (m.last_seen - m.first_seen) / (n - 1) : null;
  if (m.active && !g && Orchestra.continuous(m)) return { word: "active", cls: "live", detail: `${every ? `about every ${ago(every)} · ` : ""}last event ${ago(now - m.last_seen)} ago`,
    title: "heard within the last 2 minutes; its events come too close together to make a cadence of beats" };
  const rule = g ? `usual gap ${ago(g)}` : "no cadence yet: judged by the 2-minute floor";
  if (m.active) return { word: "in rhythm", cls: "live", detail: `${rule} · last event ${ago(now - m.last_seen)} ago`,
    title: `heard within 2.5× its usual gap (at least 2 min): ${rule}` };
  return { word: `quiet since ${hhmm(m.last_seen)}`, cls: "quiet", detail: g ? `usual gap ${ago(g)}` : "", title: `nothing heard within 2.5× its usual gap (at least 2 min)${g ? `: usual gap ${ago(g)}` : ""}` };
};
// The instances a declared machine's instruments measure that report themselves down: points
// arrive, and their own "up" series (named up, or ending _up) reads 0. A report, never a verdict.
// [{instance, series, instrument}]
Orchestra.downOf = (m) => {
  const atts = (m && m.measured && !m.measured.unknown && m.measured.attachments) || [];
  const isUp = (n) => n === "up" || /_up$/.test(n);
  return atts.flatMap((a) => ((a.instances || {}).list || []).filter((i) => i.measured).map((i) => {
    const s = (a.series || []).find((x) => isUp(x.name) && (x.labels || {})[a.instance_label] === i.value && +x.value === 0);
    return s ? { instance: i.value, series: s.name, instrument: a.instrument } : null; }).filter(Boolean));
};
// The Dashboard's Machines panel: every machine on the Machines page is a row or in a note, so the
// rows and notes add up to the count in its header. Rows: the continuous machines and any other
// while it is active; notes: the declared ones not heard (and the proposed ones never heard) and
// the quiet ones that are not continuous.
Orchestra.dashboardGroups = (ms) => {
  const rows = ms.filter((m) => !m.unseen && (m.mode === "continuous" || m.active)), rest = ms.filter((m) => !rows.includes(m));
  const unheard = rest.filter((m) => m.intent && !m.intent.heard);
  return { rows, proposed: unheard.filter((m) => m.intent.state === "proposed"), declared: unheard.filter((m) => m.intent.state !== "proposed"),
           quiet: rest.filter((m) => !unheard.includes(m)) };
};

// Machine cards a package draws for its own machines (orchestra/plugins.py). A machine belongs to
// a package when its announcement says so, or the package declares it (``m.package``). The
// package's every-page script registers, for its package name:
//   card(m, {compact})  -> the inside of the machine's card (HTML), or null for Orchestra's own;
//   open(m)             -> true when it opened the machine's dialog itself, else Orchestra opens its own;
//   summary(m)          -> a few words for a machine's line in a short list (the Dashboard's), or null;
//   rank(m)             -> where its machines go in a list (Orchestra's own are 0; default 50).
// The card is always drawn inside Orchestra's frame: a package draws what is in it, nothing around
// it, and what Orchestra observed of the machine (``rows``) is drawn under it on every card.
// ``changed()`` asks the pages to draw the cards again (its data arrived). Any machine no package
// claims gets Orchestra's card and dialog.
// What a machine's instances announced beyond what Orchestra reads (``about``: the rest of
// orchestra.machine.started's data, passed on unread, rule 2), as plain "key: value" lines in the
// order announced; no key means anything here, only ``disabled`` is put first.
Orchestra.aboutLines = (m) => {
  const about = (m && m.about) || {}, keys = Object.keys(about).sort((a, b) => (b === "disabled") - (a === "disabled"));
  const word = (v) => (Array.isArray(v) ? v.map(String).join(", ") : v === null ? "none" : String(v));
  return keys.map((k) => `${k}: ${word(about[k])}`);
};
Orchestra.aboutHtml = (m) => Orchestra.aboutLines(m).map((l) => `<div class="about-line">${esc(l)}</div>`).join("");
Orchestra.machineCards = (() => {
  const by = new Map();
  const changed = () => document.dispatchEvent(new Event("orchestra:machinecards"));
  return {
    register(pkg, spec) { by.set(pkg, spec); changed(); },
    of(m) { return (m && m.package && by.get(m.package)) || null; },
    card(m, opts = {}) { const s = this.of(m); try { return s && s.card ? s.card(m, opts) : null; } catch (e) { return null; } },
    summary(m) { const s = this.of(m); try { return s && s.summary ? s.summary(m) : null; } catch (e) { return null; } },
    wrap(m, html, extra = "") {
      return `<div class="panel ${extra} ${m.unseen ? "unseen" : ""}" data-id="${esc(m.id)}" tabindex="0" role="button" aria-label="${esc(m.name || m.id)}: open its details" onclick="openMachine(this.dataset.id)" onkeydown="if(event.target===this&&(event.key==='Enter'||event.key===' ')){event.preventDefault();openMachine(this.dataset.id)}">${html}</div>`;
    },
    // What Orchestra observed of a machine, as the rows of its card, drawn under whatever its
    // package put there: the notes it announced (Orchestra.aboutLines), how it is engaged and what kind of thing it is (announced), its package,
    // its instances, when it was seen, what it publishes (all time, and the rate in the last ten
    // minutes when there is one) and listens for, its counted traffic on another system's bus
    // (rates and backlogs, never events), and the flows the latest discovery hypothesises it is
    // associated with (a match in time; a series never belongs to a machine). One function, so
    // every card shows the same rows.
    rows(m) {
      const now = Date.now() / 1000;
      // a rate only while the machine is active and the type was seen more than once: a quiet
      // machine's chip is its count alone
      const chip = (p) => { const win = Orchestra.rateWindow(p), rated = m.active && p.count > 1 && p.per_min_10m;
        const why = p.count <= 1 ? "seen once: no rate" : !m.active ? "quiet: no rate" : `none in ${win}`;
        const title = rated ? `${p.count} events, ${p.day} in 24 h, ${p.n_10m != null ? `${p.n_10m} in ${win}` : `over ${win}`}: ${p.per_min_10m}/min` : `${p.count} events, ${p.day} in 24 h · ${why}`;
        return `<span class="ty" title="${title}">${esc(p.type)} · ${p.count}${rated ? ` · ${p.per_min_10m}/min` : ""}</span>`; };
      const lv = Orchestra.liveness(m, now), about = Orchestra.aboutHtml(m);
      return `${about ? `<div class="row"><span class="muted" title="what it announced of itself, as it said it">announced</span><span class="about">${about}</span></div>` : ""}<div class="row"><span class="muted">engaged</span><span>${m.mode ? `<span class="tag k-${esc(m.mode.replace(/ /g, "_"))}">${esc(m.mode.replace("_", " "))}</span>` : '<span class="muted">not announced</span>'}</span></div><div class="row"><span class="muted" data-k="kind">kind</span><span>${m.kind ? `<span class="tag">${esc(kindWord(m.kind))}</span>` : '<span class="muted">not announced</span>'}</span></div>
    <div class="row"><span class="muted">package</span><span>${m.package ? esc(m.package) : '<span class="muted">no package</span>'}</span>${m.group ? `<span class="muted">group</span><span><span class="tag" title="the group it announced (a team): a label, not a separate system">${esc(m.group)}</span></span>` : ""}</div>
    ${m.instances && m.instances.length ? `<div class="row"><span class="muted">instances</span>${m.instances.map((i) => `<span class="ty" title="${i.kind ? `${esc(i.kind)}, ` : ""}last seen ${ago(now - i.last_seen)} ago"><span class="dot ${i.active ? "" : "off"}" style="--rc:${i.active ? "#22c55e" : "#64748b"};width:7px;height:7px"></span> ${esc(i.id)}</span>`).join("")}</div>` : ""}
    ${m.note ? `<div class="row"><span class="muted">what</span><span>${esc(m.note)}</span></div>` : ""}
    <div class="row"><span class="muted">seen</span><span class="rv">${seenText(m, now)}${m.first_seen || m.active_by ? ` · <span class="${lv.cls === "live" ? "lv-live" : "lv-quiet"}" title="${esc(lv.title)}">${esc(lv.word)}</span>${lv.detail ? ` <span class="muted">· ${esc(lv.detail)}</span>` : ""}` : ""}</span></div>
    <div class="row"><span class="muted">publishes</span>${(m.publishes || []).map(chip).join("") || '<span class="muted">nothing</span>'}</div>
    <div class="row"><span class="muted">listens for</span>${(m.subscribes || []).map((t) => `<span class="ty">${esc(t)}</span>`).join("") || '<span class="muted">nothing</span>'}</div>
    ${(m.counted || []).length ? `<div class="row"><span class="muted">counted</span>${m.counted.map((t) => t.direction === "backlog"
      ? `<span class="ty" title="what waits for it in ${esc(t.channel)}">${esc(t.channel)} · ${Math.round(t.backlog ?? 0).toLocaleString()} waiting</span>`
      : `<span class="ty" title="${Math.round(t.window).toLocaleString()} in the last hour, counted on another system's bus">${t.direction === "out" ? "→" : "←"} ${esc(t.channel)} · ${t.per_min}/min</span>`).join("")}</div>` : ""}
    <div class="row"><span class="muted" title="flows of the model its events match in time: hypotheses, not causes">flows (hypotheses)</span>${(m.flows || []).map((f) => `<a class="ty fl" href="/dynamics#f:${encodeURIComponent(f.flow)}" onclick="event.stopPropagation()" title="${esc(f.why || "")} · open it on Dynamics">${esc(Orchestra.flowLabel(f))}${f.confidence != null ? ` · ${Math.round(100 * f.confidence)}%` : ""}</a>`).join("") || '<span class="muted">none hypothesised yet</span>'}</div>`;
    },
    rank(m) { if (m.bootstrap) return 0; const s = this.of(m); try { return s && s.rank ? s.rank(m) : 50; } catch (e) { return 50; } },
    sort(ms) { return [...ms].sort((a, b) => this.rank(a) - this.rank(b) || a.id.localeCompare(b.id)); },
    open(m) {
      if (this.skip === m.id) { this.skip = null; return false; }       // "machine details": Orchestra's own dialog
      const s = this.of(m); try { return !!(s && s.open && s.open(m)); } catch (e) { return false; }
    },
    openDefault(id) { this.skip = id; if (typeof openMachine === "function") openMachine(id); else location.href = "/machines#" + encodeURIComponent(id); },
    changed,
  };
})();

// the window a publishes rate is over: the last ten minutes, or since the machine was first seen
Orchestra.rateWindow = (p) => (p.window_s && p.window_s < 600 ? `${(p.window_s / 60).toFixed(1).replace(/\.0$/, "")} min (since first seen)` : "the last 10 min");
// A hypothesised flow as Dynamics names it: its ends, then the counter's move, so two flows of one
// counter (twins) read apart. The names are SDGraph's (sd-graph.js), over the model's parts the
// page was given (/api/machines ``model_parts``); without them, the flow's own name.
Orchestra.modelParts = null;
Orchestra.flowLabel = (f) => {
  const mp = Orchestra.modelParts, G = window.SDGraph;
  if (!mp || !G) return f.name || f.flow;
  const end = (id) => (id ? G.stockName(mp, id) : "outside"), rec = mp.flows.find((x) => x.id === f.flow);
  const move = rec ? G.flowName(mp, rec) : f.name || f.flow;
  return `${end(f.from)} → ${end(f.to)} · ${move}`;
};

// Dashboard panels (static/dashboard.js): Orchestra's own and any a package registers from its
// every-page script. A panel is {id, title, mount(body, {setSub})}: mount draws into its body once
// and keeps it current itself; setSub sets the line beside its title. Where each panel goes, how
// wide it is and whether it is shown is the viewer's, kept in the browser.
Orchestra.panels = (() => {
  const list = [];
  return {
    register(spec) { if (!list.some((p) => p.id === spec.id)) { list.push(spec); document.dispatchEvent(new Event("orchestra:panels")); } },
    all() { return list.slice(); },
  };
})();

// Orchestra's own pages, in nav order: the one list every page's nav is built from, plugin pages
// included, so a page added here appears everywhere (a page's static links are only the fallback
// before this script runs).
const CORE_PAGES = [["/", "Dashboard"], ["/machines", "Machines"], ["/instruments", "Instruments"], ["/dynamics", "Dynamics"], ["/core", "Core"]];
(function coreNav() {
  const nav = $("nav"), at = $("proj");
  if (!nav || !at) return;
  for (const a of [...nav.querySelectorAll("a")]) if (a.compareDocumentPosition(at) & Node.DOCUMENT_POSITION_FOLLOWING) a.remove();
  for (const [path, title] of CORE_PAGES) {
    const a = document.createElement("a");
    a.href = path; a.textContent = title;
    if (path === "/" ? location.pathname === "/" : location.pathname === path || location.pathname.startsWith(path + "/")) a.className = "on";
    nav.insertBefore(a, at);
  }
})();

// The session (web/auth.py): a request this server refuses for want of a login goes to the login
// page and back here after; a browser logged in with the cookie gets a "log out" button in the nav.
(function session() {
  const plain = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const r = await plain(...args);
    if (r.status === 401 && new URL(r.url, location.href).origin === location.origin) {
      location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search + location.hash);
    }
    return r;
  };
  plain("/api/session").then((r) => (r.ok ? r.json() : null)).then((s) => {
    const nav = $("nav");
    if (!nav || !s || s.via !== "cookie") return;
    const f = document.createElement("form");
    f.method = "post"; f.action = "/logout"; f.style.margin = "0";
    f.innerHTML = '<button class="ctl" type="submit" title="end this browser\'s session">log out</button>';
    nav.appendChild(f);
  }).catch(() => {});
})();

// This fills in the project label on every page, and adds the installed plugins' pages
// (orchestra/plugins.py) after Orchestra's own.
fetch("/api/project").then((r) => r.json()).then((p) => { const el = $("proj"); if (el) el.textContent = p.key; }).catch(() => {});
fetch("/api/plugins").then((r) => r.json()).then((d) => {
  const nav = $("nav"), at = $("proj");
  if (!nav) return;
  for (const pg of d.pages || []) {
    const a = document.createElement("a");
    a.href = pg.path; a.textContent = pg.title;
    if (location.pathname === pg.path || location.pathname.startsWith(pg.path + "/")) a.className = "on";
    nav.insertBefore(a, at);
  }
  // scripts a plugin runs on every page, after Orchestra's own (a page that already has one keeps it)
  for (const src of d.scripts || []) {
    if ([...document.scripts].some((s) => s.src && new URL(s.src).pathname === src)) continue;
    const s = document.createElement("script"); s.src = src; document.body.appendChild(s);
  }
}).catch(() => {});

// The drawer: every one opens with a close bar (×) that stays at its top while it scrolls, closes
// on Escape, and on a phone, where it fills the screen, on Back (a history entry while it is open).
// It is a modal dialog: the page behind it is inert while it is open, the close button takes the
// focus, and closing gives the focus back to what opened it. ``key`` names what it shows: the same
// key again is a refresh (its scroll and focus kept), another opens at its top.
let DRAWER_BACK = false;           // a close's history.back() not yet arrived: its popstate is not a Back to act on
let DRAWER_FROM = null, DRAWER_FROM_ID = null;
function openDrawer(html, opts = {}) {
  const ov = $("overlay"), dr = $("drawer"), was = ov.classList.contains("open");
  // the key: given, or said by the html itself (data-drawer-key), so a page script that wraps
  // openDrawer(html) and passes the html alone keeps it
  const key = opts.key != null ? String(opts.key) : ((/data-drawer-key="([^"]*)"/.exec(html) || [])[1] || ""), same = was && key !== "" && dr.dataset.key === key, top = dr.scrollTop;
  if (!was) { DRAWER_FROM = document.activeElement; const own = DRAWER_FROM && DRAWER_FROM.closest ? DRAWER_FROM.closest("[data-id]") : null; DRAWER_FROM_ID = own ? own.dataset.id : null; }
  dr.innerHTML = '<div class="drawer-bar"><button class="ctl drawer-close" type="button" aria-label="close" title="close (Esc)" onclick="closeDrawer()">×</button></div>' + html;
  dr.dataset.key = key;
  dr.setAttribute("role", "dialog"); dr.setAttribute("aria-modal", "true");
  const h = dr.querySelector("h3");
  if (h) { h.id = h.id || "drawer-title"; dr.setAttribute("aria-labelledby", h.id); } else dr.removeAttribute("aria-labelledby");
  ov.classList.add("open");
  dr.scrollTop = same ? top : 0;
  for (const el of document.body.children) if (el !== ov && el.tagName !== "SCRIPT") el.inert = true;
  if (!same) { const c = dr.querySelector(".drawer-close"); if (c) try { c.focus({ preventScroll: true }); } catch (e) {} }
  if (!was && !DRAWER_BACK) { try { history.pushState({ ...(history.state || {}), drawer: true }, ""); } catch (e) {} }
}
// the page behind comes back, and the focus to what opened the drawer (or what replaced it)
function drawerClosed() {
  for (const el of document.body.children) el.inert = false;
  document.dispatchEvent(new Event("orchestra:drawerclosed"));
  let back = DRAWER_FROM && DRAWER_FROM.isConnected && DRAWER_FROM !== document.body ? DRAWER_FROM : null;
  if (!back && DRAWER_FROM_ID) back = document.querySelector(`[data-id="${CSS.escape(DRAWER_FROM_ID)}"]`);
  DRAWER_FROM = DRAWER_FROM_ID = null;
  if (back && back.focus) try { back.focus({ preventScroll: true }); } catch (e) {}
}
function closeDrawer() {
  const ov = $("overlay");
  if (!ov || !ov.classList.contains("open")) return;
  ov.classList.remove("open");
  drawerClosed();
  if (history.state && history.state.drawer) { try { DRAWER_BACK = true; history.back(); } catch (e) { DRAWER_BACK = false; } }
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("overlay") && $("overlay").classList.contains("open")) closeDrawer(); });
if (typeof window.addEventListener === "function") window.addEventListener("popstate", () => { const ov = $("overlay");
  // the close's own back arrived: a drawer opened meanwhile gets its history entry now
  if (DRAWER_BACK) { DRAWER_BACK = false; if (ov && ov.classList.contains("open")) { try { history.pushState({ ...(history.state || {}), drawer: true }, ""); } catch (e) {} } return; } if (ov && ov.classList.contains("open")) { ov.classList.remove("open"); drawerClosed(); } });

// A link printed by `orchestra web` carries the token after '#': never leave it in the address bar.
if (/^#token=/.test(location.hash)) { try { history.replaceState(history.state, "", location.pathname + location.search); } catch (e) {} }

// Whether the page's data is live: one word in the nav for every page's pollers. ``ok`` false
// keeps the time of the last answer, so a page that stopped hearing from the server says so.
// ``Orchestra.asOf(seconds)`` is that time as HH:MM (or HH:MM:SS), or "" before any answer.
Orchestra.conn = (() => {
  let last = null;
  const hm = (t, s) => Orchestra.when(t / 1000, { seconds: !!s });
  Orchestra.asOf = (s) => (last ? hm(last, s) : "");
  return (ok, opts = {}) => {
    const el = $("conn");
    if (ok) last = Date.now();
    if (el) {
      el.textContent = ok ? `page updated ${hm(last, true)}` : `disconnected${last ? ` · as of ${hm(last, opts.seconds)}` : ""}`;
      el.classList.toggle("stale", !ok);
      el.title = ok ? "the page is reading the server" : "the server did not answer: what the page shows is from the time given";
    }
    return last;
  };
})();


// Log highlighting (highlightLog: the Core page, the machine dialog, and the plugins' pages that
// load app.js use it). Logs have no grammar, so this is lexical: each pattern below is tried at the
// current position, first match wins, and everything else passes through escaped.
const LOG_RULES = [
  [/\x1b\[[0-9;]*m/y, null],                                                    // ANSI escapes: dropped
  [/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?/y, "ts"],
  [/\b\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\b/y, "ts"],
  [/\b(?:ERROR|CRITICAL|FATAL|Traceback|Exception|FAILED|failed|error)\b/y, "err"],
  [/\b(?:WARN(?:ING)?|warning|deprecated)\b/y, "warn"],
  [/\b(?:INFO|DEBUG|TRACE|healthy|passed|ok|OK|200|201|204)\b/y, "ok"],
  [/\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b/y, "method"],
  [/\b[45]\d{2}\b/y, "err"],
  [/\b3\d{2}\b/y, "warn"],
  [/https?:\/\/[^\s"'<>)\]]+/y, "url"],
  [/\[[^\]\n]{1,40}\]/y, "tag"],
  [/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/y, "str"],
  [/(?:~|\.{1,2})?\/[\w.\-~+@%]+(?:\/[\w.\-~+@%]*)+/y, "path"],
  [/\b[A-Za-z_][\w.-]*(?==[^=\s])/y, "key"],
  [/\b\d+(?:\.\d+)?(?:ms|s|m|h|%|[kMG]i?B)?\b/y, "num"],
];

function highlightLog(text) {
  let out = "", i = 0;
  while (i < text.length) {
    let matched = false;
    for (const [re, cls] of LOG_RULES) {
      re.lastIndex = i;
      const m = re.exec(text);
      if (m && m.index === i && m[0].length) {
        out += cls ? `<span class="lg-${cls}">${esc(m[0])}</span>` : "";
        i += m[0].length; matched = true; break;
      }
    }
    if (!matched) {
      // Advance to the next candidate start cheaply: copy a run of plain word/space chars.
      const run = /[^\x1b\d"'\[/~.A-Za-z]+|[A-Za-z]+|./y; run.lastIndex = i;
      const m = run.exec(text); const chunk = m ? m[0] : text[i];
      out += esc(chunk); i += chunk.length;
    }
  }
  return out;
}
