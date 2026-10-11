// Shared helpers, nav, and drawers for the Orchestra UI.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const color = (s) => `var(--${s})`;
const ago = (sec) => (sec < 60 ? `${Math.round(sec)}s` : sec < 3600 ? `${Math.round(sec / 60)}m` : `${(sec / 3600).toFixed(1)}h`);
const kindColor = (k) => ({ supervisor: "#bc8cff", coordinator: "#58a6ff", pipeline_manager: "#f0883e", worker: "#3fb950", reviewer: "#f85149" }[k] || "#8a90a3");
const fmtBytes = (b) => (b >= 1 << 30 ? `${(b / (1 << 30)).toFixed(1)} GB` : `${Math.round(b / (1 << 20))} MB`);

function renderNav(active, project) {
  // The links are static HTML; this only fills in the project label.
  if (project) $("proj").textContent = `${project.key} · ${project.base_branch} · ${project.model || "no model"}`;
}

// Agent prose and human input are markdown. Render it sanitized, then highlight code
// blocks, guessing the language when the fence does not name one.
function md(text) {
  if (!text) return "";
  if (!(window.marked && window.DOMPurify)) return `<pre>${esc(text)}</pre>`;
  return `<div class="md">${DOMPurify.sanitize(marked.parse(text, { gfm: true, breaks: true }))}</div>`;
}
function highlightCode(root) {
  if (!window.hljs) return;
  root.querySelectorAll("pre code").forEach((el) => {
    if (el.dataset.highlighted) return;
    const named = [...el.classList].find((c) => c.startsWith("language-"));
    if (named && hljs.getLanguage(named.slice(9))) hljs.highlightElement(el);
    else {
      const r = hljs.highlightAuto(el.textContent);
      el.innerHTML = r.value; el.classList.add("hljs", `language-${r.language || "plaintext"}`);
      el.dataset.highlighted = "yes";
    }
  });
}
function openDrawer(html) { $("drawer").innerHTML = html; highlightCode($("drawer")); $("overlay").classList.add("open"); }
function closeDrawer() { $("overlay").classList.remove("open"); }

async function openTicket(id) {
  const t = await (await fetch(`/api/tickets/${id}`)).json();
  const live = (window.STATE && STATE.tickets || []).find((x) => x.id === id);
  // What needs attention comes first, before the title: a blocker, a rejection, or why it waits.
  let alerts = "";
  if (t.state === "BLOCKED") alerts += `<div class="alert blocked"><h4>Blocked · needs a decision</h4>${md(t.blocked_reason || "(no reason recorded)")}</div>`;
  if (t.state === "REJECTED" && t.feedback) alerts += `<div class="alert rejected"><h4>Rejected by the ${esc(t.rejected_by || "reviewer")} · round ${t.review_rounds}</h4>${md(t.feedback)}</div>`;
  if (live && live.state === "OPEN" && !live.ready) alerts += `<div class="alert waiting"><h4>Waiting</h4>${esc(live.why_waiting)}</div>`;
  const stateColor = color(t.state);
  openDrawer(`${alerts}<h3><span class="pill" style="--c:${stateColor};background:${stateColor}">${t.state.replace(/_/g, " ")}</span><span style="font-family:var(--mono)">${esc(t.id)}</span> ${esc(t.title)}</h3>
    <div class="kv"><div>milestone</div><div>${esc(t.milestone_id)}</div><div>priority</div><div>${priorityText(t, live)}</div><div>depends on</div><div>${t.depends_on.join(", ") || "—"}</div>
    <div>branch</div><div class="num">${esc(t.branch || "—")}</div><div>reviewed commit</div><div class="num">${esc((t.reviewed_commit || "").slice(0, 10) || "—")}</div><div>review rounds</div><div>${t.review_rounds}</div>
    <div>sessions</div><div>${t.worker_session ? `<a href="#" onclick="openTranscript('${t.worker_session}');return false">${t.worker_session}</a>` : ""} ${t.reviewer_session ? `<a href="#" onclick="openTranscript('${t.reviewer_session}');return false">${t.reviewer_session}</a>` : ""}</div>
    ${live && live.state === "OPEN" && live.ready ? `<div>waiting</div><div>${esc(live.why_waiting)}</div>` : ""}</div>
    ${t.objective ? `<h2>Objective</h2>${md(t.objective)}` : ""}
    <h2>Description</h2>${md(t.description) || '<div class="empty">none</div>'}<h2>Acceptance</h2>${md(t.acceptance) || '<div class="empty">none</div>'}
    ${t.verification ? `<h2>Verification</h2>${md(t.verification)}` : ""}
    ${t.state !== "REJECTED" && t.feedback ? `<h2>${t.rejected_by ? "Last feedback from the " + esc(t.rejected_by) : "Note for the worker"}</h2>${md(t.feedback)}` : ""}
    <h2>Notes</h2>${t.notes.slice().reverse().map((n) => `<div class="note"><b>${esc(n.author)} · ${esc(n.kind)} · ${esc(n.created_at)}</b>${md(n.text)}</div>`).join("") || '<div class="empty">none</div>'}`);
}

