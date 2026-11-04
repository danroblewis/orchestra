// The window and step the Dynamics page says (discovery-window.js): what discovery fitted, from its
// record's `fitted` (web/dynamics.py), never only what orchestra.toml configures (UC-K finding 7).
import test from "node:test"; import assert from "node:assert/strict"; import { createRequire } from "node:module";
const DW = createRequire(import.meta.url)("../../orchestra/web/static/discovery-window.js");

test("a widened discovery says the window and step it was fitted over", () => {
  const d = { strategy: "kalman_lna", fitted: { window_s: 604800, step_s: 5040, widened_from_s: 3600 } };
  assert.equal(DW.text(d.fitted), "7 d · 84 min steps");
  assert.equal(DW.summary(d, { strategy: "kalman_lna", window_s: 3600, step_s: 30 }), "kalman_lna · 7 d · 84 min steps (configured 60 min · 30 s steps)");
  assert.doesNotMatch(DW.summary(d, { strategy: "kalman_lna", window_s: 3600, step_s: 30 }), /^kalman_lna · 60 min/);
});

test("as configured, the configured settings once; with no record, the configured settings", () => {
  const c = { strategy: "conservation", window_s: 3600, step_s: 30 };
  assert.equal(DW.summary({ strategy: "conservation", fitted: { window_s: 3600, step_s: 30 } }, c), "conservation · 60 min · 30 s steps");
  assert.equal(DW.summary(null, c), "conservation · 60 min · 30 s steps");
  assert.deepEqual([DW.dur(30), DW.dur(5040), DW.dur(36000), DW.dur(604800)], ["30 s", "84 min", "10 h", "7 d"]);
});

test("a window widened for sparse own data says so beside the configured settings", () => {
  const d = { strategy: "kalman_lna", fitted: { window_s: 64800, step_s: 540, widened_from_s: 3600, sparse: 29 } };
  assert.equal(DW.summary(d, { strategy: "kalman_lna", window_s: 3600, step_s: 30 }),
    "kalman_lna · 18 h · 9 min steps (widened for sparse data (29 levels); configured 60 min · 30 s steps)");
});

test("the strategy said is the one that ran, the configured one beside it only when it differs", () => {
  // the owner's page: kalman_lna configured, conservation found no stock, so SD Lab never ran
  const d = { strategy: "kalman_lna", ran: "conservation", sdlab: "not run: conservation found no stock to hand it", fitted: { window_s: 3600, step_s: 30 } };
  const c = { strategy: "kalman_lna", window_s: 3600, step_s: 30 };
  assert.equal(DW.summary(d, c), "conservation (configured: kalman_lna) · 60 min · 30 s steps");
  assert.equal(DW.strategy({ ran: "conservation" }, "kalman_lna"), "conservation (configured: kalman_lna)");
  assert.equal(DW.strategy({ ran: "kalman_lna", strategy: "kalman_lna" }, "kalman_lna"), "kalman_lna");
  // a record from before ``ran``: SD Lab not run says conservation made it
  assert.equal(DW.strategy({ strategy: "kalman_lna", sdlab: "not run: the counters balance every stock exactly" }, "kalman_lna"), "conservation (configured: kalman_lna)");
  // no model, only the record of the discovery that found none: still the strategy that ran
  assert.equal(DW.summary({ strategy: "kalman_lna", ran: "conservation" }, c), "conservation (configured: kalman_lna) · 60 min · 30 s steps");
});
