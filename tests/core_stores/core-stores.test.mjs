// CoreStores (core-stores.js): the Core page's external stores section. A store's row says where it
// is, how it is authenticated (never a secret), its match, caps and today's requests, its last read
// and error and what Orchestra keeps of it; a project with none says so; a section that cannot be
// read says why; completion asks only the bounded label endpoints.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static/core-stores.js"), "utf8") + "\nglobalThis.CoreStores = CoreStores;", { filename: "core-stores.js" });

const NOW = 1_800_000_000;
const STORE = {
  name: "shop", type: "prometheus", url: "http://127.0.0.1:8920", where: "http://127.0.0.1:8920", prefix: "shop",
  auth: { kinds: ["bearer"], credentials: [{ what: "bearer", from: "environment variable SHOP_TOKEN", present: false }], insecure: false },
  match: ['{namespace="shop"}'], max_series: 40, rate: 5, burst: 10, per_day: 2000,
  bucket: { store: { today: 12, per_day: 2000, held_s: 0 }, web: { today: 3, per_day: 400 }, web_share: 0.2 },
  last_ok: NOW - 120, last_error: { at: NOW - 30, error: "a selector needs a metric name", from: "this page" },
  inferred: { definitions: 14, inferred: 12, at: NOW - 3600, left_out: 2 },
};

test("a store's row says where, how, within what and how much", () => {
  const html = CoreStores.rowHtml(STORE, NOW);
  assert.match(html, /http:\/\/127\.0\.0\.1:8920/);
  assert.match(html, /bearer from environment variable SHOP_TOKEN · missing/);
  assert.match(html, /\{namespace=&quot;shop&quot;\}/);
  assert.match(html, /40 series at most · 5 requests\/s \(bursts of 10\) · 2,000 a day/);
  assert.match(html, /12 of 2,000 today \(UTC\), every reader of the store on this machine · this web server&#39;s 20%: 3 of 400/);
  assert.match(html, /<div>last read<\/div><div>2m ago<\/div>/);
  assert.match(html, /a selector needs a metric name<\/span> <span class="muted">\(this page, 30s ago\)/);
  assert.match(html, /14 series definitions kept \(12 inferred, 2 left out\) · inferred 1\.0h ago/);
});

test("a store never read and never inferred says so", () => {
  const html = CoreStores.rowHtml({ ...STORE, last_ok: null, last_error: null, inferred: null, auth: { kinds: [], credentials: [] } }, NOW);
  assert.match(html, /<div>last read<\/div><div>never<\/div>/);
  assert.match(html, /<div>last error<\/div><div>none<\/div>/);
  assert.match(html, /none yet: the host&#39;s discovery infers/);
  assert.match(html, /<div>auth<\/div><div>none<\/div>/);
});

test("the empty state, and a section that cannot be read", () => {
  assert.match(CoreStores.stateHtml({ ok: true, stores: [], refused: [] }), /class="empty".*declares no <code>\[\[sources\]\]<\/code> entry/);
  assert.match(CoreStores.stateHtml({ ok: false, error: "the external stores cannot be read: ImportError: x" }), /probe bad.*cannot be read: ImportError: x/);
  assert.equal(CoreStores.stateHtml({ ok: true, stores: [STORE], refused: [] }), null);
  assert.equal(CoreStores.stateHtml({ ok: true, stores: [], refused: [{ name: "bad", error: "why" }] }), null);
  assert.match(CoreStores.refusedHtml({ name: "bad", error: "a literal secret <x>" }), /<b>bad<\/b>: refused: a literal secret &lt;x&gt;/);
});

test("a value is escaped, never markup", () => {
  const html = CoreStores.rowHtml({ ...STORE, match: ['{a="<script>"}'], last_error: { at: NOW, error: "<img onerror=x>", from: "this page" } }, NOW);
  assert.ok(!html.includes("<script>") && !html.includes("<img"));
});

test("completion asks only the bounded label endpoints", () => {
  assert.deepEqual(CoreStores.lookup({ kind: "name", prefix: "q" }), ["label/__name__/values", { selector: "" }]);
  assert.deepEqual(CoreStores.lookup({ kind: "label", metric: "queue_depth" }), ["labels", { selector: "queue_depth" }]);
  assert.deepEqual(CoreStores.lookup({ kind: "value", metric: null, label: "pod" }), ["label/pod/values", { selector: "" }]);
  const c = CoreStores.cache();
  c.addNames(["up", "queue_depth"]);
  c.addLabels("queue_depth", ["__name__", "service", "pod"]);
  c.addValues("queue_depth", "service", ["worker", "api"]);
  c.addLabels("", ["namespace"]);
  assert.deepEqual(c.catalog().metrics.map((m) => m.name), ["queue_depth", "up"]);
  assert.deepEqual([...c.labelsOf("queue_depth").keys()].sort(), ["namespace", "pod", "service"]);
  assert.deepEqual([...c.labelsOf("queue_depth").get("service")].sort(), ["api", "worker"]);
});

test("an answer's note says what was sent and what was cut", () => {
  assert.equal(CoreStores.noteText({ matched: 60, lines: new Array(50), limit: 50, requests: 2, query: 'up{namespace="shop"}' }),
    '60 series, the first 50 shown (limit 50) · 2 requests · sent: up{namespace="shop"}');
  assert.match(CoreStores.instantHtml({ lines: [{ labels: { __name__: "up", job: "w" }, points: [[1, 1]] }] }), /up\{job=&quot;w&quot;\}<\/td><td class="num">1</);
  assert.match(CoreStores.instantHtml({ lines: [] }), /no series at this instant/);
});

test("the labels button narrows to the query's first selector", () => {
  assert.equal(CoreStores.firstSelector("sum by (service) (rate(http_requests_total[5m]))"), "http_requests_total");
  assert.equal(CoreStores.firstSelector('rate(queue_depth{service="a}b"}[5m]) / up'), 'queue_depth{service="a}b"}');
  assert.equal(CoreStores.firstSelector('{job="x"}'), '{job="x"}');
  assert.equal(CoreStores.firstSelector("time() + 1"), "");
  assert.equal(CoreStores.firstSelector(""), "");
});
