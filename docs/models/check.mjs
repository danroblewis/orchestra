// Model-level acceptance tests for the user-story models.
//
//   node docs/models/check.mjs            (SD Lab at ~/orchestra/sdlab, or set SDLAB=<path>)
//
// Validates every model with SD Lab's own validator (sdlab.server.validate), simulates each
// variant with SD Lab's own simulator (sdlab/static/sim.js), assembles the desk model from the
// stories plus the declared couplings, and checks the acceptance properties in docs/user-stories.md.
// Nothing here changes SD Lab; it only reads it.

import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { HERE, leverage, read, clone, STORIES, applyVariant, desk, validateAll, measure, myQueue, sideOf } from "./lib.mjs";

// ---- the acceptance checks ----
const results = [];
// kind: "validity" (the model reproduces what is known, or a rule holds structurally: must pass),
//       "requirement" (a design target from docs/user-stories.md: may fail, and is then a design gap),
//       "info" (a finding the model reports; no pass or fail)
function check(id, story, kind, text, ok, detail) { results.push({ id, story, kind, text, ok: kind === "info" ? null : !!ok, detail }); }

const models = {};
const sims = {};
for (const s of STORIES) {
  const base = read(`${s}.json`), vars = read(`${s}.variants.json`);
  for (const v of ["designed", ...Object.keys(vars)]) {
    const m = applyVariant(base, vars, v);
    models[`${s}/${v}`] = m;
    sims[`${s}/${v}`] = measure(m);
  }
}
for (const v of ["designed", "manual"]) { models[`desk/${v}`] = desk(v); sims[`desk/${v}`] = measure(models[`desk/${v}`]); }

const errors = validateAll(models);

// EXPORT=<dir>: write every model and variant as its own SD Lab model file, to open in the editor
if (process.env.EXPORT) {
  for (const [key, m] of Object.entries(models)) {
    const [story, variant] = key.split("/");
    const id = `${story}-${variant}`;
    writeFileSync(join(process.env.EXPORT, `${id}.json`),
                  JSON.stringify({ ...m, id, name: `${m.name.replace(/ \(.*\)$/, "")} (${variant})` }, null, 1));
  }
}
for (const [k, errs] of Object.entries(errors)) check("V", k, "validity", "SD Lab's validator accepts the model", errs.length === 0, errs.join("; ") || "ok");

const f1 = (x) => (Math.abs(x) >= 10 ? x.toFixed(0) : x.toFixed(2));

// Story 1
{
  const S = "story-1-simple-task", D = sims[`${S}/designed`], M = sims[`${S}/manual`], R = sims[`${S}/rising`], MR = sims[`${S}/manual-rising`], B = sims[`${S}/better-first-pass`];
  const mD = models[`${S}/designed`], mM = models[`${S}/manual`];
  const arrivals = 0.15 * D.H;
  check("1.1", S, "validity", "Manual reproduces today: I am fully busy, work piles up waiting for me, few requests finish",
        M.mach.me.avgBusy > 0.95 && myQueue(mM, M, M.n) > myQueue(mM, M, 0) + 10 && M.end("t_delivered") < 0.3 * arrivals,
        `busy ${(M.mach.me.avgBusy * 100).toFixed(0)}%, waiting for me ${f1(myQueue(mM, M, 0))} → ${f1(myQueue(mM, M, M.n))}, ${f1(M.end("t_delivered"))} of ${f1(arrivals)} delivered`);
  check("1.2", S, "requirement", "Designed: nothing piles up waiting for me", myQueue(mD, D, D.n) <= 3,
        `waiting for me at the end: ${f1(myQueue(mD, D, D.n))}`);
  check("1.3", S, "requirement", "Designed: most requests are delivered within four weeks",
        D.end("t_delivered") >= 0.6 * arrivals, `${f1(D.end("t_delivered"))} delivered of ${f1(arrivals)} asked (manual: ${f1(M.end("t_delivered"))})`);
  const myPer = D.hours("me") / Math.max(1e-9, D.end("t_delivered"));
  check("1.4", S, "requirement", "Designed: at most one hour of my time per delivered request", myPer <= 1.0,
        `${f1(myPer)} h per delivered request (busy ${(D.mach.me.avgBusy * 100).toFixed(0)}% of my free time)`);
  check("1.5", S, "requirement", "Designed: at most $20 of agent work per delivered request",
        D.spent / Math.max(1e-9, D.end("t_delivered")) <= 20, `$${f1(D.spent / D.end("t_delivered"))} per delivered`);
  const ours = sideOf(mD, "ours"), co = sideOf(mD, "company"), itf = sideOf(mD, "interface");
  const wip = (X, ids) => ids.reduce((a, id) => a + X.avg(id), 0);
  const cycle = (X) => (wip(X, ours) + wip(X, co) + wip(X, itf)) / Math.max(1e-9, X.end("t_delivered") / X.H);
  const share = wip(D, co) / Math.max(1e-9, wip(D, ours) + wip(D, co) + wip(D, itf));
  check("1.6", S, "requirement", "Designed: started to merged within 4 working days (32 working hours, Little's law)",
        cycle(D) <= 32, `mean cycle ${f1(cycle(D))} working hours (${f1(cycle(D) / 8)} days); ${(share * 100).toFixed(0)}% of work in progress sits in company stocks`);
  check("1.6b", S, "info", "Fewer rounds at each boundary (better first pass): cost and cycle", null,
        `$${f1(B.spent / B.end("t_delivered"))} per delivered, cycle ${f1(cycle(B) / 8)} days, ${f1(B.end("t_delivered"))} delivered`);
  check("1.7", S, "requirement", "Requests rising to 10 a week: designed still keeps up; manual falls further behind",
        myQueue(mD, R, R.n) <= 4 && myQueue(mM, MR, MR.n) > myQueue(mM, M, M.n),
        `waiting for me: designed ${f1(myQueue(mD, R, R.n))}, manual ${f1(myQueue(mM, MR, MR.n))}; my busy ${(R.mach.me.avgBusy * 100).toFixed(0)}%`);
}