let transcriptPaging = null;   // {id, nextBefore, hasMore, loading}

async function openTranscript(id) {
  const r = await fetch(`/api/sessions/${id}/transcript?limit=30`);
  if (!r.ok) {
    const perTicket = /^(worker|reviewer)-/.test(id);
    return openDrawer(`<h3>${esc(id)}</h3><div class="empty">${perTicket
      ? "No record of this session: it has not run yet, or it finished before transcripts were kept (" + esc(id) + ")."
      : "This session has not been started. It comes up with <code>orchestra run</code>."}</div>`);
  }
  const d = await r.json(); const s = d.session;
  const state = s.status === "running" ? "working" : s.status === "archived" ? "finished (ticket closed)" : s.alive ? "resident, waiting for work" : "not running";
  const when = (t) => (t ? new Date(t * 1000).toLocaleString() : "—");
  const perTicket = /^(worker|reviewer)-/.test(id);
  const stopBtn = perTicket && s.status === "running" && s.alive && s.ticket_id
    ? `<button class="ctl kill" style="margin-left:auto" onclick="stopAgent('${esc(s.ticket_id)}','${esc(id)}')">■ stop this agent</button>` : "";
  let html = `<h3>${esc(id)} <span class="muted">${state}</span>${stopBtn}</h3>
    <div class="kv"><div>kind</div><div>${esc(s.kind || "")}</div><div>process</div><div>${s.alive ? "pid " + s.pid : "none"}</div>
    ${s.ticket_id ? `<div>ticket</div><div><a href="#" onclick="openTicket('${esc(s.ticket_id)}');return false">${esc(s.ticket_id)}</a></div>` : ""}
    <div>last started</div><div>${when(s.started_at)}${s.status === "running" ? ` <span class="muted">(turn running ${ago((Date.now() / 1000) - s.started_at)})</span>` : ""}</div>
    <div>doing now</div><div>${sessionChip(s, Date.now() / 1000)}</div>
    <div>last output</div><div>${s.last_output_at ? ago((Date.now() / 1000) - s.last_output_at) + " ago" : "—"}</div>
    <div>last settled</div><div>${when(s.settled_at)}</div>
    <div>turns</div><div>${d.turns} · ${d.total} messages</div><div>session file</div><div class="muted" style="word-break:break-all">${esc(s.session_file || "not created yet")}</div></div>`;
  if (id === "supervisor") html += `<form id="chat" class="chat top" onsubmit="return sendToSupervisor(event)">
      <textarea id="chat-input" rows="3" placeholder="Message the Supervisor… (Enter to send, Shift+Enter for a new line)" ${s.alive ? "" : "disabled"}></textarea>
      <button type="submit" ${s.alive ? "" : "disabled"}>Send</button>
      ${s.alive ? "" : '<div class="empty">The Supervisor is reachable while <code>orchestra run</code> is up.</div>'}
    </form><div id="live"></div>`;
  html += `<h2>Transcript · newest first</h2><div id="transcript">`;
  html += d.messages.length ? d.messages.map(renderMessage).join("") : `<div class="empty">${s.file_exists ? "No messages yet." : "No turns yet: Pi creates the session file on the first prompt. This agent is woken by events or, for the supervisor, by a message."}</div>`;
  html += `</div><div id="transcript-more" class="empty" style="margin-top:8px">${d.has_more ? "scroll for older messages…" : "beginning of session"}</div>`;
  openDrawer(html);
  transcriptPaging = { id, nextBefore: d.next_before, hasMore: d.has_more, loading: false };
  const ta = $("chat-input");
  if (ta) { ta.focus(); ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("chat").requestSubmit(); } }); }
}

