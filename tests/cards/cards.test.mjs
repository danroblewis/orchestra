// The rows Orchestra draws on every machine's card (Orchestra.machineCards.rows in app.js): what
// it observed and what the machine announced, under whatever the machine's package drew.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm"; import { createRequire } from "node:module";

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
  assert.match(rows, /flows \(hypotheses\)<\/span><a class="ty fl" href="\/dynamics#f:loaves_baked"[^>]*title="baker's order.baked events match its increments · open it on Dynamics">loaves &lt;baked&gt;</);   // no flow record: no number
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
  const rows = Orchestra.machineCards.rows({ ...m, cadence_s: 12 });
  assert.match(rows, /class="lv-live"[^>]*>active<\/span> <span class="muted">· about every 12s; last 5s ago/);
  assert.match(Orchestra.machineCards.rows({ ...m, active: false, instances: [] }), />quiet<\/span> <span class="muted">· since \d\d:\d\d/);
  // no cadence: no rhythm to be in, neutral, never "in rhythm"
  const plain = Orchestra.liveness({ ...m, first_seen: now - 20 });
  assert.equal(plain.word, "heard 5s ago"); assert.equal(plain.cls, "neutral");
  assert.doesNotMatch(Orchestra.machineCards.rows({ ...m, first_seen: now - 20 }), /in rhythm/);
  // past 2.5× its own cadence but inside the 2-minute floor: late, amber
  const late = Orchestra.liveness({ ...m, subscribes: [], last_seen: now - 60, cadence_s: 12 });
  assert.equal(late.word, "late by its own rhythm"); assert.equal(late.cls, "late"); assert.match(late.detail, /about every 12s; last 1m ago/);
  // its only event is its own announcement
  assert.equal(Orchestra.liveness({ ...m, publishes: [] }).word, "announced, nothing published yet");
  // what it listens for arrives and it does not act: not answering, whatever its rhythm
  const hung = Orchestra.liveness({ ...m, unanswered: { "order.assigned": { count: 3, since: now - 300 } } });
  assert.equal(hung.cls, "late"); assert.match(hung.word, /^not answering: 3 order.assigned since \d\d:\d\d/);
  assert.equal(Orchestra.liveness({ ...m, unanswered: { "order.assigned": { count: 1, since: now - 30 } } }).cls !== "late", true);   // inside the floor: not yet
  assert.match(Orchestra.machineCards.rows({ ...m, unanswered: { "order.assigned": { count: 3, since: now - 300 } } }), /order.assigned<\/span> <span class="lv-late"[^>]*>3 since its last event</);
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

test("the Dashboard's rows and notes add up to every machine on the Machines page, grouped by the header's words", () => {
  const seen = (id, x) => ({ id, publishes: [{ type: "t", count: 5 }], first_seen: now - 900, ...x });
  const ms = [seen("a", { mode: "continuous", active: true, last_seen: now - 5, cadence_s: 30 }), seen("b", { mode: "ad hoc", active: true, last_seen: now - 5 }),
              seen("c", { mode: "ad hoc", active: false, last_seen: now - 900 }), seen("q", { mode: "continuous", active: false, last_seen: now - 900 }),
              seen("hung", { mode: "ad hoc", active: false, last_seen: now - 900, subscribes: ["x"], unanswered: { x: { count: 4, since: now - 600 } } }),
              { id: "d", unseen: true }, { id: "sail", unseen: true, intent: { state: "declared", heard: false } },
              { id: "fci", unseen: true, intent: { state: "proposed", heard: false } }, seen("e", { mode: "scheduled", active: false, last_seen: now - 900, intent: { state: "declared", heard: true } })];
  const g = Orchestra.dashboardGroups(ms);
  assert.equal(g.rows.length + g.declared.length + g.proposed.length + g.quiet.length + g.unseen.length, ms.length);
  assert.deepEqual([g.rows, g.declared, g.proposed, g.quiet, g.unseen].map((x) => x.map((y) => y.id)), [["a", "b", "hung"], ["sail"], ["fci"], ["c", "q", "e"], ["d"]]);
  // the quiet note is exactly the header's quiet ones; a machine not answering is a row, never folded into quiet
  assert.equal(g.quiet.length, ms.filter((x) => Orchestra.livenessGroup(x) === "quiet").length);
  assert.equal(Orchestra.livenessGroup(ms[4]), "not answering");
});

