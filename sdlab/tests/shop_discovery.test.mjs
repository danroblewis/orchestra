// Discovering the web shop's structure from its per-second levels (sdlab/examples/shop), graded
// against the answer key, on the whole run and as a run grows (the page's "keep discovering").
// Services finish requests within a second, so the links between them (a caller's level drives its
// callee's arrivals; nothing moves) live in single steps: see screenLinks in discover.js.
import test from "node:test";
import assert from "node:assert";
import fs from "fs";
import { createRequire } from "module";
const require = createRequire(import.meta.url);
const { discoverAll, screenLinks } = require("../sdlab/static/discover.js");

const model = JSON.parse(fs.readFileSync(new URL("../sdlab/examples/shop.json", import.meta.url)));
const run = JSON.parse(fs.readFileSync(new URL("./fixtures/shop-run.json", import.meta.url)));
const truth = JSON.parse(fs.readFileSync(new URL("../sdlab/examples/shop/truth.json", import.meta.url))).sd_structure;
const trueLinks = new Set(truth.driven_inflows.map((d) => `${d.driver}>${d.into}`));
const trueMoves = new Set(truth.flows.filter((f) => f.from && f.to).map((f) => `${f.from}>${f.to}`));

// what the page does: the first `steps` seconds, its window, and the eras that have started
function grade(steps) {
  const cut = { t: run.t.slice(0, steps), levels: Object.fromEntries(Object.entries(run.levels).map(([k, v]) => [k, v.slice(0, steps)])) };
  const eras = run.eras.map((e) => ({ start: e.start })).filter((e) => e.start <= cut.t[cut.t.length - 1]);
  const t0 = Date.now();
  const r = discoverAll(model.stocks, cut, { window: 5, eras: eras.length > 1 ? eras : undefined });
  const links = r.flows.filter((f) => f.driver), moves = r.flows.filter((f) => f.from && f.to && !f.driver);
  return {
    ms: Date.now() - t0, r,
    links: links.length, trueLinks: links.filter((f) => trueLinks.has(`${f.driver}>${f.to}`)).length,
    moves: moves.length, trueMoves: moves.filter((f) => trueMoves.has(`${f.from}>${f.to}`)).length,
    drains: r.flows.filter((f) => f.from && !f.to).length,
  };
}

test("shop: the whole run gives its call graph as links, the queues' workers as flows, and every drain", () => {
  const g = grade(run.t.length);
  const say = JSON.stringify({ ...g, r: undefined });
  assert.ok(g.trueLinks >= 25, `true links ${say}`);                  // of 65 (before: 1 of 3)
  assert.ok(g.trueLinks / g.links >= 0.5, `precision ${say}`);
  assert.ok(g.trueMoves >= 2, `queue -> pool ${say}`);                // of 6 (before: none)
  assert.ok(g.trueMoves >= g.moves - 2, `false moves ${say}`);
  assert.ok(g.drains >= 30, `drains ${say}`);                         // 36 stocks drain to outside
  assert.ok(g.ms < 10000, `took ${g.ms} ms`);
});

test("shop: as the run grows, links are found from the first minutes on and stay mostly right", () => {
  for (const [steps, least] of [[300, 12], [1000, 15], [3000, 22]]) {
    const g = grade(steps);
    const say = `${steps} steps: ${JSON.stringify({ ...g, r: undefined })}`;
    assert.ok(g.trueLinks >= least, say);
    assert.ok(g.trueLinks / g.links >= 0.45, say);
    assert.ok(g.moves - g.trueMoves <= 5, say);
  }
});

// A caller with two callees, all finishing within a step: each callee's level is about half the
// caller's (plus its own noise and traffic), a fourth stock is unrelated. Levels only, as a
// dashboard shows them.
function calls(n = 2000, seed = 3) {
  let x = seed;
  const rnd = () => ((x = (x * 1103515245 + 12345) % 2147483648) / 2147483648);
  const poisson = (m) => { let k = 0, p = Math.exp(-m), s = p; const u = rnd(); while (u > s && k < 200) { k++; p *= m / k; s += p; } return k; };
  const levels = { a: [], b: [], c: [], d: [] }, t = [];
  for (let i = 0; i < n; i++) {
    const a = poisson(10 + 4 * Math.sin(i / 300));
    levels.a.push(a); levels.b.push(poisson(0.5 * a + 1)); levels.c.push(poisson(0.4 * a + 2)); levels.d.push(poisson(6));
    t.push(i);
  }
  return { t, levels };
}

test("screenLinks: a fast caller's level drives its callees, in that direction, and nothing else", () => {
  const stocks = ["a", "b", "c", "d"].map((id) => ({ id, unit: "requests" }));
  const s = screenLinks(stocks, stocks, calls());
  const found = s.links.map((l) => `${l.driver}>${l.to}`).sort();
  assert.deepEqual(found, ["a>b", "a>c"], JSON.stringify(s.links));
  s.links.forEach((l) => assert.ok(l.k > 0));
});

test("screenLinks leaves slow stocks to the windowed search: the socks run has no screened links", () => {
  const stocks = JSON.parse(fs.readFileSync(new URL("../sdlab/examples/socks.json", import.meta.url))).stocks;
  const socks = JSON.parse(fs.readFileSync(new URL("./fixtures/socks-run.json", import.meta.url)));
  assert.equal(screenLinks(stocks, stocks, socks).links.length, 0);
});
