// What a discovery left out (left-out.js, the Dynamics page's "How it was found"): the series the
// model is drawn from are never counted as left out, and the buckets add up to the heading.
import test from "node:test"; import assert from "node:assert/strict"; import { createRequire } from "node:module";
const LeftOut = createRequire(import.meta.url)("../../orchestra/web/static/left-out.js");

const ref = (name, labels) => ({ name, labels: { project: "p", ...labels } });
const m = { stocks: [{ id: "open", series: ref("tickets", { state: "OPEN" }), evidence: { balance: [{ sign: 1, series: 'moved_total{to="OPEN"}' }] } }],
            flows: [{ id: "in", counter: ref("moved_total", { to: "OPEN" }) }] };

test("a series the model uses is not left out: 'all N' only when the model uses none", () => {
  const d = { looked_at: 10, left_out: { "a": "a level that did not change", "b": "a counter of only 1 event" } };
  const c = LeftOut.counts(d, d.left_out, m);
  assert.deepEqual([c.n, c.used, c.left, c.named, c.unnamed, c.all], [10, 2, 8, 2, 6, false]);
  assert.equal(c.used + c.kept + c.named + c.unnamed, c.n);          // the buckets add up to what was looked at
  assert.ok(LeftOut.counts(d, d.left_out, { stocks: [], flows: [] }).all);   // no model: all 10 were left out
});

test("the keys are the record's: labels sorted, no project label", () => {
  assert.equal(LeftOut.keyOf(ref("x", { b: "2", a: "1" })), 'x{a="1",b="2"}');
  assert.deepEqual([...LeftOut.used(m)].sort(), ['moved_total{to="OPEN"}', 'tickets{state="OPEN"}']);
});