// Story 2
{
  const S = "story-2-prod-command", D = sims[`${S}/designed`], M = sims[`${S}/manual`], T = sims[`${S}/manual-thorough`];
  const run = models[`${S}/designed`].flows.find((f) => f.id === "p_run");
  const allRunsByMe = Object.entries(models).filter(([k]) => k.startsWith(S) || k.startsWith("desk"))
    .every(([, m]) => { const f = m.flows.find((g) => g.id === "p_run"); return !f || f.machine === "me"; });
  check("2.1", S, "validity", "Structural: only I run production commands, in every variant", run.machine === "me" && allRunsByMe, "p_run machine = me everywhere");
  const handled = (X) => X.end("p_declined") + X.end("p_candidates") + X.end("p_archived") + X.end("p_problem_statements") + X.end("p_in_review") + X.end("p_policies");
  const per = (X) => X.hours("me") / Math.max(1e-9, handled(X));
  check("2.2", S, "requirement", "Designed: full due diligence costs me under a quarter of doing it all myself",
        per(D) <= 0.25 * per(T), `${f1(per(D))} h per request vs ${f1(per(T))} h doing it all myself (today's shortcut: ${f1(per(M))} h)`);
  check("2.3", S, "requirement", "Designed: prevention is adopted, and requests become rarer",
        D.end("p_policies") >= 1 && D.rate("p_arrive")[D.n] < D.rate("p_arrive")[0],
        `${f1(D.end("p_policies"))} adopted in 12 weeks; arrivals ${f1(D.rate("p_arrive")[0] * 40)} → ${f1(D.rate("p_arrive")[D.n] * 40)} a week (today's shortcut adopts ${f1(M.end("p_policies"))})`);
  check("2.4", S, "requirement", "Designed: every repeat needed in other environments becomes a ticket",
        D.end("p_gov_followups") < 0.5 && D.end("p_gov_tickets") > 0, `${f1(D.end("p_gov_tickets"))} filed, ${f1(D.end("p_gov_followups"))} waiting (today: ${f1(M.end("p_gov_followups"))} never filed)`);
}

// Story 3
{
  const S = "story-3-status-request", D = sims[`${S}/designed`], M = sims[`${S}/manual`];
  const per = (X) => X.hours("me") / Math.max(1e-9, X.end("s_answered"));
  check("3.1", S, "requirement", "Designed: the status page stays current (at most 10 stale items)", D.avg("s_stale") <= 10,
        `mean stale ${f1(D.avg("s_stale"))} (manual ${f1(M.avg("s_stale"))})`);
  check("3.2", S, "requirement", "Designed: an answer costs me at most 15 minutes; manual at least an hour",
        per(D) <= 0.25 && per(M) >= 1.0, `${f1(per(D))} h vs ${f1(per(M))} h per answer`);
}

