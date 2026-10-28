// Renders the Experiments pages' parts (static/experiment-view.js, predictions.js, charts.js)
// from the web routes' answers, as the pages do, without a browser:
//   node experiments_render.mjs <dir>
// <dir>/answers.json holds what tests/unit/test_experiment_pages.py read through the web app;
// the HTML of each part is printed as JSON, for the test to check.
import fs from "node:fs"; import path from "node:path"; import vm from "node:vm";

globalThis.window = globalThis;
globalThis.document = { dispatchEvent() {}, addEventListener() {}, getElementById: () => null, createElement: () => ({}), scripts: [], querySelectorAll: () => [] };
globalThis.location = { pathname: "/experiments", search: "", hash: "" };
globalThis.fetch = () => new Promise(() => {});
const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static");
for (const f of ["app.js", "charts.js", "predictions.js", "experiment-view.js"]) vm.runInThisContext(fs.readFileSync(path.join(STATIC, f), "utf8"), { filename: f });

const a = JSON.parse(fs.readFileSync(path.join(process.argv[2], "answers.json"), "utf8"));
const out = {};
for (const [name, x] of Object.entries(a.experiments)) {
  const nm = ExperimentView.namesOf(x.experiment);
  out[name] = { diff: ExperimentView.diff(x.diff, nm), log: ExperimentView.log(x.experiment.log, nm),
                prediction: x.prediction ? ExperimentView.prediction(x.prediction, x.experiment.prediction, nm) : "", runs: {} };
  for (const r of x.runs) {
    out[name].runs[r.run.mode] = r.run.mode === "forward" ? ExperimentView.forward(r.run, r.measured, nm, 600)
      : r.run.mode === "replay" ? ExperimentView.replay(r.run, nm, 600) : ExperimentView.inverse(r.run, nm, r.solved);
  }
}
out.predictions = a.predictions.map((p) => Predictions.one(p));
// an expected equation: its params are an object, not the comparison's rows (it once broke the Dynamics page)
const eq = { kind: "equation", flow: "arrive", equation: "2 * c", params: { c: 1 } };
out.equation = Predictions.one({ status: "judged", source: "ops", expect: [eq], horizon_s: 600, era: "e1",
  verdict: { verdict: "side effect", expectations: [{ ...eq, status: "different", law: { expected: 10, events: 20, z: 3 } }] } });
process.stdout.write(JSON.stringify(out));
