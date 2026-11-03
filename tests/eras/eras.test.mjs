// The Dynamics page's eras bar (dynamics.html erasBar) and its panel wrapper (paint), run as the
// page defines them: a prediction made before any era is recorded is drawn as waiting for its first
// era (SPEC §4.5: it waits until its change begins an era), and one panel's renderer failing says so
// in that panel only. The model is the third live walkthrough's (T2c, step 16), trimmed.
import test from "node:test"; import assert from "node:assert/strict";
import fs from "node:fs"; import path from "node:path"; import vm from "node:vm";

const STATIC = path.resolve(import.meta.dirname, "../../orchestra/web/static");
const page = fs.readFileSync(path.join(STATIC, "dynamics.html"), "utf8");
// a top-level function of the page's script, by name: from its line to the first closing brace at column 0
const fnSource = (name) => { const m = page.match(new RegExp(`^function ${name}\\(.*?\\n\\}\\n`, "ms")); assert.ok(m, `no function ${name} in dynamics.html`); return m[0]; };

function element(id) {
  const kids = [];
  return { id, innerHTML: "", textContent: "", style: {}, kids,
    querySelector: (sel) => (sel === ":scope > .panel-err" ? kids.find((k) => k.className.split(" ").includes("panel-err")) || null : null),
    insertAdjacentElement: (_, n) => { kids.unshift(n); n.isConnected = true; n.remove = () => { kids.splice(kids.indexOf(n), 1); n.isConnected = false; }; return n; } };
}
function pageContext(model) {
  const els = {};
  const ctx = { MODEL: model, console: { error() {} }, esc: (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
    nice: (s) => String(s).toLowerCase().replace(/_/g, " "), stockName: (id) => id, flowName: (f) => f.id, ago: () => "1 h",
    Orchestra: { when: () => "today" }, document: { createElement: () => ({ className: "", textContent: "" }) },
    $: (id) => (els[id] ||= element(id)), els };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(STATIC, "predictions.js"), "utf8") + "\nthis.Predictions = Predictions;", ctx);
  for (const f of ["erasBar", "eraKept", "eraPredictions", "eraChanges", "paint"]) vm.runInContext(fnSource(f), ctx);
  return ctx;
}
const model = { era: null, current_era: null, eras_recorded: [], flows: [{ id: "SAILED" }], stocks: [], discovery: {},
  predictions: [{ id: "6712cc47c20d49a79b470e6a5da747ee", source: "supervisor", made_at: 1793594621.241, subject: "machine:review_nudger",
    change: "dcb7e5407b6b4cef85b7dea6bdcfd298", expect: [{ kind: "factor", flow: "SAILED", factor: 1.2 }], horizon_s: 604800, status: "waiting", era: null }] };

test("a prediction and no era recorded: the bar says no era yet and the prediction waits for its first", () => {
  const ctx = pageContext(model);
  assert.doesNotThrow(() => vm.runInContext("erasBar()", ctx));
  const html = ctx.els.eras.innerHTML;
  assert.equal(ctx.els.eras.style.display, "");
  assert.match(html, /No era recorded yet: the first begins when a machine says it changed the system\. Each prediction below waits for its first era\./);
  assert.doesNotMatch(html, /class="eratl"/);              // no timeline without an era
  assert.match(html, /Predictions/); assert.match(html, /SAILED/);
});

test("no era and no prediction: the bar is hidden", () => {
  const ctx = pageContext({ ...model, predictions: [] });
  vm.runInContext("erasBar()", ctx);
  assert.equal(ctx.els.eras.style.display, "none");
});

test("one era recorded: the timeline is drawn, with the time before it", () => {
  const ctx = pageContext({ ...model, era: "e1", current_era: "e1", eras_recorded: [{ id: "e1", label: "review_nudger", start: Date.now() / 1000 - 3600 }] });
  vm.runInContext("erasBar()", ctx);
  assert.match(ctx.els.eras.innerHTML, /class="eratl"/); assert.match(ctx.els.eras.innerHTML, />before</); assert.doesNotMatch(ctx.els.eras.innerHTML, /No era recorded yet/);
});

test("an era with changes kept in it says them under its head, and in its button's title", () => {
  const changes = [{ id: "m1", type: "github.pr.merged", source: "bot.github.sail-bot", subject: "riff/hackriff#2", at: Date.now() / 1000 - 3000 },
    { id: "m2", type: "github.pr.merged", source: "bot.github.sail-bot", subject: "riff/hackriff#3", at: Date.now() / 1000 - 2700 }];
  const ctx = pageContext({ ...model, era: "e1", current_era: "e1",
    eras_recorded: [{ id: "e1", label: "github.pr.merged from bot.github.sail-bot", start: Date.now() / 1000 - 3600, changes }] });
  vm.runInContext("erasBar()", ctx);
  const html = ctx.els.eras.innerHTML;
  assert.match(html, /and 2 later changes kept in it, too soon after its start for an era of their own/);
  assert.match(html, /riff\/hackriff#3/); assert.match(html, /2 later changes kept in it · current/);
});

test("an era with no change kept in it says nothing of them", () => {
  const ctx = pageContext({ ...model, era: "e1", current_era: "e1", eras_recorded: [{ id: "e1", label: "x", start: Date.now() / 1000 - 3600 }] });
  vm.runInContext("erasBar()", ctx);
  assert.doesNotMatch(ctx.els.eras.innerHTML, /kept in it/);
});

test("a renderer that throws says so in its own panel only, and the note goes once it draws", () => {
  const ctx = pageContext(model);
  vm.runInContext(`paint("eras", () => { throw new Error("boom"); }); paint("tables", () => { $("tables").innerHTML = "ok"; });`, ctx);
  assert.equal(ctx.els.eras.kids[0].textContent, "this panel could not be drawn: boom");
  assert.equal(ctx.els.tables.innerHTML, "ok"); assert.equal(ctx.els.tables.kids.length, 0);
  vm.runInContext(`paint("eras", () => { throw new Error("again"); })`, ctx);
  assert.equal(ctx.els.eras.kids.length, 1); assert.equal(ctx.els.eras.kids[0].textContent, "this panel could not be drawn: again");
  vm.runInContext(`paint("eras", erasBar)`, ctx);
  assert.equal(ctx.els.eras.kids.length, 0);
});
