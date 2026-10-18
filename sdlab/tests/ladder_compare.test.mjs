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

test("measures and the explanation come from the scorer's parts", () => {
  const scores = { status: "fail", recall: 0.75, precision: 0.6, right: 2, of: 4,
    parts: [{ key: "outside -> A [const]", found: true, ok: true, error: 0.01, true: 10, found_value: 10.1 },
      { key: "A -> B [A]", found: true, ok: true, error: 0.03, true: 0.3, found_value: 0.309 },
      { key: "C -> outside [C]", found: true, ok: false, error: 0.71, true: 0.1, found_value: 0.171 },
      { key: "B -> outside [B]", found: false, ok: false, error: 1, true: 0.2, found_value: null }],
    spurious: [{ key: "outside -> C [B]", value: 0.11, size: 4 }],
    behaviour: { in_sample: { 20: { skill: 0.8, ci: [0.7, 0.9] }, 100: { skill: 0.5, ci: [0.4, 0.6] } }, fresh: { 20: { skill: 0.75 } } } };
  const m = L.measures(scores);
  assert.equal(m.errorScore, 3 / 4);
  assert.equal(m.rateWorst, "the drain of C");
  assert.ok(Math.abs(m.rateMean - (0.01 + 0.03 + 0.71) / 3) < 1e-9 && m.rateMax === 0.71);
  assert.equal(m.spurious, 1); assert.equal(m.spuriousSize, 4); assert.deepEqual(m.skill20ci, [0.7, 0.9]);
  const e = L.explain(scores);
  assert.match(e, /Found the inflow to A and the move A → B within 3%/);
  assert.match(e, /Missed the drain of B/);
  assert.match(e, /the drain of C too high \(0\.171 for 0\.1, 71% off\)/);
  assert.match(e, /invented the link B ⇒ C \(0\.11\)/);
  assert.match(e, /Fail: 1 true number missing, 1 off and 1 invented\./);
  const eq = L.explain({ status: "equivalent", parts: [{ key: "outside -> B [A]", found: false, ok: false }], spurious: [{ key: "A -> B [A]", value: 0.2 }] });
  assert.match(eq, /It read the link A ⇒ B as the move A → B/);
  assert.match(L.explain({ status: "pass", parts: [{ key: "A -> B [A]", found: true, ok: true, error: 0 }], spurious: [] }), /^Found the one true number within 1%\. Pass/);
});

test("the diff has a line per flow: matched, off, missed, invented", () => {
  const found = [
    { from: null, to: "A", rate: { form: "constant", value: 10.1 } },
    { from: "A", to: "B", rate: { form: "proportional", stock: "A", k: 0.24 } },
    { from: "R", to: null, rate: { form: "proportional", stock: "A", k: 0.16 } },
  ];
  const scores = { status: "fail", parts: [part("outside -> A [const]", true, true, 10, 10.1), part("A -> B [A]", false, true, 0.3, 0.24),
    part("uses R on A -> B", false, false, 0.5), part("B -> outside [B]", false, false, 0.2)],
    spurious: [{ key: "R -> outside [A]", value: 0.16 }] };
  const lines = L.diffLines(L.compare(coflow, found, scores));
  assert.deepEqual(lines.map((l) => l.sign), ["✓", "~", "−", "+"]);
  assert.equal(lines[0].note, "found 10.1");
  assert.match(lines[1].note, /found 0\.24·A: 0\.24 for 0\.3 \(20% low\); missed the co-flow/);
  assert.equal(lines[2].note, "missed");
  assert.equal(lines[3].note, "invented 0.16·A");
  assert.equal(lines[3].ends, "R → outside");
});
