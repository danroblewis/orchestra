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
const COLORS = { designed: "#0f766e", manual: "#b45309", purple: "#7c3aed", blue: "#2563eb", grey: "#6b7280", red: "#dc2626", yellow: "#ca8a04" };
const SWATCH = { designed: "🟩", manual: "🟧", purple: "🟪", blue: "🟦", grey: "⬜", red: "🟥", yellow: "🟨" };
function mermaidChart(title, yLabel, series, every, xLabel) {
  // series: [{label, color, values}] sampled every `every` time units
  const n = Math.min(...series.map((x) => x.values.length));
  const xs = [];
  for (let i = 0; i < n; i += every) xs.push(Math.round(i / every));
  const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1));
  return [
    "```mermaid", "---", "config:", "  themeVariables:", "    xyChart:",
    `      plotColorPalette: "${series.map((x) => COLORS[x.color] || x.color).join(", ")}"`, "---",
    "xychart-beta", `  title "${title}"`, `  x-axis "${xLabel}" [${xs.join(", ")}]`, `  y-axis "${yLabel}"`,
    ...series.map((x) => `  line [${xs.map((k) => fmt(x.values[k * every])).join(", ")}]`), "```",
    `*Lines:* ${series.map((x) => `${SWATCH[x.color] || "■"} ${x.label}`).join(" · ")}`,
  ].join("\n");
}

// ---- measures: how a charted value is computed from the simulation ----
const nameIn = (m) => { const n = {}; m.stocks.forEach((x) => (n[x.id] = x.name)); m.flows.forEach((x) => (n[x.id] = x.name)); return n; };
const q = (s) => `“${s}”`;
function measureValues(spec, m, X) {
  const T = X.series.t.length, L = X.series.levels, R = X.series.rates;
  const zeros = () => new Array(T).fill(0);
  if (spec.stocks) return X.series.t.map((_, i) => spec.stocks.reduce((a, id) => a + (L[id] || zeros())[i], 0));
  if (spec.flows) return X.series.t.map((_, i) => spec.flows.reduce((a, id) => a + (R[id] || zeros())[i], 0) * (spec.per_week ? 40 : 1));
  if (spec.share) return X.series.t.map((_, i) => { const of = spec.share.of.reduce((a, id) => a + R[id][i], 0), inn = spec.share.in.reduce((a, id) => a + R[id][i], 0); return 100 * of / Math.max(1e-9, inn); });
  if (spec.machine_hours_per_week) { const cap = m.machines.find((x) => x.id === spec.machine_hours_per_week).capacity; return X.series.busy[spec.machine_hours_per_week].map((b) => b * cap * 40); }
  if (spec.machine_busy_share) return X.series.busy[spec.machine_busy_share].map((b) => 100 * b);
  if (spec.waiting_for) return X.series.t.map((_, i) => myQueue(m, X, i));
  if (spec.agent_spend_per_week || spec.agent_spend_total) {
    const per = X.series.t.map((_, i) => m.flows.reduce((a, f) => a + (R[f.id][i] || 0) * (f.uses || []).filter((u) => u.stock === "budget").reduce((c, u) => c + +u.per, 0), 0));
    if (spec.agent_spend_per_week) return per.map((v) => v * 40);
    let acc = 0; return per.map((v) => (acc += v));
  }
  throw new Error(`unknown measure ${JSON.stringify(spec)}`);
}
function measureFormula(spec, m) {
  const n = nameIn(m), list = (ids) => ids.map((id) => q(n[id] || id)).join(" + ");
  if (spec.stocks) return spec.stocks.length === 1 ? `the level of the stock ${q(n[spec.stocks[0]] || spec.stocks[0])} (\`${spec.stocks[0]}\`)` : `the sum of the stocks ${list(spec.stocks)}`;
  if (spec.flows) return `the rate of ${list(spec.flows)}${spec.per_week ? ", per hour × 40" : ""}`;
  if (spec.share) return `100 × (${list(spec.share.of)}) ÷ (${list(spec.share.in)}), using each flow's rate`;
  if (spec.machine_hours_per_week) return `the machine ${q(spec.machine_hours_per_week)}'s busy share × its capacity × 40`;
  if (spec.machine_busy_share) return `the machine ${q(spec.machine_busy_share)}'s busy share × 100`;
  if (spec.waiting_for) return `the sum of every stock whose outflow runs on the machine ${q(spec.waiting_for)}`;
  if (spec.agent_spend_per_week) return "Σ over every flow that uses the budget: its rate × its cost per item, per hour × 40";
  if (spec.agent_spend_total) return "the running total of agent spend per hour";
  return JSON.stringify(spec);
}

