// The Dynamics page's tags on declared parts (Intended.declTag, intended-dynamics.js): who said what,
// "proposed by", "expected by", never "unconfirmed" (the owner, 2026-11-01).
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

globalThis.window = globalThis;
globalThis.location = { search: "" };
globalThis.MODEL = { stocks: [], flows: [], versions: [], intended: { shown: 2 } };
globalThis.Orchestra = { when: () => "12:00" };
globalThis.ago = (s) => `${Math.round(s / 60)} min`;
for (const f of ["intended-core.js", "intended-marks.js", "intended-dynamics.js"])
  vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static", f), "utf8") + "\nglobalThis.Intended = typeof Intended !== 'undefined' ? Intended : undefined;", { filename: f });

test("a proposed part is proposed by whoever proposed it; a declared one expected by whoever declared it", () => {
  assert.deepEqual(Intended.declTag({ state: "proposed", provenance: { author: "workflows", source: "workflows" } }), { text: "proposed by the Workflows", cls: "im-t-unconf" });
  const mine = Intended.declTag({ state: "declared", provenance: { author: "owner", via: "page" } });
  assert.deepEqual(mine, { text: "expected by you", cls: "im-t-user" });
  assert.equal(Intended.declTag({ state: "declared", present: true }).text, "expected");
});
