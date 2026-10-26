// What the Dynamics page calls stocks and flows (SDGraph.names): by what tells them apart, with the
// series' name as their family.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const SDGraph = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/sd-graph.js"));

const stock = (id, name, labels) => ({ id, name: id, series: name ? { name, labels: { project: "p", machine: "beads", ...labels } } : null });
const flow = (id, from, to, name, labels) => ({ id, name: id, from, to, counter: { name, labels: { project: "p", machine: "w", ...labels } } });
const model = {
  stocks: [stock("o", "beads_issues", { status: "open", type: "task" }), stock("p", "beads_issues", { status: "in_progress", type: "task" }),
           stock("c", "beads_issues", { status: "closed", type: "task" }), stock("e", "beads_issues", { status: "open", type: "epic" }),
           stock("q", "bus_queue_length", {}), stock("h", null, {})],
  flows: [flow("op", "o", "p", "beads_issue_transitions_total", { from: "open", to: "in_progress", type: "task" }),
          flow("pc", "p", "c", "beads_issue_transitions_total", { from: "in_progress", to: "closed", type: "task" }),
          flow("px", "p", null, "beads_issue_transitions_total", { from: "in_progress", to: "dropped", type: "task" }),
          flow("ne", null, "e", "beads_issues_created_total", { type: "epic" }),
          { id: "u", name: "outside → h", from: null, to: "h" }],
};

test("a stock is named by what tells it apart within its series, the series is its family", () => {
  const n = SDGraph.names(model).stocks;
  assert.deepEqual([n.o.name, n.p.name, n.c.name, n.e.name], ["open", "in progress", "closed", "open · epic"]);
  assert.equal(n.o.family, "beads issues");
});

test("a series alone is named by itself; an unmeasured stock by its own name", () => {
  const n = SDGraph.names(model).stocks;
  assert.deepEqual([n.q.name, n.q.family], ["bus queue length", ""]);
  assert.equal(n.h.name, "h");
});

test("a flow is named by its series, without what its ends already say", () => {
  const f = (id) => SDGraph.flowName(model, model.flows.find((x) => x.id === id));
  assert.equal(f("op"), "beads issue transitions");
  assert.equal(f("px"), "beads issue transitions · dropped");
  assert.equal(f("ne"), "beads issues created");
  assert.equal(f("u"), "unmeasured inflow");
});

test("a namespace shared by several lone series becomes their family", () => {
  const m = { stocks: [stock("a", "bakery_orders_baking", {}), stock("b", "bakery_shelf_items", {}), stock("c", "yelp_rating", {})], flows: [] };
  const n = SDGraph.names(m).stocks;
  assert.deepEqual([n.a.name, n.a.family, n.b.name, n.c.name, n.c.family], ["orders baking", "bakery", "shelf items", "yelp rating", ""]);
});

test("names stay unique when the usual value is left out", () => {
  const m = { stocks: [stock("a", "q", { k: "x", t: "u" }), stock("b", "q", { k: "x", t: "u" , z: "1"}), stock("c", "q", { k: "y", t: "u", z: "2" }), stock("d", "q", { k: "x", t: "v", z: "1" })], flows: [] };
  const names = Object.values(SDGraph.names(m).stocks).map((v) => v.label);
  assert.equal(new Set(names).size, names.length, names.join(" | "));
});