// ---- equations in words ----
const num = (v) => (Math.abs(v) >= 100 ? Math.round(v).toString() : +(+v).toPrecision(3) + "");
function rateText(f, n) {
  const r = f.rate || {};
  const name = (id) => q(n[id] || id);
  switch (r.form) {
    case "constant": return `${num(r.value)} per hour (${num(r.value * 40)} a week)`;
    case "proportional": return `${num(r.k)} × ${name(r.stock)}`;
    case "gap": return `(${num(r.goal)} − ${name(r.stock)}) ÷ ${num(r.time)}`;
    case "linear": return [r.c ? num(r.c) : null, ...(r.terms || []).map((t) => `${num(t.k)} × ${name(t.stock)}`)].filter(Boolean).join(" + ") + " per hour";
    case "available": return `as fast as its machine allows (everything in ${name(f.from)})`;
    default: return JSON.stringify(r);
  }
}
const effectText = (e, n) => `× ${q(n[e.stock] || e.stock)} effect (${e.shape === "table" ? e.points.map((p) => `${num(p[0])}→${num(p[1])}`).join(", ") : `level ÷ ${e.normal}`})`;

// ---- assemble ----
mkdirSync(join(HERE, "svg"), { recursive: true });
const results = existsSync(join(HERE, "results.json")) ? JSON.parse(readFileSync(join(HERE, "results.json"), "utf8")) : { results: [] };
const doc = [
  "# User-story diagrams",
  "",
  "Generated by `node docs/models/render.mjs`. Don't edit by hand. The source of everything here",
  "is `models/build.py`; run `build.py`, `check.mjs` and `render.mjs` after changing it. Every flow's",
  "equation is in `user-story-equations.md`.",
  "",
  "Stories and their acceptance tests are in `user-stories.md`; assumptions in `models/README.md`.",
  "",
  "**Where the numbers come from.** Every equation, initial value, input, variant, chart and measure",
  "was written by hand (by Claude, from what you described of your work) in `models/build.py`.",
  "They are planning estimates, not measurements, and nothing here was fitted or discovered from",
  "data. The simulation is deterministic: the same files always give the same charts. Each chart",
  "lists the measure it plots and the formula used to compute it.",
  "",
  "**How to read the diagrams.**",
  "",
  "- **Boxes are stocks.** They're blue in our band, amber in the interface (where work crosses into",
  "  company systems, and my outbox), and grey in the company band (observed, not owned). Dashed",
  "  boxes are information stocks.",
  "- **Arrows are flows,** coloured by the machine that runs them, named under each label. A flow",
  "  that splits shows its share on each branch. Clouds are outside the model.",
  "- **Dashed cyan lines are effects:** a stock that speeds or slows a flow. These are the feedback",
  "  loops.",
  "- **The agent budget is left out of the diagrams** to keep them readable. Every agent flow draws",
  "  on it.",
  "",
];
const eq = ["# User-story equations", "", "Generated by `node docs/models/render.mjs` from `models/build.py`. Every stock's starting value and",
  "every flow's equation, for each story model, as simulated. All values were written by hand as planning",
  "estimates; see `models/README.md`.", ""];
const html = ['<!doctype html><meta charset="utf-8"><title>User-story models</title>',
  '<style>body{font:15px system-ui,sans-serif;margin:24px;background:#fff;color:#1f2937}h2{margin-top:40px}div.d{overflow-x:auto;border:1px solid #e5e7eb;border-radius:8px;padding:8px}div.d svg{height:auto;max-width:none}</style>',
  "<h1>User-story models</h1><p>Drawn with SD Lab's diagram renderer. Bands: ours (blue), interface (amber), company (grey). Flows are coloured by machine.</p>"];

