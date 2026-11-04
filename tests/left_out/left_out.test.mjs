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

test("the series left out at once are counted by the reasons the record gives, never a fixed phrase", () => {
  const lo = { a: "too new to measure: its first point is after the window's last step", b: "too new to measure: …", c: "Orchestra's own (the host's and the Core page's plumbing)",
               d: "a level that did not change" };
  assert.equal(LeftOut.early(lo, 3), "2 too new to measure, 1 Orchestra's own");
  assert.equal(LeftOut.early(lo, 5), "2 too new to measure, 1 Orchestra's own, 2 without a reason in the record");
  assert.doesNotMatch(LeftOut.early(lo, 3), /not being written/);
});

test("each group a person can act on says what would help (the owner's field report, 2026-11-04)", () => {
  const d = { start: 0, end: 3600 };
  const short = (n) => `written for only ${n} min of the 60 min the window holds data for (20%, less than the 50% a stock must cover): too new`;
  assert.equal(LeftOut.help([short(10), short(14)], d),
    "What would help: wait, or widen the match to series with history (the window holds 60 min of data; they were written for 10–14 min).");
  assert.equal(LeftOut.help([short(9)], d), "What would help: wait, or widen the match to series with history (the window holds 60 min of data; it was written for 9 min).");
  assert.equal(LeftOut.help(["no counters balance it (best R² 0.10)"], d),
    "What would help: a level with no matching counters: add the counters that fill and drain it, or a place count.");
  assert.equal(LeftOut.help(["a counter that did not move in the window"], d), "What would help: the counters were flat for 60 min: wait for traffic or widen the match.");
  assert.match(LeftOut.help(["Orchestra's own (the host's plumbing)"], d), /^Nothing to do/);
  assert.equal(LeftOut.help(["a flag (it only ever takes 0 and 1)"], d), "");
});
