// Run with: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const { simulate } = require("../sdlab/static/sim.js");
const bakery = () => JSON.parse(readFileSync(new URL("../sdlab/examples/bakery.json", import.meta.url)));

test("one Baker on every flow is overloaded and misses the sales target", () => {
  const { summary } = simulate(bakery());
  const baker = summary.machines.find((m) => m.machine === "baker");
  assert.ok(baker.overloadedShare > 0.5, `baker overloaded only ${baker.overloadedShare}`);
  const sold = summary.targets.find((t) => t.stock === "sold");
  assert.equal(sold.met, false);
});

test("handing baking to an oven meets the target", () => {
  const m = bakery();
  m.machines.push({ id: "oven", name: "Oven", kind: "code", color: "#c2410c", capacity: 1 });
  m.flows.find((f) => f.id === "bake").machine = "oven";
  const { summary } = simulate(m);
  assert.equal(summary.targets.find((t) => t.stock === "sold").met, true);
});

test("a flow with no machine does not run, and stocks never go negative", () => {
  const m = bakery();
  m.flows.find((f) => f.id === "order").machine = null;
  const { series, summary } = simulate(m);
  assert.deepEqual(summary.unassigned, ["order"]);
  assert.ok(series.rates.order.every((r) => r === 0));
  for (const id of Object.keys(series.levels)) assert.ok(series.levels[id].every((v) => v >= 0), id);
});

test("material is conserved through a ratio", () => {
  const m = {
    dt: 0.5, horizon: 10,
    stocks: [{ id: "a", initial: 10 }, { id: "b", initial: 0 }],
    flows: [{ id: "f", from: "a", to: "b", ratio: 2, rate: { form: "constant", value: 1 }, machine: "environment" }],
    machines: [],
  };
  const { series } = simulate(m);
  const last = series.t.length - 1;
  assert.equal(series.levels.a[last] + 2 * series.levels.b[last], 10);
});

test("a flow with several outputs splits by its weights", () => {
  const m = {
    dt: 1, horizon: 1,
    stocks: [{ id: "a", initial: 10 }, { id: "b", initial: 0 }, { id: "c", initial: 0 }],
    flows: [{ id: "f", from: "a", to: "b", outputs: ["c"], split: { b: 3, c: 1 }, rate: { form: "constant", value: 4 }, machine: "environment" }],
    machines: [],
  };
  const { series } = simulate(m);
  assert.equal(series.levels.b[1], 3);
  assert.equal(series.levels.c[1], 1);
});

test("a busy machine shares its time fairly, and gives time a flow cannot use to the others", () => {
  const m = {
    dt: 1, horizon: 1,
    stocks: [{ id: "a", initial: 100 }, { id: "b", initial: 1 }, { id: "x", initial: 0 }, { id: "y", initial: 0 }],
    flows: [
      { id: "big", from: "a", to: "x", rate: { form: "available" }, work: 1, machine: "w" },
      { id: "small", from: "b", to: "y", rate: { form: "available" }, work: 1, machine: "w" },
    ],
    machines: [{ id: "w", capacity: 10 }],
  };
  const { rate, busy } = fit_free_rates(m);
  assert.equal(rate.small, 1);        // it only has 1 to take
  assert.equal(rate.big, 9);          // so the rest of the machine's time goes here
  assert.equal(busy.w, 1);
});
function fit_free_rates(m) {
  const { flowRates } = require("../sdlab/static/sim.js");
  return flowRates(m, { a: 100, b: 1, x: 0, y: 0 }, 1);
}

test("fitting recovers a coefficient from a run that followed it", () => {
  const { fit } = require("../sdlab/static/sim.js");
  const truth = {
    dt: 1, horizon: 60,
    stocks: [{ id: "s", initial: 0 }, { id: "gone", initial: 0 }],
    flows: [
      { id: "in", from: null, to: "s", rate: { form: "constant", value: 5 }, machine: "environment" },
      { id: "out", from: "s", to: "gone", rate: { form: "proportional", stock: "s", k: 0.2 }, machine: "environment" },
    ],
    machines: [],
  };
  const run = simulate(truth, { fromZero: true }).series;
  const guess = JSON.parse(JSON.stringify(truth));
  guess.flows[1].rate.k = 0.9;                       // a wrong belief about the outflow
  const rows = fit(guess, run);
  const out = rows.find((r) => r.flow === "out");
  assert.equal(out.change, true);
  assert.equal(out.proposed.rate.form, "proportional");
  assert.ok(Math.abs(out.proposed.rate.k - 0.2) < 0.01, `fitted k ${out.proposed.rate.k}`);
  assert.equal(rows.find((r) => r.flow === "in").change, false);   // the right equation is kept
});

test("an effect slows a flow as the stock it depends on runs low", () => {
  const { flowRates } = require("../sdlab/static/sim.js");
  const m = {
    stocks: [{ id: "blanks" }, { id: "parts" }, { id: "bits" }],
    flows: [{ id: "mill", from: "blanks", to: "parts", rate: { form: "available" }, work: 1, machine: "cnc",
              effects: [{ stock: "bits", shape: "linear", normal: 10 }] }],
    machines: [{ id: "cnc", capacity: 4 }],
  };
  assert.equal(flowRates(m, { blanks: 100, parts: 0, bits: 10 }, 1).rate.mill, 4);   // full bits: full speed
  assert.equal(flowRates(m, { blanks: 100, parts: 0, bits: 5 }, 1).rate.mill, 2);    // half the bits: half speed
  const table = { ...m, flows: [{ ...m.flows[0], effects: [{ stock: "bits", shape: "table", points: [[0, 0], [2, 0.5], [10, 1]] }] }] };
  assert.equal(flowRates(table, { blanks: 100, parts: 0, bits: 1 }, 1).rate.mill, 1); // 0.25 of 4
});

test("a co-flow uses up another stock and stops when it runs out", () => {
  const m = {
    dt: 1, horizon: 10,
    stocks: [{ id: "blanks", initial: 100 }, { id: "parts", initial: 0 }, { id: "bits", initial: 0.5 }],
    flows: [{ id: "mill", from: "blanks", to: "parts", rate: { form: "constant", value: 10 }, machine: "environment", uses: [{ stock: "bits", per: 0.01 }] }],
    machines: [],
  };
  const { series } = simulate(m);
  const last = series.t.length - 1;
  assert.ok(Math.abs(series.levels.parts[last] - 50) < 1e-6, `parts ${series.levels.parts[last]}`);   // 0.5 bits / 0.01 = 50 parts
  assert.equal(series.levels.bits[last], 0);
});

test("a machine's capacity can be per unit of a stock", () => {
  const { flowRates } = require("../sdlab/static/sim.js");
  const m = {
    stocks: [{ id: "todo" }, { id: "done" }, { id: "staff" }],
    flows: [{ id: "work", from: "todo", to: "done", rate: { form: "available" }, work: 1, machine: "team" }],
    machines: [{ id: "team", capacity: 2, capacity_stock: "staff" }],
  };
  assert.equal(flowRates(m, { todo: 100, done: 0, staff: 3 }, 1).rate.work, 6);
});

test("leverage ranks the flow that limits the goal first", () => {
  const { leverage } = require("../sdlab/static/sim.js");
  const bakery = JSON.parse(readFileSync(new URL("../sdlab/examples/bakery.json", import.meta.url)));
  const r = leverage(bakery);
  assert.deepEqual(r.goals, ["sold"]);
  assert.ok(r.rows[0].effect.sold.change > 0);
  assert.ok(["mix", "bake"].includes(r.rows[0].flow), `top: ${r.rows[0].flow}`);
});
