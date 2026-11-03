// The Machines page's frames E1–E4 (docs/proposals/intended-model.md §7): which machine each opens,
// the map as the mockups pinned it, and the structural checks run in the page. Used by
// render_intended.cjs, which renders them beside the Dynamics page's frames.
const fs = require("fs"), path = require("path");
const ROOT = path.resolve(__dirname, "../..");
const FRAMES = { E1: "feature_count_improver", E2: "feature_count_improver", E3: "nightly_metrics", "E3-continuous": "nightly_metrics",
  "E3-external": "nightly_metrics", E4: "sail" };

// the map as the mockups pinned it
function layout() {
  const lay = JSON.parse(JSON.parse(fs.readFileSync(path.join(ROOT, "mockups/fixtures/layouts.json"), "utf8"))["machines.events"]);
  const at = [["m:orchestra-host", -150, 40], ["m:planner", 60, 60], ["m:coordinator", 330, 300], ["m:supervisor", 60, 520], ["m:worker", 600, 60],
    ["m:reviewer", 600, 560], ["m:merge_gate", 330, 640], ["m:feature_count_improver", 935, 330], ["m:nightly_metrics", 930, 600], ["m:sail", 960, 330],
    ["ev:request.done", 200, 150], ["ev:request.refused", -80, 170], ["ev:ticket.created", 150, 300], ["ev:task.attention_needed", 170, 420],
    ["ev:group:ev:gate.conflict+ev:work.requested", 150, 470], ["ev:gate.conflict", 150, 470], ["ev:orchestra.prediction.judged", 330, 170],
    ["ev:task.assigned", 470, 330], ["ev:task.released", 470, 230], ["ev:review.requested", 620, 300], ["ev:review.approved", 480, 660],
    ["ev:gate.landed", 200, 600], ["ev:task.reported", 790, 120], ["ev:session.settled", 790, 220], ["ev:changes.requested", 790, 330],
    ["ev:gate.rejected", 790, 430], ["ev:work.requested", 560, 440], ["ev:work.improvement_proposed", 880, 530], ["ev:summary.requested", 790, 600],
    ["ev:summary.ready", 1000, 700]];
  for (const [id, x, y] of at) lay[id] = [x, y, 1];
  return JSON.stringify(lay);
}

