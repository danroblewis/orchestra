// The model's projection as the pages say it (projection.js), on a saved simulate response
// (tests/fixtures/projection: made by the real sd/simulate.py for the model beside it): the strip's
// sentences, every "no projection" with its reason, the flows table's count, and the chart's band.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm"; import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const Projection = require("../../orchestra/web/static/projection.js");
const fix = (f) => JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, "../fixtures/projection", f), "utf8"));
const model = fix("model.json"), sim = fix("simulate.json");
const names = { stock: (id) => model.stocks.find((s) => s.id === id).name };
const when = (t) => `t+${Math.round((t - sim.now) / 60)}`;
const o = { names, when, differs: () => false, horizon: 30 };
const lines = (html) => [...html.matchAll(/<div class="pline[^"]*"[^>]*>(.*?)<\/div>/g)].map((m) => m[1]);

test("one line per stock that moves, an emptying or a crossing first, each with its trust", () => {
  const ls = lines(Projection.strip(model, sim, o));
  assert.equal(ls[0], "drafts empties by t+6: 6 → 0 by t+30 if nothing changes (trusted 15 min)");
  assert.equal(ls[1], "in review leaves its expected level (below 5) at t+11: 3 → 12 by t+30 if nothing changes (trusted 15 min)");
  assert.equal(ls[2], "queued: 4 → 10 by t+30 if nothing changes (trusted 15 min)");
  assert.equal(ls.at(-1), "no projection: sailed (worse than holding); parked (no level measured)", "every no projection with its reason");
  assert.equal(ls.length, 4, "nothing holds here, so no 'and N more'");
});

test("a stock whose flow is not moving as its equation says has no projection: equations wrong now", () => {
  const differs = (f) => f.id === "started";
  assert.equal(Projection.reason(model, sim, "queued", differs), "equations wrong now");
  assert.equal(Projection.reason(model, sim, "drafts", differs), null);
  assert.match(Projection.strip(model, sim, { ...o, differs }), /no projection: queued, in review \(equations wrong now\); sailed \(worse than holding\); parked \(no level measured\)/);
  // a flow replayed (too few events) is never judged against an equation it does not have
  assert.equal(Projection.reason(model, sim, "in_review", (f) => f.id === "parked_in"), null);
});

test("at most six lines; the rest are counted, and stocks that hold say nothing", () => {
  const many = { ...model, stocks: [], flows: model.flows }, s = { ...sim, stocks: {}, projection: {} };
  for (let i = 0; i < 9; i++) { const id = `s${i}`; many.stocks.push({ id, name: `step ${i}` }); s.stocks[id] = { start: 1, end: 2 + i, trust: null, no_projection: null }; s.projection[id] = [[sim.now, 1], [sim.now + 1800, 2 + i]]; }
  for (let i = 0; i < 3; i++) { const id = `h${i}`; many.stocks.push({ id, name: `hold ${i}` }); s.stocks[id] = { start: 5, end: 5.1, trust: null, no_projection: null }; s.projection[id] = [[sim.now, 5], [sim.now + 1800, 5.1]]; }
  const ls = lines(Projection.strip(many, s, { ...o, names: { stock: (id) => many.stocks.find((x) => x.id === id).name } }));
  assert.equal(ls.length, 7);
  assert.match(ls[0], /^step 8: 1 → 10 .*\(trust not measured\)$/, "the largest move first; no band without a trust");
  assert.equal(ls[6], "and 3 more that move, 3 that hold");
  assert.ok(!ls.some((l) => l.startsWith("hold")));
  const fewer = { ...many, stocks: many.stocks.slice(7) };
  assert.equal(lines(Projection.strip(fewer, s, { ...o, names: { stock: (id) => many.stocks.find((x) => x.id === id).name } })).at(-1), "and 3 more that hold");
});

test("with no fitted flow, or a simulation that failed, the strip is one line saying why", () => {
  const bare = { ...model, flows: model.flows.map((f) => ({ ...f, current: { ...f.current, quality: { events: 1 } } })) };
  assert.deepEqual(lines(Projection.strip(bare, sim, o)), ["No projection: the model has no fitted flows yet, so its equations say nothing of what comes next."]);
  assert.deepEqual(lines(Projection.strip(model, { ok: false, error: "no history yet" }, o)), ["No projection: no history yet."]);
});

test("the flows table's count: what the equation moves over the horizon, blank where there is no projection", () => {
  const f = (id) => model.flows.find((x) => x.id === id);
  assert.equal(Projection.count(sim, f("assigned")), 18);
  assert.equal(Projection.count(sim, f("parked_in")), null, "replayed: too few events for an equation");
  assert.equal(Projection.count(sim, f("started"), (g) => g.id === "started"), null, "not moving as its equation says now");
});

test("the chart's band: shaded within what was tested, lighter beyond, inside the frame", () => {
  globalThis.window = globalThis; globalThis.addEventListener = () => {};
  globalThis.document = { dispatchEvent() {}, addEventListener() {}, getElementById: () => null, createElement: () => ({}), scripts: [] };
  globalThis.location = { pathname: "/dynamics" }; globalThis.fetch = () => new Promise(() => {});
  for (const f of ["app.js", "charts.js"]) vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static", f), "utf8"), { filename: f });
  const hist = fix("history.json").stocks.queued, s = sim.stocks.queued, [tested, beyond] = Projection.bands(s);
  assert.ok(tested.length > 2 && beyond.length > 2 && tested.at(-1)[0] === beyond[0][0] && tested.at(-1)[0] === s.tested_until);
  const w = (b) => b.at(-1)[2] - b.at(-1)[1];
  assert.ok(w(beyond) > 2 * w(tested), "it widens past what was tested");
  for (const W of [1200, 358]) {
    const svg = Charts.line([{ label: "queued", points: hist, step: true, color: "#60a5fa" },
      { label: "queued, projected", points: sim.projection.queued, color: "#60a5fa", dash: "5 3", nokey: true },
      { label: "t", points: [], band: tested, color: "#60a5fa", nokey: true, bandOpacity: 0.2 }, { label: "b", points: [], band: beyond, color: "#60a5fa", nokey: true, bandOpacity: 0.08 }],
      { W, H: 220, now: sim.now, range: [hist[0][0], sim.now + sim.horizon], marks: [{ t: sim.now, label: "now" }],
        notes: [{ t: sim.now, v: 12, text: "worse than holding", anchor: "start" }] });
    const bands = [...svg.matchAll(/<path class="band"[^>]*fill-opacity="([\d.]+)" d="([^"]+)"/g)];
    assert.deepEqual(bands.map((b) => b[1]), ["0.2", "0.08"]);
    const xs = bands.flatMap((b) => [...b[2].matchAll(/[ML]([\d.]+),/g)].map((m) => +m[1]));
    assert.ok(Math.max(...xs) <= W - 8 + 0.1 && Math.min(...xs) >= 46, `the band stays inside the frame at ${W}`);
    assert.match(svg, /stroke-dasharray="5 3"/);
    assert.equal((svg.match(/<span data-i=/g) || []).length, 1, "the projection and its bands have no key of their own");
    assert.match(svg, /text-anchor="start"[^>]*>worse than holding</);
    assert.match(svg, />\+30 min</, "the future is said from now");
  }
});