test("a machine's rhythm is its merged beats, never its least-used or busiest instance's", () => {
  // worker/1 rare, worker/2 busy: the machine's own beats say about every 5 min; heard 100 s ago is active
  const w = { id: "worker", publishes: [{ type: "t", count: 50 }], subscribes: [], first_seen: now - 7200, last_seen: now - 100, active: true, cadence_s: 300,
              instances: [{ id: "worker/1", cadence_s: 900, active: true }, { id: "worker/2", cadence_s: 20, active: true }] };
  const lv = Orchestra.liveness(w);
  assert.equal(lv.word, "active"); assert.match(lv.detail, /about every 5m/);
});

test("idle after a run with nothing it listens for waiting is quiet, not late", () => {
  const w = { id: "worker", publishes: [{ type: "t", count: 50 }], subscribes: ["work.offered"], first_seen: now - 7200, last_seen: now - 60, active: true, cadence_s: 12 };
  const lv = Orchestra.liveness(w);
  assert.equal(lv.word, "quiet: nothing it listens for is waiting"); assert.equal(lv.cls, "quiet");
});

test("a continuous machine with no cadence, silent six times its average gap, is late by its own rhythm", () => {
  // 361 events over an hour: one every 10 s; silent 60 s
  const w = { id: "pump", publishes: [{ type: "t", count: 361 }], subscribes: [], first_seen: now - 3660, last_seen: now - 60, active: true };
  const lv = Orchestra.liveness(w);
  assert.equal(lv.word, "late by its own rhythm"); assert.equal(lv.cls, "late");
  assert.equal(Orchestra.liveness({ ...w, last_seen: now - 5 }).word, "active");
});

test("each unanswered type has its own count, and a type no listener answered is said once with its listeners", () => {
  const u = Orchestra.unanswered({ unanswered: { "offer.made": { count: 4, since: now - 600 }, "offer.withdrawn": { count: 4, since: now - 500 } } });
  assert.match(u.text, /^4 offer.made, 4 offer.withdrawn since \d\d:\d\d/);
  const lines = Orchestra.unansweredTypes({ unanswered_types: [{ type: "work.offered", count: 8, since: now - 600, listeners: ["nudger", "worker"] }, { type: "fresh", count: 1, since: now - 10, listeners: ["a", "b"] }] });
  assert.equal(lines.length, 1);
  assert.match(lines[0], /^8 work.offered since \d\d:\d\d[^,]*, answered by none of its listeners: nudger, worker$/);
});

test("a card's flow chip says the hypothesis as Dynamics does: confidence and chance, no number when timing cannot tell", () => {
  globalThis.Evidence = createRequire(import.meta.url)("../../orchestra/web/static/evidence-text.js");
  const rec = (hs) => ({ current: { origin: "fitted", quality: { events: 40 } }, machines: hs });
  const one = { flow: "f", name: "f", confidence: 0.62, chance: 0.1, record: rec([{ machine: "baker", confidence: 0.62, chance: 0.1 }]) };
  assert.match(Orchestra.machineCards.rows({ ...m, flows: [one] }), />loaves &lt;baked&gt;|· 62%, 10% by chance</);
  const crowd = { ...one, record: rec([{ machine: "baker", confidence: 0.62 }, { machine: "a", confidence: 0.6 }, { machine: "b", confidence: 0.58 }]) };
  const rows = Orchestra.machineCards.rows({ ...m, flows: [crowd] });
  assert.doesNotMatch(rows, /62%/);
  assert.match(rows, /title="timing cannot tell it from 2 others/);
  const few = { ...one, record: { ...rec(one.record.machines), current: { origin: "fitted", quality: { events: 2 } } } };
  assert.doesNotMatch(Orchestra.machineCards.rows({ ...m, flows: [few] }), /62%/);
  delete globalThis.Evidence;
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

test("what a machine announced beyond what Orchestra reads is printed as key: value lines, disabled first", () => {
  const noted = { ...m, package: null, about: { fake: true, writes: ["slack.post", "slack.dm"], disabled: "token expired", stand_in: "for the reviewer" } };
  assert.deepEqual(Orchestra.aboutLines(noted), ["disabled: token expired", "fake: true", "writes: slack.post, slack.dm", "stand_in: for the reviewer"]);
  const rows = Orchestra.machineCards.rows(noted);       // no package card registered: Orchestra's rows still say it
  assert.match(rows, /announced<\/span><span class="about"><div class="about-line">disabled: token expired<\/div><div class="about-line">fake: true</);
  assert.match(Orchestra.machineCards.rows({ ...noted, package: "bakery" }), /disabled: token expired/);
  assert.match(Orchestra.aboutHtml({ about: { disabled: "<b>x</b>" } }), /disabled: &lt;b&gt;x&lt;\/b&gt;/);
  assert.doesNotMatch(Orchestra.machineCards.rows({ ...m, about: {} }), /announced</);
});
