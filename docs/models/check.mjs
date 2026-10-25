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

const pct = (x) => `${Math.round(x * 100)}%`;
const weekEmpty = (X) => { const i = X.series.levels.budget.findIndex((v) => v < 5); return i < 0 ? "never" : Math.round(i / 40); };
const f1 = (x) => (Math.abs(x) >= 10 ? x.toFixed(0) : x.toFixed(2));

// Story 1: agents that learn
{
  const S = "story-1-simple-task", V = (v) => sims[`${S}/${v}`], mod = (v) => models[`${S}/${v}`];
  const D = V("designed"), M = V("manual"), NL = V("no-learning"), SU = V("surge"), SP = V("surge-protected"), BT = V("blind-trust");
  const WEEK = 40;
  const at = (X, id, i) => X.series.levels[id][Math.min(i, X.n)];
  const backlog = (X, i) => ["t_asks", "t_scoped", "t_ticket_draft", "t_open"].reduce((a, id) => a + at(X, id, i), 0);
  const delivered = (X) => X.end("t_landed_recent") + X.end("t_delivered") + X.end("t_latent") + X.end("t_bugs");
  const badShare = (X, i) => { const r = X.series.rates, ok = r.t_ok[i], fl = r.t_flaw[i], fa = r.t_fail[i]; return (fl + fa) / Math.max(1e-9, ok + fl + fa); };
  const avgBad = (X, from, to) => { let a = 0, n = 0; for (let i = from; i <= to; i++) { a += badShare(X, i); n++; } return a / n; };
  const early = (X) => avgBad(X, 2 * WEEK, 4 * WEEK), late = (X) => avgBad(X, X.n - 4 * WEEK, X.n);
  const bugsPer100 = (X) => 100 * (X.end("t_bugs") + X.end("t_latent")) / Math.max(1e-9, delivered(X));

  check("1.1", S, "validity", "Manual reproduces today: I am fully busy and the backlog keeps growing",
        M.mach.me.avgBusy > 0.95 && backlog(M, M.n) > backlog(M, 0) + 20,
        `busy ${(M.mach.me.avgBusy * 100).toFixed(0)}%, backlog ${f1(backlog(M, 0))} → ${f1(backlog(M, M.n))} in 26 weeks, ${f1(delivered(M))} delivered`);
  check("1.2", S, "requirement", "Designed: learning beats decay: the playbook at least doubles and fewer attempts go wrong",
        D.end("t_playbook") >= 2 * at(D, "t_playbook", 0) && late(D) < early(D),
        `playbook ${f1(at(D, "t_playbook", 0))} → ${f1(D.end("t_playbook"))} entries; attempts failing or flawed ${pct(early(D))} (weeks 2–4) → ${pct(late(D))} (last 4 weeks)`);
  check("1.3", S, "info", "Without learning: the playbook rots, more attempts go wrong, debt grows, and the budget runs out sooner", null,
        `playbook → ${f1(NL.end("t_playbook"))}; going wrong ${pct(late(NL))} vs ${pct(late(D))}; debt ${f1(NL.end("t_debt"))} vs ${f1(D.end("t_debt"))}; budget empty from week ${weekEmpty(NL)} vs ${weekEmpty(D)}; delivered ${f1(delivered(NL))} vs ${f1(delivered(D))}`);
  check("1.4", S, "requirement", "Under a surge of asks, the playbook keeps growing (no capability trap)",
        SU.end("t_playbook") >= at(SU, "t_playbook", 8 * WEEK),
        `surge: playbook peaks at ${f1(Math.max(...SU.series.levels.t_playbook))}, ends at ${f1(SU.end("t_playbook"))}; with lesson capture protected it ends at ${f1(SP.end("t_playbook"))}`);
  const myPer = D.hours("me") / Math.max(1e-9, delivered(D));
  check("1.5", S, "requirement", "Designed: at most one hour of my time per delivered task", myPer <= 1,
        `${f1(myPer)} h per delivered (manual ${f1(M.hours("me") / Math.max(1e-9, delivered(M)))} h); my busy share ${(D.mach.me.avgBusy * 100).toFixed(0)}%`);
  check("1.6", S, "requirement", "Escaped flaws stay under 5 per 100 delivered, even when I start out trusting blindly",
        bugsPer100(D) <= 5 && bugsPer100(BT) <= 5, `${f1(bugsPer100(D))} per 100 designed, ${f1(bugsPer100(BT))} with blind trust`);
  const tr = (X) => `${f1(at(X, "t_trust", 0))} → low ${f1(Math.min(...X.series.levels.t_trust))} → ${f1(X.end("t_trust"))}`;
  check("1.7", S, "info", "Trust: earned slowly, cut by late findings", null, `designed ${tr(D)}; blind trust ${tr(BT)}`);
  check("1.8", S, "requirement", "Designed: the backlog stays small for all 26 weeks", Math.max(...D.series.t.map((_, i) => backlog(D, i))) <= 10,
        `largest backlog ${f1(Math.max(...D.series.t.map((_, i) => backlog(D, i))))}; at the end ${f1(backlog(D, D.n))}`);
  const asksPerWeek = (X, i) => X.series.rates.t_ask[i] * WEEK;
  check("1.9", S, "info", "Success breeds demand until the budget binds (limits to growth)", null,
        `asks ${f1(asksPerWeek(D, 0))} → ${f1(asksPerWeek(D, D.n))} a week; requesters' confidence ${f1(at(D, "t_reputation", 0))} → ${f1(D.end("t_reputation"))}; budget empty from week ${weekEmpty(D)}`);
  check("1.10", S, "requirement", "At most $20 of agent work per delivered task", D.spent / Math.max(1e-9, delivered(D)) <= 20,
        `$${f1(D.spent / Math.max(1e-9, delivered(D)))} per delivered`);
  const wipIds = mod("designed").stocks.filter((x) => ["requests", "attempts", "changes", "PRs"].includes(x.unit) && !x.final &&
    !["t_landed_recent", "t_latent", "t_asks"].includes(x.id)).map((x) => x.id);
  const cyc = (X) => wipIds.reduce((a, id) => a + X.avg(id), 0) / Math.max(1e-9, (X.end("t_landed_recent") + X.end("t_delivered")) / X.H);
  check("1.11", S, "requirement", "Designed: ticket to landed within 4 working days (Little's law over 26 weeks)", cyc(D) <= 32,
        `mean ${f1(cyc(D) / 8)} days (manual ${f1(cyc(M) / 8)} days)`);
}

