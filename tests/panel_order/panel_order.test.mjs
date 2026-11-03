// The Dashboard's panel order (panel-order.js): the viewer's wide layout, and on a phone a panel
// that asks to be last (the Host) below the others, so a package's panel comes first.
import test from "node:test"; import assert from "node:assert/strict"; import { createRequire } from "node:module";
const PanelOrder = createRequire(import.meta.url)("../../orchestra/web/static/panel-order.js");

const machines = { id: "machines" }, host = { id: "host", phone: "last" }, work = { id: "work" };

test("on a phone, a package's panel registered late goes above the Host", () => {
  const ids = (ps) => ps.map((p) => p.id);
  assert.deepEqual(ids(PanelOrder.wide([machines, host, work], {})), ["machines", "host", "work"]);
  assert.deepEqual(ids(PanelOrder.phone([machines, host, work], {})), ["machines", "work", "host"]);
});

test("wide, the viewer's arrangement wins: by row, then column; one never placed after", () => {
  const at = { host: { x: 0, y: 0 }, machines: { x: 6, y: 0 }, work: { x: 0, y: 9 } };
  assert.deepEqual(PanelOrder.wide([machines, host, work, { id: "new" }], at).map((p) => p.id), ["host", "machines", "work", "new"]);
  assert.deepEqual(PanelOrder.phone([machines, host, work], at).map((p) => p.id), ["machines", "work", "host"]);
});

test("Where this is going comes after Model and, on a phone, above the Host", () => {
  const model = { id: "model" }, where = { id: "where" };
  const ids = (ps) => ps.map((p) => p.id);
  assert.deepEqual(ids(PanelOrder.wide([machines, model, where, host], {})), ["machines", "model", "where", "host"]);
  assert.deepEqual(ids(PanelOrder.phone([machines, model, host, where], {})), ["machines", "model", "where", "host"]);
});
