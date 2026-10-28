// One experiment as the owner reads it (sd/experiments/): its edits as an equation diff against
// its base, its edit log, its runs (forward, replay, inverse) and the prediction it became. Pure:
// every function takes the API's JSON and returns HTML (charts through charts.js), so a test can
// render them without a browser. Nothing here changes an experiment (AGENTS.md rule 9).
const ExperimentView = (() => {
  const nice = (s) => String(s ?? "outside").replace(/_/g, " ");
  const n = (v) => (v == null || !isFinite(v) ? "—" : Charts.num(v));
  const when = (t) => (t ? new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
  const dur = (s) => (s == null ? "—" : s >= 86400 ? `${+(s / 86400).toFixed(1)} d` : s >= 3600 ? `${+(s / 3600).toFixed(1)} h` : s >= 60 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`);
  const pct = (r) => (r == null ? "" : `${r >= 1 ? "+" : "−"}${Math.abs(100 * (r - 1)).toFixed(r > 0.9 && r < 1.1 ? 1 : 0)}%`);
  const COLOR = { measured: "var(--s-measured)", base: "var(--s-base)", experiment: "var(--s-exp)" };
  const VS = { better: "▲ better", same: "= same", worse: "▼ worse" };
  const vs = (v) => (v ? `<span class="vs ${esc(v)}">${VS[v] || esc(v)}</span>` : '<span class="muted">not scored</span>');
  const tick = (ok) => (ok ? '<span class="vs better">✓ met</span>' : '<span class="vs worse">✗ missed</span>');
  const params = (p, other) => Object.entries(p || {}).map(([k, v]) => `<span class="${other && other[k] !== v ? "chg" : ""}">${esc(k)} = ${n(v)}</span>`).join(", ");

  // names from the experiment's draft (and its base): a stock's or flow's name, else its id in words
  function namesOf(x) {
    const s = {}, f = {};
    for (const m of [x.base && x.base.model, x.draft].filter(Boolean)) {
      for (const r of m.stocks || []) s[r.id] = r.name || r.id;
      for (const r of m.flows || []) f[r.id] = r.name || r.id;
    }
    return { stock: (id) => (id == null ? "outside" : nice(s[id] || id)), flow: (id) => nice(f[id] || id) };
  }
  const ends = (r, nm) => `${esc(nm.stock(r.from))} → ${esc(nm.stock(r.to))}`;

  // ---- the edits: an equation diff against the base
  function side(r, other, nm, label) {
    if (!r) return `<div class="lbl">${label}</div><div class="none">${label === "before" ? "not in the base: added" : "removed"}</div>`;
    return `<div class="lbl">${label} <span class="muted">· ${ends(r, nm)}${r.origin ? ` · ${esc(r.origin)}` : ""}</span></div>
      <div>${r.equation != null ? `<span class="eq">${esc(r.equation)}</span>` : '<span class="none">no equation in the language</span>'}</div>
      ${Object.keys(r.params || {}).length ? `<div class="params">${params(r.params, other && other.params)}</div>` : ""}`;
  }
  function flowDiff(id, before, after, nm, what) {
    return `<div class="dhead"><b>${esc(nm.flow(id))}</b> <span class="muted">${esc(id)}</span> <span class="what">${esc(what)}</span></div>
      <div class="diff"><div class="before">${side(before, after, nm, "before")}</div><div class="after">${side(after, before, nm, "after")}</div></div>`;
  }
  function diff(d, nm) {
    const parts = [];
    for (const c of d.flows.changed) parts.push(flowDiff(c.id, c.before, c.after, nm, `replaced: ${c.what.map((w) => (w === "params" ? "its numbers" : w === "equation" ? "its equation" : `its ${w} end`)).join(", ")}`));
    for (const a of d.flows.added) parts.push(flowDiff(a.id, null, a, nm, "added"));
    for (const r of d.flows.removed) parts.push(flowDiff(r.id, r, null, nm, "removed"));
    const sa = d.stocks.added, sr = d.stocks.removed, sc = d.scenario || {};
    if (sa.length) parts.push(`<div class="dhead"><b>Stocks added</b> <span class="what">hidden: no series measures them</span></div>${sa.map((s) => `<div>${esc(nm.stock(s.id))} <span class="muted">starting at ${n(s.initial)}</span></div>`).join("")}`);
    if (sr.length) parts.push(`<div class="dhead"><b>Stocks removed</b></div><div>${sr.map((s) => esc(nm.stock(s))).join(", ")}</div>`);
    const ins = Object.entries(sc.inputs || {}), lv = Object.entries(sc.levels || {});
    if (ins.length) parts.push(`<div class="dhead"><b>Input scenarios</b> <span class="what">what a forward run assumes</span></div>${ins.map(([k, v]) => `<div><span class="eq">${esc(k)}</span> ${esc(scenarioText(v))}</div>`).join("")}`);
    if (lv.length) parts.push(`<div class="dhead"><b>Starting levels</b> <span class="what">where a forward run starts a stock</span></div>${lv.map(([k, v]) => `<div>${esc(nm.stock(k))}: ${n(v)}</div>`).join("")}`);
    return parts.join("") || '<div class="empty">No edits yet: the draft is its base.</div>';
  }
  function scenarioText(v) {
    if (!v || typeof v !== "object") return String(v);
    if (v.kind === "hold") return "held at its last measured value";
    if (v.kind === "value") return `set to ${n(v.value)}`;
    if (v.kind === "scale") return `its last value ×${v.factor}`;
    if (v.kind === "step") return `held, then ${n(v.value)} from +${dur(v.at_s)}`;
    if (v.kind === "ramp") return `ramped to ${n(v.value)} by +${dur(v.to_s)}`;
    if (v.kind === "series") return `a given series (${(v.points || []).length} points)`;
    return JSON.stringify(v);
  }

  // ---- the edit log, in order, refused batches included
  function opText(e, nm) {
    const P = (p) => (p && Object.keys(p).length ? ` {${Object.entries(p).map(([k, v]) => `${k}: ${n(v)}`).join(", ")}}` : "");
    switch (e && e.op) {
      case "add_flow": return `add flow ${e.id} (${nm.stock(e.from)} → ${nm.stock(e.to)}) = ${e.equation}${P(e.params)}`;
      case "replace_flow": return `replace ${e.id} = ${e.equation}${P(e.params)}${"from" in e || "to" in e ? ` (ends ${nm.stock(e.from)} → ${nm.stock(e.to)})` : ""}`;
      case "remove_flow": return `remove flow ${e.id}`;
      case "set_params": return `set ${e.flow}${P(e.params)}`;
      case "add_stock": return `add hidden stock ${e.id} starting at ${n(e.initial ?? 0)}`;
      case "remove_stock": return `remove stock ${e.id}`;
      case "set_level": return e.level == null ? `clear ${e.stock}'s starting level` : `start ${e.stock} at ${n(e.level)}`;
      case "set_input": return `input ${e.input}: ${scenarioText(e.scenario)}`;
      case "load_model": return "load a whole model as the draft";
      default: return JSON.stringify(e);
    }
  }
  function log(entries, nm) {
    if (!entries.length) return '<div class="empty">No edits yet.</div>';
    return `<div class="log">${entries.map((b, i) => {
      const head = `<span class="when">${when(b.at)} · ${esc(b.by)}</span>`;
      if (b.discarded) return `<div class="b mark">${head}<div><b>Discarded</b></div></div>`;
      if (b.committed) return `<div class="b mark">${head}<div><b>Committed</b> as prediction <span class="eq">${esc(b.committed)}</span></div></div>`;
      const ops = (b.edits || []).map((e, j) => `<div class="op ${!b.ok && j === b.index ? "failed" : ""}">${!b.ok && j === b.index ? "✗ " : ""}${esc(opText(e, nm))}</div>`).join("");
      return `<div class="b ${b.ok ? "" : "refused"}">${head} · batch ${i + 1}${b.ok ? "" : ' · <b class="vs worse">✗ refused: nothing changed</b>'}${ops}${b.ok ? "" : `<div class="err">${esc(b.error)}</div>`}</div>`;
    }).join("")}</div>`;
  }

  // ---- runs
  const chartW = (W) => Math.max(320, Math.min(760, W || 600));
  function trustCallouts(r, nm) {
    const out = [];
    const lim = r.limits || [];
    if (lim.length) {
      const bad = lim.some((x) => x.run === "experiment" && x.new);
      out.push(`<div class="callout ${bad ? "bad" : "warn"}"><b class="h">⚠ Limits hit (${lim.length})</b><ul>${lim.map((x) => `<li><b>${esc(nm.stock(x.stock))}</b>, the ${esc(x.run)} run: ${x.kind === "floor" ? "reaches 0 (its outflows are cut to what it holds)" : `goes ${x.kind === "below bound" ? "below" : "above"} the bound ${n(x.bound)}`}${x.at_s != null ? ` at +${dur(x.at_s)}` : " in some members only"}; ${Math.round(100 * x.members)}% of the band's runs${x.new ? " · <b>new: the base does not</b>" : ""}</li>`).join("")}</ul></div>`);
    }
    const nt = r.not_trusted || [];
    if (nt.length) out.push(`<div class="callout warn"><b class="h">⚠ Not trusted here (${nt.length})</b><ul>${nt.map((x) => `<li><b>${x.kind === "stock" ? esc(nm.stock(x.id)) : esc(nm.flow(x.id))}</b> <span class="muted">${esc(x.kind)}</span>: ${x.why.map(esc).join("; ")}</li>`).join("")}</ul></div>`);
    else out.push('<div class="callout good"><b>✓ Trusted:</b> no stock or changed flow was flagged.</div>');
    out.push(nonfinite(r, nm));
    return out.join("");
  }
  // rates that were not numbers (log(0)), counted per flow and taken as 0
  function nonfinite(r, nm) {
    const rows = ["base", "experiment"].flatMap((k) => Object.entries((r.nonfinite || {})[k] || {}).filter(([, c]) => c).map(([f, c]) => `${esc(nm.flow(f))} ${c}× in the ${k}`));
    return rows.length ? `<div class="callout bad"><b>⚠ Rates that were not numbers</b> were taken as 0: ${rows.join("; ")}.</div>` : "";
  }
  const series = (t0, ts, vals) => ts.map((t, i) => [t0 + t, vals[i]]).filter((p) => p[1] != null);
  const bandOf = (t0, ts, b) => ts.map((t, i) => [t0 + t, b.lo[i], b.hi[i]]);
  const last = (b) => (b ? `${n(b.central[b.central.length - 1])} <span class="muted">(${n(b.lo[b.lo.length - 1])}–${n(b.hi[b.hi.length - 1])})</span>` : "—");

  function forward(run, measured, nm, W) {
    const r = run.result, now = r.now;
    const cards = Object.entries(r.stocks).map(([sid, s]) => {
      const lines = [];
      const m = (measured && measured[sid]) || [];
      if (m.length) lines.push({ label: "measured", points: m, color: COLOR.measured });
      if (s.base) lines.push({ label: "base", points: series(now, r.t, s.base.central), band: bandOf(now, r.t, s.base), color: COLOR.base });
      if (s.experiment) lines.push({ label: "experiment", points: series(now, r.t, s.experiment.central), band: bandOf(now, r.t, s.experiment), color: COLOR.experiment });
      const after = m.some((p) => p[0] > now + 1);
      return `<div class="card"><h4>${esc(nm.stock(sid))} ${s.trusted ? '<span class="vs better">✓ trusted</span>' : '<span class="verdict side">⚠ not trusted</span>'}</h4>
        <div class="cap">starts at ${n(s.start.experiment ?? s.start.base)}${s.unit ? " " + esc(s.unit) : ""}; at +${dur(r.horizon_s)}: base ${last(s.base)}, experiment ${last(s.experiment)}${s.difference ? `; difference ${last(s.difference)}` : ""}</div>
        ${Charts.line(lines, { W: chartW(W), H: 190, tight: true, marks: [{ t: now, label: "now" }] })}
        <div class="cap muted">${m.length ? `measured: the hour before the run${after ? ", and since (what happened)" : ""}` : "no measured level read for this stock"} · bands: 10–90% of ${r.band.members} runs${(r.band.structural || {})[sid] ? ", widened by the model's held-out misses" : ""}${s.behaviour ? ` · behaviour ${(+s.behaviour.score).toFixed(2)} (${esc(s.behaviour.level)}): its runs from part-way through its window missed by ${(+s.behaviour.error).toFixed(2)} × the level's spread` : ""}</div>
        ${s.why.length ? `<ul class="why">${s.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}</div>`;
    }).join("");
    const rates = Object.entries(r.rates_now || {});
    return `<div class="tally"><span>from <b>${when(now)}</b>, <b>${dur(r.horizon_s)}</b> ahead, steps of ${dur(r.step_s)}</span><span>changed flows: ${(r.changed || []).map((f) => esc(nm.flow(f))).join(", ") || "none"}</span></div>
      ${trustCallouts(r, nm)}
      <div class="grid">${cards}</div>
      ${rates.length ? `<h3>The changed flows' rates now <span class="muted">(per ${esc(r.time_unit)})</span></h3><div class="scroll"><table class="dt"><tr><th>flow</th><th class="num">base</th><th class="num">experiment</th><th class="num">seen</th></tr>${rates.map(([f, x]) => `<tr><td>${esc(nm.flow(f))}</td><td class="num">${n(x.base)}</td><td class="num">${n(x.experiment)}</td><td class="num">${x.observed ? `${n(x.observed[0])}–${n(x.observed[1])}` : "—"}</td></tr>`).join("")}</table></div>` : ""}
      ${(r.replayed || []).length ? `<div class="cap muted">Replayed from their measured rates (no equation): ${r.replayed.map((f) => esc(nm.flow(f))).join(", ")}</div>` : ""}
      <details class="how"><summary>how the band is made</summary>${esc(r.band.how)}</details>`;
  }

  function replay(run, nm, W) {
    const r = run.result, t0 = r.start, sm = r.summary;
    const tally = (k) => `${sm[k].better} better, ${sm[k].same} the same, ${sm[k].worse} worse`;
    const cards = Object.entries(r.stocks).map(([sid, s]) => {
      const lines = [];
      if (s.measured) lines.push({ label: "measured", points: s.measured.filter((p) => p[1] != null).map(([t, v]) => [t0 + t, v]), color: COLOR.measured });
      if (s.base) lines.push({ label: "base, simulated", points: series(t0, r.t, s.base), color: COLOR.base });
      if (s.experiment) lines.push({ label: "experiment, simulated", points: series(t0, r.t, s.experiment), color: COLOR.experiment });
      const e = s.error || {};
      return `<div class="card"><h4>${esc(nm.stock(sid))} ${vs(s.versus_base)}</h4>
        <div class="cap">error against measured (0 is perfect, 1 is as far off as the level varies): base <b>${n(e.base)}</b>, experiment <b>${n(e.experiment)}</b></div>
        ${Charts.line(lines, { W: chartW(W), H: 190, tight: true })}</div>`;
    }).join("");
    const fit = (x) => (x && x.one_step ? `${x.one_step.d2 != null ? `d² ${n(x.one_step.d2)}` : "d² —"} <span class="muted">· dev ${n(x.one_step.deviance)}</span>` : '<span class="muted">—</span>');
    const rows = Object.entries(r.flows).map(([f, x]) => `<tr><td>${esc(nm.flow(f))}</td><td class="num">${fit(x.base)}</td><td class="num">${fit(x.experiment)}</td><td>${vs(x.versus_base)}</td><td class="num">${n(x.measured_total)}</td><td class="num">${n(x.base && x.base.total)}</td><td class="num">${n(x.experiment && x.experiment.total)}</td></tr>`).join("");
    const worse = sm.stocks.worse + sm.flows.worse;
    return `<div class="tally"><span>window <b>${when(r.start)}</b> – <b>${when(r.end)}</b> (${dur(r.end - r.start)})</span></div>
      <div class="callout ${worse ? "bad" : sm.stocks.better + sm.flows.better ? "good" : "warn"}"><b class="h">Against the base</b>stocks: ${tally("stocks")} · flows: ${tally("flows")}</div>${nonfinite(r, nm)}
      <div class="grid">${cards}</div>
      <h3>Each flow's fit <span class="muted">(one step: its equation on the measured levels, against its counter; d² 1 is perfect, 0 no better than a constant rate)</span></h3>
      <div class="scroll"><table class="dt"><tr><th>flow</th><th class="num">base fit</th><th class="num">experiment fit</th><th>experiment against base</th><th class="num">counted</th><th class="num">base moved</th><th class="num">experiment moved</th></tr>${rows}</table></div>
      <details class="how"><summary>how it is scored</summary>${esc(r.how)}</details>`;
  }

  function changeText(c, nm) {
    if (c.kind === "param") return `${nm.flow(c.flow)}: ${c.param} ${n(c.base)} → ${n(c.value)} (×${n(c.factor)})`;
    if (c.kind === "rate") return `${nm.flow(c.flow)}: its whole rate ×${n(c.factor)}`;
    if (c.kind === "new_flow") return `a new flow ${c.flow} (${nm.stock(c.from)} → ${nm.stock(c.to)}) = ${c.equation} {${Object.entries(c.params || {}).map(([k, v]) => `${k}: ${n(v)}`).join(", ")}}`;
    return JSON.stringify(c);
  }
  function targetText(t, nm) {
    const what = t.part === "stock" ? nm.stock(t.id) : nm.flow(t.id);
    if (t.kind === "scale") return `${what}: ${t.part === "stock" ? "mean level" : "moved"} ×${n(t.value)} the base replay's`;
    if (t.kind === "level") return `${what}: mean level ${n(t.value)}`;
    if (t.kind === "below" || t.kind === "above") return `${what}: ${t.kind === "below" ? "highest below" : "lowest above"} ${n(t.value)}`;
    if (t.kind === "total") return `${what}: moved ${n(t.value)}`;
    if (t.kind === "hold") return `${what}: kept as it was`;
    return `${what}: ${t.kind} ${n(t.value)}`;
  }
  function inverse(run, nm, solvedDiff) {
    const r = run.result, u = r.uniqueness || {}, o = run.options || {};
    const out = [];
    const metAlt = (r.alternatives || []).filter((a) => a.met).length;
    if (r.ambiguous) {
      const why = [];
      if (metAlt) why.push(`${metAlt} other change${metAlt > 1 ? "s" : ""} of the same size also reach${metAlt > 1 ? "" : "es"} the target${r.targets.length > 1 ? "s" : ""} (below)`);
      if (u.checked && !u.consistent) why.push(`the uniqueness check disagrees: from the data the solved model would make, discovery ${u.extra.length ? `also finds changed laws for ${u.extra.map((f) => esc(nm.flow(f))).join(", ")}` : ""}${u.extra.length && u.missed.length ? ", and " : ""}${u.missed.length ? `does not find ${u.missed.map((f) => esc(nm.flow(f))).join(", ")} changed` : ""}`);
      out.push(`<div class="callout bad"><b class="h">⚠ Ambiguous: this answer is not the only one</b><ul>${why.map((w) => `<li>${w}</li>`).join("")}</ul></div>`);
    }
    out.push(r.reached ? `<div class="callout good"><b>✓ Reached</b> with ${r.count} change${r.count === 1 ? "" : "s"}.</div>`
      : `<div class="callout warn"><b>⚠ Not reached:</b> the closest the solver came, with ${r.count} change${r.count === 1 ? "" : "s"}.</div>`);
    if (r.stopped) out.push(`<div class="callout warn"><b>⚠ Stopped early:</b> ${esc(r.stopped)}</div>`);
    const asked = r.targets.filter((t) => t.kind !== "hold"), held = r.targets.filter((t) => t.kind === "hold");
    const heldFlows = (o.hold || []).filter((h) => h.flow).map((h) => nm.flow(h.flow));
    out.push(`<div class="tally"><span>window <b>${when(r.window[0])}</b> – <b>${when(r.window[1])}</b></span><span>${r.evaluations} replays in ${n(r.elapsed_s)} s</span></div>
      <h3>Asked for</h3><div class="scroll"><table class="dt"><tr><th>target</th><th class="num">goal</th><th class="num">solved</th><th class="num">base replay</th><th class="num">measured</th><th></th></tr>
      ${asked.map((t) => `<tr><td>${esc(targetText(t, nm))}</td><td class="num">${n(t.goal)}</td><td class="num">${n(t.solved)}</td><td class="num">${n(t.base_replay)}</td><td class="num">${n(t.measured)}</td><td>${tick(t.met)}</td></tr>`).join("")}</table></div>
      <h3>Held</h3><div>${[...heldFlows.map((f) => `${esc(f)}: its equation kept (not a candidate)`), ...held.map((t) => `${esc(targetText(t, nm))} ${tick(t.met)}`)].map((x) => `<div>${x}</div>`).join("") || '<span class="muted">nothing held: anything not targeted may move</span>'}</div>
      <h3>The changes found</h3>${r.changes.length ? r.changes.map((c) => `<div class="eq" style="margin:2px 0">${esc(changeText(c, nm))}</div>`).join("") : '<div class="muted">none</div>'}
      ${r.experiment ? `<div class="cap">as a new draft: <a href="/experiments/${esc(r.experiment)}">${esc(r.experiment)}</a>, its equations against the base:</div>${solvedDiff ? diff(solvedDiff, nm) : '<div class="muted">reading its diff…</div>'}` : ""}
      <h3>Side effects <span class="muted">(what was not named and moved more than 5%)</span></h3>
      ${(r.side_effects || []).length ? `<div class="scroll"><table class="dt"><tr><th>what</th><th class="num">base replay</th><th class="num">solved</th><th class="num">size</th></tr>${r.side_effects.slice().sort((a, b) => Math.abs(Math.log(b.ratio || 1)) - Math.abs(Math.log(a.ratio || 1))).map((s) => `<tr><td>${esc(s.part === "stock" ? nm.stock(s.id) : nm.flow(s.id))} <span class="muted">${esc(s.what)}</span></td><td class="num">${n(s.base_replay)}</td><td class="num">${n(s.solved)}</td><td class="num">×${n(s.ratio)} (${pct(s.ratio)})<span class="ratio" style="width:${Math.min(80, Math.round(30 * Math.abs(Math.log(s.ratio || 1))))}px"></span></td></tr>`).join("")}</table></div>` : '<div class="muted">none</div>'}
      <h3>Alternatives of the same size</h3>
      ${(r.alternatives || []).length ? r.alternatives.map((a) => `<div style="margin:3px 0">${a.met ? '<span class="verdict side">also reaches it</span>' : '<span class="vs same">does not reach it</span>'} ${a.changes.map((c) => `<span class="eq">${esc(changeText(c, nm))}</span>`).join(" ")} <span class="muted">loss ${n(a.loss)}</span></div>`).join("") : '<div class="muted">none tried, or none came close</div>'}
      <h3>Uniqueness check</h3>${uniqueness(u, nm)}`);
    return out.join("");
  }
  function uniqueness(u, nm) {
    if (!u.checked) return `<div class="muted">not checked: ${esc(u.why || "")}</div>`;
    const fl = (xs) => (xs.length ? xs.map((f) => esc(nm.flow(f))).join(", ") : "none");
    const laws = Object.entries(u.laws || {});
    return `<div class="callout ${u.consistent ? "good" : "bad"}"><b>${u.consistent ? "✓ Consistent" : "⚠ Inconsistent"}:</b> recovered ${fl(u.recovered)} · missed ${fl(u.missed)} · also changed ${fl(u.extra)}${u.unmeasured.length ? ` · not measured ${fl(u.unmeasured)}` : ""}</div>
      ${laws.length ? `<div class="scroll"><table class="dt"><tr><th>flow</th><th>its law</th><th class="num">deviance gain</th></tr>${laws.map(([f, l]) => `<tr><td>${esc(nm.flow(f))}</td><td>${esc(l.status)}</td><td class="num">${n(l.deviance_gain)}</td></tr>`).join("")}</table></div>` : ""}
      <details class="how"><summary>how it is checked</summary>${esc(u.how || "")}</details>`;
  }

  // ---- the prediction a committed experiment became
  function prediction(p, rec, nm) {
    if (!p) return "";
    const v = p.verdict || null;
    const head = `<div class="xhead"><span style="font-size:14px">${Predictions.badge(p.status === "judged" ? v.verdict : null, v && v.partial)}</span>
      <span class="muted">${p.status === "judged" ? `judged ${dur(p.horizon_s)} after the change` : p.status === "invalid" ? "invalid: " + esc(p.why) : p.era ? "waiting for the horizon" : p.status === "not yet recorded" ? "not yet recorded by the host" : "waiting for its change to begin an era"}</span></div>`;
    const expect = (p.expect || rec.expect || []);
    const meta = `<div class="meta"><div>expects</div><div>${expect.length ? expect.map((e) => `<div><span class="eq">${esc(Predictions.expectText(e, nm))}</span></div>`).join("") : "nothing changes (the null test)"}</div>
      <div>change</div><div><span class="eq">${esc(p.change || rec.change || "—")}</span> <span class="muted">the id the change is published with</span></div>
      <div>era</div><div>${p.era ? `<a href="/dynamics?era=${encodeURIComponent(p.era)}">${esc(p.era)}</a> <span class="muted">begun by the change</span>` : '<span class="muted">its change has not begun an era yet</span>'}</div>
      <div>horizon</div><div>${dur(p.horizon_s ?? rec.horizon_s)}</div>
      <div>made</div><div>${when(p.made_at ?? rec.made_at)} by ${esc(p.source || "")} <span class="muted">· prediction ${esc(p.id || rec.id)}</span>${rec.no_trajectories ? ` <span class="muted">· no forward run went with it (${esc(rec.no_trajectories)})</span>` : ""}</div></div>`;
    const ev = v ? Predictions.evidence(v, nm) : [];
    return head + meta + (ev.length ? `<h3>Evidence</h3><div class="pred ${Predictions.CLASS[v.partial || v.verdict] || ""}">${ev.map((x) => `<div class="ev">${x}</div>`).join("")}</div>` : "");
  }

  return { namesOf, diff, log, forward, replay, inverse, prediction, when, dur, nice, vs, opText };
})();
