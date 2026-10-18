// Run with: node --test tests/ladder_compare.test.mjs
// The ladder page's comparison of a true model with a found one (sdlab/static/ladder-compare.js)
// and the shared diagram layout (sdlab/static/diagram.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const L = require("../sdlab/static/ladder-compare.js");
const D = require("../sdlab/static/diagram.js");

const coflow = {
  stocks: [{ id: "A" }, { id: "B" }, { id: "R" }],
  flows: [
    { id: "in", from: null, to: "A", rate: { form: "constant", value: 10 } },
    { id: "ab", from: "A", to: "B", rate: { form: "proportional", stock: "A", k: 0.3 }, uses: [{ stock: "R", per: 0.5 }] },
    { id: "b_out", from: "B", to: null, rate: { form: "proportional", stock: "B", k: 0.2 } },
  ],
};
const part = (key, ok, found = true, t = 1, f = 1) => ({ key, kind: "x", ok, found, true: t, found_value: found ? f : null });

test("part keys parse into ends and readers", () => {
  assert.deepEqual(L.parseKey("A -> B [A]"), { kind: "flow", from: "A", to: "B", reader: "A" });
  assert.deepEqual(L.parseKey("outside -> A [const]"), { kind: "flow", from: null, to: "A", reader: "const" });
  assert.deepEqual(L.parseKey("uses R on A -> B"), { kind: "uses", stock: "R", from: "A", to: "B" });
  assert.deepEqual(L.parseKey("A -> (hidden) -> B"), { kind: "hidden", from: "A", to: "B" });
});

test("flows are classed right, wrong, missing and spurious", () => {
  const found = [
    { from: null, to: "A", rate: { form: "constant", value: 10 } },
    { from: "A", to: "B", rate: { form: "proportional", stock: "A", k: 0.25 } },
    { from: "R", to: null, rate: { form: "linear", c: 0, terms: [{ stock: "A", k: 0.15 }] } },
  ];
  const scores = { status: "fail", parts: [part("outside -> A [const]", true, true, 10, 10), part("A -> B [A]", false, true, 0.3, 0.25),
    part("uses R on A -> B", false, false, 0.5), part("B -> outside [B]", false, false, 0.2)],
    spurious: [{ key: "R -> outside [A]", value: 0.15 }] };
  const c = L.compare(coflow, found, scores);
  assert.deepEqual(c.truth.map((t) => t.cls), ["ok", "wrong", "missing"]);
  assert.deepEqual(c.found.map((x) => x.cls), ["ok", "wrong", "spurious"]);
  assert.equal(c.truth[1].reads.find((r) => r.kind === "uses").cls, "missing");
  assert.match(c.truth[1].badge, /found 0.25/);
  assert.match(c.found[1].badge, /true 0.3/);
  assert.ok(c.rows.find((r) => r.ends === "R → outside").cls === "spurious");
});

test("an equivalent result paints what differs blue, not red", () => {
  const scores = { status: "equivalent", parts: [part("outside -> A [const]", true), part("A -> B [A]", true), part("uses R on A -> B", false, false), part("B -> outside [B]", true)],
    spurious: [{ key: "R -> outside [A]", value: 0.15 }] };
  const found = [{ from: "R", to: null, rate: { form: "proportional", stock: "A", k: 0.15 } }];
  const c = L.compare(coflow, found, scores);
  assert.equal(c.truth[1].cls, "equiv");
  assert.equal(c.found[0].cls, "equiv");
});

test("a hidden stock's chain owns the hidden part, on both sides", () => {
  const truth = { stocks: [{ id: "A" }, { id: "H", measured: false }, { id: "B" }],
    flows: [{ id: "a_h", from: "A", to: "H", rate: { form: "proportional", stock: "A", k: 0.2 } }, { id: "h_b", from: "H", to: "B", rate: { form: "proportional", stock: "H", k: 0.1 } }] };
  const found = [{ from: "A", to: "x1", rate: { form: "proportional", stock: "A", k: 0.2 } }, { from: "x1", to: "B", rate: { form: "proportional", stock: "x1", k: 0.1 } }];
  const c = L.compare(truth, found, { status: "pass", parts: [{ key: "A -> (hidden) -> B", ok: true, found: true, true: { k_in: 0.2, delay: 10 }, found_value: { k_in: 0.2, delay: 10 } }], spurious: [] });
  assert.deepEqual(c.truth.map((t) => t.cls), ["ok", "ok"]);
  assert.deepEqual(c.found.map((x) => x.cls), ["ok", "ok"]);
  assert.deepEqual(c.extraStocks, ["x1"]);
  assert.deepEqual(c.rows.map((r) => [r.ends, r.truth.length, r.found.length]), [["A → (hidden) → B", 2, 2]], "one row for both chains");
});

test("equations read as a person would write them", () => {
  assert.equal(L.rateText({ form: "proportional", stock: "A", k: 0.5 }), "0.5·A");
  assert.equal(L.rateText({ form: "gap", stock: "I", goal: 300, time: 5 }), "(300 − I) / 5");
  assert.equal(L.equation(coflow.flows[1]), "0.3·A, uses 0.5 R each");
  const sched = { every: 200, changes: [{ t: 1, label: "fast", set: { ab: { form: "proportional", stock: "A", k: 0.5 } }, announce: true }, { t: 101, label: "slow", set: { ab: { form: "proportional", stock: "A", k: 0.25 } }, announce: true }] };
  assert.match(L.equation({ id: "ab", rate: { form: "proportional", stock: "A", k: 0.5 } }, sched), /fast: 0.5·A, slow: 0.25·A \(repeats every 200\), announced/);
  assert.equal(L.fmt({ mean: 0.4, per_window: [0.5, 0.25] }), "0.5 / 0.25");
});

test("the layout is the same every time and puts a chain in columns", () => {
  const flows = [{ from: "A", to: "B" }, { from: "B", to: "C" }, { from: "C", to: "D" }, { from: null, to: "A" }];
  const a = D.layout(["A", "B", "C", "D"], flows), b = D.layout(["A", "B", "C", "D"], flows);
  assert.deepEqual(a, b);
  assert.ok(a.A.x < a.B.x && a.B.x < a.C.x && a.C.x < a.D.x);
  const w = D.layout(["A", "B", "C", "D"], flows, { maxCols: 2 });
  assert.ok(w.C.y > w.A.y && w.C.x === w.A.x, "wrapped into a second band");
});
