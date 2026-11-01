// The declared layer on the Machines page (docs/proposals/intended-model.md §6.1, §7; frames E1–E4):
// what /api/machines says a person or the Supervisor declared, beside what the bus shows.
//
//   the map    a declared machine's links and event types are drawn even when nobody listens yet
//              (``intended_edges``); a proposed machine is dashed violet, "unconfirmed"; a declared
//              one never heard is an outline with no halo; the latest change's links are marked
//              "+ new link" or "− link removed" for ten minutes; while the panel is open the
//              highlight rule shades everything by its distance from the machine.
//   the panel  a column beside the map, every field read-only: the envelope's rows (kind, managed,
//              engagement, receives, emits, reads), the opaque ``spec`` in the order it was
//              declared, "a guess" on guessed items, the expected effect, P5's "Measured by". The
//              only controls are requests to the Supervisor (confirm, discard, the kind switch),
//              POST /api/intended/request; nothing here changes a machine (AGENTS.md rule 9).
//   the cards  the unconfirmed badge, the latest change's chips, the measured row.
//
// It never makes a machine: an undeclared machine's panel shows what the bus observed of it.
const IntendedMachines = (() => {
  const JUST_S = 600;                         // "just now": the latest change, for ten minutes
  const HOURS = { 3600: "1 hour", 86400: "1 day", 604800: "7 days" };
  let OPEN = null, ASKED = {};                // the panel's machine; requests sent and not yet seen in the answer
  const list = () => Orchestra.machineList() || [];
  const byId = (id) => list().find((m) => m.id === id);
  const now = () => Date.now() / 1000;
  const fresh = (it) => !!(it && it.latest && it.latest.at && now() - it.latest.at < JUST_S);
  const added = (it, f) => (fresh(it) && ((it.latest.added || {})[f])) || [];
  const removed = (it, f) => (fresh(it) && ((it.latest.removed || {})[f])) || [];
  const before = (it) => (fresh(it) && it.latest.before) || {};
  const guessed = (it, f, i) => (it.guessed || []).some((g) => g === f || (i != null && g === `${f}[${i}]`));
  const words = (k) => String(k).replace(/_/g, " ");
  const cap = (k) => words(k).charAt(0).toUpperCase() + words(k).slice(1);
  const span = (s) => (HOURS[s] || (s >= 86400 ? `${Math.round(s / 86400)} days` : s >= 3600 ? `${Math.round(s / 3600)} hours` : `${Math.round(s / 60)} min`));

  // who put it there, in the owner's words: "proposed by the Supervisor", "added by you"
  function byWhom(it) {
    const p = it.provenance || {}, a = it.author || p.author;
    if (a === "owner") return it.state === "proposed" ? "added by you" : "declared by you";
    const who = p.source || a || "a plugin";
    return `${it.state === "proposed" ? "proposed" : "declared"} by the ${esc(who.charAt(0).toUpperCase() + who.slice(1))}`;
  }
  function stateTag(m) {
    const it = m.intent;
    if (it.state === "proposed") return { text: "unconfirmed", cls: "im-t-unconf" };
    if (!it.heard) return { text: "declared · never heard", cls: "im-t-ghost" };
    return { text: "declared", cls: "im-t-decl" };
  }
  // P5's per-machine block (web/measured.py): {attachments, measured, last_measured, instances, instruments, unknown}
  const measuredOf = (m) => (m.measured && !m.measured.unknown ? m.measured : null);
  const measuredCount = (m) => { const ms = measuredOf(m); return ms ? ms.instances || 0 : 0; };
  const instList = (a) => ((a.instances || {}).list || []);

  // ---- the map ----
  // the declared links to add to the graph: [{from, to, kind, observed, gone, state, machine, type}]
  function links(d, hidden) {
    const fam = (t) => t.split(".")[0];
    return (d.intended_edges || []).filter((e) => !hidden.has(fam(e.kind === "publishes" ? e.to : e.from)))
      .map((e) => ({ ...e, machine: e.kind === "publishes" ? e.from : e.to, type: e.kind === "publishes" ? e.to : e.from }));
  }
  // a link's look, over the page's own: added just now (green), removed (a faint ghost), declared
  // and not observed (dashed); null when the declaration says nothing of it
  function edgeStyle(l) {
    if (!l.declared && !l.gone && !l.added) return null;
    if (l.gone) return { cls: "im-gone-edge", dash: "2 6", color: "#5b6272", hoverColor: "#8b95a7", width: 1.4 };
    if (l.added) return { cls: "im-add-edge", color: "#86efac", hoverColor: "#86efac", width: 2, dash: l.declared ? "5 4" : undefined };
    return { cls: "im-decl-edge", dash: "5 4" };
  }
  // the machine nodes and event types a declaration touches: their classes, sub-lines and tags
  function decorate(d, nodes, links) {
    const machines = new Map(d.machines.map((m) => [m.id, m]));
    const listened = new Set(d.machines.flatMap((m) => m.subscribes || []));
    const published = new Set(d.machines.flatMap((m) => (m.publishes || []).map((p) => p.type)));
    for (const n of nodes) {
      if (n.machine) {
        const m = machines.get(n.mid), it = m && m.intent;
        if (!it) continue;
        const mode = (it.engagement || {}).mode, eng = mode === "scheduled" && it.engagement.at ? `scheduled · ${it.engagement.at}` : mode;
        if (it.state === "proposed") {
          n.cls = `${n.cls || ""} im-proposed`; n.sub = ["unconfirmed", eng, it.managed === "external" ? "external" : ""].filter(Boolean).join(" · ");
          n.tags = [{ text: it.author === "owner" ? "unconfirmed · added by you" : "unconfirmed", cls: "im-t-unconf" }];
        } else if (!it.heard) {
          n.cls = `${n.cls || ""} im-unheard`; n.halo = false; n.color = "transparent"; n.sub = "declared · never heard";
          n.tags = [{ text: measuredOf(m) && measuredOf(m).measured ? "declared · measured" : "declared · unheard", cls: "im-t-ghost" }];
        }
        if (fresh(it)) (n.tags = n.tags || []).push({ text: "changed just now", cls: "im-t-chg", below: true });
        continue;
      }
      if (n.kind !== "box" || !n.id.startsWith("ev:")) continue;
      const types = n.labels || [n.label];
      const mine = links.filter((l) => l.ev === n.id);
      if (!mine.length) continue;
      const tags = [];
      if (mine.some((l) => l.gone)) tags.push({ text: "− link removed", cls: "im-t-gone" });
      if (mine.some((l) => l.added && !l.gone)) { tags.push({ text: "+ new link", cls: "im-t-add" }); n.cls = `${n.cls || ""} im-ring-add`; }
      const loose = types.every((t) => !published.has(t) || !listened.has(t)) && mine.every((l) => l.declared || l.gone) && mine.some((l) => !l.gone);
      if (loose && !n.cnt) { n.sub = types.some((t) => !published.has(t) && !listened.has(t)) ? "declared · new type" : "declared"; n.cls = `${n.cls || ""} im-decl-event`; }
      if (tags.length) n.tags = tags;
    }
  }
  // the highlight rule (§7): the machine and its event types at full colour, the machines on those
  // at .7, their other event types and the machines on those at .45, the rest dimmed. In the
  // machines-only view, one hop is a machine away. Links the latest change removed stay full.
  function focusSpec(id, nodes, edges, mode) {
    const nid = "m:" + id, adj = new Map(), gone = new Set();
    const add = (a, b) => { (adj.get(a) || adj.set(a, new Set()).get(a)).add(b); };
    for (const e of edges) {
      if (e.toEdge) continue;
      if ((e.cls || "").includes("im-gone-edge")) { if (e.source === nid) gone.add(e.target); if (e.target === nid) gone.add(e.source); continue; }
      add(e.source, e.target); add(e.target, e.source);
    }
    const dist = new Map([[nid, 0]]);
    for (let q = [nid]; q.length;) { const next = []; for (const a of q) for (const b of adj.get(a) || []) if (!dist.has(b)) { dist.set(b, dist.get(a) + 1); next.push(b); } q = next; }
    const step = mode === "machines" ? 2 : 1;
    const level = (n) => {
      if (gone.has(n.id)) return 1;
      const k = dist.has(n.id) ? dist.get(n.id) * step : Infinity;
      return k <= 1 ? 1 : k === 2 ? 0.7 : k <= 4 ? 0.45 : 0.1;
    };
    return { id: nid, levelOf: level, edgeLevel: (e) => ((e.cls || "").includes("im-gone-edge") && (e.source.id === nid || e.target.id === nid) ? 1 : null) };
  }

  // ---- the cards ----
  // declared machines first: the unconfirmed ones, then the rest of the declared, then the page's order
  function sort(ms) {
    const rank = (m) => (!m.intent ? 2 : m.intent.state === "proposed" ? 0 : 1);
    return [...ms].sort((a, b) => rank(a) - rank(b));
  }
  function decorateCards(host) {
    for (const m of list()) {
      const it = m.intent, card = host.querySelector(`.panel[data-id="${CSS.escape(m.id)}"]`);
      if (!card) continue;
      card.classList.toggle("im-open", m.id === OPEN);
      if (!it) continue;
      const tag = stateTag(m);
      card.classList.add(it.state === "proposed" ? "im-card" : "im-card-declared");
      const h3 = card.querySelector("h3");
      if (h3 && !h3.querySelector(".im-tag")) h3.insertAdjacentHTML("beforeend", `<span class="im-tag ${tag.cls}">${tag.text}</span>${it.state === "proposed" ? `<span class="muted im-by">${byWhom(it)}</span>` : ""}`);
      const rows = [...card.querySelectorAll(".row")], row = (name) => rows.find((r) => r.firstElementChild && r.firstElementChild.textContent === name);
      const seen = row("seen"), ms = measuredOf(m);
      if (seen && !it.heard) {
        const n = ms ? (ms.instruments || []).length : 0, inst = measuredCount(m);
        seen.lastElementChild.innerHTML = `never heard${n ? ` · measured by ${n} instrument${n === 1 ? "" : "s"} · ${inst} instance${inst === 1 ? "" : "s"} (last hour)` : m.comparison ? ` · ${esc(m.comparison)}` : ""}${ms && ms.last_measured ? ` <span class="muted">· last measured ${ago(now() - ms.last_measured)} ago</span>` : ""}`;
        const chips = ms ? ms.attachments.flatMap((a) => instList(a).filter((i) => i.measured).map((i) => i.value)) : [];
        if (inst && !card.querySelector(".im-meas-row")) seen.insertAdjacentHTML("afterend", `<div class="row im-meas-row"><span class="muted">measured ×${inst}</span>${[...new Set(chips)].map((v) => `<span class="ty im-meas-chip">${esc(v)}</span>`).join("")}<span class="muted">by ${ms.instruments.map(esc).join(", ")}</span></div>`);
      }
      const plus = new Set([...added(it, "receives"), ...added(it, "emits")]), minus = new Set([...removed(it, "receives"), ...removed(it, "emits")]);
      if (plus.size || minus.size) card.querySelectorAll(".ty").forEach((c) => { const t = c.textContent.trim().split(" · ")[0];
        if (plus.has(t)) c.classList.add("im-chip-add"); });
      const listens = row("listens for");
      if (listens && minus.size) for (const t of minus) if (![...listens.querySelectorAll(".ty")].some((c) => c.textContent.trim() === t)) listens.insertAdjacentHTML("beforeend", `<span class="ty im-chip-gone" title="removed just now">${esc(t)}</span>`);
    }
  }

  // ---- the panel: read-only renderings, and the requests ----
  const chip = (t, st, extra = "") => `<span class="ty ${st === "add" ? "im-chip-add" : st === "gone" ? "im-chip-gone" : ""}">${esc(t)}</span>${st === "add" ? '<span class="im-tag im-t-add">+ added just now</span>' : st === "gone" ? '<span class="im-tag im-t-gone">− removed</span>' : ""}${extra}`;
  const guess = '<span class="im-tag im-t-ghost" title="the Supervisor\'s guess: ask it to set or confirm">a guess</span>';
  const field = (label, html, cls = "") => `<div class="im-f ${cls}"><div class="im-fl">${esc(label)}</div><div class="im-fv">${html}</div></div>`;
  const ind = (opts, on, cls = "") => `<span class="im-ind ${cls}" title="read-only: ask the Supervisor to change it">${opts.map((o) => `<span class="${o === on ? "on" : ""}">${esc(o)}</span>`).join("")}</span>`;
  const box = (v, mono) => `<div class="im-ro ${mono ? "mono" : ""}">${esc(v)}</div>`;
  const inl = (v) => `<span class="im-ro mono inline">${esc(v)}</span>`;
  const ask = (what = "ask the Supervisor") => `<span class="im-ask">${esc(what)}</span>`;
  const h4 = (t, note = "", tag = "") => `<h4>${esc(t)}${note ? ` <span class="muted im-h4note">${note}</span>` : ""}${tag}</h4>`;

  // the opaque spec, as declared and in its order: every list numbered, text as a value, a table for
  // a flat object (arguments, environment), anything deeper as nested rows; a key the latest
  // change rewrote is marked
  function specValue(k, v, mono) {
    if (v == null || v === "") return '<span class="muted">none</span>';
    if (Array.isArray(v)) return `<ol class="im-list">${v.map((x) => `<li>${typeof x === "object" ? esc(JSON.stringify(x)) : esc(x)}</li>`).join("")}</ol>`;
    if (typeof v === "object") {
      const flat = Object.values(v).every((x) => x == null || typeof x !== "object");
      if (flat) return `<table class="dt im-args">${Object.entries(v).map(([a, b]) => `<tr><td class="num">${esc(a)}</td><td>${esc(b ?? "")}</td></tr>`).join("")}</table>`;
      return Object.entries(v).map(([a, b]) => field(words(a), specValue(a, b, mono))).join("");
    }
    if (typeof v === "string" && v.includes("\n")) return `<pre class="im-eg">${esc(v)}</pre>`;
    return box(String(v), mono);
  }
  function spec(it, mono) {
    const s = it.spec || {}, was = before(it), out = [];
    for (const [k, v] of Object.entries(s)) {
      const chg = k in was ? `<span class="im-tag im-t-chg">${Array.isArray(v) ? "rewritten" : "changed"} just now</span>` : "";
      const g = guessed(it, `spec.${k}`) || guessed(it, k) ? guess : "";
      const more = v && typeof v === "object" && !Array.isArray(v) ? ask("ask the Supervisor to add one") : "";
      out.push(Array.isArray(v) ? `${h4(cap(k), "", chg + g)}${specValue(k, v, mono)}` : field(words(k), specValue(k, v, mono) + more + chg + g));
    }
    return out.join("");
  }
  // what a Programmatic machine's declared engagement says, in words, and nothing of who runs it
  const MODE_NOTE = { "ad hoc": "declared as engaged ad hoc", continuous: "declared as engaged continuously", scheduled: "declared as engaged on a schedule" };
  function engagementRow(it) {
    const e = it.engagement || {}, was = before(it).engagement;
    let html = ind(["ad hoc", "continuous", "scheduled"], e.mode, it.kind === "programmatic" ? "tabs" : "");
    if (e.mode === "scheduled") html += ` ${e.at ? inl(`daily at ${e.at}`) : ""}${e.tz ? inl(e.tz) : ""}${e.missed ? `<span class="muted"> · missed: ${esc(e.missed)}</span>` : ""}`;
    if (guessed(it, "engagement") || guessed(it, "engagement.at")) html += guess;
    if (was) html += `<span class="im-tag im-t-chg">changed just now</span><div class="muted im-was">was ${esc(was.mode || "not set")}${was.at ? ` at ${esc(was.at)}` : ""}${was.tz ? ` (${esc(was.tz)})` : ""}</div>`;
    return field("engagement", html);
  }
  function types(it, f, observedListeners) {
    const items = it[f] || [], gone = removed(it, f), plus = new Set(added(it, f));
    if (!items.length && !gone.length) return '<span class="muted">none declared</span>';
    const one = (t, i) => {
      const extra = (guessed(it, f, i) ? guess : "") + (f === "emits" && !observedListeners.has(t) ? `${observedListeners.published.has(t) ? "" : '<span class="im-tag im-t-ghost">new type</span>'}<span class="muted">nobody listens for it yet</span>` : "");
      return chip(t, plus.has(t) ? "add" : null, extra);
    };
    return `<div class="im-chips">${items.map(one).join("")}${gone.map((t) => chip(t, "gone")).join("")}</div>`;
  }
  function reads(it) {
    const r = it.reads || [];
    if (!r.length) return '<span class="muted">nothing declared</span>';
    return `<div class="im-chips">${r.map((k, i) => `<a class="ty im-metric" href="/dynamics#s:${encodeURIComponent(k)}">${esc(k)}</a>${guessed(it, "reads", i) ? guess : ""}`).join("")}</div>`;
  }
  function effect(it) {
    const ee = it.expected_effect;
    if (!ee) return `${h4("Expected effect")}<div class="muted">none declared yet: a machine with no expected effect cannot be judged</div>`;
    const verdict = ee.verdict ? `<span class="im-tag im-t-decl">${esc(ee.verdict)}</span>` : ee.status ? `<span class="im-tag im-t-ghost">${esc(ee.status)}</span>` : "";
    const rows = ee.edits.map((e) => { const up = /↑|appears|×(1\.|[2-9])/.test(e.label), down = /↓|disappears|×0/.test(e.label);
      return `<a class="im-pred ${e.publishable ? "" : "im-wait"} ${up ? "up" : down ? "down" : ""}" href="${esc(e.link || "/dynamics")}"><b>${esc(e.label)}</b><span class="muted">${e.publishable ? "" : esc(e.why || "not publishable yet")}</span></a>`; }).join("");
    return `${h4("Expected effect", `a prediction, judged later · horizon ${span(ee.horizon_s)}`, verdict)}<div class="im-preds">${rows}</div>`;
  }
  // "Measured by" (P5 §3): per attachment its instrument and kind, match, instance label, state, the
  // series it matches, and its measured and quiet instances with their last values
  function measuredBy(m) {
    const ms = m.measured && m.measured.attachments ? m.measured : null, atts = ms ? ms.attachments : (m.intent.attachments || []);
    if (!atts.length) return "";
    const one = (a) => {
      const inst = a.instances || {}, list = inst.list || [], names = (a.names || []).map((x) => x.name);
      const valueOf = (v, name) => { const x = (a.series || []).find((s) => s.name === name && (s.labels || {})[a.instance_label] === v); return x ? x.value : ""; };
      const state = a.state === "proposed" ? '<span class="im-tag im-t-unconf">unconfirmed</span>' : `<span class="im-tag im-t-decl">${esc(a.state || "declared")}</span>`;
      const match = a.shown || (a.match ? [a.match.prefix ? `${a.match.prefix}*` : "", ...Object.entries(a.match.labels || {}).map(([k, v]) => `${k}="${v}"`)].filter(Boolean).join(" ") : "");
      const status = a.status && a.status !== "measured" ? `<span class="im-tag im-t-ghost">${esc(a.comparison || a.status)}</span>` : "";
      return `<div class="im-attach"><div class="im-attach-head"><b>${esc(a.instrument)}</b>${a.kind ? ` <span class="ty">${esc(a.kind)}</span>` : ""} ${state}${status}${a.shared ? '<span class="im-tag im-t-ghost" title="another declared machine\'s match selects the same series">shared</span>' : ""}</div>
        ${field("match", match ? `<span class="ty">${esc(match)}</span>` : '<span class="muted">everything the instrument records</span>')}
        ${field("instances", a.instance_label ? `<span class="ty">${esc(a.instance_label)}</span>${ms ? ` <span class="muted">· ${inst.measured || 0} measured, ${inst.quiet || 0} quiet${inst.too_many ? ", too many to list" : ""}</span>` : ""}${inst.note ? `<div class="muted im-note">${esc(inst.note)}</div>` : ""}` : '<span class="muted">one: no instance label</span>')}
        ${ms ? field("series", (a.names || []).map((x) => `<span class="ty">${esc(x.name)} ×${x.count}</span>`).join("") || '<span class="muted">none matches yet</span>') : ""}
        ${list.length ? `<div class="im-scroll"><table class="dt im-meas"><tr><th>${esc(a.instance_label)}</th><th>state</th>${names.map((c) => `<th class="num" title="${esc(c)}">${esc(a.match && a.match.prefix && c.startsWith(a.match.prefix) ? c.slice(a.match.prefix.length) : c)}</th>`).join("")}<th class="num">last</th></tr>${list.map((i) => `<tr><td class="num">${esc(i.value)}</td><td><span class="im-live ${i.measured ? "" : "off"}"></span> ${i.measured ? "measured" : "quiet"}</td>${names.map((c) => `<td class="num">${esc(valueOf(i.value, c))}</td>`).join("")}<td class="num">${i.last ? `${ago(now() - i.last)} ago` : ""}</td></tr>`).join("")}</table></div>
          <div class="muted im-note">measured means points are arriving, not that it is up</div>` : ms ? "" : '<div class="muted im-note">what it measures is being read</div>'}</div>`;
    };
    return `${h4("Measured by", `${atts.length} instrument${atts.length === 1 ? "" : "s"} · declared provenance: what measures it, never a sign it runs`)}${atts.map(one).join("")}`;
  }
  function status(m) {
    const it = m.intent, asked = it.requested || ASKED[m.id], p = it.provenance || {};
    const when = p.at ? ` · ${ago(now() - p.at)} ago` : "";
    const acts = (change) => asked && (!change || asked.change === change)
      ? `<span class="im-waiting" title="the request is on the bus; the Supervisor answers it">asked the Supervisor${asked.control ? ` to ${esc(words(asked.control))}` : ""} · waiting</span>`
      : `<span class="im-acts"><button class="ctl im-primary" title="asks the Supervisor to confirm it" onclick="IntendedMachines.request('confirm','${esc(m.id)}'${change ? `,'${esc(change)}'` : ""})">confirm</button><button class="ctl" title="asks the Supervisor to discard it" onclick="IntendedMachines.request('discard','${esc(m.id)}'${change ? `,'${esc(change)}'` : ""})">discard</button></span>`;
    let html = it.state === "proposed" ? `<div class="im-status"><span>${byWhom(it)} · unconfirmed</span>${acts(null)}</div>`
      : `<div class="im-status im-status-declared"><span>${byWhom(it)}${when} · confirmed</span>${asked && asked.control === "switch_kind" ? acts(null) : ""}</div>`;
    for (const pc of it.pending || []) {
      const what = [...Object.keys(pc.set || {}).map((k) => `set ${words(k)}`), ...Object.entries(pc.add || {}).map(([k, v]) => `add ${v.join(", ")} to ${words(k)}`), ...Object.entries(pc.remove || {}).map(([k, v]) => `remove ${v.join(", ")} from ${words(k)}`)].join("; ");
      html += `<div class="im-status im-pending"><span>a change ${esc(((pc.provenance || {}).source) ? `by the ${pc.provenance.source}` : "")} waits for you: ${esc(what)}</span>${acts(pc.change)}</div>`;
    }
    return html;
  }
  function why(it) {
    const q = fresh(it) && (it.latest.quotes || []).length ? it.latest.quotes : (it.provenance || {}).quote ? [it.provenance.quote] : [];
    const g = (it.guessed || []).length ? ` · ${[...new Set(it.guessed.map((x) => words(x.split("[")[0].replace(/^spec\./, ""))))].join(", ")} ${it.guessed.length === 1 ? "is" : "are"} the Supervisor's guess${it.guessed.length === 1 ? "" : "es"}` : "";
    if (!q.length) return g ? `<div class="im-why muted">${g.slice(3)}</div>` : "";
    return `<div class="im-why muted">${fresh(it) ? "changed just now, " : ""}from your message${q.length > 1 ? "s" : ""}: ${q.map((x) => `<i>"${esc(x)}"</i>`).join(" and ")}${g}</div>`;
  }
  function declaredPanel(m, d) {
    const it = m.intent, prog = it.kind === "programmatic", ext = it.managed === "external";
    const listeners = new Set(d.machines.flatMap((x) => [...(x.subscribes || []), ...((x.intent && x.intent.receives) || [])]));
    listeners.published = new Set(d.machines.filter((x) => x.id !== m.id).flatMap((x) => (x.publishes || []).map((p) => p.type)));
    const tag = stateTag(m), canSwitch = it.state === "proposed";
    const kind = field("kind", (canSwitch ? `<span class="im-seg big">${["universal", "programmatic"].map((k) => `<button class="${it.kind === k ? "on" : ""}" ${it.kind === k ? "disabled" : `onclick="IntendedMachines.request('switch_kind','${esc(m.id)}')"`} title="${it.kind === k ? "its kind" : "asks the Supervisor to switch it"}">${k === "universal" ? "Universal" : "Programmatic"}</button>`).join("")}</span>` : ind(["Universal", "Programmatic"], prog ? "Programmatic" : "Universal"))
      + `<div class="muted im-note">${prog ? "a program: a command and its interface" : "described by what it achieves"}${canSwitch ? " · switching asks the Supervisor" : ""}</div>`);
    const managed = field("managed", ind(["orchestra", "external"], it.managed) + `<div class="muted im-note">${ext ? "runs elsewhere: known by its events" + ((m.intent.attachments || []).length ? " or by the instruments attached to it" : "") : "managed by orchestra"}</div>`);
    const text = (f, label) => field(label, (it[f] ? box(it[f]) : '<span class="muted">none</span>') + (guessed(it, f) ? guess : "") + (f in before(it) ? '<span class="im-tag im-t-chg">changed just now</span>' : ""));
    const tags = field("tags", (it.tags || []).map((t) => `<span class="ty">${esc(t)}</span>`).join("") || '<span class="muted">none</span>');
    const body = prog
      ? `${engagementRow(it)}<div class="im-tabbody"><div class="muted im-tabnote">${cap(MODE_NOTE[(it.engagement || {}).mode] || "no engagement declared")}${ext ? "; it runs elsewhere" : ""}.</div>${spec(it, true) || '<span class="muted">nothing declared yet</span>'}</div>${text("title", "title")}${text("description", "description")}${tags}`
      : `${engagementRow(it)}${text("title", "title")}${text("description", "description")}${tags}${spec(it, false)}`;
    const heard = it.heard;
    const insts = heard ? "" : `${h4("Instances")}<div class="muted">none heard on the bus</div>`;
    const tail = heard ? "" : `${measuredBy(m)}${h4("Flows (hypotheses)")}<div class="muted">none hypothesised yet${measuredOf(m) && measuredOf(m).measured ? ": a machine that is only measured gets none; its route to the model is an expected effect" : ""}</div>${ext ? `${h4("Log")}<div class="muted">not readable: it runs outside the repository and the state directory</div>` : ""}`;
    const aliases = (it.alias_candidates || []).length ? `<div class="muted im-note">heard under another name? ${it.alias_candidates.map((a) => `<span class="ty">${esc(a)}</span>`).join("")} ${ask("ask the Supervisor to join them")}</div>` : "";
    return `<div class="im-head"><span class="dot im-dashdot" style="--rc:${mcolor(m.id)}"></span><b>${esc(it.title || m.id)}</b><span class="im-tag ${tag.cls}">${tag.text}</span><button class="ctl im-close" onclick="IntendedMachines.close()" title="close the panel (Esc)">×</button></div>
      <div class="muted im-id">id and bus source <span class="ty">${esc(m.id)}</span>${heard ? ` <button class="ctl" onclick="openMachine('${esc(m.id)}',{dialog:true})">details and log</button>` : ""}</div>
      ${status(m)}${why(it)}${aliases}${kind}${managed}${body}
      ${h4("Receives")}${types(it, "receives", listeners)}
      ${h4("Emits")}${types(it, "emits", listeners)}
      ${h4("Reads")}${reads(it)}
      ${insts}${effect(it)}${tail}
      <div class="muted im-foot">Every field is read-only: ${ask()} to change any of it.${it.state === "proposed" ? " Confirm asks the Supervisor." : ""}</div>`;
  }
  // a machine nothing declared: what the bus observed of it, and its dialog for the rest
  function observedPanel(m) {
    return `<div class="im-head"><span class="dot ${m.active ? "" : "off"}" style="--rc:${m.bootstrap ? "#fbbf24" : mcolor(m.id)}"></span><b>${esc(m.name || m.id)}</b><span class="im-tag im-t-obs">observed</span><button class="ctl im-close" onclick="IntendedMachines.close()" title="close the panel (Esc)">×</button></div>
      <div class="muted im-id">id and bus source <span class="ty">${esc(m.id)}</span> <button class="ctl" onclick="openMachine('${esc(m.id)}',{dialog:true})">details and log</button></div>
      <div class="muted im-why">Nothing is declared of it: what follows is what the bus shows and what it announced.</div>
      <div class="im-obs">${Orchestra.machineCards.rows(m)}</div>
      <div class="muted im-foot">To declare what it is for, what it should listen for or what effect it should have, ${ask()}.</div>`;
  }

  function draw(d) {
    const side = $("im-side"), row = $("im-row");
    if (!side) return;
    const m = OPEN && byId(OPEN);
    if (!m) { if (OPEN) OPEN = null; row.classList.remove("open"); side.innerHTML = ""; return; }
    row.classList.add("open");
    side.classList.toggle("im-side-declared", !!m.intent && m.intent.state !== "proposed");
    side.classList.toggle("im-side-observed", !m.intent);
    const html = m.intent ? declaredPanel(m, d) : observedPanel(m);
    if (side.dataset.html !== html) { side.dataset.html = html; const top = side.scrollTop; side.innerHTML = html; side.scrollTop = top; }
  }
  // the page calls these
  function open(id) {
    if (!byId(id)) return false;
    OPEN = id; window.LOOPSIG = null;
    if (typeof render === "function") render();
    return true;
  }
  function close() { OPEN = null; if (typeof render === "function") render(); }
  // a request to the Supervisor: shown as waiting at once, then as the server notes it (``requested``)
  async function request(control, id, change) {
    ASKED[id] = { control, change: change || null };
    if (typeof render === "function") render();
    try {
      const r = await fetch("/api/intended/request", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ control, part: "machine", id, ...(change ? { change } : {}), from: "machines page" }) });
      const a = await r.json();
      if (!a.ok) alert(a.error || "the request was refused");
    } catch (e) { /* the page says it is disconnected */ }
    if (typeof load === "function") await load();
    delete ASKED[id];
    if (typeof render === "function") render();
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && OPEN && !$("overlay").classList.contains("open")) close(); });
  return { links, edgeStyle, decorate, focusSpec, sort, decorateCards, draw, open, close, request, opened: () => OPEN,
           added };
})();
