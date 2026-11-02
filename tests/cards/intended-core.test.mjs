// IntendedCore (intended-core.js): who the owner's requests reach. A placeholder a plugin declared
// but the bus never heard is no listener; asker() says the three cases: some, none known, unknown.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

globalThis.window = globalThis;
vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static/intended-core.js"), "utf8") + "\nglobalThis.IntendedCore = IntendedCore;", { filename: "intended-core.js" });
const REQ = "orchestra.intent.requested";

test("an unseen placeholder is not a listener", () => {
  const ms = [{ id: "operator", subscribes: [REQ] }, { id: "supervisor", subscribes: [REQ], unseen: true }, { id: "baker", subscribes: ["order.placed"] }];
  assert.deepEqual(IntendedCore.listenersOf(ms), ["operator"]);
  assert.deepEqual(IntendedCore.listenersOf([{ id: "supervisor", subscribes: [REQ], unseen: true }]), []);
});

test("asker says some, none and unknown", () => {
  const some = IntendedCore.asker(["operator"]), none = IntendedCore.asker([]), unknown = IntendedCore.asker(null);
  assert.equal(some.ask("link"), "ask operator to link");
  assert.equal(none.ask("link"), "no machine listens for requests to link: nothing will act on this");
  assert.equal(unknown.ask("link"), "ask the machine that listens for requests to link");
  const what = "declare what it is for", doing = "Declaring what it is for";
  assert.equal(some.sentence(what, doing), "To declare what it is for, ask operator.");
  assert.equal(none.sentence(what, doing), `Declaring what it is for needs a machine that listens for ${REQ}; none does, so nothing will act on it yet.`);
  assert.equal(unknown.sentence(what, doing), "To declare what it is for, ask the machine that listens for requests.");
});

test("declaredBy names who from the provenance, never how the call came", () => {
  assert.equal(IntendedCore.declaredBy({ state: "declared", provenance: { source: "integrator", author: "integrator", via: "plugin" } }), "declared by integrator");
  assert.equal(IntendedCore.declaredBy({ state: "declared", provenance: { author: "owner", via: "page" } }), "declared by you");
  // through a plugin or the endpoint, author: owner is the caller's assertion: the page says who made it
  assert.equal(IntendedCore.declaredBy({ state: "declared", provenance: { author: "owner", source: "worker/1", via: "endpoint", quote: "q" } }),
    "declared by owner (quoted), per worker/1");
  assert.equal(IntendedCore.declaredBy({ state: "proposed", provenance: { author: "owner", via: "plugin", quote: "q" } }), "proposed by owner (quoted), per a plugin");
  assert.equal(IntendedCore.declaredBy({ state: "proposed", provenance: { source: "agents", author: "agents" } }), "proposed by agents");
  assert.equal(IntendedCore.declaredBy({ state: "declared" }), "");
});

// The owner (2026-11-01): "What does confirmed or unconfirmed even mean here?" A declared machine's
// tag says what is observed and who said what; the word "unconfirmed" is gone.
test("a declared machine's tag says what is heard and who said what", () => {
  const w = (intent, extra = {}) => IntendedCore.machineWords({ id: "worker", package: "workflows", ...extra, intent });
  const plugin = { author: "workflows", provenance: { author: "workflows", source: "workflow delivery_sail" } };
  // heard: no tag at all (no tag means heard, everywhere); who said what is the line under it
  assert.deepEqual(w({ state: "proposed", heard: true, ...plugin }), { text: "", cls: "", by: "proposed by the workflows plugin (workflow delivery_sail)" });
  assert.equal(w({ state: "proposed", heard: false, ...plugin }).cls, "im-t-ghost");
  assert.equal(w({ state: "proposed", heard: false, ...plugin }).text, "proposed, never heard");
  assert.equal(w({ state: "declared", heard: true, author: "owner", provenance: { author: "owner", via: "page" } }).text, "");
  assert.equal(w({ state: "declared", heard: false, author: "owner", provenance: { author: "owner", via: "page" } }).text, "declared, never heard");
  const confirmed = w({ state: "declared", heard: true, ...plugin, confirmed: { by: "owner", via: "page" } });
  assert.equal(confirmed.text, "");                   // heard: no tag; who confirmed it is the line under it
  assert.equal(confirmed.by, "proposed by the workflows plugin (workflow delivery_sail), confirmed by you");
  assert.equal(w({ state: "proposed", heard: true, author: "ops", provenance: { source: "integrator" } }).by, "proposed by the Integrator");
  // a machine of no package, proposed by a plugin another machine on the bus belongs to; brief on the map
  const bot = { id: "bot.sail", intent: { state: "proposed", heard: true, ...plugin } };
  assert.equal(IntendedCore.machineWords(bot).by, "proposed by the Workflow delivery_sail");
  assert.equal(IntendedCore.machineWords(bot, [{ id: "worker", package: "workflows" }], true).by, "proposed by the workflows plugin");
  for (const it of [{ state: "proposed", heard: true }, { state: "proposed" }, { state: "declared" }]) assert.ok(!/unconfirmed/.test(JSON.stringify(w(it))));
});

test("the confirm control says what confirming does", () => {
  assert.equal(IntendedCore.asker(["supervisor"]).title(IntendedCore.CONFIRMS),
    "asks supervisor to adopt this proposal as a declaration; it changes nothing observed");
});
