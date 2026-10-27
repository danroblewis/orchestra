// The rows Orchestra draws on every machine's card (Orchestra.machineCards.rows in app.js): what
// it observed and what the machine announced, under whatever the machine's package drew.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

// app.js and machine-dialog.js are page scripts: give them the little of the browser they touch at load
globalThis.window = globalThis;
globalThis.document = { dispatchEvent() {}, addEventListener() {}, getElementById: () => null, createElement: () => ({}), scripts: [] };
globalThis.location = { pathname: "/machines" };
globalThis.fetch = () => new Promise(() => {});
for (const f of ["app.js", "machine-dialog.js"]) vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static", f), "utf8"), { filename: f });

const now = Date.now() / 1000;
const m = { id: "baker", mode: "ad hoc", kind: "program", package: "bakery", publishes: [{ type: "order.baked", count: 12, day: 12, per_min_10m: 0 }, { type: "oven.opened", count: 40, day: 9, per_min_10m: 0.6 }],
            subscribes: ["order.assigned"], metrics: ['loaves_total{oven="1"}'], instances: [{ id: "1", first_seen: now - 100, last_seen: now - 5, active: true }], first_seen: now - 100, last_seen: now - 5, active: true };

test("every card names the package and what the machine listens for, whoever drew its head", () => {
  const rows = Orchestra.machineCards.rows(m);
  assert.match(rows, /package<\/span><span>bakery</);
  assert.match(rows, /listens for<\/span><span class="ty">order.assigned<\/span>/);
  assert.match(rows, /instances<\/span>.*> 1<\/span>/);
  assert.match(rows, /loaves_total\{oven=&quot;1&quot;\}/);
  const wrapped = Orchestra.machineCards.wrap(m, "<h3>the package's head</h3>" + rows);
  assert.ok(wrapped.startsWith('<div class="panel') && wrapped.includes("the package's head") && wrapped.includes("bakery"));
});

test("the mode tag's class has no space in it, and a kind is said as announced", () => {
  const rows = Orchestra.machineCards.rows(m);
  assert.match(rows, /class="tag k-ad_hoc">ad hoc</);
  assert.match(Orchestra.machineCards.rows({ ...m, mode: "continuous", kind: "service" }), /k-continuous">continuous<.*>service</);
  assert.match(Orchestra.machineCards.rows({ ...m, mode: null, kind: null, package: null, publishes: [], subscribes: [], metrics: [], instances: [], first_seen: null }), /not announced.*not announced.*no package.*no events yet.*nothing.*nothing.*none labelled machine="baker"/s);
});

test("a publishes chip shows the all-time count, and a rate only when there is one", () => {
  const rows = Orchestra.machineCards.rows(m);
  assert.match(rows, />order.baked · 12<\/span>/);
  assert.match(rows, />oven.opened · 40 · 0.6\/min<\/span>/);
  assert.match(rows, /title="12 events, 12 in 24 h, 0\/min in the last 10 min"/);
});