// the structural checks: each returns a list of failures, run in the page. The wording is the page's
// since the owner's 2026-11-01 change (6e0e22e1, IntendedCore.machineWords): no "unconfirmed", a tag
// only for what is not observed ("proposed, never heard", "declared, never heard"); a declared value
// is shown beside the announced one ("declared continuous · observed …", 8dcd3ff4), not as pills.
const CHECKS = {
  common: (id) => {
    const f = [], side = document.getElementById("im-side"), q = (s) => side.querySelector(s);
    if (!document.getElementById("im-row").classList.contains("open")) f.push("the panel is not open");
    if (side.querySelector("input, textarea, select")) f.push("the panel has an input: every field is read-only");
    // a way to ask the machine that listens for requests: an "ask …" line, or, where the kind switch is
    // offered, the switch and confirm / discard themselves (8dcd3ff4 drops the footer's ask line there)
    if (!side.querySelector(".im-ask, .im-seg button, .im-acts button")) f.push("no 'ask' affordance");
    const node = document.querySelector(`#evsvg-host g.ng-node[data-id="m:${id}"]`);
    if (!node) f.push(`no node m:${id}`); else if (node.matches(".ng-dim,.ng-shade1,.ng-shade2")) f.push("the open machine is shaded");
    const card = document.querySelector("#cards .panel");
    if (!card || card.dataset.id !== id) f.push(`its card is not first (${card && card.dataset.id})`);
    if (!q(".im-head") || !q(".im-id")) f.push("no panel head");
    return f;
  },
  shades: () => {
    const f = [], n = (c) => document.querySelectorAll(`#evsvg-host g.ng-node.${c}`).length;
    if (!n("ng-shade1")) f.push("no node at .7 (one hop)"); if (!n("ng-shade2")) f.push("no node at .45 (two hops)"); if (!n("ng-dim")) f.push("nothing dimmed");
    const op = (sel) => { const e = document.querySelector(sel); return e ? +getComputedStyle(e).opacity : null; };
    if (op("#evsvg-host g.ng-node.ng-shade1") !== 0.7) f.push("one hop is not at .7");
    if (op("#evsvg-host g.ng-node.ng-shade2") !== 0.45) f.push("two hops are not at .45");
    return f;
  },
  E1: () => {
    const f = [], side = document.getElementById("im-side"), t = side.textContent;
    for (const s of ["Feature Count Improver", "proposed, never heard", "proposed by the Supervisor", "create a new Universal Machine", "Invariants", "Steps", "Uses",
      "Expected effect", "waits for a series", "nobody listens for it yet", "horizon 7 days"]) if (!t.includes(s)) f.push(`panel lacks "${s}"`);
    if (side.querySelectorAll(".im-acts button").length !== 2) f.push("no confirm / discard");
    if ((side.querySelector(".im-seg button.on") || {}).textContent !== "Universal") f.push("kind is not Universal");
    const on = [...side.querySelectorAll(".im-decl-val b")].map((e) => e.textContent);
    if (!on.includes("orchestra") || !on.includes("continuous")) f.push(`declared values: ${on}`);
    if ([...side.querySelectorAll(".im-tag")].filter((e) => e.textContent === "a guess").length !== 2) f.push("not two guesses");
    const steps = [...side.querySelectorAll("h4")].find((h) => h.textContent.startsWith("Steps"));
    if (!steps || !steps.nextElementSibling || steps.nextElementSibling.querySelectorAll("li").length !== 5) f.push("not five steps");
    if (side.querySelectorAll(".im-pred").length !== 4) f.push("not four expected-effect rows");
    const node = document.querySelector('g.ng-node[data-id="m:feature_count_improver"]');
    if (!node || !node.classList.contains("im-proposed") || !node.textContent.includes("proposed, never heard")) f.push("node not drawn proposed, never heard");
    const ev = document.querySelector('g.ng-node[data-id="ev:work.improvement_proposed"]');
    if (!ev) f.push("its declared event type is not drawn"); else { if (!ev.textContent.includes("declared")) f.push("its event type is not tagged declared"); if (ev.matches(".ng-dim,.ng-shade1,.ng-shade2")) f.push("its event type is shaded"); }
    const card = document.querySelector('#cards .panel[data-id="feature_count_improver"]');
    if (!card || !card.classList.contains("im-card") || !card.textContent.includes("proposed, never heard")) f.push("card lacks the 'proposed, never heard' tag");
    return f;
  },
  E2: () => {
    const f = [], side = document.getElementById("im-side"), t = side.textContent;
    for (const s of ["changed just now", "was continuous", "rewritten just now", "daily at 00:00", "America/Los_Angeles", "+ added just now", "− removed"])
      if (!t.includes(s)) f.push(`panel lacks "${s}"`);
    if (document.querySelectorAll("g.ng-edge.im-gone-edge").length !== 2) f.push(`gone links: ${document.querySelectorAll("g.ng-edge.im-gone-edge").length}`);
    if (document.querySelectorAll("g.ng-edge.im-add-edge").length < 3) f.push("fewer than three new links");
    const tags = [...document.querySelectorAll("#evsvg-host .ng-tag")].map((e) => e.textContent);
    if (tags.filter((x) => x === "+ new link").length < 2) f.push("no '+ new link' tags"); if (tags.filter((x) => x === "− link removed").length < 1) f.push("no '− link removed' tag");
    if (!tags.includes("changed just now")) f.push("node lacks 'changed just now'");
    for (const ty of ["session.settled", "task.reported"]) { const n = [...document.querySelectorAll("#evsvg-host g.ng-node")].find((g) => g.textContent.includes(ty));
      if (n && n.matches(".ng-dim,.ng-shade1,.ng-shade2")) f.push(`removed link's ${ty} is shaded`); }
    if (!document.querySelector('#cards .panel[data-id="feature_count_improver"] .im-chip-gone')) f.push("card lacks the removed chips");
    return f;
  },
  E3: (id, mode) => {
    const f = [], side = document.getElementById("im-side"), t = side.textContent;
    for (const s of ["Nightly metrics", "added by owner (quoted), per supervisor", "Declared as engaged"]) if (!t.includes(s)) f.push(`panel lacks "${s}"`);
    if ((side.querySelector(".im-seg button.on") || {}).textContent !== "Programmatic") f.push("kind is not Programmatic");
    const on = [...side.querySelectorAll(".im-decl-val b")].map((e) => e.textContent), label = (s) => [...side.querySelectorAll(".im-tabbody .im-fl")].some((e) => e.textContent === s);
    const want = { adhoc: ["orchestra", "ad hoc"], continuous: ["orchestra", "continuous"], external: ["external", "continuous"] }[mode];
    for (const w of want) if (!on.includes(w)) f.push(`not declared ${w} (${on})`);
    const fields = { adhoc: ["command", "arguments", "environment", "stdin", "exit"], continuous: ["command", "protocol", "listens on", "send", "receive", "health"], external: ["source", "runs where", "log"] }[mode];
    for (const s of fields) if (!label(s)) f.push(`no ${s} row`);
    if (mode === "external" && label("command")) f.push("an external machine shows a command");
    if (mode === "adhoc" && [...side.querySelectorAll(".im-ask")].filter((e) => e.textContent.includes("add one")).length !== 2) f.push("not two 'ask … to add one'");
    if (!document.querySelector('g.ng-node[data-id="m:nightly_metrics"].im-proposed')) f.push("node not unconfirmed");
    return f;
  },
  E4: () => {
    const f = [], side = document.getElementById("im-side"), t = side.textContent;
    for (const s of ["SAIL", "declared, never heard", "confirmed by owner (quoted), per supervisor", "none heard on the bus", "Measured by", "company_prom", "runner-3", "Flows (guessed from timing)", "not readable"])
      if (!t.includes(s)) f.push(`panel lacks "${s}"`);
    if (side.querySelectorAll("table.im-meas tr").length !== 4) f.push("the measured table has not three rows");
    const node = document.querySelector('g.ng-node[data-id="m:sail"]');
    if (!node || !node.classList.contains("im-unheard")) f.push("node is not the outline"); else if (node.querySelector(".ng-halo")) f.push("node has a halo");
    if ([...document.querySelectorAll("#evsvg-host g.ng-edge")].some((e) => (e.dataset.id || "").includes("m:sail"))) f.push("node has links");
    if (!node || !node.textContent.includes("declared · measured")) f.push("node not tagged 'declared · measured'");
    const card = document.querySelector('#cards .panel[data-id="sail"]'), ct = card ? card.textContent : "";
    for (const s of ["never heard · measured by 1 instrument · 3 instances (last hour)", "last measured", "measured ×3", "declared, never heard"]) if (!ct.includes(s)) f.push(`card lacks "${s}"`);
    if (!document.querySelector("#evsvg-host g.ng-node.ng-dim")) f.push("the rest is not shadowed");
    return f;
  },
};
const checksOf = (frame) => frame === "E1" ? [CHECKS.E1, CHECKS.shades] : frame === "E2" ? [CHECKS.E2, CHECKS.shades] : frame === "E4" ? [CHECKS.E4] : [CHECKS.E3];

module.exports = { FRAMES, layout, CHECKS, checksOf };
