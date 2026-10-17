// Run with: node --test tests/example_milling.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const { simulate, leverage } = require("../sdlab/static/sim.js");
const milling = () => JSON.parse(readFileSync(new URL("../sdlab/examples/milling.json", import.meta.url)));

test("milling starts slow with one bit and speeds up as bits arrive", () => {
  const { series } = simulate(milling());
  const mill = series.rates.mill, bits = series.levels.bits;
  assert.equal(bits[0], 1);
  assert.ok(mill[1] < 2, `milling at t=1 is ${mill[1]}`);
  assert.ok(mill[20] > mill[1] * 1.5, `milling at t=20 is ${mill[20]}`);
});

test("bits stay short, milling cannot keep up with arrivals, and the shipping goal is missed", () => {
  const { series, summary } = simulate(milling());
  const last = series.t.length - 1;
  assert.ok(series.levels.bits[last] < 5, `bits ${series.levels.bits[last]}`);
  assert.ok(series.rates.mill[last] < 3.8, `milling ${series.rates.mill[last]}`);
  assert.ok(series.levels.blanks[last] > series.levels.blanks[60]);
  assert.equal(summary.targets.find((t) => t.stock === "shipped").met, false);
});

test("the co-flow uses bits: with no deliveries the one bit wears out and milling stops", () => {
  const m = milling();
  m.flows.find((f) => f.id === "order").machine = null;
  const { series } = simulate(m);
  const last = series.t.length - 1;
  assert.ok(series.levels.bits[last] < 0.05, `bits ${series.levels.bits[last]}`);
  assert.ok(series.levels.shipped[last] <= 11, `shipped ${series.levels.shipped[last]}`);
});

test("a higher bit target lifts the effect and meets the goal", () => {
  const m = milling();
  m.flows.find((f) => f.id === "order").rate.goal = 8;
  const { summary } = simulate(m);
  assert.equal(summary.targets.find((t) => t.stock === "shipped").met, true);
});

test("leverage ranks the CNC and bit ordering above blank arrivals", () => {
  const { rows } = leverage(milling());
  const score = Object.fromEntries(rows.map((r) => [r.flow, r.score]));
  assert.equal(rows[0].flow, "mill");
  assert.ok(score.order > score.arrive && score.order > score.ship, JSON.stringify(score));
});
