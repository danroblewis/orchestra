// What the Dynamics page calls stocks and flows (SDGraph.names): by what tells them apart, with the
// series' name as their family.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const SDGraph = require(path.resolve(import.meta.dirname, "../../orchestra/web/static/sd-graph.js"));

const stock = (id, name, labels) => ({ id, name: id, series: name ? { name, labels: { project: "p", machine: "beads", ...labels } } : null });
const flow = (id, from, to, name, labels) => ({ id, name: id, from, to, counter: { name, labels: { project: "p", machine: "w", ...labels } } });
const model = {
  stocks: [stock("o", "beads_issues", { status: "open", type: "loaf" }), stock("p", "beads_issues", { status: "in_progress", type: "loaf" }),
           stock("c", "beads_issues", { status: "closed", type: "loaf" }), stock("e", "beads_issues", { status: "open", type: "cake" }),
           stock("q", "bus_queue_length", {}), stock("h", null, {})],
  flows: [flow("op", "o", "p", "beads_issue_transitions_total", { from: "open", to: "in_progress", type: "loaf" }),
          flow("pc", "p", "c", "beads_issue_transitions_total", { from: "in_progress", to: "closed", type: "loaf" }),
          flow("px", "p", null, "beads_issue_transitions_total", { from: "in_progress", to: "dropped", type: "loaf" }),
          flow("ne", null, "e", "beads_issues_created_total", { type: "cake" }),
          { id: "u", name: "outside → h", from: null, to: "h" }],
};

test("a stock is named by what tells it apart within its series, the series is its family", () => {
  const n = SDGraph.names(model).stocks;
  assert.deepEqual([n.o.name, n.p.name, n.c.name, n.e.name], ["open", "in_progress", "closed", "open · cake"]);
  assert.equal(n.o.family, "beads issues");
});

test("a series alone is named by itself; an unmeasured stock by its own name", () => {
  const n = SDGraph.names(model).stocks;
  assert.deepEqual([n.q.name, n.q.family], ["bus queue length", ""]);
  assert.equal(n.h.name, "h");
});

test("a flow is named by its counter: who moved what from where to where, other labels with their key", () => {
  const f = (id) => SDGraph.flowName(model, model.flows.find((x) => x.id === id));
  assert.equal(f("op"), "beads issue transitions · open → in_progress");
  assert.equal(f("px"), "beads issue transitions · in_progress → dropped");
  assert.equal(f("ne"), "beads issues created · type cake");          // a family of one counter says its other labels
  assert.equal(f("u"), "unmeasured inflow");
  const by = { stocks: [], flows: [flow("a", null, null, "t_total", { by: "worker", from: "REJECTED" }), flow("b", null, null, "t_total", { by: "planner", status: "landed" }),
                                   flow("c", null, null, "t_total", { by: "planner", status: "failed" })] };
  assert.deepEqual(by.flows.map((x) => SDGraph.flowName(by, x)), ["t · worker: from REJECTED", "t · planner, status landed", "t · planner, status failed"]);
});

test("a counter several flows share says so; two flows between the same ends are told apart", () => {
  const twin = (id, from, to) => flow(id, from, to, "t_total", { by: "w", from: "A", to: "B" });
  const m = { stocks: [], flows: [twin("x", "o", null), twin("y", null, "p"), flow("z", "o", null, "t_total", { by: "w", from: "A", to: "C" })] };
  const n = m.flows.map((x) => SDGraph.flowName(m, x));
  assert.deepEqual(n, ["t · w: A → B (one counter, 2 flows)", "t · w: A → B (one counter, 2 flows)", "t · w: A → C"]);
});

