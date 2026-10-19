// The editor's simulator runs the engine features of 2026-10-18 (MODEL.md): measured inputs and ceilings.
// Run with: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { simulate, inputValue } = require("../sdlab/static/sim.js");

const tank = (extra) => ({
  stocks: [{ id: "T", initial: 0, ...(extra.stock || {}) }],
  flows: [
    { id: "in", from: null, to: "T", rate: { form: "proportional", stock: "pump", k: 2 }, machine: "environment" },
    { id: "out", from: "T", to: null, rate: { form: "proportional", stock: "T", k: 0.1 }, machine: "environment" },
  ],
  machines: [], dt: 0.25, horizon: 200, ...(extra.model || {}),
});

test("input values follow the engine's terms and series", () => {
  const spec = { values: [1, 2], terms: [{ fn: "step", height: 3, start: 5 }, { fn: "pulse", height: 10, start: 2, width: 1 }] };
  assert.deepEqual([0, 1, 2, 3, 4, 5].map((t) => inputValue(spec, t)), [1, 12, 2, 2, 5, 5]);
});

test("a rate reads a measured input; without the input it reads 0", () => {
  const withPump = simulate(tank({ model: { inputs: { pump: { values: [5] } } } })).series.levels.T;
  assert.ok(Math.abs(withPump[withPump.length - 1] - 100) < 1, `settles at 2 x 5 / 0.1: ${withPump[withPump.length - 1]}`);
  const none = simulate(tank({})).series.levels.T;
  assert.equal(none[none.length - 1], 0);
});

test("a ceiling holds", () => {
  const T = simulate(tank({ model: { inputs: { pump: { values: [5] } } }, stock: { max: 60 } })).series.levels.T;
  assert.ok(Math.max(...T) <= 60 + 1e-9 && T[T.length - 1] > 58, `${Math.max(...T)} ${T[T.length - 1]}`);
});
