// The rows Orchestra draws on every machine's card (Orchestra.machineCards.rows in app.js): what
// it observed and what the machine announced, under whatever the machine's package drew.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

// app.js and machine-dialog.js are page scripts: give them the little of the browser they touch at load
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.document = { dispatchEvent() {}, addEventListener() {}, getElementById: () => null, createElement: () => ({}), scripts: [] };
globalThis.location = { pathname: "/machines" };
globalThis.fetch = () => new Promise(() => {});
for (const f of ["app.js", "machine-dialog.js"]) vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static", f), "utf8"), { filename: f });

const now = Date.now() / 1000;
const m = { id: "baker", mode: "ad hoc", kind: "program", package: "bakery", publishes: [{ type: "order.baked", count: 12, day: 12, per_min_10m: 0 }, { type: "oven.opened", count: 40, day: 9, per_min_10m: 0.6 }],
            subscribes: ["order.assigned"], flows: [{ flow: "loaves_baked", name: "loaves <baked>", confidence: 0.92, why: "baker's order.baked events match its increments", hypothesis: true }], instances: [{ id: "1", first_seen: now - 100, last_seen: now - 5, active: true }], first_seen: now - 100, last_seen: now - 5, active: true };

test("every card names the package and what the machine listens for, whoever drew its head", () => {
  const rows = Orchestra.machineCards.rows(m);
  assert.match(rows, /package<\/span><span>bakery</);
  assert.match(rows, /listens for<\/span><span class="ty">order.assigned<\/span>/);
  assert.match(rows, /instances<\/span>.*> 1<\/span>/);
  // a machine's part in the model is a hypothesis, with its confidence; a series is never its own
  assert.match(rows, /flows \(hypotheses\)<\/span><a class="ty fl" href="\/dynamics#f:loaves_baked"[^>]*title="baker's order.baked events match its increments · open it on Dynamics">loaves &lt;baked&gt; · 92%</);
  assert.doesNotMatch(rows, /metrics|labelled machine/);
  const wrapped = Orchestra.machineCards.wrap(m, "<h3>the package's head</h3>" + rows);
  assert.ok(wrapped.startsWith('<div class="panel') && wrapped.includes("the package's head") && wrapped.includes("bakery"));
});

