// The Dashboard's "Where this is going" (where-panel.js): the projection's top three moves with a
// sparkline each, the predictions waiting and judged, and the equation misses; with no model, or a
// simulation that fails, it says so and renders the rest.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

globalThis.window = globalThis; globalThis.addEventListener = () => {};
globalThis.document = { dispatchEvent() {}, addEventListener() {}, getElementById: () => null, createElement: () => ({}), scripts: [] };
globalThis.location = { pathname: "/" }; globalThis.fetch = () => new Promise(() => {});
const registered = [];
for (const f of ["app.js", "evidence-text.js", "sd-graph.js", "flow-check.js", "projection.js", "predictions.js"])
  vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static", f), "utf8"), { filename: f });
const reg = Orchestra.panels.register; Orchestra.panels.register = (p) => { registered.push(p); return reg.call(Orchestra.panels, p); };
vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static/where-panel.js"), "utf8") + "\nglobalThis.Where = Where;", { filename: "where-panel.js" });

const fix = (f) => JSON.parse(fs.readFileSync(path.resolve(import.meta.dirname, "../fixtures/projection", f), "utf8"));
const model = fix("model.json"), sim = fix("simulate.json"), history = fix("history.json");
const now = sim.now, when = (t) => `t+${Math.round((t - now) / 60)}`;
const preds = { ok: true, predictions: [
  { id: "a", source: "supervisor", status: "waiting", expect: [{ kind: "factor", flow: "sailed_out", factor: 2 }], horizon_s: 7200, judge_at: now + 7200 },
  { id: "b", source: "curator", status: "waiting", expect: [], horizon_s: 3600, judge_at: null },
  ...[1, 2, 3, 4].map((i) => ({ id: `j${i}`, source: "supervisor", status: "judged", expect: [{ kind: "unchanged", flow: "assigned" }], horizon_s: 600, verdict: { verdict: i === 4 ? "no effect" : "passed", judged_at: now - 600 * (5 - i) } }))] };
const text = (html) => html.replace(/<svg[\s\S]*?<\/svg>/g, "").replace(/<[^>]+>/g, "").replace(/&gt;/g, ">");

test("the panel is registered with the Dashboard, and goes above the Host on a phone", () => {
  const p = registered.find((x) => x.id === "where");
  assert.equal(p.title, "Where this is going");
  assert.notEqual(p.phone, "last");
});

test("with a model: the top three moves with a sparkline each, the predictions, the misses", () => {
  const html = Where.render({ model, history, sim, preds, now, when, horizon: 30 });
  const moves = [...html.matchAll(/<div class="wmove">/g)];
  assert.equal(moves.length, 3);
  assert.equal((html.match(/<svg class="pspark"/g) || []).length, 3);
  assert.match(html, /stroke-dasharray="3 2"/, "the projection dashed after the history");
  const t = text(html);
  assert.match(t, /drafts empties by t\+6: 6 → 0 by t\+30 if nothing changes \(trusted 15 min\)/);
  // names as the Dynamics page gives them (SDGraph): a hidden stock by where it sits
  assert.match(t, new RegExp(`no projection: sailed \\(worse than holding\\); ${SDGraph.stockName(model, "parked")} \\(no level measured\\)`));
  assert.ok(t.includes(`supervisor predicted ${SDGraph.flowName(model, model.flows[2])} ×2, judged in 2 h`));
  assert.match(t, /curator predicted nothing changes, waiting for its change to begin an era/);
  const verdicts = [...t.matchAll(/unchanged: (\w[\w ]*) \(/g)].map((m) => m[1]);
  assert.deepEqual(verdicts, ["no effect", "passed", "passed"], "the last three verdicts, newest first");
  assert.match(t, /Every fitted flow moves as its equation says/);
});

test("a flow not moving as its equation says is named by its ends", () => {
  const h = structuredClone(history); h.flows.sailed_out = h.flows.sailed_out.map(([t]) => [t, 3]);
  const t = text(Where.render({ model, history: h, sim, preds, now, when, horizon: 30 }));
  assert.match(t, /in review → sailed is not moving as its equation says \(equation 0\.1\/min, observed 3\/min\)/);
});

test("no model: 'no model yet', and the predictions still shown", () => {
  const t = text(Where.render({ model: null, modelError: "nothing balances yet", history: null, sim: null, preds, now, when, horizon: 30 }));
  assert.match(t, /no model yet: nothing balances yet/);
  assert.match(t, /supervisor predicted/);
  assert.doesNotMatch(t, /Equation misses/);
});

test("the simulation fails: 'projection unavailable' with its error, and the rest stands", () => {
  const t = text(Where.render({ model, history, sim: { ok: false, error: "reading the history for the first time…" }, preds: null, now, when, horizon: 30 }));
  assert.match(t, /projection unavailable: reading the history for the first time…/);
  assert.match(t, /not read: the server did not answer/);
  assert.match(t, /Every fitted flow moves as its equation says/);
});
