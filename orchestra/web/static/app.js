// Shared helpers, nav, and drawers for the Orchestra UI.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const color = (s) => `var(--${s})`;
// How a machine was seen, one wording wherever it is shown: on the bus (first and last), by its
// counted traffic only, or not yet.
const seenText = (m, now = Date.now() / 1000) => (m.first_seen ? `first ${ago(now - m.first_seen)} ago, last ${ago(now - m.last_seen)} ago`
  : m.counted_only ? (m.last_seen ? `known by counts only; last counted ${ago(now - m.last_seen)} ago` : "known by counts only")
  : "no events yet");
const ago = (sec) => (sec < 60 ? `${Math.round(sec)}s` : sec < 3600 ? `${Math.round(sec / 60)}m` : `${(sec / 3600).toFixed(1)}h`);
const fmtBytes = (b) => (b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(1)} GB` : `${Math.round(b / (1 << 20))} MB`);

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
window.Orchestra = window.Orchestra || {};
Orchestra.machineCards = (() => {
  const by = new Map();
  const changed = () => document.dispatchEvent(new Event("orchestra:machinecards"));
  return {
    register(pkg, spec) { by.set(pkg, spec); changed(); },
    of(m) { return (m && m.package && by.get(m.package)) || null; },
    card(m, opts = {}) { const s = this.of(m); try { return s && s.card ? s.card(m, opts) : null; } catch (e) { return null; } },
    summary(m) { const s = this.of(m); try { return s && s.summary ? s.summary(m) : null; } catch (e) { return null; } },
    wrap(m, html, extra = "") {
      return `<div class="panel ${extra} ${m.unseen ? "unseen" : ""}" data-id="${esc(m.id)}" onclick="openMachine(this.dataset.id)">${html}</div>`;
    },
    // What Orchestra observed of a machine, as the rows of its card, drawn under whatever its
    // package put there: how it is engaged and what kind of thing it is (announced), its package,
    // its instances, when it was seen, what it publishes (all time, and the rate in the last ten
    // minutes when there is one) and listens for, its counted traffic on another system's bus
    // (rates and backlogs, never events), and the flows the latest discovery hypothesises it is
    // associated with (a match in time; a series never belongs to a machine). One function, so
    // every card shows the same rows.
    rows(m) {
      const now = Date.now() / 1000;
      const chip = (p) => `<span class="ty" title="${p.count} events, ${p.day} in 24 h, ${p.per_min_10m}/min in the last 10 min">${esc(p.type)} · ${p.count}${p.per_min_10m ? ` · ${p.per_min_10m}/min` : ""}</span>`;
      return `<div class="row"><span class="muted">engaged</span><span>${m.mode ? `<span class="tag k-${esc(m.mode.replace(/ /g, "_"))}">${esc(m.mode.replace("_", " "))}</span>` : '<span class="muted">not announced</span>'}</span><span class="muted">kind</span><span>${m.kind ? `<span class="tag">${esc(kindWord(m.kind))}</span>` : '<span class="muted">not announced</span>'}</span></div>
    <div class="row"><span class="muted">package</span><span>${m.package ? esc(m.package) : '<span class="muted">no package</span>'}</span>${m.group ? `<span class="muted">group</span><span><span class="tag" title="the group it announced (a team): a label, not a separate system">${esc(m.group)}</span></span>` : ""}</div>
    ${m.instances && m.instances.length ? `<div class="row"><span class="muted">instances</span>${m.instances.map((i) => `<span class="ty" title="${i.kind ? `${esc(i.kind)}, ` : ""}last seen ${ago(now - i.last_seen)} ago"><span class="dot ${i.active ? "" : "off"}" style="--rc:${i.active ? "#22c55e" : "#64748b"};width:7px;height:7px"></span> ${esc(i.id)}</span>`).join("")}</div>` : ""}
    <div class="row"><span class="muted">seen</span><span>${seenText(m, now)}</span></div>
    <div class="row"><span class="muted">publishes</span>${(m.publishes || []).map(chip).join("") || '<span class="muted">nothing</span>'}</div>
    <div class="row"><span class="muted">listens for</span>${(m.subscribes || []).map((t) => `<span class="ty">${esc(t)}</span>`).join("") || '<span class="muted">nothing</span>'}</div>
    ${(m.counted || []).length ? `<div class="row"><span class="muted">counted</span>${m.counted.map((t) => t.direction === "backlog"
      ? `<span class="ty" title="what waits for it in ${esc(t.channel)}">${esc(t.channel)} · ${Math.round(t.backlog ?? 0).toLocaleString()} waiting</span>`
      : `<span class="ty" title="${Math.round(t.window).toLocaleString()} in the last hour, counted on another system's bus">${t.direction === "out" ? "→" : "←"} ${esc(t.channel)} · ${t.per_min}/min</span>`).join("")}</div>` : ""}
    <div class="row"><span class="muted" title="flows of the model its events match in time: hypotheses, not causes">flows (hypotheses)</span>${(m.flows || []).map((f) => `<span class="ty" title="${esc(f.why || "")}">${esc(f.name || f.flow)}${f.confidence != null ? ` · ${Math.round(100 * f.confidence)}%` : ""}</span>`).join("") || '<span class="muted">none hypothesised yet</span>'}</div>`;
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

function openDrawer(html) { $("drawer").innerHTML = html; $("overlay").classList.add("open"); }
function closeDrawer() { $("overlay").classList.remove("open"); }


// ---- log highlighting -------------------------------------------------------
// Logs have no grammar, so this is lexical: each pattern below is tried at the
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
