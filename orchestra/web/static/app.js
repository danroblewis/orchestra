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

function openDrawer(html) { $("drawer").innerHTML = html; $("overlay").classList.add("open"); }
function closeDrawer() { $("overlay").classList.remove("open"); }

async function openTicket(id) {
  const t = await (await fetch(`/api/tickets/${id}`)).json();
  openDrawer(`<h3>${esc(t.id)} <span class="badge" style="background:${color(t.state)}">${t.state}</span> ${esc(t.title)}</h3>
    <div class="kv"><div>milestone</div><div>${esc(t.milestone_id)}</div><div>priority</div><div>${t.priority}</div><div>depends on</div><div>${t.depends_on.join(", ") || "—"}</div>
    <div>branch</div><div>${esc(t.branch || "—")}</div><div>reviewed commit</div><div>${esc((t.reviewed_commit || "").slice(0, 10) || "—")}</div><div>review rounds</div><div>${t.review_rounds}</div>
    <div>sessions</div><div>${t.worker_session ? `<a href="#" onclick="openTranscript('${t.worker_session}');return false">${t.worker_session}</a>` : ""} ${t.reviewer_session ? `<a href="#" onclick="openTranscript('${t.reviewer_session}');return false">${t.reviewer_session}</a>` : ""}</div></div>
    ${t.blocked_reason ? `<h2>Blocked</h2><pre>${esc(t.blocked_reason)}</pre>` : ""}${t.feedback ? `<h2>Feedback (${esc(t.rejected_by || "")})</h2><pre>${esc(t.feedback)}</pre>` : ""}
    <h2>Description</h2><pre>${esc(t.description)}</pre><h2>Acceptance</h2><pre>${esc(t.acceptance)}</pre>
    <h2>Notes</h2>${t.notes.map((n) => `<div class="note"><b>${esc(n.author)} · ${esc(n.kind)} · ${esc(n.created_at)}</b><br>${esc(n.text)}</div>`).join("") || '<div class="empty">none</div>'}`);
}

async function openTranscript(id) {
  const r = await fetch(`/api/sessions/${id}/transcript`);
  if (!r.ok) return openDrawer(`<h3>${esc(id)}</h3><div class="empty">no transcript yet</div>`);
  const d = await r.json();
  openDrawer(`<h3>${esc(id)} <span class="muted">${d.session.status}</span></h3>` +
    (d.messages.map((m) => `<div class="msg ${m.role}"><div class="r">${m.role} ${m.tool_calls.map((t) => `[${esc(t.name)} ${esc(JSON.stringify(t.args || {}).slice(0, 120))}]`).join(" ")}</div>${esc(m.text).slice(0, 4000)}</div>`).join("") || '<div class="empty">empty</div>'));
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
