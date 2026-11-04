// SourceView (source-view.js): a series read from another store shows its selector as the store
// spells it, copyable, beside Orchestra's name, and links to the Core page's External stores box
// with the view's query (a counter's rate(), a gauge's selector) and the fitting window; the Core
// page reads the link back.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static/source-view.js"), "utf8") + "\nglobalThis.SourceView = SourceView;", { filename: "source-view.js" });

const COUNTER = { source: "chrono", kind: "counter", selector: 'Lens:Requests_Total{service_name="checkout",status="500"}',
  store_query: 'rate(Lens:Requests_Total{service_name="checkout",status="500"}[60s])' };

test("a row shows the store's own selector as text, and a link that runs the counter's rate()", () => {
  const html = SourceView.html(COUNTER, 3 * 3600);
  assert.match(html, /<code class="sv-sel"[^>]*>Lens:Requests_Total\{service_name=&quot;checkout&quot;,status=&quot;500&quot;\}<\/code>/);
  const href = html.match(/href="([^"]+)"/)[1].replace(/&amp;/g, "&");
  const back = SourceView.parse(href.slice(href.indexOf("#")));
  assert.deepEqual(back, { store: "chrono", q: COUNTER.store_query, mode: "range", minutes: 360 });
});

test("a gauge opens as its bare selector; a query as written as written", () => {
  const g = { source: "chrono", kind: "level", selector: 'queue_depth{queue="email"}', store_query: 'queue_depth{queue="email"}' };
  assert.equal(SourceView.parse(SourceView.href(g.source, g.store_query, 3600).slice(5)).q, 'queue_depth{queue="email"}');
  const w = { source: "chrono", kind: "rate", store_query: "sum(rate(x[5m]))" };
  assert.match(SourceView.html(w, 600), />sum\(rate\(x\[5m\]\)\)<\/code>/);
  assert.equal(SourceView.html({ source: "own" }), "");
});

test("the window is the Core page's smallest that holds the fitting window, a day at most", () => {
  assert.equal(SourceView.minutes(600), 15); assert.equal(SourceView.minutes(3600), 60); assert.equal(SourceView.minutes(7200), 360);
  assert.equal(SourceView.minutes(7 * 86400), 1440);
  assert.equal(SourceView.parse("#token=abc"), null); assert.equal(SourceView.parse("#store=x"), null);
});
