// The Machines page's details panel (IntendedMachines in intended-machines.js): opened, closed and
// opened again on the same machine, it is drawn again (its cache of what it last drew is cleared on
// close, so the same drawing is not skipped into an empty panel).
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

const el = (extra = {}) => ({ innerHTML: "", dataset: {}, style: {}, scrollTop: 0, classes: new Set(),
  classList: { add(c) { this.o.classes.add(c); }, remove(c) { this.o.classes.delete(c); }, toggle(c, on) { on ? this.o.classes.add(c) : this.o.classes.delete(c); }, contains(c) { return this.o.classes.has(c); } },
  getBoundingClientRect: () => ({ top: 100 }), scrollIntoView() {}, ...extra });
const side = el(), row = el(), overlay = el();
for (const e of [side, row, overlay]) e.classList.o = e;
const byId = { "im-side": side, "im-row": row, overlay };
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.innerWidth = 1440; globalThis.innerHeight = 900;
globalThis.requestAnimationFrame = (f) => f();
globalThis.history = { state: null, replaceState() {}, pushState() {}, back() {} };
globalThis.document = { dispatchEvent() {}, addEventListener() {}, getElementById: (id) => byId[id] || null, createElement: () => ({}), scripts: [] };
globalThis.location = { pathname: "/machines", search: "", hash: "" };
globalThis.fetch = () => new Promise(() => {});
for (const f of ["app.js", "machine-dialog.js", "intended-machines.js"]) vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static", f), "utf8"), { filename: f });

const now = Date.now() / 1000;
const baker = { id: "baker", mode: "ad hoc", kind: "program", publishes: [], subscribes: [], flows: [], instances: [], first_seen: now - 100, last_seen: now - 5, active: true };
const D = { machines: [baker] };
Orchestra.machineList = () => D.machines;
globalThis.render = () => IntendedMachines.draw(D);

test("a machine's panel, closed and opened again, is drawn again", () => {
  assert.ok(IntendedMachines.open("baker"));
  assert.match(side.innerHTML, /class="im-head"/);
  assert.ok(row.classes.has("open"));
  IntendedMachines.close();
  assert.equal(side.innerHTML, "");
  assert.ok(!row.classes.has("open"));
  assert.ok(IntendedMachines.open("baker"));
  assert.match(side.innerHTML, /class="im-head"/, "the panel is empty on reopening");
  assert.ok(row.classes.has("open"));
});

test("a proposed machine's map subtitle keeps the observed mode; a declared one that differs is tagged beside it", () => {
  const sup = { id: "supervisor", mode: "continuous", intent: { state: "proposed", heard: true, engagement: { mode: "ad hoc" } } };
  const n = { machine: true, mid: "supervisor", sub: "continuous" };
  IntendedMachines.decorate({ machines: [sup] }, [n], []);
  assert.equal(n.sub, "unconfirmed · continuous · declared ad hoc");
  const same = { machine: true, mid: "supervisor", sub: "continuous" };
  IntendedMachines.decorate({ machines: [{ ...sup, intent: { ...sup.intent, engagement: { mode: "continuous" } } }] }, [same], []);
  assert.equal(same.sub, "unconfirmed · continuous");
});
