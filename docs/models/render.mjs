// Render the user-story models as pictures.
//
//   node docs/models/render.mjs        (after check.mjs, whose results.json it reads)
//
// Writes:
//   docs/models/svg/<model>.svg    stock-and-flow diagrams drawn by SD Lab's own renderer
//                                  (sdlab/static/diagram.js, run here with a small stand-in for
//                                  the browser's DOM), with the three sides as bands behind them
//   docs/user-story-diagrams.md    every story: its diagram, a Mermaid flowchart, Mermaid charts
//                                  of the simulation (manual against designed), its machines,
//                                  its crossings into company systems, and its checks
//   docs/models/diagrams.html      the same diagrams inline in one page, for a browser

import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { HERE, SDLAB, read, STORIES, applyVariant, desk, measure, myQueue } from "./lib.mjs";

const require = createRequire(import.meta.url);

// ---- a stand-in for the few DOM calls diagram.js makes ----
class El {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.text = null; this.style = {}; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  appendChild(c) { this.children.push(c); return c; }
  set textContent(t) { this.text = String(t); this.children = []; }
  get textContent() { return this.text; }
  set innerHTML(_) { this.children = []; this.text = null; }
}
globalThis.document = { createElementNS: (_ns, tag) => new El(tag) };
const SDDiagram = require(join(SDLAB, "sdlab", "static", "diagram.js"));

const THEME = { "--fg": "#1f2937", "--canvas": "#ffffff", "--muted": "#6b7280", "--mono": "ui-monospace, Menlo, monospace" };
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const themed = (v) => v.replace(/var\((--[a-z]+)\)/g, (_, k) => THEME[k] || "#000");
function serialize(e) {
  const attrs = Object.entries(e.attrs).map(([k, v]) => ` ${k}="${esc(themed(v))}"`).join("");
  const inner = e.text !== null ? esc(e.text) : e.children.map(serialize).join("");
  return `<${e.tag}${attrs}>${inner}</${e.tag}>`;
}

const SIDE = {
  ours: { label: "Ours: what Orchestra owns and runs", fill: "#eff6ff", stroke: "#2563eb" },
  interface: { label: "Interface: where work crosses, and my outbox", fill: "#fffbeb", stroke: "#d97706" },
  company: { label: "Company: observed, not owned", fill: "#f3f4f6", stroke: "#6b7280" },
};
const EFFECT = "#0891b2";

const machineOf = (model) => Object.fromEntries([...model.machines.map((m) => [m.id, m]),
  ["environment", { id: "environment", name: "environment", color: "#6b7280" }]]);
const pct = (x) => `${Math.round(x * 100)}%`;
const visible = (model) => model.stocks.filter((s) => s.id !== "budget");
const drawnFlows = (model) => model.flows.filter((f) => f.id !== "fund" && f.machine);