// Story 2: production commands, made rarer and safer
{
  const S = "story-2-prod-command", V = (v) => sims[`${S}/${v}`];
  const D = V("designed"), M = V("manual"), T = V("manual-thorough"), NR = V("no-runbooks"), NE = V("no-evidence");
  const run = models[`${S}/designed`].flows.find((f) => f.id === "p_run");
  const allRunsByMe = Object.entries(models).filter(([k]) => k.startsWith(S) || k.startsWith("desk"))
    .every(([, m]) => { const f = m.flows.find((g) => g.id === "p_run"); return !f || f.machine === "me"; });
  check("2.1", S, "validity", "Structural: only I run production commands, in every variant", run.machine === "me" && allRunsByMe, "p_run machine = me everywhere");
  const total = (X, id, from = 0, to = X.n) => X.series.rates[id].slice(from, to + 1).reduce((a, b) => a + b, 0);
  const per = (X) => X.hours("me") / Math.max(1e-9, total(X, "p_decide"));
  check("2.2", S, "requirement", "Full due diligence costs me under a quarter of doing it all myself",
        per(D) <= 0.25 * per(T), `${f1(per(D))} h per request vs ${f1(per(T))} h doing it all myself (today's shortcut ${f1(per(M))} h)`);
  const wk = (X, id, i) => X.series.rates[id][i] * 40;
  check("2.3", S, "requirement", "Prevention bends the curve: by week 26 requests run at most 75% of what they would without it",
        wk(D, "p_ask", D.n) <= 0.75 * wk(M, "p_ask", M.n),
        `${f1(wk(D, "p_ask", D.n))} a week vs ${f1(wk(M, "p_ask", M.n))} without prevention (started at ${f1(wk(D, "p_ask", 0))}); ${f1(D.end("p_policies"))} preventions in force`);
  const incShare = (X) => { const from = X.n - 320; const i = total(X, "p_incident", from), c = total(X, "p_clean", from); return i / Math.max(1e-9, i + c); };
  check("2.4", S, "requirement", "Commands causing incidents: under 5% over the last 8 weeks", incShare(D) <= 0.05,
        `${pct(incShare(D))} designed; ${pct(incShare(NR))} without runbook updates; ${pct(incShare(M))} today`);
  check("2.5", S, "requirement", "No repeat in another environment is left to come back as a surprise",
        D.end("p_followups") < 0.5 && total(D, "p_surprise") < 1,
        `${f1(total(D, "p_surprise"))} surprises designed vs ${f1(total(M, "p_surprise"))} today; ${f1(M.end("p_followups"))} unfiled at the end today`);
  check("2.6", S, "info", "Evidence speeds adoption; runbooks learn against decay; requesters learn the process", null,
        `preventions in force ${f1(D.end("p_policies"))} vs ${f1(NE.end("p_policies"))} without evidence; runbook coverage ${f1(D.end("p_runbooks"))} vs ${f1(NR.end("p_runbooks"))} without updates (${f1(M.end("p_runbooks"))} today); compliance 30 → ${f1(D.end("p_compliance"))}`);
}

