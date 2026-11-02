// What the Dynamics tables say of the evidence (evidence-text.js): a missing number reads "—", a
// stock balanced by construction says so, a flow with too few events is not called fitted, and a
// hypothesis says how many of its events matched.
import test from "node:test"; import assert from "node:assert/strict"; import { createRequire } from "node:module";
const Evidence = createRequire(import.meta.url)("../../orchestra/web/static/evidence-text.js");

test("a stock whose behaviour has a null error renders, with — for the missing numbers", () => {
  const ev = { trust: { kind: "conservation", score: null, level: "low", behaviour: { score: 0.7, level: "medium", error: null } } };
  const t = Evidence.trust(ev);
  assert.match(t, /trust — \(low\)/);
  assert.match(t, /replay off by — × its spread/);
  assert.match(Evidence.trustCell({ evidence: ev }), /—/);
  assert.equal(Evidence.trust({}), "");
});

test("a stock balanced by construction says it holds by construction and proves nothing, never 0.00 very low", () => {
  const s = { evidence: { trust: { kind: "by_construction", score: 0, level: "very low", weakest: "evidence" } } };
  assert.match(Evidence.trustCell(s), /holds by construction: its level is the count of its own moves, so the balance proves nothing/);
  assert.doesNotMatch(Evidence.trustCell(s), /D33|reporters/);
  assert.doesNotMatch(Evidence.trustCell(s), /0\.00|very low/);
  assert.doesNotMatch(Evidence.trust(s.evidence), /0\.00|very low/);
});

test("a flow fitted from fewer than 5 events reads 'n events in the window: too few to fit, no equation'", () => {
  const f = (events, origin = "fitted") => ({ current: { origin, quality: { events } } });
  assert.ok(Evidence.tooFew(f(1)));
  assert.equal(Evidence.tooFewText(f(1)), "1 event in the window: too few to fit, no equation");
  assert.equal(Evidence.tooFewText(f(0)), "0 events in the window: too few to fit, no equation");
  assert.doesNotMatch(Evidence.tooFewText(f(1)), /fitted|poisson/);
  assert.ok(!Evidence.tooFew(f(5)));
  assert.ok(!Evidence.tooFew(f(0, "declared")));
});

test("a hypothesis says how many of its events matched", () => {
  assert.equal(Evidence.matched({ test: "event by event", paired: { flow: 1, events: 0.75 }, counts: { flow: 6, events: 8 } }), "6 of 8 events matched");
  assert.equal(Evidence.matched({ test: "step by step", equal_steps_moving: 1, counts: { flow: 8, events: 8 } }), "8 of 8 events matched");
  assert.equal(Evidence.matched({ test: "by correlation", counts: { flow: 10, events: 12 } }), "12 events to 10 counted");
  assert.equal(Evidence.matched({ confidence: 0.5 }), "");
});

test("a match in time that cannot tell machines apart says so: hypotheses within the margin, or a best chance half makes", () => {
  const h = (machine, confidence, chance) => ({ machine, confidence, chance });
  const U = "timing cannot tell these machines apart";
  const crowd = { id: "g", machines: [h("a", 0.9), h("b", 0.94), h("c", 0.86)] };
  assert.equal(Evidence.untold({ flows: [crowd] }, crowd), U);
  const lucky = { id: "l", machines: [h("a", 0.95, 0.42)] };
  assert.equal(Evidence.untold({ flows: [lucky] }, lucky), U);
  const clear = { id: "x", machines: [h("a", 0.95, 0.1), h("b", 0.5)] };
  assert.equal(Evidence.untold({ flows: [clear] }, clear), "");
  assert.equal(Evidence.chance({ machines: [], current: { origin: "fitted", quality: { events: 40 } } }, h("a", 0.92, 0.41)), ", 41% by chance");
});

test("a flow with too few events to fit shows no machine percentage, as it shows no equation or fit", () => {
  const h = { machine: "worker", confidence: 0.87 };
  const few = { machines: [h], current: { origin: "fitted", quality: { events: 3 } } };
  const enough = { machines: [h], current: { origin: "fitted", quality: { events: 40 } } };
  assert.ok(Evidence.tooFew(few) && !Evidence.tooFew(enough));
  assert.equal(Evidence.confidence(few, h), "");
  assert.equal(Evidence.confidence(enough, h), " 87%");
  assert.equal(Evidence.confidence(enough, { machine: "worker" }), "");
  globalThis.Evidence = Evidence;                     // the diagram's label (sd-graph.js) reads it as the page does
  const SDGraph = createRequire(import.meta.url)("../../orchestra/web/static/sd-graph.js");
  assert.equal(SDGraph.machineLabel(few), "");
  assert.equal(SDGraph.machineLabel(enough), "worker?");
  delete globalThis.Evidence;
});