// ---- the SVG diagram ----
function svgFor(model) {
  const M = machineOf(model), stocks = visible(model);
  const D = {
    stocks: stocks.map((s) => ({ id: s.id, name: s.name, sub: s.final ? `${s.unit} · final` : s.unit, cls: `side-${s.side}`,
                                 dashed: s.unit === "pings" || s.unit === "reviews", title: s.note || s.name })),
    flows: [],
  };
  for (const f of drawnFlows(model)) {
    const m = M[f.machine] || { name: f.machine };
    const outs = f.outputs && f.outputs.length ? [f.to, ...f.outputs] : [f.to];
    const total = outs.reduce((a, o) => a + (f.split && f.split[o] !== undefined ? f.split[o] : 1), 0) || 1;
    outs.forEach((o, i) => {
      const share = (f.split && f.split[o] !== undefined ? f.split[o] : 1) / total;
      D.flows.push({
        from: f.from, to: o, cls: `m-${f.machine}`, thin: i > 0,
        label: outs.length > 1 ? `${f.name} ${pct(share)}` : f.name,
        label2: m.name, title: [f.note, f.crosses && `crosses: ${f.crosses}`].filter(Boolean).join(" — ") || f.name,
        reads: i === 0 ? (f.effects || []).map((e) => ({ stock: e.stock, label: "effect", cls: "effect", dash: "5 4" })) : [],
      });
    });
  }
  const pos = Object.fromEntries(stocks.map((s) => [s.id, { x: s.x, y: s.y }]));
  const color = (cls) => {
    if (!cls) return THEME["--fg"];
    if (cls === "effect") return EFFECT;
    if (cls.startsWith("side-")) return (SIDE[cls.slice(5)] || {}).stroke || THEME["--fg"];
    if (cls.startsWith("m-")) return (M[cls.slice(2)] || {}).color || THEME["--muted"];
    return THEME["--fg"];
  };
  const svg = new El("svg");
  const vb = SDDiagram.draw(svg, D, pos, { color });
  // the three sides as bands behind everything
  const bands = new El("g");
  const bg = new El("rect");
  Object.entries({ x: vb.x, y: vb.y - 30, width: vb.w, height: vb.h + 30, fill: THEME["--canvas"] }).forEach(([k, v]) => bg.setAttribute(k, v));
  bands.appendChild(bg);
  for (const [side, st] of Object.entries(SIDE)) {
    const ys = stocks.filter((s) => s.side === side).map((s) => s.y);
    if (!ys.length) continue;
    const y0 = Math.min(...ys) - 36, y1 = Math.max(...ys) + SDDiagram.BOX.h + 26;
    const r = new El("rect");
    Object.entries({ x: vb.x + 4, y: y0, width: vb.w - 8, height: y1 - y0, rx: 10, fill: st.fill, stroke: st.stroke, "stroke-opacity": 0.35 })
      .forEach(([k, v]) => r.setAttribute(k, v));
    bands.appendChild(r);
    const t = new El("text");
    Object.entries({ x: vb.x + 14, y: y0 + 16, "font-size": 13, "font-weight": 700, fill: st.stroke }).forEach(([k, v]) => t.setAttribute(k, v));
    t.textContent = st.label;
    bands.appendChild(t);
  }
  svg.children.unshift(bands);
  svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  svg.setAttribute("viewBox", `${vb.x} ${vb.y - 30} ${vb.w} ${vb.h + 30}`);
  svg.setAttribute("width", Math.round(vb.w));
  svg.setAttribute("height", Math.round(vb.h + 30));
  svg.setAttribute("font-family", "system-ui, -apple-system, Segoe UI, sans-serif");
  return serialize(svg);
}

// ---- the Mermaid flowchart ----
function mermaidFlow(model) {
  const M = machineOf(model), stocks = visible(model);
  const lines = ["flowchart TB"];
  for (const [side, st] of Object.entries(SIDE)) lines.push(`  classDef ${side} fill:${st.fill},stroke:${st.stroke},color:#111`);
  lines.push("  classDef outside fill:#fff,stroke:#9ca3af,color:#6b7280");
  for (const side of Object.keys(SIDE)) {
    const mine = stocks.filter((s) => s.side === side);
    if (!mine.length) continue;
    lines.push(`  subgraph ${side.toUpperCase()}["${SIDE[side].label}"]`, "    direction LR");
    for (const s of mine) lines.push(`    ${s.id}["${s.name}"]:::${side}`);
    lines.push("  end");
  }
  const styles = [];
  let n = 0;
  const edge = (a, b, label, col, dotted) => {
    lines.push(`  ${a} ${dotted ? "-.->" : "-->"}|"${label}"| ${b}`);
    styles.push(`  linkStyle ${n++} stroke:${col},stroke-width:${dotted ? 1.5 : 2.5}px`);
  };
  for (const f of drawnFlows(model)) {
    const m = M[f.machine] || { name: f.machine, color: "#6b7280" };
    const from = f.from || `out_${f.id}`, to0 = f.to || `gone_${f.id}`;
    if (!f.from) lines.push(`  out_${f.id}(("outside")):::outside`);
    if (!f.to) lines.push(`  gone_${f.id}(("gone")):::outside`);
    const outs = f.outputs && f.outputs.length ? [to0, ...f.outputs] : [to0];
    const total = outs.reduce((a, o) => a + (f.split && f.split[o] !== undefined ? f.split[o] : 1), 0) || 1;
    for (const o of outs) {
      const share = outs.length > 1 ? ` ${pct((f.split && f.split[o] !== undefined ? f.split[o] : 1) / total)}` : "";
      edge(from, o, `${f.name}${share} · ${m.name}`, m.color, false);
    }
    for (const e of f.effects || []) if (stocks.some((s) => s.id === e.stock)) edge(e.stock, f.to || o_(f), `speeds ${f.name}`, EFFECT, true);
  }
  function o_(f) { return `gone_${f.id}`; }
  return ["```mermaid", ...lines, ...styles, "```"].join("\n");
}