async function loadOlderTranscript() {
  const p = transcriptPaging; if (!p || !p.hasMore || p.loading) return;
  p.loading = true;
  try {
    const d = await (await fetch(`/api/sessions/${p.id}/transcript?before=${p.nextBefore}&limit=30`)).json();
    const box = $("transcript"); if (!box) return;
    box.insertAdjacentHTML("beforeend", d.messages.map(renderMessage).join(""));
    highlightCode(box);
    p.nextBefore = d.next_before; p.hasMore = d.has_more;
    $("transcript-more").textContent = p.hasMore ? "scroll for older messages…" : "beginning of session";
  } finally { p.loading = false; }
}
document.addEventListener("DOMContentLoaded", () => {
  $("drawer").addEventListener("scroll", () => { const el = $("drawer"); if (transcriptPaging && el.scrollTop + el.clientHeight > el.scrollHeight - 300) loadOlderTranscript(); });
});

async function sendToSupervisor(ev) {
  ev.preventDefault();
  const ta = $("chat-input"), btn = ev.target.querySelector("button"), live = $("live");
  const message = ta.value.trim();
  if (!message) return false;
  ta.value = ""; ta.disabled = true; btn.disabled = true;
  live.insertAdjacentHTML("afterbegin", `<div class="msg assistant"><div class="r">supervisor · working…</div><div id="live-body"></div></div><div class="msg user"><div class="r">you</div>${md(message)}</div>`);
  highlightCode(live); $("drawer").scrollTop = 0;
  try {
    const resp = await fetch("/api/supervisor", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) });
    if (!resp.ok) { $("live-body").innerHTML = `<div class="bad">${esc((await resp.text()).slice(0, 300))}</div>`; return false; }
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl; while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl); buf = buf.slice(nl + 1); if (!line.trim()) continue;
        const e = JSON.parse(line); const body = $("live-body");
        if (e.type === "tool_start") body.innerHTML += `<div class="tc"><div class="r">⚙ ${esc(e.name || "tool")}</div></div>`;
        else if (e.type === "assistant_end") {
          const txt = e.text || "";
          if (txt.trim()) { body.innerHTML += md(txt); highlightCode(body); }
        } else if (e.type === "done") body.previousElementSibling.textContent = e.error ? `supervisor · ${e.error}` : e.timed_out ? "supervisor · timed out" : "supervisor";
      }
    }
  } catch (err) { $("live-body").innerHTML += `<div class="bad">${esc(String(err))}</div>`; }
  finally { ta.disabled = false; btn.disabled = false; ta.focus(); }
  return false;
}

const SHELL_TOOLS = new Set(["bash", "shell", "sh", "powershell"]);

function renderToolCall(t) {
  const args = t.args && typeof t.args === "object" ? t.args : {};
  if (SHELL_TOOLS.has(t.name) && typeof args.command === "string")
    return `<div class="tc"><div class="r">⚙ ${esc(t.name)}</div><pre><code class="language-bash">${esc(args.command)}</code></pre></div>`;
  const shown = Object.keys(args).length ? JSON.stringify(args, null, 1) : (typeof t.args === "string" ? t.args : "");
  return `<div class="tc"><div class="r">⚙ ${esc(t.name)}</div>${shown ? `<pre><code class="language-json">${esc(shown).slice(0, 3000)}</code></pre>` : ""}</div>`;
}

