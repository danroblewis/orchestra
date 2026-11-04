// The Dynamics page's discovery line and its drawer (discovery-runs.js) rendered from a fixture of
// /api/dynamics/runs: the last run's duration, requests and outcome as a link, the health as a
// shape and words, the phase and elapsed time while a run goes; the drawer's health, phase bar,
// cost per source, trend lines and history with the inference rounds marked.
import test from "node:test"; import assert from "node:assert/strict"; import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const DR = require("../../orchestra/web/static/discovery-runs.js");
const VIEW = require("./fixture.json");
const text = (html) => html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&#39;/g, "'").replace(/\s+/g, " ").trim();

test("the line: the last run as a link with the health's shape beside it", () => {
  const html = DR.lineHtml(VIEW);
  assert.match(text(html), /last run: 3 m 12 s · 53 requests · saved v7/);
  assert.match(html, /<a href="#" class="dr-link" onclick="DiscoveryRuns.open\(\);return false"/);
  assert.match(html, /<span class="dr-dot dr-amber" title="the last run took 3 m 12 s, more than 3× the median of 58 s" aria-label="discovery needs a look">▲<\/span>/);
});

test("the line while a run goes: its phase and elapsed time, counting on between reads", () => {
  const v = { ...VIEW, running: { kind: "discovery", trigger: "button", phase: "inference", what: "chrono", elapsed_s: 62 } };
  assert.match(text(DR.lineHtml(v)), /^▲ rediscovering: inference \(survey, probes\) \(chrono\) · 1 m 2 s · last run: 3 m 12 s/);
  assert.match(text(DR.lineHtml(v, 10)), /· 1 m 12 s ·/);
  assert.match(text(DR.lineHtml({ ...v, running: { trigger: "schedule", phase: "fit", elapsed_s: 5 } })), /discovering: the strategy's fit · 5\.0 s/);
  assert.equal(text(DR.lineHtml({ ok: true, runs: [], health: { level: "none", reasons: [] } })), "○ no run recorded yet");
});

test("the drawer: health first, the phases as a bar, the cost per source and the outcome", () => {
  const html = DR.drawerHtml(VIEW), t = text(html);
  assert.ok(t.startsWith("Discovery runs needs a look ▲ the last run took 3 m 12 s, more than 3× the median of 58 s"));
  const segs = [...html.matchAll(/<div class="dr-seg" style="flex:([\d.]+) 1 0;background:[^"]+" title="([^"]+)"/g)].map((m) => [m[2].replace(/&#39;/g, "'"), +m[1]]);
  assert.deepEqual(segs.map((s) => s[0]), ["store reads: 1 m 1 s", "the strategy's fit: 2 m 1 s", "saving: 9.3 s"]);   // no inference this run: no segment
  assert.ok(Math.abs(segs.reduce((a, s) => a + s[1], 0) - 1) < 0.001);
  assert.match(t, /outcome saved v7 took 3 m 12 s strategy kalman_lna window 1 h 0 m in 30 s steps model 5 stocks, 9 flows, 31 series left out/);
  const rows = [...html.matchAll(/<tr><td>(\w+)<\/td>((?:<td class="num[^"]*">[^<]*<\/td>)+)<\/tr>/g)].map((m) => [m[1], text(m[2])]);
  assert.deepEqual(rows, [["chrono", "41 5 36 0 180 10,800 2.3 MB 48 s 1 4,141 / 20,000"], ["kube", "12 12 0 0 40 1,900 — 3.0 s 0 200 / 5,000"]]);
});

test("the drawer: trend lines over the last day and the history with inference rounds marked", () => {
  const html = DR.drawerHtml(VIEW), t = text(html);
  assert.match(t, /The last day · 12 discovery runs/);
  assert.match(html, /aria-label="duration per run over the last day, 12 runs, at most 3 m 12 s"/);
  assert.match(html, /aria-label="requests per run over the last day, 12 runs, at most 53"/);
  const hist = html.slice(html.indexOf('<table class="dt dr-hist">'));
  const rows = [...hist.matchAll(/<tr class="([^"]*)">(.*?)<\/tr>/g)];
  assert.equal(rows.length, 13);
  assert.match(text(rows[0][2]), /schedule 3 m 12 s 53 12,700 saved v7$/);
  const inf = rows.filter((r) => r[1] === "dr-inf");
  assert.equal(inf.length, 1);
  assert.match(text(inf[0][2]), /inference chrono 20 s 22 0 inferred 14 definitions$/);
});

test("no run yet: the drawer says when one runs", () => {
  const t = text(DR.drawerHtml({ ok: true, runs: [], every_s: 300, health: { level: "none", reasons: ["no discovery run recorded yet"] } }));
  assert.match(t, /No discovery run is recorded yet\. The host runs one every 5 m 0 s; the rediscover button runs one now\./);
});

test("the history: the explorer's experiments interleaved with the runs by time, their verdict and effect", () => {
  const last = VIEW.runs[VIEW.runs.length - 1];
  const experiments = [
    { id: "x1", t: last.started - 1, by: "explorer", change: { source: "chrono", split: ["subscription_id"] }, expect: "a stock per subscription",
      verdict: "kept", why: "two stocks more", rounds: ["r10", "r11"], effect: { stocks: 2, trust: 0.12, requests: -3 } },
    { id: "x2", t: last.started + 10, by: "owner", change: { source: "chrono", kinds: { legacy_queue_size: "level" } }, expect: "the queue is a stock", verdict: null },
  ];
  const html = DR.drawerHtml({ ...VIEW, experiments }), t = text(html);
  assert.match(t, /Recent runs and experiments/);
  const hist = html.slice(html.indexOf('<table class="dt dr-hist">'));
  const rows = [...hist.matchAll(/<tr class="([^"]*)">(.*?)<\/tr>/g)];
  assert.equal(rows.length, 15);
  assert.equal(rows[0][1], "dr-exp");                       // newest first: the pending one, after the last run
  assert.match(text(rows[0][2]), /experiment owner source chrono, kinds \{&quot;legacy_queue_size&quot;:&quot;level&quot;\} · expects: the queue is a stock pending: not judged yet$/);
  assert.equal(rows[1][1], "");                             // the last run
  assert.equal(rows[2][1], "dr-exp");
  assert.match(text(rows[2][2]), /experiment explorer source chrono, split \[&quot;subscription_id&quot;\] · expects: a stock per subscription kept after 2 runs · stocks \+2, trust \+0\.12, requests −3$/);
  assert.match(rows[2][2], /<td class="dr-good">kept/);
  assert.match(rows[2][2], /title="two stocks more"/);
  assert.doesNotMatch(DR.drawerHtml(VIEW), /and experiments/);
});