// ---- Mermaid line charts of the simulation ----
function chart(title, yLabel, series, every, unitLabel) {
  // series: [{name, color, values}] sampled every `every` time units
  const n = Math.min(...series.map((s) => s.values.length));
  const xs = [];
  for (let i = 0; i < n; i += every) xs.push(Math.round(i / every));
  const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1));
  const out = [
    "```mermaid",
    "---",
    "config:",
    "  themeVariables:",
    "    xyChart:",
    `      plotColorPalette: "${series.map((s) => s.color).join(", ")}"`,
    "---",
    "xychart-beta",
    `  title "${title}"`,
    `  x-axis "${unitLabel}" [${xs.join(", ")}]`,
    `  y-axis "${yLabel}"`,
    ...series.map((s) => `  line [${xs.map((x) => fmt(s.values[x * every])).join(", ")}]`),
    "```",
    `*Lines:* ${series.map((s) => `${SWATCH[s.color] || "■"} ${s.name}`).join(" · ")}`,
  ];
  return out.join("\n");
}

const MANUAL = "#b45309", DESIGNED = "#0f766e", OTHER = "#7c3aed";
// the viewer shows no raw HTML, so legends use coloured squares close to each line's colour
const SWATCH = { "#b45309": "🟧", "#0f766e": "🟩", "#7c3aed": "🟪", "#2563eb": "🟦", "#6b7280": "⬜" };
const lvl = (X, id) => X.series.levels[id];
const sum = (X, ids) => X.series.t.map((_, i) => ids.reduce((a, id) => a + (X.series.levels[id] || [])[i], 0));
const queue = (m, X) => X.series.t.map((_, i) => myQueue(m, X, i));

