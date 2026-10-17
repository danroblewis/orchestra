// Inferring stocks nobody measures from the timing of what leaves and arrives.
import test from "node:test";
import assert from "node:assert";
import fs from "fs";
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { discover, discoverAll } = require("../sdlab/static/discover.js");

// outside -> A -> (hidden) -> B -> outside. What arrives in A and what leaves B are counted, as a
// clinic counts registrations and discharges. Without the counts the data is ambiguous: two waits
// in a row (the hidden one and B's own) look the same in either order.
function synthetic(shape, tau, n = 1200, seed = 7) {
  let x = seed;
  const rnd = () => ((x = (x * 1103515245 + 12345) % 2147483648) / 2147483648);
  const levels = { a: [], b: [] }, t = [], moved = [];
  let a = 20, h = 0.15 * 20 * tau, b = 15;                    // already running when measuring starts
  const pipe = new Array(tau).fill(0.15 * 20);
  for (let i = 0; i < n; i++) {
    const arrive = Math.max(0, 3 + 2.5 * Math.sin(i / 25) + (i % 200 < 15 ? 8 : 0) + 2 * (rnd() - 0.5));
    const send = 0.15 * a * (1 + 0.4 * (rnd() - 0.5));                // real counts are noisy
    let back;
    if (shape === "pipe") { pipe.push(send); back = pipe.shift(); } else { back = h / tau; h += send - back; }
    const leave = 0.2 * b * (1 + 0.4 * (rnd() - 0.5));
    a += arrive - send; b += back - leave;
    t.push(i + 1); levels.a.push(a); levels.b.push(b);
    moved.push({ arrive: { took: {}, made: { a: arrive } }, leave: { took: { b: leave }, made: {} } });
  }
  return { stocks: [{ id: "a", unit: "things" }, { id: "b", unit: "things" }], run: { t, levels, rates: {}, moved }, start: { a: 20, b: 15 } };
}

for (const [shape, tau] of [["exp", 12], ["pipe", 18]]) {
  test(`a hidden ${shape} stock between two measured stocks is found, with its delay and size`, () => {
    const { stocks, run, start } = synthetic(shape, tau);
    const r = discover(stocks, run, { window: 2, moved: run.moved, start });
    const via = r.flows.find((f) => f.via && f.from === "a" && f.to === "b");
    assert.ok(via, JSON.stringify(r.flows.map((f) => [f.from, f.to, f.via])));
    assert.ok(Math.abs(via.rate.k - 0.15) < 0.03, JSON.stringify(via.rate));
    assert.ok(Math.abs(via.via.delay - tau) <= tau * 0.35, JSON.stringify(via.via));
    const holds = 0.15 * run.levels.a.reduce((s, v) => s + v, 0) / run.t.length * tau;
    assert.ok(Math.abs(via.via.holds - holds) < 0.3 * holds, `holds ${via.via.holds} vs ${holds}`);
    assert.ok(!r.flows.some((f) => !f.via && f.from === "a" && f.to === "b"), "not also a direct flow");
  });
}

test("with hidden stocks turned off, the same data gives flows to and from outside", () => {
  const { stocks, run } = synthetic("exp", 12);
  const r = discover(stocks, run, { window: 2, moved: run.moved, latent: false });
  assert.ok(!r.flows.some((f) => f.via));
});

test("discoverAll links stocks whose changes mirror with a lag, so the hidden stock can be found", () => {
  const { stocks, run } = synthetic("pipe", 18);
  const many = [...stocks, ...Array.from({ length: 14 }, (_, i) => ({ id: `z${i}`, unit: "things" }))];
  many.slice(2).forEach((s, i) => { run.levels[s.id] = run.t.map((t) => 5 + ((t * (i + 3)) % 7 === 0 ? 1 : 0)); });
  const r = discoverAll(many, run, { window: 2, moved: run.moved });
  assert.ok(r.flows.some((f) => f.via && f.from === "a" && f.to === "b"), JSON.stringify(r.flows.map((f) => [f.from, f.to, !!f.via])));
});

test("hospital: the lab between treatment and the ward is found with about the true delay", () => {
  const model = JSON.parse(fs.readFileSync(new URL("../sdlab/examples/hospital.json", import.meta.url)));
  const run = JSON.parse(fs.readFileSync(new URL("./fixtures/hospital-run.json", import.meta.url)));
  const r = discover(model.stocks, run, { window: 2, moved: run.moved });
  const lab = r.flows.find((f) => f.via && f.from === "treatment" && f.to === "ward");
  assert.ok(lab, JSON.stringify(r.flows.map((f) => [f.from, f.to, f.via])));
  // truth: about 1 h of treatment, then an exponential 4 h in the lab; it holds about 4.9 patients
  assert.ok(lab.via.delay >= 3 && lab.via.delay <= 8, JSON.stringify(lab.via));
  assert.ok(lab.via.holds > 2 && lab.via.holds < 15, JSON.stringify(lab.via));
});