// Story 4
{
  const S = "story-4-reviews-given", D = sims[`${S}/designed`], M = sims[`${S}/manual`];
  check("4.1", S, "requirement", "Designed: review requests to me don't pile up", D.end("r_requests") + D.end("r_briefed") <= 2,
        `${f1(D.end("r_requests") + D.end("r_briefed"))} waiting (manual ${f1(M.end("r_requests") + M.end("r_briefed"))})`);
}

// The desk: every story together
{
  const D = sims["desk/designed"], M = sims["desk/manual"], mD = models["desk/designed"], mM = models["desk/manual"];
  check("D.1", "desk", "validity", "Manual desk reproduces today: fully busy, and work piles up waiting for me",
        M.mach.me.avgBusy > 0.95 && myQueue(mM, M, M.n) > myQueue(mM, M, 0) + 10,
        `busy ${(M.mach.me.avgBusy * 100).toFixed(0)}%, waiting for me ${f1(myQueue(mM, M, 0))} → ${f1(myQueue(mM, M, M.n))}`);
  check("D.2", "desk", "requirement", "Designed desk: everything fits in my free time, with slack",
        D.mach.me.avgBusy <= 0.8 && myQueue(mD, D, D.n) <= 5,
        `busy ${(D.mach.me.avgBusy * 100).toFixed(0)}% of my free time, waiting for me ${f1(myQueue(mD, D, D.n))}`);
  check("D.3", "desk", "validity", "Structural: agents can never spend more than the budget holds", D.min("budget") >= 0, `lowest balance $${f1(D.min("budget"))}`);
  const weekly = D.spent / (D.H / 40);
  check("D.4", "desk", "requirement", "Designed desk: agent work fits the $120 weekly share without drawing down savings",
        weekly <= 120, `$${f1(weekly)} a week wanted; balance $120 → $${f1(D.end("budget"))}`);
  const noRec = clone(mD); noRec.flows.find((f) => f.id === "r_arrive").rate.value = 0;
  const NR = measure(noRec);
  check("D.5", "desk", "info", "Coupling: reviews I give speed up reviews of my PRs (reciprocity)", null,
        `${f1(D.end("t_delivered"))} simple tasks delivered with reviews given vs ${f1(NR.end("t_delivered"))} without`);
}

// ---- report ----
const lev = leverage(models["desk/designed"], { goals: ["t_delivered"] });
const lev1 = leverage(models["story-1-simple-task/designed"], { goals: ["t_delivered"] });
const crossings = Object.fromEntries(STORIES.map((s) => [s, models[`${s}/designed`].flows.filter((f) => f.crosses).map((f) => `${f.id}: ${f.crosses}`)]));
const top = (L) => L.rows.slice(0, 8).map((r) => ({ flow: r.flow, pct: +(r.effect.t_delivered.pct * 100).toFixed(1) }));
const report = { results, leverage_desk: top(lev), leverage_story1: top(lev1), crossings };
writeFileSync(join(HERE, "results.json"), JSON.stringify(report, null, 1) + "\n");
const tag = (r) => (r.kind === "info" ? "INFO" : r.ok ? "PASS" : r.kind === "validity" ? "FAIL" : "GAP ");
for (const r of results) console.log(`${tag(r)}  ${r.id.padEnd(4)} ${r.story.padEnd(34)} ${r.text}\n      ${r.detail}`);
for (const [name, rows] of [["the desk", report.leverage_desk], ["story 1 alone", report.leverage_story1]]) {
  console.log(`\nLeverage on delivered simple tasks, ${name} (each flow 10% faster):`);
  for (const r of rows) console.log(`  ${r.flow.padEnd(18)} ${r.pct > 0 ? "+" : ""}${r.pct}%`);
}
const gaps = results.filter((r) => r.kind === "requirement" && !r.ok).length;
console.log(`\n${results.filter((r) => r.kind === "validity" && r.ok).length} validity checks pass; ${gaps} design gap(s).`);
process.exit(results.every((r) => r.kind !== "validity" || r.ok) ? 0 : 1);
