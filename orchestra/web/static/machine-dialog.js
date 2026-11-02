// A machine's dialog, on any page that lists machines (the Machines page, the Dashboard): what it
// is, its instances, what it publishes and listens for, the flows it is hypothesised to be
// associated with, its last events and the tail of its log, refreshed while open. A machine its package claims opens the package's own
// dialog instead (Orchestra.machineCards). The page says where its machines are:
// Orchestra.machineList = () => [...].
window.Orchestra = window.Orchestra || {};
Orchestra.machineList = Orchestra.machineList || (() => []);
// (a machine's colour, mcolor, is app.js's: one palette on every page)
// what a machine announced it is (orchestra.machine.started data.kind, or its package's declaration), in words
const kindWord = (kind) => kind || "machine";

// a machine's dialog: what it is, its instances, what it publishes and listens for, its counted
// traffic on another system's bus, its hypothesised flows, its last events and the tail of its log
// (refreshed while open)
let OPEN = null, OPEN_TIMER = null, LOG_INST = null, EV_SHOWN = 15;
function closeMachine() { OPEN = null; clearInterval(OPEN_TIMER); $("drawer").classList.remove("mdlg"); closeDrawer(); }
// closed by the drawer's own × (app.js), Escape or Back: stop refreshing it
document.addEventListener("orchestra:drawerclosed", () => { if (OPEN) { OPEN = null; clearInterval(OPEN_TIMER); $("drawer").classList.remove("mdlg"); } });
// A page with a details panel (the Machines page: Orchestra.machinePanel) opens a machine there;
// ``{dialog: true}`` asks for this dialog itself (the panel's "details and log").
function openMachine(id, { dialog = false } = {}) {
  const own = Orchestra.machineCards && Orchestra.machineCards.skip === id;     // a package's "machine details": this dialog
  if (!dialog && !own && Orchestra.machinePanel && Orchestra.machinePanel(id)) return;
  const m = Orchestra.machineList().find((x) => x.id === id); if (!m) return;
  if (Orchestra.machineCards.open(m)) return;                     // its package draws its own dialog
  OPEN = id; LOG_INST = (m.logs || [])[0] || null; EV_SHOWN = 15;
  $("drawer").classList.add("mdlg");
  openDrawer(`<h3 data-drawer-key="m:${esc(id)}"><span class="dot ${m.active ? "" : "off"}" style="--rc:${m.bootstrap ? "#fbbf24" : mcolor(m.id)}"></span>${esc(m.id)} <span class="mchip" title="its kind, as announced">${esc(kindWord(m.kind))}</span>${m.bootstrap ? ' <span class="mchip">bootstrap host</span>' : ""}${m.mode ? ` <span class="mchip" title="how it is engaged, as announced">${esc(m.mode.replace("_", " "))}</span>` : ""}${m.package ? ` <span class="mchip" title="the package it belongs to">${esc(m.package)}</span>` : ""}</h3>
    <div class="row" id="m-seen">${dlgSeen(m)}</div>
    ${Orchestra.aboutLines(m).length ? `<h4>Announced <span style="text-transform:none;letter-spacing:0;font-weight:400">(what it said of itself, as it said it)</span></h4><div class="about">${Orchestra.aboutHtml(m)}</div>` : ""}
    <div id="m-insts">${dlgInstances(m)}</div>
    <h4>Log</h4><div class="seg" id="m-loginst"></div><div class="muted" id="m-lognote" style="font-size:11.5px"></div><div class="term" id="m-log" style="display:none"></div>
    <h4>Publishes</h4><div id="m-pubs">${dlgPublishes(m)}</div>
    <h4>Listens for</h4><div class="row">${m.subscribes.map((t) => `<span class="ty">${esc(t)}</span>`).join("") || '<span class="muted">nothing announced</span>'}</div>
    ${(m.counted || []).length ? `<h4>Counted traffic <span style="text-transform:none;letter-spacing:0;font-weight:400">(counts a source read from another system's bus; never events)</span></h4><table class="dt"><tr><th>channel</th><th></th><th>last 10 min</th><th>last hour</th><th>waiting</th></tr>${m.counted.map((t) => `<tr><td class="num">${esc(t.channel)}</td><td>${t.direction === "out" ? "produces into" : t.direction === "in" ? "consumes from" : "its backlog"}</td><td class="num">${t.direction === "backlog" ? "" : `${t.per_min}/min`}</td><td class="num">${t.direction === "backlog" ? "" : Math.round(t.window).toLocaleString()}</td><td class="num">${t.backlog == null ? "" : Math.round(t.backlog).toLocaleString()}</td></tr>`).join("")}</table>` : ""}
    <h4>Flows <span style="text-transform:none;letter-spacing:0;font-weight:400">(hypotheses: its events match the flow's counter in time, which is not a cause)</span></h4>${(m.flows || []).length ? `<table class="dt"><tr><th>flow</th><th>confidence</th><th>its events</th><th>why</th></tr>${m.flows.map((f) => `<tr><td><a href="/dynamics#f:${encodeURIComponent(f.flow)}" title="open it on Dynamics">${esc(Orchestra.flowLabel(f))}</a></td><td class="num" title="${esc(Orchestra.hypothesis(m, f).title)}">${esc(Orchestra.hypothesis(m, f).text || (Orchestra.hypothesis(m, f).title ? "no number" : "—"))}</td><td class="num">${esc((f.events || {}).type || "")}</td><td class="muted">${esc(f.why || "")}</td></tr>`).join("")}</table>` : '<div class="muted">none hypothesised yet: no flow of the latest model matches its events</div>'}
    <h4>Last events <span style="text-transform:none;letter-spacing:0;font-weight:400">(envelopes; the data is the machine's own)</span></h4><div id="m-events" class="muted">reading…</div>`, { key: "m:" + id });
  machineDetail();
  clearInterval(OPEN_TIMER); OPEN_TIMER = setInterval(() => { if (!$("overlay").classList.contains("open")) return closeMachine(); machineDetail(true); }, 5000);
}
// the parts of the dialog that change while it is open, drawn again on every refresh
function dlgSeen(m) {
  const lv = Orchestra.liveness(m);
  return `<span class="muted">seen</span><span>${seenText(m)} · ${Orchestra.livenessHtml(lv)}</span>`;
}
function dlgInstances(m) {
  const insts = m.instances && m.instances.length ? m.instances : [], now = Date.now() / 1000;
  // an instance announced more than once restarted: when last, and how many times
  const again = (i) => (i.announced > 1 ? `<span class="stale" title="it published orchestra.machine.started ${i.announced} times: each is a start">announced again at ${esc(Orchestra.when(i.announced_at))} (${i.announced} times)</span>` : '<span class="muted">once</span>');
  return insts.length ? `<h4>Instances</h4><table class="dt"><tr><th>instance</th><th>kind</th><th>state</th><th>rhythm</th><th>announced</th><th>first seen</th><th>last seen</th><th>log</th></tr>${insts.map((i) => `<tr><td class="num">${esc(i.id)}</td><td>${i.kind ? esc(i.kind) : '<span class="muted">—</span>'}${i.mode ? ` <span class="muted">· ${esc(i.mode)}</span>` : ""}</td><td title="${i.cadence_s ? `seen on the bus about every ${ago(i.cadence_s)}` : Orchestra.continuous(i) ? "publishes continuously: its events come too close together to make a cadence of beats" : "no cadence observed yet: judged by the 2-minute floor"}">${i.active ? '<span style="color:#22c55e">active</span>' : '<span class="muted">quiet</span>'}</td><td class="num">${i.cadence_s ? `about every ${ago(i.cadence_s)}` : '<span class="muted">—</span>'}</td><td>${again(i)}</td><td>${ago(now - i.first_seen)} ago</td><td>${ago(now - i.last_seen)} ago</td><td>${(m.logs || []).includes(i.id) ? "announced" : '<span class="muted">—</span>'}</td></tr>`).join("")}</table>` : "";
}
// each type's count in the window its rate is over, beside the rate; none for a type seen once
function dlgPublishes(m) {
  if (!(m.publishes || []).length) return '<div class="muted">nothing</div>';
  const young = m.publishes.some((p) => p.window_s && p.window_s < 600);
  const head = young ? "rate, since first seen" : "rate, last 10 min";
  const rate = (p) => (p.count <= 1 ? '<span class="muted" title="seen once: no rate">—</span>'
    : `${p.n_10m ?? "?"} in ${p.window_s ? (p.window_s / 60).toFixed(1).replace(/\.0$/, "") : 10} min · ${p.per_min_10m}/min`);
  return `<table class="dt"><tr><th>event type</th><th>all time</th><th>last 24h</th><th>${head}</th></tr>${m.publishes.map((p) => `<tr><td class="num">${esc(p.type)}</td><td class="num">${p.count}</td><td class="num">${p.day}</td><td class="num">${rate(p)}</td></tr>`).join("")}</table>`;
}
async function machineDetail(refresh) {
  const id = OPEN; if (!id) return;
  const m = Orchestra.machineList().find((x) => x.id === id) || { logs: [] }, q = encodeURIComponent(id);
  const [ev, lg] = await Promise.all([
    fetch(`/api/machines/${q}/events`).then((r) => r.json()).catch(() => null),
    fetch(`/api/machines/${q}/log?lines=300` + (LOG_INST ? `&instance=${encodeURIComponent(LOG_INST)}` : "")).then((r) => r.json()).catch(() => null)]);
  if (OPEN !== id) return;
  // the header, the instances and the publishes as the page's latest read says them now
  const live = Orchestra.machineList().find((x) => x.id === id);
  if (live) for (const [el, html] of [["m-seen", dlgSeen(live)], ["m-insts", dlgInstances(live)], ["m-pubs", dlgPublishes(live)]]) { const x = $(el); if (x && x.dataset.html !== html) { x.dataset.html = html; x.innerHTML = html; } }
  // each row opens to its whole envelope (the data stays the machine's own); "older" shows more of
  // the last events the page keeps, which rows stay open kept across refreshes
  if (ev) { const box = $("m-events"), open = new Set([...box.querySelectorAll("details[open]")].map((d) => d.dataset.id)), list = ev.events || [];
    const row = (e) => `<details class="evrow" data-id="${esc(e.id || "")}" ${open.has(e.id || "") ? "open" : ""}><summary><span class="muted">${e.t ? new Date(e.t * 1000).toLocaleTimeString() : ""}</span> <span class="num">${esc(e.type)}</span> <span class="num muted">${esc(e.instance || "")}</span> <span class="num muted">${esc(e.subject || "")}</span></summary>
      <div class="kv evenv"><span class="muted">id</span><span class="num">${esc(e.id || "—")}</span><span class="muted">source</span><span class="num">${esc(id + (e.instance ? "/" + e.instance : ""))}</span><span class="muted">time</span><span class="num">${e.t ? esc(new Date(e.t * 1000).toISOString()) : "—"}</span><span class="muted">subject</span><span class="num">${esc(e.subject || "—")}</span><span class="muted">data</span><span class="muted">the machine's own; not read by Orchestra</span></div></details>`;
    box.innerHTML = list.length ? list.slice(0, EV_SHOWN).map(row).join("") + (list.length > EV_SHOWN ? `<button class="ctl" onclick="EV_SHOWN+=15;machineDetail(true)">older (${list.length - EV_SHOWN} more kept)</button>` : "")
      : '<span class="muted">none since the web server started reading the bus</span>'; }
  $("m-loginst").innerHTML = (m.logs || []).length > 1 ? m.logs.map((i) => `<button class="${i === LOG_INST ? "on" : ""}" onclick="LOG_INST='${esc(i)}';machineDetail(true)">${esc(i)}</button>`).join("") : "";
  const box = $("m-log"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 8;
  // no terminal box under a log that cannot be read: only the reason
  if (lg && lg.ok && lg.path) { box.style.display = ""; box.innerHTML = lg.lines.length ? highlightLog(lg.lines.join("\n")) : '<span class="muted">the log is empty</span>';
    // when the log was last written, amber when that is older than the machine's own last event and the floor: a log gone quiet
    const t = Date.now() / 1000, w = lg.written, quiet = w != null && t - w > Orchestra.FLOOR_S && m.last_seen && m.last_seen > w;
    $("m-lognote").innerHTML = `${esc(lg.path)} · last ${lg.lines.length} lines${w != null ? ` · <span class="${quiet ? "stale" : ""}" title="${quiet ? "the machine published after its log was last written" : "the log file's modification time"}">last written ${esc(ago(Math.max(0, t - w)))} ago (${esc(Orchestra.when(w))})</span>` : ""} · refreshed every 5 s`; }
  else if (lg && lg.ok && (lg.lines || []).length) { box.style.display = ""; box.innerHTML = highlightLog(lg.lines.join("\n")); $("m-lognote").textContent = lg.note || ""; }
  else { box.style.display = "none"; box.innerHTML = ""; $("m-lognote").textContent = lg ? (lg.ok ? lg.note || "not read: no log announced" : lg.error) : "the log could not be read"; }
  if (atEnd || !refresh) box.scrollTop = box.scrollHeight;
}
