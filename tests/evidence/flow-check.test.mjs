// A flow against its equation (flow-check.js), like for like: the observed rate is a count over a
// bucket, so the equation is its mean over the level samples in the same bucket. A 0/1 queue drained
// in proportion to its level (k 29/min, the level 1 a tenth of the time) moves about 3/min, and its
// equation over the same buckets says about 3/min: no miss. At one instant it would say 0 or 29.
import test from "node:test"; import assert from "node:assert/strict"; import { createRequire } from "node:module";
const FlowCheck = createRequire(import.meta.url)("../../orchestra/web/static/flow-check.js");

const T0 = 1_800_000_000, STEP = 30, SAMPLE = 3;
// level samples every 3 s over four 30 s buckets; ``ones``: which samples read 1
function queue(ones) {
  const levels = [];
  for (let t = T0 - 4 * STEP + SAMPLE; t <= T0; t += SAMPLE) levels.push([t, ones(levels.length) ? 1 : 0]);
  const levelAt = (id, t) => { let v = null; for (const [tt, x] of levels) { if (tt > t) break; v = x; } return v; };
  const samplesIn = (a, b) => levels.map((p) => p[0]).filter((t) => t > a && t <= b);
  return { levels, levelAt, samplesIn };
}
const flow = { id: "out", from: "q", current: { form: "proportional", inputs: ["q"], params: { k: 29 }, quality: { dispersion: 1 } } };
const obs = (rate) => [1, 2, 3, 4].map((i) => [T0 - (4 - i) * STEP, rate]);

test("a 0/1 queue's proportional outflow at mean level 0.1 does not differ from 3/min observed", () => {
  const q = queue((i) => i % 10 === 0);                     // one sample in ten reads 1: mean level 0.1
  const mean = q.levels.reduce((a, p) => a + p[1], 0) / q.levels.length;
  assert.ok(Math.abs(mean - 0.1) < 1e-9, String(mean));
  assert.equal(FlowCheck.predicted(flow, T0, q.levelAt), 0);  // the instant says 0
  const a = FlowCheck.against(flow, obs(3), { step: STEP, levelAt: q.levelAt, samplesIn: q.samplesIn, minutes: 2 });
  assert.ok(Math.abs(a.eq - 2.9) < 1e-9, String(a.eq));
  assert.equal(a.differs, false);
});

test("a stall (nothing observed while the level is 1 throughout) differs", () => {
  const q = queue(() => true);
  const a = FlowCheck.against(flow, obs(0), { step: STEP, levelAt: q.levelAt, samplesIn: q.samplesIn, minutes: 2 });
  assert.equal(a.eq, 29);
  assert.equal(a.differs, true);
  assert.equal(a.quiet, true);
});

test("the equation's line has one point per observed bucket, each the mean of the levels sampled in it", () => {
  const q = queue((i) => i < 10);                           // the first bucket full, the rest empty
  const line = FlowCheck.line(flow, obs(3), STEP, q.levelAt, q.samplesIn);
  assert.deepEqual(line.map((p) => p[0]), obs(3).map((p) => p[0]));
  assert.deepEqual(line.map((p) => p[1]), [29, 0, 0, 0]);
});

test("with no level sampled inside a bucket, the equation is read at the bucket's end", () => {
  const levelAt = () => 2;
  assert.equal(FlowCheck.bucketMean(flow, T0, STEP, levelAt, () => []), 58);
  assert.deepEqual(FlowCheck.reads({ current: { spec: { form: "linear", terms: [{ stock: "a" }, { stock: "b" }] } } }), ["a", "b"]);
});
