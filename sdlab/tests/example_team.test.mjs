// Run with: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const { simulate, leverage, flowRates } = require("../sdlab/static/sim.js");
const team = () => JSON.parse(readFileSync(new URL("../sdlab/examples/team.json", import.meta.url)));

test("the Team's throughput grows as its staff grows", () => {
  const { series } = simulate(team());
  const staff = series.levels.staff, work = series.rates.work;
  assert.equal(work[0], 0, "no staff, nothing done");
  for (let i = 0; i < series.t.length; i++) {
    assert.ok(work[i] <= staff[i] + 1e-9, `week ${i}: ${work[i]} done with ${staff[i]} staff`);
    if (series.levels.backlog[i] > 5) assert.ok(series.busy.team[i] > 0.99 || staff[i] === 0, `week ${i}: team idle with a backlog`);
  }
  const at = (n) => staff.findIndex((s) => s >= n);
  assert.ok(at(3) > 0 && at(12) > at(3), "staff grows");
  assert.ok(work[at(12)] > 3 * work[at(3)], `${work[at(3)]} at 3 staff, ${work[at(12)]} at 12`);
});

test("capacity is per person: the same backlog goes twice as fast with twice the staff", () => {
  const m = team(), rate = (staff) => flowRates(m, { backlog: 100, done: 0, training: 0, staff, left: 0 }, 0.25).rate.work;
  assert.equal(rate(0), 0);
  assert.ok(Math.abs(rate(5) - 5) < 1e-9 && Math.abs(rate(10) - 10) < 1e-9, `${rate(5)}, ${rate(10)}`);
  const trainees = flowRates(m, { backlog: 100, done: 0, training: 4, staff: 10, left: 0 }, 0.25).rate.work;
  assert.ok(Math.abs(trainees - 8.5) < 1e-9, `four recruits in training: ${trainees}`);
});

test("recruits slow the team, the team overshoots, and the goal is just missed", () => {
  const { series, summary } = simulate(team());
  const staff = series.levels.staff, last = staff.length - 1;
  assert.ok(Math.max(...series.levels.training) > 4);
  assert.ok(staff[last] > 10 * 1.3, `${staff[last]} staff for 10 items a week`);
  const done = summary.targets.find((t) => t.stock === "done");
  assert.equal(done.met, false);
  assert.ok(done.atBy > 0.8 * done.goal);
  const lev = leverage(team());
  assert.deepEqual(lev.goals, ["done"]);
  const score = Object.fromEntries(lev.rows.map((r) => [r.flow, r.score]));
  assert.ok(score.work > score.hire && score.hire > 0 && score.leave < 0, JSON.stringify(score));
});
