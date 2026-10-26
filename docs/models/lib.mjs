// Shared by check.mjs and render.mjs: loading models, variants, the desk, SD Lab's validator and
// simulator, and the measures the checks and charts use.

import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

export const HERE = dirname(fileURLToPath(import.meta.url));
export const SDLAB = process.env.SDLAB;      // an SD Lab checkout; this repository has none it can use
if (!SDLAB) throw new Error("set SDLAB to the path of an SD Lab checkout (its sdlab/static/sim.js is needed)");
const require = createRequire(import.meta.url);
export const { simulate, leverage } = require(join(SDLAB, "sdlab", "static", "sim.js"));

export const read = (f) => JSON.parse(readFileSync(join(HERE, f), "utf8"));
export const clone = (x) => JSON.parse(JSON.stringify(x));
export const STORIES = ["story-1-simple-task", "story-2-prod-command", "story-3-status-request", "story-4-reviews-given"];

// ---- variants: a variant overrides fields of named flows (and may start from another variant) ----
export function applyVariant(model, variants, name) {
  if (!name || name === "designed") return clone(model);
  const v = variants[name];
  if (!v) throw new Error(`no variant ${name}`);
  const m = applyVariant(model, variants, v.base);
  for (const [id, patch] of Object.entries(v.stocks || {})) {
    const st = m.stocks.find((x) => x.id === id);
    if (!st) throw new Error(`variant ${name}: no stock ${id}`);
    Object.assign(st, clone(patch));
  }
  for (const [id, patch] of Object.entries(v.flows || {})) {
    const f = m.flows.find((g) => g.id === id);
    if (!f) throw new Error(`variant ${name}: no flow ${id}`);
    Object.assign(f, clone(patch));
    if (f.uses && !f.uses.length) delete f.uses;
  }
  return m;
}

// ---- the desk: every story in one model, sharing machines and the budget ----
export function desk(variant) {
  const parts = STORIES.map((s, i) => {
    const m = applyVariant(read(`${s}.json`), read(`${s}.variants.json`), variant);
    for (const st of m.stocks) if (st.id !== "budget") st.y += 900 * i;   // stack the stories on one canvas
    return m;
  });
  const out = { id: `desk-${variant}`, name: `Desk (${variant})`, time_unit: "working hour", horizon: Math.max(...parts.map((p) => p.horizon || 160)), dt: 0.25,
                description: "Every story in one model: they share my time, the agents and the budget.",
                stocks: [], flows: [], machines: [] };
  for (const p of parts) for (const key of ["stocks", "flows", "machines"]) {
    for (const item of p[key]) {
      const have = out[key].find((x) => x.id === item.id);
      if (!have) out[key].push(item);
      else if (JSON.stringify(have) !== JSON.stringify(item)) throw new Error(`${key} ${item.id} differs between stories`);
    }
  }
  for (const c of read("desk.couplings.json").effects) {
    const f = out.flows.find((g) => g.id === c.flow);
    f.effects = [...(f.effects || []), c.effect];
  }
  return out;
}

// ---- SD Lab's validator, in Python ----
export function validateAll(models) {
  const script = [
    "import json, sys",
    "from sdlab.server import validate",
    "models = json.load(sys.stdin)",
    "print(json.dumps({k: validate(m) for k, m in models.items()}))",
  ].join("\n");
  const outp = execFileSync("uv", ["run", "--project", SDLAB, "python", "-c", script],
                            { input: JSON.stringify(models), encoding: "utf8", cwd: SDLAB, stdio: ["pipe", "pipe", "ignore"] });
  return JSON.parse(outp.trim().split("\n").pop());
}

// ---- measures ----
export function measure(model) {
  const { series, summary } = simulate(model);
  const n = series.t.length - 1, H = series.t[n];
  const lv = (id) => series.levels[id] || [];
  const end = (id) => lv(id)[n];
  const min = (id) => Math.min(...lv(id));
  const avg = (id) => lv(id).reduce((a, b) => a + b, 0) / lv(id).length;
  const mach = Object.fromEntries(summary.machines.map((m) => [m.machine, m]));
  const cap = Object.fromEntries(model.machines.map((m) => [m.id, m.capacity]));
  const hours = (id) => (mach[id] ? mach[id].avgBusy * cap[id] * H : 0);
  const fund = model.flows.find((f) => f.id === "fund");
  const spent = (model.stocks.find((s) => s.id === "budget").initial + fund.rate.value * H) - end("budget");
  const rate = (id) => series.rates[id] || [];
  return { series, summary, n, H, end, min, avg, mach, hours, spent, rate };
}

// Work waiting for me: the levels of stocks whose outflows run on my time.
export const myQueue = (model, X, at) => model.flows.filter((f) => f.machine === "me" && f.from).map((f) => f.from)
  .filter((v, i, a) => a.indexOf(v) === i).reduce((a, id) => a + X.series.levels[id][at], 0);
export const sideOf = (model, side) => model.stocks.filter((s) => s.side === side && !s.final && s.id !== "budget" && s.unit !== "pings").map((s) => s.id);