// Story 3: being the one who knows
{
  const S = "story-3-status-request", V = (v) => sims[`${S}/${v}`];
  const D = V("designed"), M = V("manual"), NN = V("no-nudges"), NG = V("nagging");
  const total = (X, id) => X.series.rates[id].reduce((a, b) => a + b, 0);
  const items = (X) => X.avg("s_current") + X.avg("s_stale");
  check("3.1", S, "validity", "Manual reproduces the spiral: confidence falls, questions multiply, I am nearly always busy",
        M.end("s_confidence") < 25 && M.series.rates.s_ask[M.n] > 3 * M.series.rates.s_ask[0] && M.mach.me.avgBusy > 0.9,
        `confidence 50 → ${f1(M.end("s_confidence"))}; questions ${f1(M.series.rates.s_ask[0] * 40)} → ${f1(M.series.rates.s_ask[M.n] * 40)} a week; busy ${pct(M.mach.me.avgBusy)}`);
  check("3.2", S, "requirement", "The status page stays current: under 10% of items stale on average",
        D.avg("s_stale") <= 0.1 * items(D), `${pct(D.avg("s_stale") / items(D))} stale (today ${pct(M.avg("s_stale") / items(M))})`);
  const perAnswer = (X) => X.hours("me") / Math.max(1e-9, total(X, "s_answer"));
  check("3.3", S, "requirement", "An answer costs me at most 15 minutes, including corrections and firefights", perAnswer(D) <= 0.25,
        `${f1(perAnswer(D))} h per answer (today ${f1(perAnswer(M))} h)`);
  check("3.4", S, "requirement", "My manager's confidence ends higher than it started, and questions do not multiply",
        D.end("s_confidence") > 50 && D.series.rates.s_ask[D.n] <= 1.25 * D.series.rates.s_ask[0],
        `confidence 50 → ${f1(D.end("s_confidence"))}; questions ${f1(D.series.rates.s_ask[0] * 40)} → ${f1(D.series.rates.s_ask[D.n] * 40)} a week`);
  const firstShare = (X) => { const n = total(X, "s_notice"), f = total(X, "s_found_first"); return n / Math.max(1e-9, n + f); };
  check("3.5", S, "requirement", "I learn of at least 85% of blocked projects before my manager does", firstShare(D) >= 0.85,
        `${pct(firstShare(D))} (today ${pct(firstShare(M))})`);
  check("3.6", S, "info", "Nudging: none lets sources rot; too much wears out patience and they rot anyway (fixes that fail)", null,
        `source hygiene at week 26: designed ${f1(D.end("s_hygiene"))}, no nudges ${f1(NN.end("s_hygiene"))}, nagging ${f1(NG.end("s_hygiene"))}; patience: designed ${f1(D.end("s_patience"))}, nagging ${f1(NG.end("s_patience"))}`);
}