// ---- per story: what to chart ----
const CHARTS = {
  "story-1-simple-task": (v) => [
    chart("Work waiting for me", "items", [
      { name: "manual (today)", color: MANUAL, values: queue(v.manual.m, v.manual.X) },
      { name: "designed", color: DESIGNED, values: queue(v.designed.m, v.designed.X) }], 8, "working day"),
    chart("Simple tasks delivered (cumulative)", "requests", [
      { name: "manual (today)", color: MANUAL, values: lvl(v.manual.X, "t_delivered") },
      { name: "designed", color: DESIGNED, values: lvl(v.designed.X, "t_delivered") },
      { name: "designed, better first pass", color: OTHER, values: lvl(v["better-first-pass"].X, "t_delivered") }], 8, "working day"),
    chart("Where requests wait (designed)", "requests", [
      { name: "ours and interface", color: "#2563eb", values: sum(v.designed.X, v.designed.m.stocks.filter((s) => s.side !== "company" && !s.final && s.id !== "budget" && s.unit !== "pings").map((s) => s.id)) },
      { name: "company (checks, review, SAIL)", color: "#6b7280", values: sum(v.designed.X, v.designed.m.stocks.filter((s) => s.side === "company" && !s.final).map((s) => s.id)) }], 8, "working day"),
  ],
  "story-2-prod-command": (v) => [
    chart("Preventions adopted", "policies", [
      { name: "today's shortcut", color: MANUAL, values: lvl(v.manual.X, "p_policies") },
      { name: "designed", color: DESIGNED, values: lvl(v.designed.X, "p_policies") }], 40, "week"),
    chart("Production command requests per week", "requests / week", [
      { name: "today's shortcut", color: MANUAL, values: v.manual.X.series.rates.p_arrive.map((r) => r * 40) },
      { name: "designed", color: DESIGNED, values: v.designed.X.series.rates.p_arrive.map((r) => r * 40) }], 40, "week"),
  ],
  "story-3-status-request": (v) => [
    chart("Stale status items", "items", [
      { name: "manual (today)", color: MANUAL, values: lvl(v.manual.X, "s_stale") },
      { name: "designed", color: DESIGNED, values: lvl(v.designed.X, "s_stale") }], 8, "working day"),
    chart("Manager questions waiting", "questions", [
      { name: "manual (today)", color: MANUAL, values: lvl(v.manual.X, "s_asks") },
      { name: "designed", color: DESIGNED, values: lvl(v.designed.X, "s_asks") }], 8, "working day"),
  ],
  "story-4-reviews-given": (v) => [
    chart("Reviews given recently (goodwill)", "reviews", [
      { name: "manual (today)", color: MANUAL, values: lvl(v.manual.X, "r_recent") },
      { name: "designed", color: DESIGNED, values: lvl(v.designed.X, "r_recent") }], 8, "working day"),
  ],
  desk: (v) => [
    chart("Work waiting for me, every story together", "items", [
      { name: "manual (today)", color: MANUAL, values: queue(v.manual.m, v.manual.X) },
      { name: "designed", color: DESIGNED, values: queue(v.designed.m, v.designed.X) }], 8, "working day"),
    chart("Share of my free time in use", "share", [
      { name: "manual (today)", color: MANUAL, values: v.manual.X.series.busy.me },
      { name: "designed", color: DESIGNED, values: v.designed.X.series.busy.me }], 8, "working day"),
    chart("Agent budget balance (designed)", "dollars", [
      { name: "designed", color: DESIGNED, values: lvl(v.designed.X, "budget") }], 8, "working day"),
  ],
};

// ---- assemble ----
mkdirSync(join(HERE, "svg"), { recursive: true });
const results = existsSync(join(HERE, "results.json")) ? JSON.parse(readFileSync(join(HERE, "results.json"), "utf8")) : { results: [] };
const doc = [
  "# User-story diagrams",
  "",
  "Generated by `node docs/models/render.mjs` from the models in `models/`. Don't edit by hand;",
  "edit `models/build.py`, then run `build.py`, `check.mjs` and `render.mjs`.",
  "",
  "Stories and their acceptance tests are in `user-stories.md`; assumptions in `models/README.md`.",
  "",
  "**How to read the diagrams.**",
  "",
  "- **Boxes are stocks.** They're blue in our band, amber in the interface (where work crosses",
  "  into company systems, and my outbox), and grey in the company band (observed, not owned).",
  "  Dashed boxes are information stocks.",
  "- **Arrows are flows,** coloured by the machine that runs them. Its name is under each label:",
  "  me, the analyst, drafter or implementation agents, Orchestra's programs, or the environment",
  "  (the company and its people). A flow that splits shows its share on each branch. Clouds are",
  "  outside the model.",
  "- **Dashed cyan lines are effects:** a stock that speeds or slows a flow.",
  "- **The agent budget is left out of the diagrams** to keep them readable. Every agent flow",
  "  draws on it.",
  "",
  "In the charts, 🟧 is the manual baseline (today), 🟩 the designed system, and 🟪 a what-if.",
  "",
];
const html = ['<!doctype html><meta charset="utf-8"><title>User-story models</title>',
  '<style>body{font:15px system-ui,sans-serif;margin:24px;background:#fff;color:#1f2937}h2{margin-top:40px}div.d{overflow-x:auto;border:1px solid #e5e7eb;border-radius:8px;padding:8px}div.d svg{height:auto;max-width:none}</style>',
  "<h1>User-story models</h1><p>Drawn with SD Lab's diagram renderer. Bands: ours (blue), interface (amber), company (grey). Flows are coloured by machine.</p>"];

