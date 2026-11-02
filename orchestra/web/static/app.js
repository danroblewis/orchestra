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
// Colours are given in a stable order over the sorted ids of every machine the Machines API lists
// (Orchestra.setMachines, kept in the browser so every page has the same list), so no two machines
// share one while the palette lasts (16); past it a hue comes round again, never the grey that means
// "no machine". Before any list is known, a hash of the id.
const MPAL = ["#60a5fa", "#f59e0b", "#e879f9", "#22c55e", "#f87171", "#38bdf8", "#facc15", "#a78bfa", "#fb923c", "#2dd4bf",
  "#818cf8", "#f472b6", "#a3e635", "#c084fc", "#34d399", "#fda4af"];
const MGREY = "#94a3b8";
let MORDER = (() => { try { return JSON.parse(localStorage.getItem("orchestra.machine.order")) || null; } catch (e) { return null; } })();
const mcolor = (id) => { if (!id || id === "none") return MGREY;
  if (MORDER) { const i = MORDER.indexOf(String(id).split("/")[0]); if (i >= 0) return MPAL[i % MPAL.length]; }
  let h = 0; for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return MPAL[h % MPAL.length]; };
const ago = (sec) => (sec < 60 ? `${Math.round(sec)}s` : sec < 3600 ? `${Math.round(sec / 60)}m` : `${(sec / 3600).toFixed(1)}h`);
const fmtBytes = (b) => (b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(1)} GB` : `${Math.round(b / (1 << 20))} MB`);

window.Orchestra = window.Orchestra || {};
// the machines /api/machines listed: their colours' order (mcolor), the same on every page
Orchestra.setMachines = (ms) => { const ids = [...new Set((ms || []).map((m) => m.id))].sort();
  if (MORDER && ids.length === MORDER.length && ids.every((x, i) => x === MORDER[i])) return;
  MORDER = ids; try { localStorage.setItem("orchestra.machine.order", JSON.stringify(ids)); } catch (e) {} };
// One time formatter, with the zone, for every page (a plugin's pages delegate to it):
// "12:03 PST"; {seconds: true} "12:03:07 PST"; {date: true} "Nov 1, 12:03 PST".
// ``t`` in seconds since the epoch; none reads "—"
Orchestra.when = (t, o = {}) => (t == null ? "—" : new Date(t * 1000).toLocaleString(undefined, {
  ...(o.date ? { month: "short", day: "numeric" } : {}), hour: "2-digit", minute: "2-digit", ...(o.seconds ? { second: "2-digit" } : {}),
  hourCycle: "h23", timeZoneName: "short" }));
const hhmm = (t) => Orchestra.when(t);
// Whether a machine is active, said the same way everywhere (the Dashboard's row, a card's seen row,
// the map's tooltip, the dialog), in one word set: active / late / quiet / no evidence yet (and
// "not answering" when what it listens for arrives and it does not act), with green only for
// active. A cadence (orchestra/cadence.py: three beats at least) is its own rhythm: active while heard
// within it, late past 2.5× it though inside the 2-minute floor. With no cadence there is no rhythm to
// be in: "heard Ns ago", neutral. A machine whose events never stop long enough to make a beat (none
// more than BURST_S apart) publishes continuously: active. The host's flag is the runtime record's
// (``active_by: "runtime"``): "running". {word, cls ("live", "late", "neutral" or "quiet"), detail, title}
Orchestra.BURST_S = 48;            // cadence.BURST_S: an event this soon after the last is the same burst
Orchestra.FLOOR_S = 120;           // cadence.ACTIVE_FLOOR_S
Orchestra.MARGIN = 2.5;            // cadence.ACTIVE_MARGIN
Orchestra.continuous = (x) => !x.cadence_s && x.first_seen != null && x.last_seen != null && x.last_seen - x.first_seen > Orchestra.BURST_S;
// what it listens for that arrived after its own last event, unanswered: {n, type, since, types,
// parts, text} for the ones past the floor, or null (web/machines.py ``unanswered``). ``text`` gives
// each type its own count, the oldest first: "4 job.made, 4 job.dropped since 22:24"
Orchestra.unanswered = (m, now = Date.now() / 1000) => {
  const u = Object.entries((m && m.unanswered) || {}).filter(([, v]) => v.count > 0 && now - v.since > Orchestra.FLOOR_S).sort((a, b) => a[1].since - b[1].since);
  if (!u.length) return null;
  const parts = u.map(([type, v]) => ({ type, count: v.count, since: v.since }));
  return { n: parts.reduce((a, p) => a + p.count, 0), type: parts[0].type, since: parts[0].since, types: parts.map((p) => p.type), parts,
           text: `${parts.map((p) => `${p.count} ${p.type}`).join(", ")} since ${hhmm(parts[0].since)}` };
};
// the types several machines listen for that none of them answered (web/machines.py
// ``unanswered_types``), past the floor, each said once: "8 job.made since 22:24, answered by
// none of its listeners: worker, nudger"
Orchestra.unansweredTypes = (d, now = Date.now() / 1000) => ((d && d.unanswered_types) || []).filter((u) => u.count > 0 && now - u.since > Orchestra.FLOOR_S)
  .map((u) => `${u.count} ${u.type} since ${hhmm(u.since)}, answered by none of its listeners: ${(u.listeners || []).join(", ")}`);
Orchestra.liveness = (m, now = Date.now() / 1000) => {
  if (m.active_by === "runtime") return { word: m.active ? "running" : "not running", cls: m.active ? "live" : "quiet", detail: "",
    title: "by the runtime record: the host process is in it; it publishes only when it starts and stops" };
  if (!m.last_seen) return { word: "no evidence yet", cls: "quiet", detail: "", title: m.intent ? "declared: nothing on the bus under it" : "nothing on the bus under it yet" };
  const last = `last ${ago(now - m.last_seen)} ago`, since = now - m.last_seen;
  const un = Orchestra.unanswered(m, now);
  if (un) return { word: `not answering: ${un.text}`, cls: "late", detail: last,
    title: `events it listens for (${un.types.join(", ")}) arrived after its own last event and it has not acted since` };
  const n = (m.publishes || []).reduce((a, p) => a + (p.count || 0), 0);
  if (!n && m.active) return { word: "announced, nothing published yet", cls: "neutral", detail: last, title: "its only event is its own announcement" };
  // its rhythm is the machine's own (its instances' beats merged, web/machines.py), never one instance's
  const g = m.cadence_s || null;
  // events too close together to make beats: how often, on average, never "continuously" (beside an
  // announced "ad hoc" that would read as a contradiction)
  const every = n > 1 ? (m.last_seen - m.first_seen) / (n - 1) : null;
  // late, for a machine that listens for something, while nothing it listens for waits, is only quiet
  const late = (lv) => ((m.subscribes || []).length ? { word: "quiet: nothing it listens for is waiting", cls: "quiet", detail: lv.detail,
    title: `${lv.title}; nothing it listens for arrived since its last event, so there is nothing for it to do` } : lv);
  if (m.active && !g && every != null && every < Orchestra.BURST_S && Orchestra.continuous(m)) {
    // no cadence, but it publishes often: its average gap is its rhythm
    const lv = { detail: `about every ${ago(every)} · last event ${ago(since)} ago` };
    if (since <= Math.max(Orchestra.BURST_S, Orchestra.MARGIN * every)) return { ...lv, word: "active", cls: "live", title: "heard within its usual gap; its events come too close together to make a cadence of beats" };
    if (since <= Math.max(Orchestra.FLOOR_S, Orchestra.MARGIN * every)) return late({ ...lv, word: "late by its own rhythm", cls: "late", title: `not heard within ${Orchestra.MARGIN}× its average gap (${ago(every)})` });
    return { word: "quiet", cls: "quiet", detail: `since ${hhmm(m.last_seen)}; about every ${ago(every)}`, title: `nothing heard within ${Orchestra.MARGIN}× its average gap (at least 2 min)` };
  }
  if (m.active && !g) return { word: `heard ${ago(since)} ago`, cls: "neutral", detail: "no rhythm of its own yet (three beats make one)",
    title: "heard within the 2-minute floor; with no cadence of its own there is no rhythm to be in" };
  if (m.active && since > Orchestra.MARGIN * g) return late({ word: "late by its own rhythm", cls: "late", detail: `about every ${ago(g)}; ${last}`,
    title: `not heard within ${Orchestra.MARGIN}× its usual gap, though still within the 2-minute floor` });
  if (m.active) return { word: "active", cls: "live", detail: `about every ${ago(g)}; ${last}`, title: `heard within ${Orchestra.MARGIN}× its usual gap (at least 2 min)` };
  return { word: "quiet", cls: "quiet", detail: `since ${hhmm(m.last_seen)}${g ? `; about every ${ago(g)}` : ""}`, title: `nothing heard within ${Orchestra.MARGIN}× its usual gap (at least 2 min)${g ? `: usual gap ${ago(g)}` : ""}` };
};
// the word a machine is counted under (the Dashboard's header and its rows and notes): active, not
// answering, late, heard (no rhythm yet), quiet, or no evidence yet
Orchestra.livenessGroup = (m, now = Date.now() / 1000) => { const lv = Orchestra.liveness(m, now);
  return lv.cls === "late" ? (lv.word.startsWith("not answering") ? "not answering" : "late") : lv.cls === "live" ? "active" : lv.cls === "neutral" ? "heard, no rhythm yet" : m.last_seen ? "quiet" : "no evidence yet"; };
// a liveness as a span: its word in its class's colour (lv-live green, lv-late amber, the rest grey)
Orchestra.livenessHtml = (lv) => `<span class="lv-${lv.cls}" title="${esc(lv.title)}">${esc(lv.word)}</span>${lv.detail ? ` <span class="muted">· ${esc(lv.detail)}</span>` : ""}`;
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
// rows and notes add up to the count in its header, grouped by the word the header counts it under
// (Orchestra.livenessGroup): a machine late or not answering is always a row; the quiet note holds
// exactly the header's quiet ones; the declared ones not heard (and the proposed ones never heard)
// and the rest with no evidence yet are notes of their own.
Orchestra.dashboardGroups = (ms, now = Date.now() / 1000) => {
  const group = new Map(ms.map((m) => [m, Orchestra.livenessGroup(m, now)]));
  const unheard = ms.filter((m) => group.get(m) === "no evidence yet" && m.intent && !m.intent.heard);
  const quiet = ms.filter((m) => group.get(m) === "quiet"), unseen = ms.filter((m) => group.get(m) === "no evidence yet" && !unheard.includes(m));
  return { rows: ms.filter((m) => !["quiet", "no evidence yet"].includes(group.get(m))), proposed: unheard.filter((m) => m.intent.state === "proposed"),
           declared: unheard.filter((m) => m.intent.state !== "proposed"), quiet, unseen, group };
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
    // the frame carries the machine's colour (mcolor, the same on every page) in its corner, drawn by
    // Orchestra whatever the package draws inside it
    wrap(m, html, extra = "") {
      return `<div class="panel mcard ${extra} ${m.unseen ? "unseen" : ""}" data-id="${esc(m.id)}" tabindex="0" role="button" aria-label="${esc(m.name || m.id)}: open its details" onclick="openMachine(this.dataset.id)" onkeydown="if(event.target===this&&(event.key==='Enter'||event.key===' ')){event.preventDefault();openMachine(this.dataset.id)}"><span class="mcard-id" style="background:${m.bootstrap ? "#fbbf24" : mcolor(m.id)}" title="its colour on every page"></span>${html}</div>`;
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
    <div class="row"><span class="muted">seen</span><span class="rv">${seenText(m, now)}${m.first_seen || m.active_by ? ` · ${Orchestra.livenessHtml(lv)}` : ""}</span></div>
    ${Orchestra.restarted(m) ? `<div class="row"><span class="muted">started</span><span>${Orchestra.restarted(m)}</span></div>` : ""}
    <div class="row"><span class="muted">publishes</span>${(m.publishes || []).map(chip).join("") || '<span class="muted">nothing</span>'}</div>
    <div class="row"><span class="muted">listens for</span>${(m.subscribes || []).map((t) => `<span class="ty">${esc(t)}</span>${unansweredText(m, t)}`).join("") || '<span class="muted">nothing</span>'}</div>
    ${(m.counted || []).length ? `<div class="row"><span class="muted">counted</span>${m.counted.map((t) => t.direction === "backlog"
      ? `<span class="ty" title="what waits for it in ${esc(t.channel)}">${esc(t.channel)} · ${Math.round(t.backlog ?? 0).toLocaleString()} waiting</span>`
      : `<span class="ty" title="${Math.round(t.window).toLocaleString()} in the last hour, counted on another system's bus">${t.direction === "out" ? "→" : "←"} ${esc(t.channel)} · ${t.per_min}/min</span>`).join("")}</div>` : ""}
    <div class="row"><span class="muted" title="flows of the model its events match in time: hypotheses, not causes">flows (hypotheses)</span>${(m.flows || []).map((f) => { const h = Orchestra.hypothesis(m, f);
      return `<a class="ty fl" href="/dynamics#f:${encodeURIComponent(f.flow)}" onclick="event.stopPropagation()" title="${esc([h.title, f.why].filter(Boolean).join(" · "))} · open it on Dynamics">${esc(Orchestra.flowLabel(f))}${h.text ? ` · ${esc(h.text)}` : ""}</a>`; }).join("") || '<span class="muted">none hypothesised yet</span>'}</div>`;
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

// a machine's hypothesis on a flow as Dynamics says it (evidence-text.js, over the flow's record from
// /api/machines): its confidence and what chance alone would pair ("62%, 38% by chance"); no number
// where timing cannot tell it from the flow's other machines, or the flow had too few events to fit,
// or the flow's record is not known: {text, title}
Orchestra.hypothesis = (m, f) => {
  const E = window.Evidence, rec = f && f.record;
  if (!E || !rec) return { text: "", title: "" };
  const flow = { ...rec, machines: (rec.machines || []).length ? rec.machines : [{ machine: m.id, confidence: f.confidence, chance: f.chance }] };
  const h = flow.machines.find((x) => x.machine === m.id) || { machine: m.id, confidence: f.confidence, chance: f.chance };
  if (E.tooFew(flow)) return { text: "", title: E.tooFewText(flow) };
  const others = flow.machines.length - 1;
  if (E.untold(null, flow)) return { text: "", title: others ? `timing cannot tell it from ${others} other${others === 1 ? "" : "s"}` : E.untold(null, flow) };
  return { text: `${E.confidence(flow, h).trim()}${E.chance(flow, h)}`, title: "" };
};
// a machine announced more than once by one of its instances (a restart): a tag on its card,
// "announced again at 22:29 (3 times)" (web/machines.py ``announced``)
Orchestra.restarted = (m) => { const again = (m.instances || []).filter((i) => i.announced > 1), n = again.length ? Math.max(...again.map((i) => i.announced)) : (m.announced || 0);
  const at = again.length ? Math.max(...again.map((i) => i.announced_at || 0)) : m.announced_at;
  return n > 1 && at ? `<span class="tag" title="an instance published orchestra.machine.started more than once: each is a start">announced again at ${esc(hhmm(at))} (${n} times)</span>` : ""; };
// beside a type a machine listens for: how many arrived since its own last event (web/machines.py)
const unansweredText = (m, t) => { const u = ((m && m.unanswered) || {})[t]; if (!u || !u.count) return "";
  const old = Date.now() / 1000 - u.since > Orchestra.FLOOR_S;
  return ` <span class="${old ? "lv-late" : "muted"}" title="published by other machines after this one's last event, the oldest at ${esc(hhmm(u.since))}">${u.count} since its last event</span>`; };
// the window a publishes rate is over: the last ten minutes, or since the machine was first seen
Orchestra.rateWindow = (p) => (p.window_s && p.window_s < 600 ? `${(p.window_s / 60).toFixed(1).replace(/\.0$/, "")} min (since first seen)` : "the last 10 min");
// A hypothesised flow as Dynamics names it: its ends, then the counter's move, so two flows of one
// counter (twins) read apart. The names are SDGraph's (sd-graph.js), over the model's parts the
// page was given (/api/machines ``model_parts``); without them, the flow's own name.
Orchestra.modelParts = null;
Orchestra.flowLabel = (f) => {
  const mp = Orchestra.modelParts, G = window.SDGraph;
  if (!mp || !G) return f.name || f.flow;
  const rec = mp.flows.find((x) => x.id === f.flow), end = (which) => (rec ? G.endName(mp, rec, which) : f[which] ? G.stockName(mp, f[which]) : "outside");
  const move = rec ? G.flowName(mp, rec) : f.name || f.flow;
  return `${end("from")} → ${end("to")} · ${move}`;
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

// A phone's nav is one row that scrolls: the current page is scrolled into view, and while links are
// off the right edge the row fades out there (style.css nav.more-right)
function navFit() {
  const nav = $("nav"); if (!nav) return;
  const on = nav.querySelector("a.on");
  if (on && nav.scrollWidth > nav.clientWidth) { const l = on.offsetLeft - nav.offsetLeft, r = l + on.offsetWidth;
    if (l < nav.scrollLeft || r > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = Math.max(0, r - nav.clientWidth + 24); }
  nav.classList.toggle("more-right", nav.scrollWidth > nav.clientWidth + nav.scrollLeft + 2);
}
if ($("nav")) { $("nav").addEventListener("scroll", () => $("nav").classList.toggle("more-right", $("nav").scrollWidth > $("nav").clientWidth + $("nav").scrollLeft + 2), { passive: true });
  addEventListener("resize", navFit); setTimeout(navFit, 0); }

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
    nav.appendChild(f); navFit();
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
  navFit();
  // scripts a plugin runs on every page, after Orchestra's own (a page that already has one keeps it)
  for (const src of d.scripts || []) {
    if ([...document.scripts].some((s) => s.src && new URL(s.src).pathname === src)) continue;
    const s = document.createElement("script"); s.src = src; document.body.appendChild(s);
  }
}).catch(() => {});

// A redraw that replaces what has the keyboard focus gives it back: before ``render`` the focused
// element's key is noted (data-id, data-name, data-item, data-fid, data-sid or data-key, on it or
// the nearest element around it in ``container``), and after it the element with that key is focused.
Orchestra.keepFocus = (container, render) => {
  const a = document.activeElement, keys = ["id", "name", "item", "fid", "sid", "key"];
  let key = null;
  if (container && a && a !== container && container.contains(a))
    for (let el = a; el && el !== container && !key; el = el.parentElement) { const k = keys.find((x) => el.dataset && el.dataset[x] != null); if (k) key = [k, el.dataset[k]]; }
  const out = render();
  if (key && container) { const el = container.querySelector(`[data-${key[0]}="${CSS.escape(key[1])}"]`);
    if (el && el !== document.activeElement && el.focus) try { el.focus({ preventScroll: true }); } catch (e) {} }
  return out;
};

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
  // the same drawer redrawn keeps its focus (Orchestra.keepFocus); another opens on its close button
  const draw = () => { dr.innerHTML = '<div class="drawer-bar"><button class="ctl drawer-close" type="button" aria-label="close" title="close (Esc)" onclick="closeDrawer()">×</button></div>' + html; };
  if (same) Orchestra.keepFocus(dr, draw); else draw();
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
// Tab stays inside an open drawer: from its last control to its first, Shift+Tab the other way, never through the page behind
document.addEventListener("keydown", (e) => {
  const ov = $("overlay"), dr = $("drawer");
  if (e.key !== "Tab" || !ov || !dr || !ov.classList.contains("open")) return;
  const all = [...dr.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, textarea, summary, [tabindex]:not([tabindex="-1"])')].filter((x) => x.offsetParent !== null);
  if (!all.length) return;
  const first = all[0], last = all[all.length - 1], at = document.activeElement;
  if (e.shiftKey && (at === first || !dr.contains(at))) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && (at === last || !dr.contains(at))) { e.preventDefault(); first.focus(); }
});
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