// Story 4: reviewing teammates' PRs
{
  const S = "story-4-reviews-given", V = (v) => sims[`${S}/${v}`];
  const D = V("designed"), M = V("manual"), Q = V("comment-quota"), NL = V("no-agent-learning");
  const total = (X, id, from = 0) => X.series.rates[id].slice(from).reduce((a, b) => a + b, 0);
  const reviews = (X) => total(X, "r_review_clean") + total(X, "r_review_flawed");
  const missShare = (X) => { const from = X.n - 320, c = total(X, "r_catch", from), m = total(X, "r_miss", from); return m / Math.max(1e-9, c + m); };
  const perReview = (X) => X.hours("me") / Math.max(1e-9, reviews(X));
  check("4.1", S, "requirement", "A review costs me at most half an hour, brief included", perReview(D) <= 0.5,
        `${f1(perReview(D))} h per review (today ${f1(perReview(M))} h)`);
  check("4.2", S, "requirement", "I miss at most 15% of real defects over the last 8 weeks", missShare(D) <= 0.15,
        `${pct(missShare(D))} missed (today ${pct(missShare(M))}; agent not learning ${pct(missShare(NL))})`);
  const comments = (X) => (total(X, "r_catch") + total(X, "r_nit")) / (X.H / 40);
  check("4.3", S, "requirement", "At least 8 review comments a week, most of them substantive", comments(D) >= 8 && total(D, "r_catch") >= total(D, "r_nit"),
        `${f1(comments(D))} a week; substantive ${f1(total(D, "r_catch") / (D.H / 40))}, nitpicks ${f1(total(D, "r_nit") / (D.H / 40))}`);
  check("4.4", S, "info", "A comment quota hits the count and spends goodwill (Goodhart)", null,
        `comments ${f1(comments(Q))} a week vs ${f1(comments(D))}; goodwill at week 26 ${f1(Q.end("r_goodwill"))} vs ${f1(D.end("r_goodwill"))}`);
  check("4.5", S, "info", "The agent's map of the code, the team's skill, and my reputation", null,
        `map ${f1(D.end("r_knowledge"))} vs ${f1(M.end("r_knowledge"))} today; team skill ${f1(D.end("r_skill"))} vs ${f1(M.end("r_skill"))}; reputation ${f1(D.end("r_reputation"))} vs ${f1(M.end("r_reputation"))}`);
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
  const noRec = clone(mD);
  for (const id of ["r_ask_clean", "r_ask_flawed"]) noRec.flows.find((f) => f.id === id).rate = { form: "constant", value: 0 };
  const NR = measure(noRec);
  const waitDays = (X) => (X.avg("t_review_sound") + X.avg("t_review_flawed")) / Math.max(1e-9, (X.series.rates.t_rev_ok.reduce((a, b) => a + b, 0) + X.series.rates.t_rev_catch.reduce((a, b) => a + b, 0) + X.series.rates.t_rev_miss.reduce((a, b) => a + b, 0)) / X.H) / 8;
  check("D.5", "desk", "info", "Coupling: reviews I give shorten the wait for reviews of my PRs (reciprocity)", null,
        `my PRs wait ${f1(waitDays(D))} days in human review with reviews given vs ${f1(waitDays(NR))} without; delivered ${f1(D.end("t_delivered"))} vs ${f1(NR.end("t_delivered"))} (the budget, not review, limits deliveries)`);
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