const all = [...STORIES, "desk"];
for (const s of all) {
  const variants = {};
  if (s === "desk") {
    for (const v of ["designed", "manual"]) { const m = desk(v); variants[v] = { m, X: measure(m) }; }
  } else {
    const base = read(`${s}.json`), vars = read(`${s}.variants.json`);
    for (const v of ["designed", ...Object.keys(vars)]) { const m = applyVariant(base, vars, v); variants[v] = { m, X: measure(m) }; }
  }
  const D = variants.designed;
  const svg = svgFor(D.m);
  writeFileSync(join(HERE, "svg", `${s}.svg`), svg + "\n");
  html.push(`<h2>${esc(D.m.name || s)}</h2><div class="d">${svg}</div>`);

  const title = s === "desk" ? "The desk: every story together" : D.m.name;
  doc.push(`## ${title}`, "");
  if (D.m.description) doc.push(D.m.description, "");
  doc.push(`![${title}](models/svg/${s}.svg)`, "");
  doc.push("### Simulation: manual against designed", "");
  for (const c of CHARTS[s](variants)) doc.push(c, "");

  // machines
  const M = machineOf(D.m);
  doc.push("### Machines", "", "| Machine | Kind | Flows | Busy, designed | Busy, manual |", "|---|---|---|---|---|");
  const busy = (V, id) => { const r = V.X.summary.machines.find((x) => x.machine === id); return r ? pct(r.avgBusy) : "–"; };
  for (const m of D.m.machines) {
    const k = D.m.flows.filter((f) => f.machine === m.id).length;
    if (k || (variants.manual && variants.manual.m.flows.some((f) => f.machine === m.id))) doc.push(`| ${m.name} | ${m.kind} | ${k} | ${busy(D, m.id)} | ${variants.manual ? busy(variants.manual, m.id) : "–"} |`);
  }
  doc.push(`| Environment (company, people) | — | ${D.m.flows.filter((f) => f.machine === "environment" && f.id !== "fund").length} | — | — |`, "");

  // crossings
  const cross = D.m.flows.filter((f) => f.crosses);
  if (cross.length) {
    doc.push("### Crossings into company systems", "", "| Flow | Machine | Crosses |", "|---|---|---|");
    for (const f of cross) doc.push(`| ${f.name} | ${(M[f.machine] || {}).name || f.machine} | ${f.crosses} |`);
    doc.push("");
  }

  // checks
  const mine = (results.results || []).filter((r) => (s === "desk" ? r.story === "desk" : r.story === s));
  if (mine.length) {
    doc.push("### Checks", "", "| Id | Kind | Check | Result | Detail |", "|---|---|---|---|---|");
    for (const r of mine) doc.push(`| ${r.id} | ${r.kind} | ${r.text} | ${r.kind === "info" ? "info" : r.ok ? "pass" : r.kind === "validity" ? "**fail**" : "**gap**"} | ${r.detail} |`);
    doc.push("");
  }

  doc.push("### The same model as a Mermaid flowchart", "", mermaidFlow(D.m), "");
}
writeFileSync(join(HERE, "..", "user-story-diagrams.md"), doc.join("\n"));
writeFileSync(join(HERE, "diagrams.html"), html.join("\n") + "\n");
console.log(`wrote ${all.length} diagrams, docs/user-story-diagrams.md and docs/models/diagrams.html`);