const all = [...STORIES, "desk"];
for (const s of all) {
  const variants = {}, vdefs = s === "desk" ? { manual: { description: "Every story's manual variant together." } } : read(`${s}.variants.json`);
  if (s === "desk") {
    for (const v of ["designed", "manual"]) { const m = desk(v); variants[v] = { m, X: measure(m) }; }
  } else {
    const base = read(`${s}.json`);
    for (const v of ["designed", ...Object.keys(vdefs)]) { const m = applyVariant(base, vdefs, v); variants[v] = { m, X: measure(m) }; }
  }
  const D = variants.designed, n = nameIn(D.m);
  const svg = svgFor(D.m);
  writeFileSync(join(HERE, "svg", `${s}.svg`), svg + "\n");
  html.push(`<h2>${esc(D.m.name || s)}</h2><div class="d">${svg}</div>`);

  const title = s === "desk" ? "The desk: every story together" : D.m.name;
  doc.push(`## ${title}`, "");
  if (D.m.description) doc.push(D.m.description, "");
  doc.push(`![${title}](models/svg/${s}.svg)`, "");
  if (D.m.loops) {
    doc.push("### Feedback loops", "", "| Loop | Type | Through | What it does |", "|---|---|---|---|");
    for (const l of D.m.loops) doc.push(`| ${l.id} | ${l.polarity} | ${l.stocks.map((id) => n[id] || id).join(" → ")} | ${l.says} |`);
    doc.push("");
  }

  // the starting state and what drives the model from outside
  doc.push("### Starting state and drivers", "");
  const nonzero = D.m.stocks.filter((x) => +x.initial);
  doc.push(`Every stock starts at 0 except: ${nonzero.map((x) => `${x.name} ${num(x.initial)} ${x.unit}`).join("; ")}.`, "");
  const drivers = D.m.flows.filter((f) => !f.from && f.machine === "environment");
  doc.push("Flows into the model from outside (the drivers). None is a waveform unless it reads an input:", "", "| Flow | Rate |", "|---|---|");
  for (const f of drivers) doc.push(`| ${f.name} → ${q(n[f.to] || f.to)} | ${rateText(f, n)} ${(f.effects || []).map((e) => effectText(e, n)).join(" ")} |`);
  doc.push("");
  if (D.m.inputs) for (const [k, spec] of Object.entries(D.m.inputs)) doc.push(`Input \`${k}\`: ${(spec.terms || []).map((t) => t.fn === "ramp" ? `a ramp from 0, rising ${num(t.slope)} per hour (${num(t.slope * D.m.horizon)} by hour ${D.m.horizon})` : JSON.stringify(t)).join(" + ")}.`, "");
  if (s !== "desk") {
    doc.push("**Variants** (each starts from the designed model and changes only what's listed):", "");
    for (const [v, d] of Object.entries(vdefs)) {
      const ch = [...Object.entries(d.stocks || {}).map(([id, p]) => `${q(n[id] || id)} starts at ${p.initial}`),
        ...Object.entries(d.flows || {}).map(([id, p]) => `${q(n[id] || id)}: ${p.machine === null ? "nobody does it" : [p.machine && `on ${p.machine}`, p.work !== undefined && `${p.work} h each`, p.rate && `rate ${rateText({ ...D.m.flows.find((f) => f.id === id), rate: p.rate }, n)}`, p.effects && (p.effects.length ? "effects changed" : "no effects"), p.split && "split changed"].filter(Boolean).join(", ")}`)];
      doc.push(`- **${v}**${d.base ? ` (from ${d.base})` : ""}: ${d.description} *Changes:* ${ch.join("; ") || "none"}.`);
    }
    doc.push("");
  }

  // charts, from data
  const C = read(`${s}.charts.json`);
  doc.push("### Simulation", "");
  for (const c of C.charts) {
    const series = c.series.map((x) => ({ label: x.label, color: x.color, values: measureValues(C.measures[x.measure], variants[x.variant].m, variants[x.variant].X) }));
    doc.push(mermaidChart(c.title, c.unit, series, c.every, c.x), "");
    const used = [...new Set(c.series.map((x) => x.measure))];
    doc.push(`*Plotted:* ${used.map((id) => `**${C.measures[id].name}** = ${measureFormula(C.measures[id], D.m)}`).join("; ")}. ${c.why}`, "");
  }

  // machines
  const M = machineOf(D.m);
  doc.push("### Machines", "", "| Machine | Kind | Capacity (hours per hour) | Flows | Busy, designed | Busy, manual |", "|---|---|---|---|---|---|");
  const busy = (V, id) => { const r = V.X.summary.machines.find((x) => x.machine === id); return r ? pct(r.avgBusy) : "–"; };
  for (const m of D.m.machines) {
    const k = D.m.flows.filter((f) => f.machine === m.id).length;
    if (k || (variants.manual && variants.manual.m.flows.some((f) => f.machine === m.id))) doc.push(`| ${m.name} | ${m.kind} | ${m.capacity} | ${k} | ${busy(D, m.id)} | ${variants.manual ? busy(variants.manual, m.id) : "–"} |`);
  }
  doc.push(`| Environment (company, people) | — | — | ${D.m.flows.filter((f) => f.machine === "environment" && f.id !== "fund").length} | — | — |`, "");

  const cross = D.m.flows.filter((f) => f.crosses);
  if (cross.length) {
    doc.push("### Crossings into company systems", "", "| Flow | Machine | Crosses |", "|---|---|---|");
    for (const f of cross) doc.push(`| ${f.name} | ${(M[f.machine] || {}).name || f.machine} | ${f.crosses} |`);
    doc.push("");
  }
  const mine = (results.results || []).filter((r) => (s === "desk" ? r.story === "desk" : r.story === s) && r.id !== "V");
  if (mine.length) {
    doc.push("### Checks", "", "| Id | Kind | Check | Result | Detail |", "|---|---|---|---|---|");
    for (const r of mine) doc.push(`| ${r.id} | ${r.kind} | ${r.text} | ${r.kind === "info" ? "info" : r.ok ? "pass" : r.kind === "validity" ? "**fail**" : "**gap**"} | ${r.detail} |`);
    doc.push("");
  }
  doc.push("### The same model as a Mermaid flowchart", "", mermaidFlow(D.m), "");

  // the equations page
  if (s !== "desk") {
    eq.push(`## ${D.m.name}`, "", `Time unit: ${D.m.time_unit}; horizon ${D.m.horizon} (${D.m.horizon / 40} weeks); step ${D.m.dt}.`, "");
    eq.push("### Stocks", "", "| Stock | Id | Side | Starts at | Unit | Note |", "|---|---|---|---|---|---|");
    for (const x of D.m.stocks) eq.push(`| ${x.name} | \`${x.id}\` | ${x.side} | ${num(+x.initial || 0)} | ${x.unit} | ${x.note || ""} |`);
    eq.push("", "### Flows", "", "| Flow | Id | From → to | Machine | Rate | Effects | Machine time per item | Cost per item |", "|---|---|---|---|---|---|---|---|");
    for (const f of D.m.flows) {
      const to = f.outputs && f.outputs.length ? [f.to, ...f.outputs].map((o) => `${n[o] || o} ${Math.round(100 * (f.split[o] ?? 1) / Object.values(f.split).reduce((a, b) => a + b, 0))}%`).join(", ") : (n[f.to] || f.to || "outside");
      eq.push(`| ${f.name} | \`${f.id}\` | ${n[f.from] || f.from || "outside"} → ${to} | ${(M[f.machine] || {}).name || f.machine} | ${rateText(f, n)} | ${(f.effects || []).map((e) => effectText(e, n)).join(" ") || "—"} | ${f.work ? `${f.work} h` : "—"} | ${(f.uses || []).map((u) => `$${u.per}`).join(" ") || "—"} |`);
    }
    eq.push("");
  }
}
writeFileSync(join(HERE, "..", "user-story-diagrams.md"), doc.join("\n"));
writeFileSync(join(HERE, "..", "user-story-equations.md"), eq.join("\n"));
writeFileSync(join(HERE, "diagrams.html"), html.join("\n") + "\n");
console.log(`wrote ${all.length} diagrams, docs/user-story-diagrams.md, docs/user-story-equations.md and docs/models/diagrams.html`);
