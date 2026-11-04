// The left-out explorer's drawer (explain-drawer.js) rendered from a discovery record (sd/explain.py):
// the owner's case, per-method gauges of a per-interval count under one match with nothing else
// there, says in words that it is a rate, that nothing under the match could drive or balance it,
// and what to add; and a kept stock's drawer says why it was kept.
import test from "node:test"; import assert from "node:assert/strict"; import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const Explain = require("../../orchestra/web/static/explain-drawer.js");
const OWNER = require("./owner-case.json");      // tests/unit/test_discover_explain.py's owner_case, method A
const href = (store, q, w) => `/core#store=${encodeURIComponent(store)}&q=${encodeURIComponent(q)}&w=${w}`;
const text = (html) => html.replace(/<[^>]+>/g, " ").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ");

test("the owner's per-interval count: a rate, nothing under the match to drive or balance it, and what to add", () => {
  const html = Explain.html(OWNER.key, OWNER, { href }), t = text(html);
  assert.match(t, /It reads as a rate: each reading is new/);
  assert.match(t, /A per-interval count \(calls per scrape interval\) says how fast something happens, not how much is held/);
  assert.match(t, /there was no counter in the window at all, so nothing under the match could be its inflows and outflows/);
  assert.match(t, /R² 0\.00 is that of an empty balance, not a comparison with any other series/);
  assert.match(t, /The 2 other series under the match share its name/);
  assert.match(t, /What would help: a per-interval count is a rate.*nothing else under the match could drive or balance it/);
  assert.match(t, /such as calls in flight or a queue's depth, or widen the match to more families/);
  // the verdict is the record's sentence
  assert.ok(t.includes(OWNER.left_out));
});

test("the drawer shows the sparkline, the exact query copyable with a view link, the kind and the forms tried", () => {
  const html = Explain.html(OWNER.key, OWNER, { href });
  assert.match(html, /<svg class="xp-spark"[^>]*><polyline /);
  assert.match(html, /<code class="xp-q" style="user-select:all[^"]*">sum by \(method\) \(\{__name__=&quot;grpc_client_callMillis:count&quot;, method=~&quot;A\|B\|C&quot;\}\)<\/code>/);
  assert.match(html, /<a class="sv-view" href="\/core#store=chrono&amp;q=/);
  assert.match(text(html), /summed by its split over instance, pod/);
  assert.match(text(html), /Read as a gauge \(a level\): its source's definition reads it as a level\. 181 points, one every 60 s/);
  // the forms table: the constant as the reference, the one form tried, its R² and why it lost
  const rows = [...html.matchAll(/<tr><td class="num">([^<]+)<\/td><td>([^<]*)<\/td><td class="num">([^<]+)<\/td><td><b>([^<]+)<\/b>/g)].map((m) => [m[1], m[2], m[4]]);
  assert.deepEqual(rows, [["c", "none", "reference"], ["c + b × level", "its own level", "refuted"]]);
  assert.match(text(html), /never offered \(its own name\): chrono_grpc_client_callmillis_count\{method="B"\}, chrono_grpc_client_callmillis_count\{method="C"\}/);
  assert.match(text(html), /best balance none · R² 0\.00 against 0\.9 needed · no balance fits/);
});

test("a kept stock's drawer says why it was kept, with no 'what would help'", () => {
  const rec = { kept: true, stock: "shelf", verdict: "a stock: its changes are balanced by + baked − sold at R² 0.99 (at least 0.9 is needed), exact in 97% of steps",
    kind: { as: "gauge", why: "not named a counter (_total), or it falls: a level", evidence: { points: 90, min: 0, max: 30, whole: true, falls: 40, never_falls: false } },
    read: { source: "own", query: 'shelf{machine="shop"}', window: [0, 3600], step: 30, points: 90, span_s: 3570, min: 0, max: 30, spark: [1, 2, null, 4] },
    roles: { balance: { in_window: 4, counters: { n: 3, keys: ["baked", "sold", "stale"] }, kept_apart: {}, terms: [{ series: "baked", sign: 1 }, { series: "sold", sign: -1 }], r2: 0.99, outcome: "fits", min_r2: 0.9 },
      input: { name: null, to_flows: [{ flow: "sold", chosen: true }], to_levels: [] } } };
  const html = Explain.html('shelf{machine="shop"}', { explain: rec, window: { start: 0, end: 3600 } }, { href, help: "never shown for a stock" }), t = text(html);
  assert.match(html, /<span class="tag">stock<\/span>/);
  assert.match(t, /fits at R² 0\.99\./);
  assert.ok(!/What would help/.test(t) && !/sv-view/.test(html));        // an own series has no store to view it in
  assert.match(html, /<polyline [^>]*points="[^"]+"\/><circle /);           // a gap splits the line; a lone point is a dot
});

test("a left-out series with counters to try falls back to its group's words", () => {
  const rec = { kept: false, verdict: "no counters balance it (best R² 0.40 with a)", kind: { as: "gauge", why: "x", evidence: {} }, read: {},
    roles: { balance: { in_window: 2, counters: { n: 2, keys: ["a", "b"] }, terms: [{ series: "a", sign: 1 }], r2: 0.4, outcome: "no balance fits", min_r2: 0.9 } } };
  assert.equal(Explain.help(rec, "What would help: add the counters."), "What would help: add the counters.");
  assert.match(Explain.story(rec).join(" "), /Tried as a level to balance with 2 counters as its possible moves: the best balance, \+ a, fits at R² 0\.40, short of the 0\.9 a stock needs\./);
});