test("the mode tag's class has no space in it, and a kind is said as announced", () => {
  const rows = Orchestra.machineCards.rows(m);
  assert.match(rows, /class="tag k-ad_hoc">ad hoc</);
  assert.match(Orchestra.machineCards.rows({ ...m, mode: "continuous", kind: "service" }), /k-continuous">continuous<.*>service</);
  assert.match(Orchestra.machineCards.rows({ ...m, mode: null, kind: null, package: null, publishes: [], subscribes: [], flows: [], instances: [], first_seen: null }), /not announced.*not announced.*no package.*no events yet.*nothing.*nothing.*none hypothesised yet/s);
});

test("engaged and kind are rows of their own, so a narrow panel never wraps a kind under the engaged label", () => {
  const rows = Orchestra.machineCards.rows(m);
  assert.match(rows, /<div class="row"><span class="muted">engaged<\/span><span><span class="tag k-ad_hoc">ad hoc<\/span><\/span><\/div>/);
  assert.match(rows, /<div class="row"><span class="muted" data-k="kind">kind<\/span><span><span class="tag">program<\/span><\/span><\/div>/);
});

test("a publishes chip shows the all-time count, and a rate only when there is one", () => {
  const rows = Orchestra.machineCards.rows(m);
  assert.match(rows, />order.baked · 12<\/span>/);
  assert.match(rows, />oven.opened · 40 · 0.6\/min<\/span>/);
  assert.match(rows, /title="12 events, 12 in 24 h · none in the last 10 min"/);
  // the rate says the count it is of, and its window; a quiet machine's chips are counts alone
  assert.match(Orchestra.machineCards.rows({ ...m, publishes: [{ type: "oven.opened", count: 40, day: 9, n_10m: 6, window_s: 600, per_min_10m: 0.6 }] }), /title="40 events, 9 in 24 h, 6 in the last 10 min: 0.6\/min">oven.opened · 40 · 0.6\/min</);
  const quiet = Orchestra.machineCards.rows({ ...m, active: false });
  assert.match(quiet, />oven.opened · 40<\/span>/);
  assert.match(quiet, /quiet: no rate/);
  assert.match(Orchestra.machineCards.rows({ ...m, publishes: [{ type: "once", count: 1, day: 1, n_10m: 1, window_s: 600, per_min_10m: 0.1 }] }), /title="1 events, 1 in 24 h · seen once: no rate">once · 1</);
});

test("a card's seen row says the state in words, with the rule it was judged by; the host's is the runtime record's", () => {
  const rows = Orchestra.machineCards.rows({ ...m, instances: [{ ...m.instances[0], cadence_s: 12 }] });
  assert.match(rows, /in rhythm<\/span> <span class="muted">· usual gap 12s · last event 5s ago/);
  assert.match(Orchestra.machineCards.rows({ ...m, active: false, instances: [] }), /quiet since \d\d:\d\d/);
  assert.match(Orchestra.machineCards.rows({ ...m, first_seen: now - 20 }), /no cadence yet: judged by the 2-minute floor/);
  // heard for longer than a burst and still no cadence: its events never stop; how often, on average,
  // never "continuously" (beside an announced "ad hoc" that read as a contradiction, R2)
  const busy = Orchestra.liveness({ ...m, first_seen: now - 3600, last_seen: now - 3, publishes: [{ type: "x", count: 201 }] });
  assert.equal(busy.word, "active");
  assert.match(busy.detail, /^about every 18s · last event 3s ago$/);
  assert.doesNotMatch(busy.word + busy.detail, /rhythm|no cadence/);
  const host = Orchestra.liveness({ id: "orchestra-host", bootstrap: true, active: true, active_by: "runtime", last_seen: now - 600 });
  assert.equal(host.word, "running");
  assert.match(host.title, /runtime record/);
  assert.doesNotMatch(host.word + host.detail, /rhythm/);
});

test("the Dashboard's rows and notes add up to every machine on the Machines page", () => {
  const ms = [{ id: "a", mode: "continuous", active: true }, { id: "b", mode: "ad hoc", active: true }, { id: "c", mode: "ad hoc", active: false, last_seen: now - 900 },
              { id: "d", unseen: true }, { id: "sail", unseen: true, intent: { state: "declared", heard: false } },
              { id: "fci", unseen: true, intent: { state: "proposed", heard: false } }, { id: "e", mode: "scheduled", active: false, intent: { state: "declared", heard: true } }];
  const g = Orchestra.dashboardGroups(ms);
  assert.equal(g.rows.length + g.declared.length + g.proposed.length + g.quiet.length, ms.length);
  assert.deepEqual([g.rows, g.declared, g.proposed, g.quiet].map((x) => x.map((y) => y.id)), [["a", "b"], ["sail"], ["fci"], ["c", "d", "e"]]);
});

test("an instance whose own up series reads 0 is reported down, and one reading 1 is not", () => {
  const att = { instrument: "company_prom", instance_label: "runner", instances: { list: [{ value: "runner-1", measured: true }, { value: "runner-3", measured: true }] },
                series: [{ name: "sail_up", labels: { runner: "runner-1" }, value: 1 }, { name: "sail_up", labels: { runner: "runner-3" }, value: 0 }, { name: "sail_queue", labels: { runner: "runner-1" }, value: 0 }] };
  assert.deepEqual(Orchestra.downOf({ measured: { attachments: [att] } }), [{ instance: "runner-3", series: "sail_up", instrument: "company_prom" }]);
  assert.deepEqual(Orchestra.downOf({ measured: { unknown: true } }), []);
});

test("one palette for a machine's colour, defined once, in app.js", () => {
  const dir = path.resolve(import.meta.dirname, "../../orchestra/web/static");
  const defines = fs.readdirSync(dir).filter((f) => /\.(js|html)$/.test(f) && /const MPAL\s*=/.test(fs.readFileSync(path.join(dir, f), "utf8")));
  assert.deepEqual(defines, ["app.js"]);
  assert.equal(mcolor("worker"), mcolor("worker"));
  assert.equal(mcolor(null), "#94a3b8"); assert.equal(mcolor("none"), "#94a3b8");
});
