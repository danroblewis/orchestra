// Run with: node --test tests/simplify.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { suggest, apply } = require("../sdlab/static/simplify.js");

const T = 100, t = Array.from({ length: T }, (_, i) => i + 1);
const wave = (f) => t.map((x) => f(x));
const base = () => ({
  stocks: [{ id: "a", name: "A" }, { id: "b", name: "B" }, { id: "c", name: "C" }, { id: "lonely", name: "Lonely" }, { id: "goal", name: "Goal", target: { value: 5 } }],
  flows: [
    { id: "in", name: "In", from: null, to: "a", rate: { form: "constant", value: 5 }, machine: "environment", query: "x" },
    { id: "ab", name: "A to B", from: "a", to: "b", rate: { form: "constant", value: 5 }, machine: "environment", query: "x" },
    { id: "bc", name: "B to C", from: "b", to: "c", rate: { form: "constant", value: 5 }, machine: "environment", query: "x" },
    { id: "dead", name: "Dead", from: "a", to: "c", rate: { form: "constant", value: 0 }, machine: "environment", query: "x" },
  ],
  machines: [],
});
const run = () => ({
  t,
  levels: { a: wave((x) => 50 + 10 * Math.sin(x / 7)), b: wave(() => 0), c: wave((x) => x * 5), lonely: wave(() => 3), goal: wave(() => 1) },
  rates: { in: wave(() => 5), ab: wave((x) => 5 + Math.sin(x)), bc: wave((x) => 5 + Math.sin(x)), dead: wave(() => 0) },
});

test("a flow that never moved anything is suggested for removal; one that moved once is not", () => {
  const r = run();
  let s = suggest(base(), r);
  assert.ok(s.some((x) => x.kind === "remove-flow" && x.flows[0] === "dead"));
  r.rates.dead[60] = 40;                                   // an outage drain: nothing, then a lot, once
  s = suggest(base(), r);
  assert.ok(!s.some((x) => x.kind === "remove-flow" && x.flows[0] === "dead"));
});

test("a stock things pass straight through is suggested as a direct connection", () => {
  const s = suggest(base(), run());
  const p = s.find((x) => x.kind === "pass-through");
  assert.ok(p && p.stocks[0] === "b", JSON.stringify(s.map((x) => x.title)));
  const m = apply(base(), p);
  assert.equal(m.flows.find((f) => f.id === "ab").to, "c");
  assert.ok(!m.flows.some((f) => f.id === "bc"));
  assert.equal(m.stocks.find((x) => x.id === "b").hide, true);       // hidden, not removed
});

test("unconnected and unchanging stocks are suggested for hiding; goals and keep marks are respected", () => {
  const s = suggest(base(), run());
  assert.ok(s.some((x) => x.kind === "hide-stock" && x.stocks[0] === "lonely"));
  assert.ok(!s.some((x) => (x.stocks || []).includes("goal")));
  const kept = base(); kept.stocks.find((x) => x.id === "lonely").keep = true;
  assert.ok(!suggest(kept, run()).some((x) => (x.stocks || []).includes("lonely")));
});

test("two flows between the same stocks are suggested for merging", () => {
  const m = base(); m.flows.push({ id: "ab2", name: "A to B again", from: "a", to: "b", rate: { form: "constant", value: 1 }, machine: "environment" });
  const s = suggest(m, run());
  const mg = s.find((x) => x.kind === "merge-flows");
  assert.ok(mg);
  const merged = apply(m, mg);
  assert.equal(merged.flows.filter((f) => f.from === "a" && f.to === "b").length, 1);
  assert.equal(merged.flows.find((f) => f.id === "ab").rate.value, 6);
});

test("a stock that moves exactly like another is suggested as a twin", () => {
  const m = base(); m.stocks.push({ id: "a2", name: "A again" }); m.flows.push({ id: "x2", name: "X", from: null, to: "a2", rate: { form: "constant", value: 1 }, machine: "environment" });
  const r = run(); r.levels.a2 = r.levels.a.map((v) => v * 1.001);
  assert.ok(suggest(m, r).some((x) => x.kind === "hide-stock" && x.stocks[0] === "a2" && /exactly like A/.test(x.reason)));
});
