// The proposed additions to /dynamics and /machines, drawn on top of the real pages for each frame
// of the owner's scenario (2026-10-31). Loaded last on the page (tools/serve.py); shim.js holds
// the page's fetches until it has run, so everything here is in place before the page draws.
// What it does, per frame (?frame=...):
//   - edits the fixtures' answers (MOCK.on) where the scenario changes what the server says: a new
//     model version, a new stock and flow, a proposed machine;
//   - wraps the real page's functions (SDGraph.build, tables, versionBar, NetGraph.create's render,
//     cards) to add the new marks: ghost, new-in-version, unconfirmed, expected;
//   - opens the drawers and draws the new panels in the pages' own markup and classes.
// Nothing in orchestra/web/static is changed; the CSS for the new marks is additions.css.
(() => {
  const F = MOCK.frame, PAGE = location.pathname;
  const NOW = Date.now() / 1000;
  const hhmm = (t) => new Date(t * 1000).toTimeString().slice(0, 5);
  const finish = (ms) => setTimeout(() => { MOCK.done = true; }, ms);

  // ---- SVG marks: a pill tag, a ring, a pin ----
  function svgTag(g, x, y, text, cls = "") {
    const t = g.append("g").attr("class", "mk-svgtag " + cls).attr("transform", `translate(${x},${y})`);
    const w = text.length * 5.6 + 14;
    t.append("rect").attr("x", 0).attr("y", -9).attr("width", w).attr("height", 16).attr("rx", 8);
    t.append("text").attr("x", 7).attr("y", 3).text(text);
    return w;
  }
  function svgRing(g, s, cls = "mk-ring") {
    if (s.r) g.insert("circle", ":first-child").attr("class", cls).attr("r", s.r + 6);
    else g.insert("rect", ":first-child").attr("class", cls).attr("x", -s.w / 2 - 6).attr("y", -s.h / 2 - 6).attr("width", s.w + 12).attr("height", s.h + 12).attr("rx", 10);
  }
  function svgPin(g, x, y, label) {
    const p = g.append("g").attr("class", "mk-pin").attr("transform", `translate(${x},${y})`);
    p.append("path").attr("d", "M0,-6 a4,4 0 1 1 0.01,0 Z M-1,-2 L0,5 L1,-2 Z");
    p.append("circle").attr("cy", -6).attr("r", 4);
    p.append("line").attr("x1", 0).attr("y1", -2).attr("x2", 0).attr("y2", 5);
    if (label) p.append("text").attr("x", 7).attr("y", -2).text(label);
  }
  window.MK = { svgTag, svgRing, svgPin };

  // every graph's render: a node's mark (mkDecorate) is drawn after the page's own decoration, and
  // MK.afterRender(graph, nodes, edges) runs after each drawing (the pages redraw on their own timers)
  const create = NetGraph.create;
  NetGraph.create = (el, opts) => {
    const graph = create(el, opts), render = graph.render;
    graph.render = (nodes, edges) => {
      for (const n of nodes) if (n.mkDecorate) { const base = n.decorate, mk = n.mkDecorate; n.decorate = (g, x, s) => { if (base) base(g, x, s); mk(g, x, s); }; }
      if (MK.beforeRender) ({ nodes, edges } = MK.beforeRender(nodes, edges) || { nodes, edges });
      render(nodes, edges);
      if (MK.afterRender) MK.afterRender(graph, nodes, edges);
    };
    MK.graph = graph;
    return graph;
  };

  if (PAGE === "/dynamics") dynamics();
  else if (PAGE === "/machines") machines();

  // =====================================================================================
  // /dynamics
  // =====================================================================================
  function dynamics() {
    const DONE = "tasks_tickets_DONE", ACC = "acceptance_tests_passing", FLOW = "acceptance_tests_passing_net@tasks_tickets_DONE";
    const LAYOUT = F === "layout_dynamics";
    const D = F.replace("-closed", "");
    const withAcc = D === "D2" || D === "D3" || LAYOUT;
    const diff = D === "D2" || LAYOUT;
    window.SHOW_ACC = true;                      // every stock on the diagram: DONE, commits and files too
    if (LAYOUT) { try { localStorage.removeItem("orchestra.netgraph.dynamics.v2"); } catch (e) {} }
    // the diagram as a person would have arranged it (dragged, so pinned): the ticket states along the
    // top, the repository's stocks and DONE below, Features beside DONE and the new stock under it.
    // Every frame uses the same places, so the frames compare.
    else for (const [id, x, y] of [["s:tasks_tickets_OPEN", 0, 0], ["s:tasks_tickets_IN_PROGRESS", 330, 0], ["s:tasks_tickets_READY_FOR_REVIEW", 680, 0],
      ["s:test_report_files_read", 1030, 0], ["s:repo_files", 0, 210], ["s:repo_commits", 330, 210], ["s:features", 680, 210], ["s:tasks_tickets_DONE", 1030, 210],
      ["s:" + ACC, 1030, 400]]) MOCK.layout("dynamics.v2", id, x, y);
    const declaredAt = NOW - (D === "D1" ? 120 : 600);               // "declared by you · 2 min ago"
    const recordingSince = NOW - 32 * 60;                            // 3 points, every 15 min

    // ---- the server's answers, as they would be in each frame ----
    MOCK.on(/^\/api\/dynamics\/model/, (b) => {
      const m = b.model;
      // the model's version history: v14 before the Features series was recorded; v15 after
      const n = withAcc ? 15 : 14, v0 = m.versions[0];
      m.versions = Array.from({ length: n }, (_, i) => ({ ...v0, version: i + 1, saved_at: NOW - (n - i) * 3600 + (i === n - 1 ? 3600 - 180 : 0) }));
      m.versions[n - 1].note = v0.note;
      m.version = m.current = n;
      if (withAcc) { m.live = false; addAcceptance(m); }
      return b;
    });
    MOCK.on(/^\/api\/dynamics\/history/, (b) => {
      if (!withAcc) return b;
      const done = b.stocks[DONE];
      b.stocks[ACC] = done.map(([t, v]) => [t, accLevel(v)]);
      b.flows[FLOW] = done.map(([t, v]) => [t, +(0.034 * v).toFixed(3)]);
      return b;
    });
    MOCK.on(/^\/api\/dynamics\/simulate/, (b) => {
      if (!withAcc) return b;
      const e = b.era[DONE] || [], p = b.projection[DONE] || [];
      b.era[ACC] = e.map(([t, v]) => [t, accLevel(v) + 0.4]); b.projection[ACC] = p.map(([t, v]) => [t, accLevel(v)]);
      return b;
    });
    const accLevel = (done) => 41 + Math.floor(done / 3);
    function addAcceptance(m) {
      const done = m.stocks.find((s) => s.id === DONE), lvl = m.levels[DONE];
      const series = { ...done.series, name: ACC, labels: { project: done.series.labels.project, instrument: "features.acceptance" }, resolution_s: 900 };
      const trust = { ...done.evidence.trust, kind: "net_flow", score: 0.58, level: "medium", weakest: "held_out", components: { held_out: 0.58, level: 0.81, units: 0.66 },
        held_out_r2: 0.58, units: 3, persistence: 1, persistence_of: 1, why: ["only 3 points of its own, every 15 min: the fit is over the stretches between them"],
        behaviour: { ...done.evidence.trust.behaviour, score: 0.61, level: "medium", error: 0.47, hold_error: 0.9 } };
      m.stocks.push({ id: ACC, name: "acceptance tests passing", unit: "tests", series,
        evidence: { written_by: "features.acceptance", accumulator: false, trust, live_from: recordingSince, held_minutes: 0,
          net_flow: { form: "0.034 × DONE", r2: 0.91, stretches: 2, stretch_s: 900, aic: -11.2, aic_constant: -7.9, forms_tried: 6, driver: DONE } } });
      m.levels[ACC] = { t: lvl.t, v: accLevel(lvl.v) };
      const tmpl = m.flows.find((f) => f.to === DONE);
      const eq = { form: "proportional", params: { k: 0.034 }, origin: "fitted", method: "least-squares", inputs: [DONE], spec: {}, sources: ["own"], prior: {},
        quality: { events: 3, dispersion: 0.2, live_minutes: 32, aic: -11.2, aic_constant: -7.9, aic_linear_tasks_tickets_DONE: -10.6 } };
      m.flows.push({ ...tmpl, id: FLOW, name: "acceptance tests passing (net flow)", counter: null, from: DONE, to: ACC, machine: null, machines: [],
        association: "no machine associated yet: no machine's events match a level read every 15 min",
        equations: [eq], current: eq, measured_by: [], evidence: { net_flow_of: ACC } });
    }

    // ---- the graph: the expected stock, the new and the removed ----
    const build = SDGraph.build;
    SDGraph.build = (m, opts) => {
      const g = build(m, opts);
      const done = g.nodes.find((n) => n.sid === DONE);
      // Features: expected (declared by the person), with no series: a ghost, same shape as a stock
      const note = D === "D1" ? ["expected · declared by you · 2 min ago", "no series yet"]
        : D === "D2" || LAYOUT ? ["expected · not in v15", "no series of its own"] : ["expected · not in v15", "no series of its own"];
      g.nodes.push({ id: "s:features", kind: "box", label: "Features", lines: ["Features"], caption: "expected stock", w: 180, h: 92, dashed: true,
        color: "#8b95a7", fill: "#0b0e14", charge: -1600, sub: " ", cls: "mk-ghost" + (D === "D1" ? " mk-user" : ""), mkNote: note,
        mkDecorate: (gg, n, s) => {
          gg.append("text").attr("class", "ng-sub").attr("text-anchor", "middle").attr("y", -s.h / 2 + 48).text(note[1]);
          svgTag(gg, -s.w / 2, -s.h / 2 - 14, note[0], D === "D1" ? "mk-t-user" : "mk-t-ghost");
          if (D === "D3") svgTag(gg, -s.w / 2, s.h / 2 + 14, "your note · waiting for a flow", "mk-t-user");
        } });
      if (withAcc) {
        const acc = g.nodes.find((n) => n.sid === ACC);
        if (acc) {
          acc.cls = diff ? "mk-new" : "mk-expected";
          acc.mkDecorate = (gg, n, s) => {
            if (diff) { svgRing(gg, s); svgTag(gg, -s.w / 2, -s.h / 2 - 16, "new in v15", "mk-t-new"); }
            else { svgPin(gg, -s.w / 2 + 6, -s.h / 2 - 12, "expected"); }
          };
        }
        const fe = g.edges.find((e) => e.fid === FLOW);
        if (fe && diff) { fe.cls = (fe.cls || "") + " mk-new-edge"; fe.color = "#6ea8fe"; fe.label = [fe.label[0], "new in v15"]; }
      }
      // a flow v14 had that v15 does not: drawn as its ghost while "changes since v14" is on
      if (diff) g.edges.push({ id: "s:repo_files>s:repo_commits:gone", source: "s:repo_files", target: "s:repo_commits", color: "#5b6272", dash: "3 5", width: 2.2,
        bend: 70, cls: "mk-removed", label: ["0.41 /min · gone in v15", "was fitted in v14"] });
      return g;
    };

    // ---- the version bar: the existing controls, and "changes since v14" ----
    const vb = window.versionBar;
    window.versionBar = () => {
      vb();
      if (!withAcc || LAYOUT) return;
      $("ver").insertAdjacentHTML("beforeend", `<label class="mk-toggle ${diff ? "on" : ""}" title="draw what changed since the version before: new stocks and flows ringed, removed ones as ghosts"><span class="mk-sw"></span>changes since v14</label>`);
    };

    // ---- the tables: an Expected group above the stocks discovery found ----
    const tb = window.tables;
    window.tables = () => {
      tb();
      const st = $("stocks"), head = st.querySelector("tr");
      const exp = [`<tr class="mk-exprow"><td><span class="mk-ghostdot"></span><b>Features</b> <span class="mk-tag mk-t-${D === "D1" ? "user" : "ghost"}">${D === "D1" ? "declared by you" : "not in v15"}</span></td><td class="num">—</td>
        <td class="muted">${D === "D1" ? `no series yet → <span style="color:#86efac">recording</span> <span class="muted">(features.acceptance, since ${hhmm(recordingSince)})</span>` : D === "D3" ? "no series of its own · waiting for a flow" : "no series of its own · discovery found none for it in v15"}</td></tr>`];
      if (D === "D3") {
        const row = [...st.querySelectorAll("tr")].find((r) => r.textContent.includes("acceptance tests passing"));
        if (row) { row.classList.add("mk-exprow"); row.cells[0].insertAdjacentHTML("afterbegin", '<span class="mk-pinchip" title="expected: always shown">⌖</span>'); exp.push(row.outerHTML); row.remove(); }
      }
      head.insertAdjacentHTML("afterend", `<tr class="mk-group"><td colspan="3">Expected <span class="count">${exp.length}</span> <span class="muted">· always shown, found or not</span></td></tr>${exp.join("")}
        <tr class="mk-group"><td colspan="3">Found by discovery <span class="count">${st.querySelectorAll("tr").length - 1 - (D === "D3" ? 0 : 0)}</span></td></tr>`);
      $("nstocks").textContent = `${MODEL.stocks.length} found · ${exp.length} expected`;
      if (diff) {
        const rows = [...$("stocks").querySelectorAll("tr")], r = rows.find((x) => x.textContent.includes("acceptance tests passing") && !x.classList.contains("mk-exprow"));
        if (r) r.cells[0].insertAdjacentHTML("beforeend", ' <span class="mk-tag mk-t-new">new in v15</span>');
        const fr = [...$("flows").querySelectorAll("tr")].pop();
        if (fr) fr.cells[0].insertAdjacentHTML("beforeend", ' <span class="mk-tag mk-t-new">new in v15</span>');
        $("flows").insertAdjacentHTML("beforeend", `<tr class="mk-gone"><td><s>repo files → repo commits</s> <span class="mk-tag mk-t-gone">gone in v15</span><div class="muted" style="font-size:11px">files → commits</div></td><td class="num"><s>0.41 /min</s></td><td><span class="origin fitted">fitted</span> <span class="muted">in v14 · ghost shown</span></td><td class="muted">merge_gate 71% in v14</td></tr>`);
      }
    };

    // ---- the legend: the new marks ----
    const dr = window.draw;
    window.draw = () => {
      dr();
      const lg = $("legend"), tail = lg.querySelector(":scope > span.muted:last-child");
      const items = `<span class="lg mk-lg" title="a stock you said to expect, which this version has"><i class="mk-sw-present"></i>expected, present</span>
        <span class="lg mk-lg" title="a stock you said to expect, which this version does not have: drawn as a ghost"><i class="mk-sw-ghost"></i>expected, missing (ghost)</span>
        <span class="lg mk-lg"><i class="mk-sw-new"></i>new in this version</span>
        <span class="lg mk-lg"><i class="mk-sw-gone"></i>removed since last version</span>`;
      if (tail) tail.insertAdjacentHTML("beforebegin", items); else lg.insertAdjacentHTML("beforeend", items);
    };

    // ---- D2: what changed since v14, beside the loops ----
    if (diff && !LAYOUT) {
      const loops = $("loops"), row = document.createElement("div");
      row.className = "mk-loopsrow"; loops.parentNode.insertBefore(row, loops); row.appendChild(loops);
      row.insertAdjacentHTML("beforeend", `<div class="panel mk-changes" id="mk-changes">
        <h2 style="margin-top:0"><span>Changes since v14</span><span class="count">4</span></h2>
        <div class="mk-chg new"><span class="mk-sign">+</span><div><div>stock <b>acceptance tests passing</b> <span class="mk-tag mk-t-new">new · inferred</span></div>
          <div class="muted">from the series <span class="ty">acceptance_tests_passing</span> recorded by features.acceptance since ${hhmm(recordingSince)}; no counters, its net flow fitted</div></div>
          <span class="mk-acts"><button class="ctl mk-primary">expect</button><button class="ctl">ignore</button></span></div>
        <div class="mk-chg new"><span class="mk-sign">+</span><div><div>flow <b>DONE → acceptance tests passing</b> <span class="mk-tag mk-t-new">new</span></div>
          <div class="muted"><span class="num">0.034 × DONE /min</span> · fitted from correlation; untested</div></div></div>
        <div class="mk-chg gone"><span class="mk-sign">−</span><div><div>flow <s>files → commits</s> <span class="mk-tag mk-t-gone">gone in v15</span></div>
          <div class="muted">was fitted in v14 (<span class="num">0.41 /min</span>, merge_gate 71%) · ghost shown</div></div></div>
        <div class="mk-chg ghost"><span class="mk-sign">○</span><div><div>expected stock <b>Features</b> <span class="mk-tag mk-t-ghost">expected · not in v15</span></div>
          <div class="muted">declared by you; discovery did not link it to anything it found · ghost shown</div></div></div>
        <div class="muted" style="font-size:11px;margin-top:8px">Against version 14, saved ${Math.round((NOW - (NOW - 2 * 3600)) / 3600)} h ago. <b>expect</b> keeps a stock on the diagram whatever a later discovery finds; <b>ignore</b> takes it off this list.</div>
      </div>`);
    }

    // ---- D1: the Features drawer ----
    function featuresDrawer() {
      const pts = [[recordingSince, 41], [recordingSince + 900, 43], [recordingSince + 1800, 46]];
      const x = (t) => 4 + (t - pts[0][0]) / 1800 * 232, y = (v) => 30 - (v - 40) / 7 * 26;
      const spark = `<svg class="mk-spark" viewBox="0 0 240 34"><path class="a" d="M${x(pts[0][0])},34 ${pts.map(([t, v]) => `L${x(t)},${y(v)}`).join(" ")} L${x(pts[2][0])},34 Z"/><path class="l" d="${pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t)},${y(v)}`).join(" ")}"/>${pts.map(([t, v]) => `<circle cx="${x(t)}" cy="${y(v)}" r="2.6"/>`).join("")}</svg>`;
      const opt = (k, on, title, how, kind) => `<div class="mk-opt ${on ? "on" : ""}"><span class="mk-radio"></span><div class="mk-optbody"><div><b>${k}</b> ${title}${on ? ' <span class="mk-tag mk-t-chosen">chosen</span>' : ""}</div><div class="muted">${how}</div></div><span class="ty mk-kind">${kind}</span></div>`;
      openDrawer(`<h3>Features <span class="tag">stock</span> <span class="mk-tag mk-t-user">expected · declared by you</span> <span class="mk-tag mk-t-ghost">no series yet</span></h3>
        <div class="muted" style="font-size:12px;margin-bottom:8px">You declared it ${Math.round((NOW - declaredAt) / 60)} min ago in the Supervisor's chat: <i>"I think we need to start tracking features, then, because we currently aren't. I'm going to create a Features stock."</i> It is expected, not found: drawn as a ghost until a series measures it and a discovery finds it. Nothing about the model changes until then.</div>
        <div class="def"><div>now</div><div class="num">—</div>
        <div>status</div><div>no series yet → <span style="color:#86efac">recording</span> <span class="muted">(the option chosen below)</span></div>
        <div>declared</div><div>by you · ${hhmm(declaredAt)} · beside <b>DONE</b> <span class="muted">(where you said it belongs: what the task workflow delivers)</span></div>
        <div>machines</div><div><span class="muted">none: an expected stock has no flows until discovery finds one</span></div></div>
        <h4>How to measure it <span class="muted" style="text-transform:none;letter-spacing:0;font-weight:400">· the Supervisor's options; it chose one with you in its chat</span></h4>
        <div class="mk-opts">
          ${opt("a", true, "passing acceptance tests on main", "a <code>[[collect]]</code> script runs <code>pytest tests/acceptance --junitxml</code> on main every 15 min and prints how many pass", "script collector")}
          <div class="mk-rec"><div class="mk-recline"><span class="mk-live"></span>recording since ${hhmm(recordingSince)} · instrument <b>features.acceptance</b> · 3 points <span class="muted">· every 15 min · last 46</span></div>${spark}
            <details class="mk-script"><summary>the script <span class="muted">· machines/features_acceptance.sh and its [[collect]] entry, as the Supervisor wrote them on DEMO-35 · 9 lines</span></summary></details>
            <div class="mk-peek"><pre>#!/bin/sh
# Passing acceptance tests on main, as Prometheus text:
#   acceptance_tests_passing N
set -eu
tmp=$(mktemp -d)
git worktree add --quiet --detach "$tmp/main" main
…</pre><pre>[[collect]]
name = "features.acceptance"
command = "machines/features_acceptance.sh"
every = "15m"
timeout = "5m"</pre></div></div>
          ${opt("b", false, "e2e tests passing", "the same script, reading the e2e suite's junit file (<code>tests/e2e</code>) instead", "script collector")}
          ${opt("c", false, "tickets labelled <span class=\"ty\">feature</span> reaching DONE", "from the task system's counters (<code>tasks_ticket_transitions_total{to=\"DONE\"}</code>, by label): no new instrument, but it counts what was planned as a feature, not what works", "task system's counters")}
          ${opt("d", false, "a simulated placeholder series", "a script that writes a slow ramp, so the rest works before the real one exists; marked simulated wherever it is shown", "script collector · simulated")}
        </div>
        <h4>Level</h4><div class="muted" style="font-size:12px">No series is bound to it yet: nothing to draw. Once a discovery finds a stock in what features.acceptance records, it is shown here, and you can say whether that is this stock.</div>`);
    }

    // ---- run the frame ----
    if (LAYOUT) { finish(45000); return; }
    const after = (ms, fn) => setTimeout(fn, ms);
    if (F === "D1-closed" || F === "D3-closed") { finish(3500); return; }
    if (F === "D1") after(2500, () => { featuresDrawer(); finish(800); });
    else if (F === "D3") after(2500, () => {
      Live.openStock(ACC);
      const h3 = document.querySelector("#drawer h3");
      h3.insertAdjacentHTML("beforeend", '<span class="mk-tag mk-t-exp">⌖ expected</span>');
      h3.insertAdjacentHTML("afterend", `<div class="mk-expect"><label class="mk-toggle on"><span class="mk-sw"></span><b>Expected:</b>&nbsp;always show this stock</label>
        <div class="muted">confirmed expected · present in v15 · tracked by inference since v15 <span class="mk-sep">·</span> confirmed by you just now, from "Changes since v14"</div></div>`);
      finish(2500);
    });
    else finish(3500);
  }

  // =====================================================================================
  // /machines
  // =====================================================================================
  function machines() {
    const FCI = "feature-count-improver", NM = "nightly-metrics";
    const E = F.split("-")[0], E3MODE = F.includes("-") ? F.split("-")[1] : "adhoc";
    const LAYOUT = F === "layout_machines";
    const who = E === "E3" ? NM : FCI, NID = "m:" + who;
    const ADDED = ["changes.requested", "gate.rejected", "gate.landed"], REMOVED = ["session.settled", "task.reported"];
    EV_MODE = "events";
    if (LAYOUT) { try { localStorage.removeItem("orchestra.netgraph.machines.events"); } catch (e) {} }
    // the map as a person would have arranged it (dragged, so pinned): the task workflow on the left
    // and in the middle, the proposed machine on the right with the event types it listens for in a
    // column beside it. Every frame uses the same places.
    else {
      const sup = Object.keys(MOCK.saved("machines.events")).find((k) => k.startsWith("ev:group:ev:gate.base_broken"));
      for (const [id, x, y] of [["m:orchestra-host", -150, 40], ["m:planner", 60, 60], ["m:coordinator", 330, 300], ["m:supervisor", 60, 520], ["m:worker", 600, 60],
        ["m:reviewer", 600, 560], ["m:merge_gate", 330, 640], ["m:" + FCI, 960, 330], ["m:" + NM, 930, 600],
        ["ev:request.done", 200, 150], ["ev:request.refused", -80, 170], ["ev:ticket.created", 150, 300], ["ev:task.attention_needed", 170, 420],
        ["ev:gate.conflict", 150, 470], ["ev:group:ev:gate.conflict+ev:gate.rejected", 150, 470], ["ev:orchestra.prediction.judged", 330, 170],
        ["ev:task.assigned", 470, 330], ["ev:task.released", 470, 230], ["ev:review.requested", 620, 300], ["ev:review.approved", 480, 660],
        ["ev:gate.landed", 200, 600], ["ev:task.reported", 790, 120], ["ev:session.settled", 790, 220], ["ev:changes.requested", 790, 330],
        ["ev:gate.rejected", 790, 430], ["ev:work.requested", 720, 440], ["ev:summary.requested", 790, 600], [sup, -150, 560]]) if (id) MOCK.layout("machines.events", id, x, y);
    }                                       // the map with its event types: what the machine listens for is the point
    // ---- the proposed machine, as the machines list would carry it ----
    const blank = { bootstrap: false, name: null, group: null, about: {}, instances: [], first_seen: null, last_seen: null, active: false, flows: [], logs: [] };
    const fci = { ...blank, id: FCI, kind: "agent", package: null, mode: E === "E2" ? "scheduled" : "continuous",
      publishes: [{ type: "work.requested", count: 0, day: 0, per_min_10m: 0 }],
      subscribes: E === "E2" || LAYOUT ? [...ADDED, ...REMOVED] : REMOVED.slice() };
    const nm = { ...blank, id: NM, kind: "program", package: null, mode: { adhoc: "ad hoc", continuous: "continuous", external: "continuous" }[E3MODE],
      publishes: [{ type: "summary.ready", count: 0, day: 0, per_min_10m: 0 }], subscribes: ["gate.landed"] };
    MOCK.on(/^\/api\/machines(\?|$)/, (b) => { if (b && b.machines) b.machines.push(E === "E3" ? nm : fci); return b; });

    // ---- the page's layout: the map, and the details panel on its right ----
    const host = $("evmap-host"), row = document.createElement("div");
    row.className = "mk-evrow"; host.parentNode.insertBefore(row, host); row.appendChild(host);
    row.insertAdjacentHTML("beforeend", `<div class="panel mk-side" id="mk-side"></div>`);

    // ---- the map: the proposed machine dashed, its links new or gone, the rest shadowed ----
    MK.beforeRender = (nodes, edges) => {
      for (const n of nodes) if (n.id === NID) {
        n.cls = (n.cls || "") + " mk-proposed";
        n.sub = E === "E3" ? `unconfirmed · ${{ adhoc: "ad hoc", continuous: "continuous", external: "external" }[E3MODE]}` : E === "E2" ? "scheduled · daily" : "unconfirmed · continuous";
      }
      for (const e of edges) {
        if (e.target !== NID && e.source !== NID) continue;
        if (E === "E2" && REMOVED.some((t) => e.source.includes("ev:" + t))) { e.cls = (e.cls || "") + " mk-gone-edge"; e.dash = "2 6"; e.color = "#5b6272"; e.hoverColor = "#5b6272"; }
        else if (E === "E2" && ADDED.some((t) => e.source.includes("ev:" + t))) { e.cls = (e.cls || "") + " mk-add-edge"; e.color = "#86efac"; e.hoverColor = "#86efac"; e.width = 2; }
        else { e.cls = (e.cls || "") + " mk-guess-edge"; }
      }
      return { nodes, edges };
    };
    MK.afterRender = (graph, nodes, edges) => {
      const svg = d3.select("#evsvg-host svg");
      const me = svg.select(`g.ng-node[data-id="${NID}"]`);
      if (!me.empty()) {
        svgTag(me, E === "E3" ? -150 : -38, -36, E === "E3" ? "unconfirmed · added by you" : "unconfirmed", "mk-t-unconf");
        if (E === "E2") svgTag(me, -48, 66, "changed just now", "mk-t-chg");
      }
      if (E === "E2") for (const t of ADDED) svg.selectAll("g.ng-node").filter((n) => n.id.includes("ev:" + t)).each(function () {
        const g = d3.select(this), s = NetGraph.size(d3.select(this).datum()); svgRing(g, s, "mk-ring mk-ring-add"); svgTag(g, -s.w / 2, -s.h / 2 - 12, "+ new link", "mk-t-add"); });
      if (E === "E2") for (const t of REMOVED) svg.selectAll("g.ng-node").filter((n) => n.id.includes("ev:" + t)).each(function () {
        const g = d3.select(this), s = NetGraph.size(d3.select(this).datum()); svgTag(g, -s.w / 2, -s.h / 2 - 12, "− link removed", "mk-t-gone"); });
      if (E === "E3" || LAYOUT) return;
      // the neighbourhood: the machine, its event types and the machines on them at full colour;
      // the next ring (their other event types, the machines on those) lighter; the rest shadowed
      const adj = new Map(); const link = (a, b) => { (adj.get(a) || adj.set(a, new Set()).get(a)).add(b); };
      for (const e of edges) if (!e.toEdge && !(e.cls || "").includes("mk-gone-edge")) { link(e.source, e.target); link(e.target, e.source); }
      const ring = (set) => new Set([...set].flatMap((id) => [...(adj.get(id) || [])]));
      const h1 = ring(new Set([NID])), full = new Set([NID, ...h1, ...ring(h1)]);
      const mid = new Set([...ring(ring(full))].filter((id) => !full.has(id)));
      if (E === "E2") for (const t of REMOVED) nodes.filter((n) => n.id.includes("ev:" + t)).forEach((n) => full.add(n.id));
      svg.selectAll("g.ng-node").classed("ng-dim", (n) => !full.has(n.id) && !mid.has(n.id)).classed("mk-dim2", (n) => mid.has(n.id)).classed("mk-focus", (n) => n.id === NID);
      const lvl = (id) => (full.has(id) ? 2 : mid.has(id) ? 1 : 0);
      svg.selectAll("g.ng-edge").each(function (e) { const k = Math.min(lvl(e.source.id), lvl(e.target.id)); d3.select(this).classed("ng-dim", k === 0).classed("mk-dim2", k === 1); });
      svg.selectAll("g.ng-label").classed("ng-dim", true);
    };

    // ---- the cards: the proposed machine's card says so ----
    const cd = window.cards;
    window.cards = () => {
      cd();
      const card = document.querySelector(`#cards .panel[data-id="${who}"]`); if (!card) return;
      card.classList.add("mk-card");
      card.querySelector("h3").insertAdjacentHTML("beforeend", `<span class="mk-tag mk-t-unconf">unconfirmed</span><span class="muted" style="font-size:11.5px;font-weight:400">${E === "E3" ? "added by you" : "proposed by the Supervisor"}</span>`);
      if (E === "E2") card.querySelectorAll(".ty").forEach((c) => { const t = c.textContent.trim();
        if (REMOVED.includes(t)) c.classList.add("mk-chip-gone"); if (ADDED.includes(t)) c.classList.add("mk-chip-add"); });
      const grid = $("cards"); grid.insertBefore(card, grid.firstChild);
    };

    // ---- the details panel ----
    const chip = (t, st) => `<span class="ty ${st === "add" ? "mk-chip-add" : st === "gone" ? "mk-chip-gone" : ""}">${esc(t)}</span>${st === "add" ? '<span class="mk-tag mk-t-add">+ added just now</span>' : st === "gone" ? '<span class="mk-tag mk-t-gone">− removed</span>' : ""}`;
    const field = (label, html, cls = "") => `<div class="mk-f ${cls}"><div class="mk-fl">${label}</div><div class="mk-fv">${html}</div></div>`;
    const seg = (opts, on, cls = "") => `<span class="mk-seg ${cls}">${opts.map((o) => `<button class="${o === on ? "on" : ""}">${o}</button>`).join("")}</span>`;
    const box = (v, mono) => `<div class="mk-input ${mono ? "mono" : ""}">${v}</div>`;
    const dot = (id) => `<span class="dot mk-dashdot" style="--rc:${mcolor(id)}"></span>`;
    function universal() {
      const e2 = E === "E2";
      const steps = e2 ? ["At 00:00, read the day's tickets that reached <b>DONE</b> or <b>REJECTED</b> from the queue, and the merge gate's results (<span class=\"ty\">gate.rejected</span>, <span class=\"ty\">gate.landed</span>).",
          "For each rejection, read why: the reviewer's <span class=\"ty\">changes.requested</span>; for each gate failure, the failing unit and its log.",
          "Group the causes across the day; keep the evidence (tickets, review notes, gate logs).",
          "For each cause, come up with an idea that would remove it, and what it should do to Features.",
          "Send the ideas to the Coordinator as <span class=\"ty\">work.requested</span>, one per cause with its evidence, for it to schedule."]
        : ["On each settled session or task report, read the ticket's history: its review and its gate result.",
          "Say why it fell short, if it did: rejected in review, failed the gate, reopened.",
          "Group the causes across tickets; keep the evidence (tickets, gate logs).",
          "For a cause seen at least twice, write one proposal that would remove it.",
          "Publish it as <span class=\"ty\">work.requested</span>, with its evidence."];
      const receives = e2 ? [...ADDED.map((t) => chip(t, "add")), ...REMOVED.map((t) => chip(t, "gone"))].join("") : REMOVED.map((t) => chip(t) + '<span class="mk-tag mk-t-ghost">a guess</span>').join("");
      return `<div class="mk-head">${dot(FCI)}<b>feature-count-improver</b><span class="mk-tag mk-t-unconf">unconfirmed</span></div>
        <div class="mk-status"><span>proposed by the Supervisor · unconfirmed</span><span class="mk-acts"><button class="ctl mk-primary">confirm</button><button class="ctl">discard</button></span></div>
        ${e2 ? `<div class="mk-why muted">changed just now, from your messages: <i>"…watch the ticket queue for DONE and REJECTED tickets, and the Merge Gate…"</i> and <i>"…make this a scheduled task for 12am every day"</i></div>`
             : `<div class="mk-why muted">from your message: <i>"create a new Universal Machine called Feature Count Improver"</i> · the events it listens for are the Supervisor's guesses</div>`}
        <div class="mk-kindrow">${seg(["Universal", "Programmatic"], "Universal", "big")}<span class="muted">an AI agent: a prompt, its tools and its events</span></div>
        ${field("title", box("Feature Count Improver"))}
        ${field("description", box("Finds why tickets are rejected or fail the gate and proposes work to remove those causes"))}
        ${field("tags", '<span class="ty">features</span><span class="ty">feedback loop</span><span class="ty">delivery</span>')}
        ${field("engagement", seg(["ad hoc", "continuous", "scheduled"], e2 ? "scheduled" : "continuous") + (e2 ? ` <span class="mk-input mono inline">daily at 00:00</span><span class="mk-tag mk-t-chg">changed just now</span><div class="muted mk-was">was continuous: it woke on every <span class="ty">session.settled</span>, many a minute</div>` : ""))}
        <h4>Invariants</h4><ul class="mk-list"><li>never changes code itself; it proposes work</li><li>reads the Features series, never writes it</li><li>one proposal per cause, with evidence</li></ul>
        <h4>Steps ${e2 ? '<span class="mk-tag mk-t-chg">rewritten just now</span>' : ""}</h4><ol class="mk-list">${steps.map((x) => `<li>${x}</li>`).join("")}</ol>
        <h4>Receives</h4><div class="mk-chips">${receives}</div>
        <h4>Emits</h4><div class="mk-chips">${chip("work.requested")}<span class="muted">to the coordinator</span></div>
        <h4>Reads</h4><div class="mk-chips"><span class="ty mk-metric">Features</span><span class="muted">expected stock</span><span class="ty mk-metric">acceptance tests passing</span><span class="muted">stock, v15</span></div>
        <h4>Expected effect <span class="muted mk-h4note">a prediction, judged later</span></h4>
        <div class="mk-preds">
          <a class="mk-pred" href="/dynamics#s:features"><b>Features</b> <span class="up">↑</span><span class="muted">expected stock · no flow yet</span></a>
          <a class="mk-pred" href="/dynamics#f:tasks_gate_runs_total_landed"><b>DONE tickets</b> <span class="up">↑</span><span class="muted">flow: tasks gate runs · landed → DONE</span></a>
          <a class="mk-pred" href="/dynamics#f:tasks_ticket_transitions_total_worker_REJECTED_IN_PROGRESS"><b>gate rejections</b> <span class="down">↓</span><span class="muted">flow: tasks ticket transitions · REJECTED</span></a>
        </div>
        <div class="muted mk-foot">Recorded as <span class="ty">orchestra.prediction.made</span> when it is confirmed, and judged against the model once its horizon has passed. Ask the Supervisor to change any of this; confirm starts it under the agents' host. Until then nothing runs and nothing is published.</div>`;
    }
    function programmatic() {
      const tabs = seg(["ad hoc", "continuous", "external"], { adhoc: "ad hoc", continuous: "continuous", external: "external" }[E3MODE], "tabs");
      const body = {
        adhoc: `<div class="muted mk-tabnote">Orchestra runs the command once for each offer it accepts, and it exits.</div>
          ${field("command", box("python -m tools.nightly_metrics", true))}
          <h4>Invocation interface</h4>
          ${field("arguments", `<table class="dt mk-args"><tr><td class="num">--date YYYY-MM-DD</td><td>the day to summarise <span class="muted">(default: yesterday)</span></td></tr><tr><td class="num">--out DIR</td><td>where the summary is written <span class="muted">(default: reports/)</span></td></tr><tr><td class="num">--dry-run</td><td>say what it would publish; publish nothing</td></tr></table><button class="ctl mk-add">+ argument</button>`)}
          ${field("environment", `<table class="dt mk-args"><tr><td class="num">ORCHESTRA_REPO</td><td>the repository's root</td></tr><tr><td class="num">ORCHESTRA_MACHINE_LOG</td><td>where its log goes</td></tr><tr><td class="num">NIGHTLY_TZ</td><td><span class="mk-input mono inline">America/Los_Angeles</span></td></tr></table><button class="ctl mk-add">+ variable</button>`)}
          ${field("stdin", `${box("JSON of the offer")}<pre class="mk-eg">{"type": "summary.requested", "subject": "2026-10-31",
 "source": "coordinator/dispatch", "data": {…}}</pre>`)}
          ${field("exit", '<span class="muted">0: done · anything else: refused, with its stderr as the reason</span>')}`,
        continuous: `<div class="muted mk-tabnote">A daemon: <code>orchestra run</code> starts the command and keeps it running.</div>
          ${field("command", box("python -m tools.nightly_metrics --serve", true))}
          <h4>Daemon</h4>
          ${field("protocol", seg(["HTTP", "GraphQL", "gRPC", "other"], "HTTP"))}
          ${field("listens on", box("127.0.0.1:8130", true))}
          ${field("send events", box("POST /events", true) + '<div class="muted">it posts each event it publishes; Orchestra wraps it in the envelope</div>')}
          ${field("receive events", seg(["poll", "push"], "poll") + ` <span class="mk-input mono inline">getTasks()</span> every <span class="mk-input mono inline">10 s</span><div class="muted">push: Orchestra POSTs each event it listens for to <code>/inbox</code></div>`)}
          ${field("health", box("GET /health", true))}`,
        external: `<div class="muted mk-tabnote">Not managed by <code>orchestra run</code>: a continuous machine with no command; known only by its events.</div>
          ${field("source", box("nightly-metrics", true) + '<div class="muted">events whose CloudEvents <code>source</code> is <code>nightly-metrics</code> or <code>nightly-metrics/&lt;instance&gt;</code> are this machine</div>')}
          ${field("runs where", box("the analytics team's own service, outside this project"))}
          ${field("log", box("not readable: outside the repository and the state directory", false) + '<div class="muted">a log is read only within the project\'s repository or state directory</div>')}`,
      }[E3MODE];
      return `<div class="mk-head">${dot(NM)}<b>nightly-metrics</b><span class="mk-tag mk-t-unconf">unconfirmed</span></div>
        <div class="mk-status"><span>added by you · unconfirmed</span><span class="mk-acts"><button class="ctl mk-primary">confirm</button><button class="ctl">discard</button></span></div>
        <div class="mk-kindrow">${seg(["Universal", "Programmatic"], "Programmatic", "big")}<span class="muted">a program: a command and its interface</span></div>
        ${field("title", box("Nightly metrics"))}
        ${field("description", box("Summarises the day's landed tickets and gate results for the Coordinator's morning planning"))}
        ${field("tags", '<span class="ty">reporting</span><span class="ty">nightly</span>')}
        ${field("engagement", tabs)}
        <div class="mk-tabbody">${body}</div>
        <h4>Receives</h4><div class="mk-chips">${chip("gate.landed")}${E3MODE === "adhoc" ? chip("summary.requested") + '<span class="muted">its offer</span>' : ""}</div>
        <h4>Emits</h4><div class="mk-chips">${chip("summary.ready")}<span class="muted">nobody listens for it yet</span></div>
        <div class="muted mk-foot">Confirm adds it under <code>[[machines]]</code> through the Supervisor${E3MODE === "external" ? " (an external machine is only named there: nothing is started)" : ""}. It is a machine by what it publishes; until it publishes, the map shows what was declared.</div>`;
    }
    const side = () => { $("mk-side").innerHTML = E === "E3" ? programmatic() : universal(); };
    if (LAYOUT) { $("mk-side").innerHTML = ""; finish(15000); return; }
    side();
    setTimeout(() => { finish(1500); }, 6000);
  }
})();
