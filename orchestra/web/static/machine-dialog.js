// A machine's dialog, on any page that lists machines (the Machines page, the Dashboard): what it
// is, its instances, what it publishes and listens for, its metrics now, its last events and the
// tail of its log, refreshed while open. A machine its package claims opens the package's own
// dialog instead (Orchestra.machineCards). The page says where its machines are:
// Orchestra.machineList = () => [...].
window.Orchestra = window.Orchestra || {};
Orchestra.machineList = Orchestra.machineList || (() => []);
// one colour per machine, the same every time for the same id
const MPAL = ["#60a5fa", "#f59e0b", "#e879f9", "#22c55e", "#f87171", "#38bdf8", "#facc15", "#a78bfa", "#fb923c", "#2dd4bf"];
const mcolor = (id) => { let h = 0; for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return MPAL[h % MPAL.length]; };
// what a machine announced it is (orchestra.machine.started data.kind, or its package's declaration), in words
const kindWord = (kind) => kind || "machine";

// a machine's dialog: what it is, its instances, what it publishes and listens for, its counted
// traffic on another system's bus, its metrics now, its last events and the tail of its log
// (refreshed while open)
let OPEN = null, OPEN_TIMER = null, LOG_INST = null;
function closeMachine() { OPEN = null; clearInterval(OPEN_TIMER); $("drawer").classList.remove("mdlg"); closeDrawer(); }
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && OPEN) closeMachine(); });
function openMachine(id) {
  const m = Orchestra.machineList().find((x) => x.id === id); if (!m) return;
  if (Orchestra.machineCards.open(m)) return;                     // its package draws its own dialog
  OPEN = id; LOG_INST = (m.logs || [])[0] || null;
  $("drawer").classList.add("mdlg");
  const insts = m.instances && m.instances.length ? m.instances : [];
  openDrawer(`<h3><span class="dot ${m.active ? "" : "off"}" style="--rc:${m.bootstrap ? "#fbbf24" : mcolor(m.id)}"></span>${esc(m.id)} <span class="tag">${esc(kindWord(m.kind))}</span>${m.bootstrap ? ' <span class="tag">bootstrap host</span>' : ""}${m.mode ? ` <span class="tag k-${esc(m.mode.replace(/ /g, "_"))}">${esc(m.mode.replace("_", " "))}</span>` : ""}${m.package ? ` <span class="tag">package: ${esc(m.package)}</span>` : ""}
      <button class="ctl" style="margin-left:auto" onclick="closeMachine()">close</button></h3>
    <div class="row"><span class="muted">seen</span><span>${seenText(m)} · ${m.active ? "active" : "quiet"}</span></div>
    ${insts.length ? `<h4>Instances</h4><table class="dt"><tr><th>instance</th><th>kind</th><th>state</th><th>first seen</th><th>last seen</th><th>log</th></tr>${insts.map((i) => `<tr><td class="num">${esc(i.id)}</td><td>${i.kind ? esc(i.kind) : '<span class="muted">—</span>'}${i.mode ? ` <span class="muted">· ${esc(i.mode)}</span>` : ""}</td><td title="${[["events", "publishes"], ["writes", "writes"]].filter(([k]) => (i.cadence_s || {})[k]).map(([k, w]) => `${w} about every ${ago(i.cadence_s[k])}`).join("; ") || "no cadence observed yet"}">${i.active ? '<span style="color:#22c55e">active</span>' : '<span class="muted">quiet</span>'}</td><td>${ago(Date.now() / 1000 - i.first_seen)} ago</td><td>${ago(Date.now() / 1000 - i.last_seen)} ago</td><td>${(m.logs || []).includes(i.id) ? "announced" : '<span class="muted">—</span>'}</td></tr>`).join("")}</table>` : ""}
    <h4>Log</h4><div class="seg" id="m-loginst"></div><div class="muted" id="m-lognote" style="font-size:11.5px"></div><div class="term" id="m-log"></div>
    <h4>Publishes</h4>${m.publishes.length ? `<table class="dt"><tr><th>event type</th><th>all time</th><th>last 24h</th><th>last 10 min</th></tr>${m.publishes.map((p) => `<tr><td class="num">${esc(p.type)}</td><td class="num">${p.count}</td><td class="num">${p.day}</td><td class="num">${p.per_min_10m}/min</td></tr>`).join("")}</table>` : '<div class="muted">nothing</div>'}
    <h4>Listens for</h4><div class="row">${m.subscribes.map((t) => `<span class="ty">${esc(t)}</span>`).join("") || '<span class="muted">nothing announced</span>'}</div>
    ${(m.counted || []).length ? `<h4>Counted traffic <span style="text-transform:none;letter-spacing:0;font-weight:400">(counts a source read from another system's bus; never events)</span></h4><table class="dt"><tr><th>channel</th><th></th><th>last 10 min</th><th>last hour</th><th>waiting</th></tr>${m.counted.map((t) => `<tr><td class="num">${esc(t.channel)}</td><td>${t.direction === "out" ? "produces into" : t.direction === "in" ? "consumes from" : "its backlog"}</td><td class="num">${t.direction === "backlog" ? "" : `${t.per_min}/min`}</td><td class="num">${t.direction === "backlog" ? "" : Math.round(t.window).toLocaleString()}</td><td class="num">${t.backlog == null ? "" : Math.round(t.backlog).toLocaleString()}</td></tr>`).join("")}</table>` : ""}
    <h4>Metrics now</h4><div id="m-metrics" class="muted">reading…</div>
    <h4>Last events <span style="text-transform:none;letter-spacing:0;font-weight:400">(envelopes; the data is the machine's own)</span></h4><div id="m-events" class="muted">reading…</div>`);
  machineDetail();
  clearInterval(OPEN_TIMER); OPEN_TIMER = setInterval(() => { if (!$("overlay").classList.contains("open")) return closeMachine(); machineDetail(true); }, 5000);
}
async function machineDetail(refresh) {
  const id = OPEN; if (!id) return;
  const m = Orchestra.machineList().find((x) => x.id === id) || { logs: [] }, q = encodeURIComponent(id);
  const [mx, ev, lg] = await Promise.all([
    refresh ? null : fetch(`/api/machines/${q}/metrics`).then((r) => r.json()).catch(() => null),
    fetch(`/api/machines/${q}/events`).then((r) => r.json()).catch(() => null),
    fetch(`/api/machines/${q}/log?lines=300` + (LOG_INST ? `&instance=${encodeURIComponent(LOG_INST)}` : "")).then((r) => r.json()).catch(() => null)]);
  if (OPEN !== id) return;
  if (mx) $("m-metrics").innerHTML = mx.series && mx.series.length ? `<table class="dt"><tr><th>series</th><th>labels</th><th>now</th><th>written</th></tr>${mx.series.map((x) => `<tr><td class="num">${esc(x.name)}</td><td class="num muted">${esc(Object.entries(x.labels).map(([k, v]) => `${k}="${v}"`).join(", "))}</td><td class="num">${x.v == null ? "—" : Charts_num(x.v)}</td><td class="muted">${x.t ? ago(Date.now() / 1000 - x.t) + " ago" : ""}</td></tr>`).join("")}</table>` : `<span class="muted">no series labelled machine="${esc(id)}"</span>`;
  if (ev) $("m-events").innerHTML = ev.events && ev.events.length ? `<table class="dt"><tr><th>when</th><th>type</th><th>instance</th><th>subject</th></tr>${ev.events.slice(0, 15).map((e) => `<tr><td class="muted">${e.t ? new Date(e.t * 1000).toLocaleTimeString() : ""}</td><td class="num">${esc(e.type)}</td><td class="num">${esc(e.instance || "")}</td><td class="num muted">${esc(e.subject || "")}</td></tr>`).join("")}</table>` : '<span class="muted">none since the web server started reading the bus</span>';
  $("m-loginst").innerHTML = (m.logs || []).length > 1 ? m.logs.map((i) => `<button class="${i === LOG_INST ? "on" : ""}" onclick="LOG_INST='${esc(i)}';machineDetail(true)">${esc(i)}</button>`).join("") : "";
  const box = $("m-log"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 8;
  if (lg && lg.ok) { box.innerHTML = lg.lines.length ? highlightLog(lg.lines.join("\n")) : '<span class="muted">the log is empty</span>'; $("m-lognote").textContent = lg.path ? `${lg.path} · last ${lg.lines.length} lines · refreshed every 5 s` : (lg.note || ""); }
  else { box.innerHTML = ""; $("m-lognote").textContent = lg ? lg.error : "the log could not be read"; }
  if (atEnd || !refresh) box.scrollTop = box.scrollHeight;
}
const Charts_num = (v) => (Math.abs(v) >= 1000 ? Math.round(v).toLocaleString() : Math.abs(v) >= 10 ? (+v).toFixed(1) : (+v).toPrecision(3).replace(/\.?0+$/, ""));
