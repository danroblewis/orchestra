// Feedback loops (orchestra/web/static/loops.js): structures, an independent loop set, merging, exchanges.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const Loops = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/loops.js"));
const E = (s) => s.split(" ").map((x) => { const [a, b] = x.split(">"); return { source: a, target: b }; });
const ids = (edges) => [...new Set(edges.flatMap((e) => [e.source, e.target]))];

test("two separate cycles are two structures with one loop each", () => {
  const edges = E("a>b b>c c>a x>y y>z z>x c>x");
  const r = Loops.analyse(ids(edges), edges);
  assert.equal(r.structures.length, 2);
  assert.deepEqual(r.structures.map((s) => s.loops.length), [1, 1]);
});

test("the loops kept are independent: no more than links − nodes + 1, and every link is in one", () => {
  // a figure eight with a chord: a>b>c>a, a>d>e>a, b>d
  const edges = E("a>b b>c c>a a>d d>e e>a b>d");
  const [s] = Loops.analyse(ids(edges), edges).structures;
  assert.equal(s.independent, 7 - 5 + 1);
  assert.ok(s.loops.length <= s.independent);
  const used = new Set(s.loops.flatMap((l) => l.nodes.map((n, j) => `${n}>${l.nodes[(j + 1) % l.nodes.length]}`)));
  for (const e of edges) assert.ok(used.has(`${e.source}>${e.target}`), `${e.source}>${e.target} in no loop`);
  assert.ok(s.cycles >= s.loops.length, "every loop is a cycle");
});

test("cycles through the same nodes are one loop with several routes", () => {
  // a>b>c>a and a>c>b>a: the same three nodes, two directions
  const edges = E("a>b b>c c>a a>c c>b b>a");
  const [s] = Loops.analyse(ids(edges), edges, { minLength: 3 }).structures;
  assert.equal(s.loops.length, 1);
  assert.equal(s.loops[0].routes.length, 2);
});

test("a two-way pair is an exchange, not a loop", () => {
  const edges = E("board>expo expo>board expo>taker taker>expo");
  const r = Loops.analyse(ids(edges), edges, { exchanges: true });
  assert.equal(r.exchanges.length, 2);
  assert.equal(r.structures.length, 0);
});

test("polarity: an odd number of negative links balances", () => {
  const edges = [{ source: "s", target: "f", sign: 1 }, { source: "f", target: "t", sign: 1 }, { source: "t", target: "g", sign: 1 }, { source: "g", target: "s", sign: -1 }];
  const [s] = Loops.analyse(ids(edges), edges).structures;
  assert.equal(s.loops[0].polarity, "B");
});

test("the bakery's event map: 649 cycles become a handful of loops and some exchanges", () => {
  const d = JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, "../fixtures/machines/bakery-2026-10-25.json"), "utf8"));
  // machine → machine when one publishes an event type the other listens for
  const listens = new Map();
  for (const e of d.edges) if (e.kind === "subscribes") listens.set(e.from, [...(listens.get(e.from) || []), e.to]);
  const edges = [];
  for (const e of d.edges) if (e.kind === "publishes") for (const m of listens.get(e.to) || []) edges.push({ source: e.from, target: m, via: e.to });
  const r = Loops.analyse(ids(edges), edges, { exchanges: true });
  const loops = r.structures.flatMap((s) => s.loops);
  console.log(`exchanges ${r.exchanges.length}, structures ${r.structures.length}, loops ${loops.length}, cycles ${r.structures.map((s) => s.cycles)}`);
  assert.ok(r.exchanges.length > 0);
  assert.ok(loops.length <= 30, `${loops.length} loops`);
  assert.ok(loops.every((l) => l.nodes.length >= 3));
});
