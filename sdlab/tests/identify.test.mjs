// Identifying a known system dynamics model from its measured stocks (sdlab/static/identify.js).
// The data comes from the ground-truth examples' simulators (generated once and cached outside the
// repository by tests/bench/datasets.py), so the right answer is known exactly.
import test from "node:test";
import assert from "node:assert";
import fs from "fs";
import path from "path";
import { spawnSync } from "child_process";
import { createRequire } from "module";

const require = createRequire(import.meta.url);
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const { identify } = require(path.join(ROOT, "sdlab/static/identify.js"));

function data(example, steps) {
  const p = spawnSync("uv", ["run", "--directory", ROOT, "python", "tests/bench/datasets.py", example, "--steps", String(steps)], { encoding: "utf8" });
  if (p.status !== 0) throw new Error(p.stderr);
  const d = JSON.parse(fs.readFileSync(p.stdout.trim().split("\n").pop()));
  const model = JSON.parse(fs.readFileSync(path.join(ROOT, "sdlab/examples", `${example}.json`)));
  return { model, run: { t: d.t, levels: d.levels } };
}
const near = (x, want, tol) => Math.abs(x - want) <= tol;
const find = (r, from, to, opts = {}) => r.flows.find((f) => f.from === from && f.to === to && (!!f.driver) === !!opts.link && (!opts.link || f.driver === opts.link));
const k = (f) => (f.rate.form === "proportional" ? f.rate.k : f.rate.terms[0].k);

test("the work pipeline: every flow between stocks, and the intake that changes", () => {
  const { model, run } = data("sd-pipeline", 6000);
  const r = identify(model.stocks, run);
  for (const [from, to, want] of [["inbox", "working", 0.3], ["working", "review", 0.2], ["review", "done", 0.25], ["review", "working", 0.05]]) {
    const f = find(r, from, to);
    assert.ok(f && near(k(f), want, 0.02), `${from} -> ${to}: ${f ? k(f) : "missing"} (truth ${want})`);
  }
  const intake = r.flows.find((f) => !f.from && f.to === "inbox" && !f.driver);
  assert.ok(intake && intake.changes >= 100 && near(intake.rate.value, 5.75, 0.6), `intake ${JSON.stringify(intake && intake.rate)}, ${intake && intake.changes} changes`);
  assert.ok(!r.flows.some((f) => f.from === "inbox" && !f.to), "nothing leaves the inbox for outside");
});

test("SaaS: the ad link, the funnel, and the budget released in eras", () => {
  const { model, run } = data("sd-saas", 3650);
  const r = identify(model.stocks, run);
  const ads = find(r, null, "visitors", { link: "ad_budget" });
  assert.ok(ads && near(k(ads), 0.114, 0.01), `ads ${ads && k(ads)}`);
  for (const [from, to, want, tol] of [["ad_budget", null, 1 / 7, 0.01], ["visitors", "trials", 0.012, 0.002], ["visitors", null, 0.25, 0.02],
                                       ["trials", "paying", 0.0157, 0.003], ["trials", null, 0.0557, 0.005], ["paying", "churned", 0.005, 0.002]]) {
    const f = r.flows.find((x) => x.from === from && x.to === to && !x.driver && x.rate.form === "proportional");
    assert.ok(f && near(k(f), want, tol), `${from} -> ${to || "outside"}: ${f ? k(f) : "missing"} (truth ${want})`);
  }
  const release = r.flows.find((f) => !f.from && f.to === "ad_budget");
  assert.ok(release && release.changes >= 30 && near(release.rate.value, 1400, 150), `release ${JSON.stringify(release && release.rate)}`);
  assert.ok(!r.flows.some((f) => f.from === "ad_budget" && f.to === "visitors"), "dollars do not become people: the ads are a link");
});