function msgTime(m) {
  if (!m.ts) return "";
  // Pi records entry timestamps as ISO strings; some message bodies carry epoch millis.
  const t = typeof m.ts === "number" ? (m.ts > 1e12 ? m.ts : m.ts * 1000) : Date.parse(m.ts);
  if (!isFinite(t)) return "";
  return `<span class="muted num" style="margin-left:8px">${new Date(t).toLocaleTimeString()} · ${ago((Date.now() - t) / 1000)} ago</span>`;
}
function renderMessage(m) {
  if (m.role === "toolResult") {
    const shell = SHELL_TOOLS.has(m.tool_name);
    const body = shell ? `<pre class="term">${highlightLog(m.text)}</pre>` : `<pre><code>${esc(m.text)}</code></pre>`;
    return `<div class="msg toolResult ${m.is_error ? "err" : ""}"><div class="r">result · ${esc(m.tool_name || "tool")}${m.is_error ? ' <span class="bad">error</span>' : ""}${msgTime(m)}</div>${body}</div>`;
  }
  return `<div class="msg ${m.role}"><div class="r">${m.role}${msgTime(m)}</div>${md(m.text.slice(0, 12000))}${m.tool_calls.map(renderToolCall).join("")}</div>`;
}

async function openGateRun(id) {
  const r = await (await fetch(`/api/gate/runs/${id}`)).json();
  openDrawer(`<h3>Gate run ${r.id} <span class="${r.status === "landed" ? "ok" : "bad"}">${r.status}</span></h3>
    <div class="kv"><div>batch</div><div>${r.batch.join(", ")}</div><div>merged</div><div>${(r.merged || []).join(", ") || "—"}</div><div>rejected</div><div>${(r.rejected || []).join(", ") || "—"}</div><div>summary</div><div>${esc(r.summary)}</div></div>
    ${(r.stages || []).map((s) => `<h2>${s.stage}:${s.name} <span class="${s.status === "passed" ? "ok" : "bad"}">${s.status}</span></h2><pre>${highlightLog(s.tail || "")}</pre>`).join("")}`);
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

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
  [/\b[A-Z]{2,}-\d+\b/y, "ticket"],
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

function openFromHash() {
  const m = location.hash.match(/^#(session|ticket|gate)=([^&]+)/);
  if (!m) return;
  ({ session: openTranscript, ticket: openTicket, gate: openGateRun })[m[1]](decodeURIComponent(m[2]));
}
window.addEventListener("hashchange", openFromHash);

async function stopAgent(ticket, sessionId) {
  if (!confirm(`Stop ${sessionId}? Its ticket ${ticket} goes back to OPEN (or back to review); the branch and session are kept.`)) return;
  const r = await fetch("/api/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "kill", ticket }) });
  if (!r.ok) alert(await r.text()); else closeDrawer();
}

function priorityText(t, live) {
  const pi = live && live.priority_info; if (!pi) return String(t.priority);
  const bits = [];
  if (pi.inherited_from) bits.push(`inherited from ${pi.inherited_from}`);
  if (pi.age_levels) bits.push(`+${pi.age_levels} for age`);
  return pi.effective === pi.own ? `${pi.own}` : `${pi.effective} <span class="muted">(own ${pi.own}; ${bits.join(", ")})</span>`;
}

// One description of what a session is doing right now, from its recorded phase.
// Returns {cls, text, title}. cls: working | waiting | resident | down | archived.
function sessionPhase(s, now) {
  if (!s) return { cls: "down", text: "down", title: "" };
  if (s.status === "archived") return { cls: "archived", text: "finished", title: "" };
  const alive = !!s.alive;
  if (s.status !== "running") return alive ? { cls: "resident", text: "resident", title: "waiting for work" } : { cls: "down", text: "down", title: "" };
  const age = (t) => ago(now - (t || now));
  const turn = `turn started ${age(s.started_at)} ago`;
  if (s.phase === "tool") return { cls: "working", text: `running ${s.tool_name || "tool"} · ${age(s.phase_since)}`, title: turn };
  if (s.phase === "generating") {
    const sinceTok = s.last_token_at ? now - s.last_token_at : 0;
    return { cls: sinceTok > 60 ? "waiting" : "working", text: `receiving tokens · last token ${ago(sinceTok)} ago`, title: turn };
  }
  // The session is mid-turn and its stream has been silent since phase_since. We report
  // how long; we do not know why.
  const wait = now - (s.phase_since || s.started_at || now);
  return { cls: wait > 60 ? "waiting" : "working", text: `no new message for ${ago(wait)}`, title: turn + " · session has not exited and nothing has streamed" };
}
function sessionChip(s, now) {
  const p = sessionPhase(s, now);
  return `<span class="chip ${p.cls}" title="${esc(p.title)}"><span class="dot"></span>${esc(p.text)}</span>`;
}