test("a flow's label names its machines as hypotheses: the leader with its confidence, a tie by names, none without one", () => {
  const f = (hs) => SDGraph.machineLabel({ machines: hs });
  assert.equal(f([{ machine: "planner", confidence: 0.94 }, { machine: "worker", confidence: 0.38 }]), "planner 94%?");
  assert.equal(f([{ machine: "reviewer", confidence: 1 }, { machine: "merge_gate", confidence: 0.99 }, { machine: "worker", confidence: 0.4 }]), "reviewer / merge_gate?");
  assert.equal(f([{ machine: "a", confidence: 0.9 }, { machine: "b", confidence: 0.9 }, { machine: "c", confidence: 0.89 }]), "3 machines?");
  assert.equal(f([{ machine: "a", confidence: null }]), "");
  assert.equal(f([]), "");
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

test("a flow measured by two counters of the same events is named by its own, and says the other's beside it", () => {
  const f = { ...flow("rd", "r", "d", "bakery_order_transitions_total", { from: "BOXED", to: "DELIVERED" }),
              evidence: { same_as: [{ name: "bakery_order_transitions_total", labels: { project: "p", machine: "w", from: "BAKING", to: "BOXED" } }] } };
  const m = { stocks: [stock("r", "bakery_orders", { state: "BAKING" }), stock("d", "bakery_orders", { state: "DELIVERED" })], flows: [f] };
  assert.equal(SDGraph.flowName(m, f), "bakery order transitions · BOXED → DELIVERED");
  assert.deepEqual(SDGraph.sameAs(m, f), ["bakery order transitions · BAKING → BOXED"]);
});

test("a stock a declared part sits beside is never hidden as one that only fills", () => {
  const acc = (id) => ({ ...stock(id, "bakery_orders", { state: id }), evidence: { accumulator: true } });
  const m = { stocks: [acc("done")], flows: [], machines: [] };
  assert.deepEqual([...SDGraph.build(m).acc], ["done"]);
  assert.deepEqual([...SDGraph.build(m, { keep: new Set(["done"]) }).acc], []);
});

test("a stock that only fills is drawn when a flow shown drains a stock into it", () => {
  const acc = (id) => ({ ...stock(id, "bakery_orders", { state: id }), evidence: { accumulator: true } });
  const withEvents = (f) => ({ ...f, current: { form: "constant", params: { c: 1 }, quality: { events: 5 } } });
  const m = { stocks: [stock("r", "bakery_orders", { state: "r" }), acc("done"), acc("tally")], machines: [],
              flows: [withEvents(flow("rd", "r", "done", "t_total", {})), withEvents(flow("x", null, "tally", "u_total", {}))] };
  const g = SDGraph.build(m);
  assert.deepEqual(g.nodes.filter((n) => n.sid).map((n) => n.sid).sort(), ["done", "r"]);
  assert.deepEqual([...g.acc], ["tally"]);
  assert.deepEqual(SDGraph.build(m, { showAcc: true }).nodes.filter((n) => n.sid).map((n) => n.sid).sort(), ["done", "r", "tally"]);
});

test("a label that names the stocks of two services' series says the service too", () => {
  const pods = (id, metric, svc, region) => ({ id, name: id, series: { name: `rig:${metric}_pods`, labels: { machine: `rig.${svc}`, service: svc, ...(region ? { region } : {}) } } });
  const m = { stocks: [pods("s", "app_latency", "search"), pods("se", "app_latency", "search", "eu-west"), pods("su", "app_latency", "search", "us-east"),
                       pods("ce", "http_duration", "checkout", "eu-west"), pods("cu", "http_duration", "checkout", "us-west")], flows: [] };
  const n = (id) => SDGraph.stockName(m, id);
  assert.deepEqual(["se", "su", "ce", "cu"].map(n), ["search · eu-west", "search · us-east", "checkout · eu-west", "checkout · us-west"]);
  assert.equal(n("s"), "rig:app latency pods");
  const tickets = { stocks: [stock("o", "tickets", { state: "open" }), stock("c", "tickets", { state: "closed" })], flows: [] };
  assert.equal(SDGraph.stockName(tickets, "o"), "open");          // one series' label: no machine needed
});

test("one series of a family several machines write keeps the qualifier that narrows it", () => {
  const m = { stocks: [{ id: "aw", name: "agents working (reviewer)", series: { name: "agents_working", labels: { machine: "reviewer", role: "reviewer", instrument: "agents.turns" } } },
                       stock("o", "tasks_tickets", { state: "OPEN" }), stock("p", "tasks_tickets", { state: "IN_PROGRESS" })], flows: [] };
  assert.equal(SDGraph.stockName(m, "aw"), "agents working (reviewer)");
  assert.equal(SDGraph.stockName(m, "o"), "OPEN");
});

test("a flow alone in its family says the labels that narrow its counter, and a shared counter says so after them", () => {
  const gate = { ...flow("g", null, "x", "tasks_gate_runs_total", { status: "landed", kind: "gate" }) };
  const twin = (id, a, b) => flow(id, a, b, "tasks_ticket_transitions_total", { by: "merge_gate", from: "APPROVED", to: "MERGING", state: "read" });
  const m = { stocks: [], flows: [gate, twin("t1", null, "m"), twin("t2", "r", null)] };
  assert.equal(SDGraph.flowName(m, gate), "tasks gate runs · kind gate, status landed");
  assert.equal(SDGraph.flowName(m, m.flows[1]), "tasks ticket transitions · merge_gate: APPROVED → MERGING, state read (one counter, 2 flows)");
});

test("an expected flow is drawn with no events, and its stock that only fills with it", () => {
  const acc = (id) => ({ ...stock(id, "bakery_orders", { state: id }), evidence: { accumulator: true } });
  const quiet = { ...flow("in", null, "fill", "fills_total", {}), current: { form: "constant", params: { c: 1 }, quality: { events: 0 } } };
  const m = { stocks: [acc("fill")], flows: [quiet], machines: [] };
  const plain = SDGraph.build(m);
  assert.deepEqual([plain.flows.length, plain.nodes.some((n) => n.sid === "fill")], [0, false]);
  const kept = SDGraph.build(m, { keep: new Set(["fill"]), keepFlows: new Set(["in"]) });
  assert.deepEqual(kept.flows.map((f) => f.id), ["in"]);
  assert.ok(kept.nodes.some((n) => n.sid === "fill") && !kept.acc.has("fill"));
});

// the owner, 2026-11-01, on the delivery_sail example: "write.held" read as a disk write, and
// "after work item moves (write.held, open_pr.waiting, delivery_sail)" as three things in one stock.
// The server names a part by its instrument's places (sd/titles.py, evidence.named); the page shows that name
const pile = (id, step, place, extra = {}) => ({ ...stock(id, "workflow_pile_items", { workflow: "delivery_sail", pile: `${step}.${place}`, step, place, instrument: "workflows.piles", ...extra }),
  name: `${step} (${place}) · ${extra.workflow || "delivery_sail"}`, evidence: { named: "places" } });
// what the instrument says of its series (collect/views.py), as the model carries it: never a label
const VIEWS = { "workflows.piles": { workflow_pile_items: [{ view: "count", place: "pile", where: { workflow: "delivery_sail", pile: "write.held" }, describes: "held at write" }, { view: "count", place: "pile" }],
                                     workflow_pile_oldest_seconds: [{ view: "age" }] } };
const move = (id, from, to, a, b, extra = {}) => flow(id, from, to, "workflow_pile_moves_total", { workflow: "delivery_sail", from: a, to: b, instrument: "workflows.piles", ...extra });

test("a part the server named by its places is shown by that name, its sentence beside it, underscores kept", () => {
  const m = { stocks: [pile("wh", "write", "held"), pile("ww", "write", "waiting"), pile("sc", "sail_check", "waiting")], flows: [], views: VIEWS };
  const n = SDGraph.names(m).stocks;
  assert.deepEqual([n.wh.name, n.ww.name, n.sc.name], ["write (held) · delivery_sail", "write (waiting) · delivery_sail", "sail_check (waiting) · delivery_sail"]);
  assert.equal(n.wh.about, "held at write");                   // the view's sentence: never in the name
  assert.equal(n.ww.about, "");                                // its view says nothing
  assert.equal(n.wh.family, "");
});

test("no label's name is known to the page: a series with step and place labels the server did not name is named by its labels", () => {
  const raw = stock("r", "workflow_pile_items", { workflow: "delivery_sail", pile: "write.held", step: "write", place: "held" });
  const n = SDGraph.names({ stocks: [raw], flows: [] }).stocks;
  assert.ok(!n.r.name.startsWith("write (held)"), n.r.name);
});

test("a stock no series measures and no place names is named by its neighbours, never after the counter that fills it", () => {
  const hidden = { id: "after_moves", name: "after workflow pile moves (write.held, open_pr.waiting, delivery_sail)", series: null, evidence: { hidden: true, passing: { ins: [], outs: [] } } };
  const m = { stocks: [pile("wh", "write", "held"), pile("ow", "open_pr", "waiting"), hidden],
              flows: [move("in", "wh", "after_moves", "write.held", "open_pr.waiting"), move("out", "after_moves", "ow", "write.held", "open_pr.waiting", { machine: "x" })] };
  assert.equal(SDGraph.stockName(m, "after_moves"), "between write (held) and open_pr (waiting) · delivery_sail");
  // one the server named by the places its moves name is shown by that name
  const placed = { ...hidden, id: "h3", name: "open_pr (waiting) … ci (waiting) · delivery_sail", evidence: { ...hidden.evidence, named: "places" } };
  assert.equal(SDGraph.stockName({ stocks: [placed], flows: [] }, "h3"), "open_pr (waiting) … ci (waiting) · delivery_sail");
});

test("a flow the server named by its places is shown by that name, never with the counter's family", () => {
  const f = { ...move("a", "wh", null, "write.held", "ci.waiting"), name: "write (held) → ci (waiting) · delivery_sail", evidence: { named: "places" } };
  assert.equal(SDGraph.flowName({ stocks: [pile("wh", "write", "held")], flows: [f] }, f), "write (held) → ci (waiting) · delivery_sail");
});

test("an instrument's series are shown by the server's title, else by their labels", () => {
  const r = { name: "workflow_pile_items", labels: { workflow: "delivery_sail", pile: "write.held", step: "write", place: "held" }, title: "write (held) · delivery_sail" };
  assert.deepEqual(SDGraph.seriesName(r, VIEWS, "workflows.piles"), { name: "write (held) · delivery_sail", family: "workflow pile items", about: "held at write" });
  assert.deepEqual(SDGraph.seriesName({ name: "floor_offers", labels: { role: "worker" } }), { name: "role worker", family: "floor offers", about: "" });
  assert.deepEqual(SDGraph.seriesName({ name: "git_branch_commits", labels: {} }), { name: "git branch commits", family: "", about: "" });
});

test("a hidden stock a strategy found is named by its neighbours; two named series of one name by their families", () => {
  const hid = { id: "x_hidden", name: "x hidden", series: null, evidence: { hidden: true, strategy: "kalman_lna" } };
  const m = { stocks: [pile("wh", "write", "held"), hid], flows: [{ id: "u", name: "u", from: "x_hidden", to: "wh" }, { id: "v", name: "v", from: null, to: "x_hidden" }], views: VIEWS };
  assert.equal(SDGraph.names(m).stocks.x_hidden.name, "between outside and write (held) · delivery_sail");
  const twin = { ...pile("age", "write", "held"), series: { name: "workflow_pile_oldest_seconds", labels: {} } };
  assert.equal(SDGraph.stockName({ stocks: [pile("wh", "write", "held"), twin], flows: [] }, "age"), "write (held) · delivery_sail · workflow pile oldest seconds");
});
