// Run with: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const { discover } = require("../sdlab/static/discover.js");
const run = JSON.parse(readFileSync(new URL("./fixtures/repair-run.json", import.meta.url)));
const model = JSON.parse(readFileSync(new URL("../sdlab/examples/repair.json", import.meta.url)));

test("discovery finds the devices that leave Intake and come back to Ready through a hidden stock", () => {
  const r = discover(model.stocks, run, { window: 5, eras: run.eras, moved: run.moved });
  const via = r.flows.find((f) => f.from === "intake" && f.to === "ready" && f.via);
  assert.ok(via, JSON.stringify(r.flows.map((f) => [f.from, f.to, f.via])));
  // 10% of Intake an hour goes to the vendor, shared between the hidden route and whatever else fits
  const sent = r.flows.filter((f) => f.from === "intake" && (f.to === null || f.via)).reduce((a, f) => a + f.rate.k, 0);
  assert.ok(Math.abs(sent - 0.1) < 0.03, `sent ${sent}`);
  assert.ok(Math.abs(via.via.delay - 15) <= 4, `delay ${via.via.delay}`);   // the vendor takes 12 to 18 hours
  assert.ok(via.via.holds > 5, `the vendor holds about ${via.via.holds} devices`);
});

test("without hidden stocks, it reports the departures and arrivals and pairs them", () => {
  const r = discover(model.stocks, run, { window: 5, eras: run.eras, moved: run.moved, latent: false });
  const out = r.flows.find((f) => f.from === "intake" && f.to === null);
  const back = r.flows.find((f) => f.from === null && f.to === "ready");
  assert.ok(out && back, JSON.stringify(r.flows.map((f) => [f.from, f.to])));
  assert.ok(out.rate.form === "proportional" && Math.abs(out.rate.k - 0.1) < 0.03, JSON.stringify(out.rate));
  assert.ok(Math.abs(out.perStep - back.perStep) < 0.2 * out.perStep, "what goes out comes back");
});

test("and the pairing suggests one hidden stock, with about the true delay", () => {
  const r = discover(model.stocks, run, { window: 5, eras: run.eras, moved: run.moved, latent: false });
  const h = r.hidden.find((x) => x.from === "intake" && x.to === "ready");
  assert.ok(h, JSON.stringify(r.hidden));
  const truth = 15;                                          // the vendor takes 12 to 18 hours
  assert.ok(h.delay !== null && Math.abs(h.delay - truth) <= truth / 2, `delay ${h.delay}`);
  assert.ok(h.balance > 0.8 && h.corr > 0.5, JSON.stringify(h));
  assert.ok(h.holds > 5, `the vendor holds about ${h.holds} devices`);
});
