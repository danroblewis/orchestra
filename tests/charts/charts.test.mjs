// Charts.line (charts.js): a series of one point is drawn as a dot and said to be one point; y
// labels are short enough for the gutter.
import test from "node:test"; import assert from "node:assert/strict"; import path from "node:path"; import fs from "node:fs"; import vm from "node:vm";

globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.document = { dispatchEvent() {}, addEventListener() {}, getElementById: () => null, createElement: () => ({}), scripts: [] };
globalThis.location = { pathname: "/core" };
globalThis.fetch = () => new Promise(() => {});
for (const f of ["app.js", "charts.js"]) vm.runInThisContext(fs.readFileSync(path.resolve(import.meta.dirname, "../../orchestra/web/static", f), "utf8"), { filename: f });

test("one point is a visible dot, said as one point so far", () => {
  const svg = Charts.line([{ label: "disk", points: [[1000, 5]] }]);
  assert.match(svg, /<circle data-i="0" cx="[\d.]+" cy="[\d.]+" r="3.5"/);
  assert.match(svg, /one point so far/);
  assert.doesNotMatch(Charts.line([{ label: "disk", points: [[1000, 5], [1060, 6]] }]), /one point so far|<circle/);
});

test("large values label the axis compactly", () => {
  const svg = Charts.line([{ label: "bytes", points: [[1000, 193e9], [1060, 194e9]] }], { tight: true });
  assert.match(svg, />19\dG</);
  assert.doesNotMatch(svg, /000,000/);
});

test("a picked range keeps the axis, and the one-point note says what the caller says, away from the dot", () => {
  const svg = Charts.line([{ label: "disk", points: [[86_000, 5]] }], { range: [0, 86_400], onePoint: "one 10m step so far; pick a shorter range for finer" });
  assert.match(svg, /one 10m step so far; pick a shorter range for finer/);
  assert.doesNotMatch(svg, /one point so far/);
  const cx = +svg.match(/<circle data-i="0" cx="([\d.]+)"/)[1];
  assert.ok(cx > 600, `the dot sits at the end of the day, not the middle (${cx})`);
  assert.match(svg, /<text class="cnote" x="52" y="18" text-anchor="start">/);          // on the left, away from the dot
});
