import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const sim = require("../sdlab/static/sim.js");
const model = require("../sdlab/examples/roastery.json");

const clone = (m) => JSON.parse(JSON.stringify(m));
const shipped = (m) => { const s = sim.simulate(m).series; return s.levels.shipped[s.t.length - 1]; };
const score = (lev, id) => lev.rows.find((r) => r.flow === id).score;

// the fix the description asks for: shipping gets its own desk
function withShippingDesk(m) {
  const f = clone(m);
  f.machines.push({ id: "desk", name: "Shipping desk", kind: "code", color: "#4338ca", capacity: 1 });
  f.flows.find((x) => x.id === "ship").machine = "desk";
  return f;
}

test("ship, on the shared packing bench, is the bottleneck; roast (slowest per bag) is not", () => {
  const work = Object.fromEntries(model.flows.filter((f) => f.work).map((f) => [f.id, f.work]));
  assert.ok(work.roast > work.ship && work.roast > work.package, "roast must look slowest per item");
  const lev = sim.leverage(model);
  assert.deepEqual(lev.goals, ["shipped"]);
  assert.equal(lev.rows[0].flow, "ship");
  assert.equal(lev.rows[1].flow, "package");
  assert.ok(score(lev, "ship") > 0.04);
  assert.ok(score(lev, "roast") < 0.01);
});

test("after giving ship its own desk, the bottleneck moves to the roaster and the goal improves", () => {
  const fixed = withShippingDesk(model);
  const lev = sim.leverage(fixed);
  assert.equal(lev.rows[0].flow, "roast");
  assert.ok(score(lev, "roast") > 0.05);
  assert.ok(score(lev, "ship") < 0.005);
  assert.ok(shipped(fixed) > shipped(model) + 25, `${shipped(model)} -> ${shipped(fixed)}`);
});

test("a second roaster meets the goal and leaves demand as the limit", () => {
  const twice = withShippingDesk(model);
  twice.machines.find((m) => m.id === "roaster").capacity = 2;
  assert.ok(sim.simulate(twice).summary.targets[0].met);
  assert.equal(sim.leverage(twice).rows[0].flow, "order");
});
