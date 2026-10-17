// Scoring what discovery found against an example's answer key (truth.json, "sd_structure").
//
// A relationship is an ordered pair of stocks: a move (things go from A to B), a link (B's
// arrivals follow A's level), a hidden stock (things leave A and arrive in B later) or an echo
// (things come back into B some time after arriving in A). Discovery is scored on the pairs it
// names, and separately on whether it named the right kind. Flows to or from outside are counted
// on their own: a model that explains everything with them has explained nothing.
import fs from "fs";
import path from "path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../..");

// the hospital's answer key predates the shared format: its flows, with hidden stocks by name
function fromHospital(t) {
  const measured = new Set(t.measured.stocks), sd = { moves: [], outside: [], hidden: [], links: [], echoes: [] };
  Object.values(t.flows).forEach((f) => {
    if (measured.has(f.from) && measured.has(f.to)) sd.moves.push({ from: f.from, to: f.to });
    else if (!f.from && measured.has(f.to)) sd.outside.push({ to: f.to });
    else if (measured.has(f.from) && !f.to) sd.outside.push({ from: f.from });
  });
  Object.values(t.hidden_stocks).forEach((h) => h.between.into.forEach((to) => sd.hidden.push({ from: h.between.out_of, to })));
  return sd;
}

export function truthOf(example) {
  const t = JSON.parse(fs.readFileSync(path.join(ROOT, "sdlab/examples", example, "truth.json")));
  const sd = t.sd_structure || fromHospital(t);
  const rel = new Map();                                           // "a>b" -> kind
  const put = (a, b, kind) => { if (a && b && !rel.has(`${a}>${b}`)) rel.set(`${a}>${b}`, kind); };
  // the shop's key predates the shared format: "flows" (moves and drains) and "driven_inflows"
  (sd.moves || (sd.flows || []).filter((f) => f.from && f.to)).forEach((m) => put(m.from, m.to, "move"));
  (sd.links || (sd.driven_inflows || []).map((d) => ({ driver: d.driver, into: d.into }))).forEach((l) => put(l.driver, l.into, "link"));
  (sd.hidden || []).forEach((h) => put(h.from, h.to, "hidden"));
  (sd.echoes || []).forEach((e) => put(e.source, e.into, "echo"));
  // what only runs longer than the example's default have (the bench's runs are long)
  const more = sd.in_long_runs || {};
  (more.moves || []).forEach((m) => put(m.from, m.to, "move"));
  (more.links || []).forEach((l) => put(l.driver, l.into, "link"));
  const outside = new Set();
  (sd.outside || (sd.flows || []).filter((f) => !f.from || !f.to)).forEach((o) => {
    if (o.from && !o.to) outside.add(`${o.from}>out`);
    if (o.to && !o.from) outside.add(`in>${o.to}`);
  });
  return { rel, outside };
}

// what a discovery result says, as relationships
export function found(result) {
  const rel = new Map(), outside = [];
  result.flows.forEach((f) => {
    let a = null, b = f.to, kind;
    if (f.driver) { a = f.driver; kind = "link"; }
    else if (f.via) { a = f.from || f.via.echo; kind = f.from ? "hidden" : "echo"; }
    else if (f.from && f.to) { a = f.from; kind = "move"; }
    if (a && b) rel.set(`${a}>${b}`, kind);
    else outside.push(f.from ? `${f.from}>out` : `in>${f.to}`);
  });
  return { rel, outside };
}

export function grade(result, truth) {
  const f = found(result);
  const hits = [...f.rel.keys()].filter((k) => truth.rel.has(k));
  const reversed = [...f.rel.keys()].filter((k) => !truth.rel.has(k) && truth.rel.has(k.split(">").reverse().join(">")));
  const kindRight = hits.filter((k) => truth.rel.get(k) === f.rel.get(k));
  const flows = result.flows.length;
  // the headline: parts of the true model recovered in the right form - each true relationship
  // named with the right kind, and each true flow to or from outside
  const parts = truth.rel.size + truth.outside.size, right = kindRight.length + new Set(f.outside.filter((k) => truth.outside.has(k))).size;
  return {
    parts, right, rightShare: parts ? right / parts : null,
    flows,
    found: f.rel.size,
    hits: hits.length,
    kindRight: kindRight.length,
    reversed: reversed.length,
    wrong: f.rel.size - hits.length - reversed.length,
    recall: truth.rel.size ? hits.length / truth.rel.size : null,
    precision: f.rel.size ? hits.length / f.rel.size : null,
    outside: f.outside.length,
    outsideRight: f.outside.filter((k) => truth.outside.has(k)).length,
    // the share of flows that only connect to outside: near 1 means discovery gave up on structure
    outsideShare: flows ? f.outside.length / flows : 0,
    pairs: new Set(f.rel.keys()),
  };
}

// how alike two discoveries are: the share of relationships they agree on (Jaccard)
export function agreement(a, b) {
  const union = new Set([...a, ...b]);
  if (!union.size) return 1;
  let both = 0; a.forEach((k) => { if (b.has(k)) both++; });
  return both / union.size;
}

// ---- grading by behaviour: do two models predict the same? ----
// From many moments in the run, both models are run forward `horizon` steps from what was there,
// and their predictions are compared with what happened. The true model is run from every stock's
// level (its hidden stocks included) with its schedule of outside changes; the discovered model from
// the measured stocks, with the outside inflows it found. A ratio near 1: as good as the truth.

function rateOf(rate, level) {
  if (!rate) return 0;
  const v = (s) => level[s] || 0;
  switch (rate.form) {
    case "constant": return Math.max(0, +rate.value || 0);
    case "proportional": return Math.max(0, (+rate.k || 0) * v(rate.stock));
    case "gap": return Math.max(0, ((+rate.goal || 0) - v(rate.stock)) / Math.max(1e-9, +rate.time || 1));
    case "linear": return Math.max(0, (+rate.c || 0) + (rate.terms || []).reduce((a, t) => a + (+t.k || 0) * v(t.stock), 0));
    default: return 0;
  }
}
function step(flows, level, t) {
  const amount = flows.map((f) => {
    if (f.inflow && f.inflow.length) {                        // a found outside inflow that changes
      const p = f.inflow.find((g) => t >= g.from && t <= g.to) || f.inflow[f.inflow.length - 1];
      return Math.max(0, p.value);
    }
    return rateOf(f.rate, level);
  });
  const next = { ...level };
  flows.forEach((f, i) => { if (f.from) next[f.from] = (next[f.from] || 0) - amount[i] * (f.ratio || 1); if (f.to) next[f.to] = (next[f.to] || 0) + amount[i]; });
  Object.keys(next).forEach((k) => { if (next[k] < 0) next[k] = 0; });
  return next;
}
function truthFlowsAt(truthModel, t, cache) {
  // the truth's flows with its schedule applied up to step t
  const sch = truthModel.schedule || { every: 0, changes: [] };
  const flows = truthModel.flows.map((f) => ({ ...f }));
  const byId = Object.fromEntries(flows.map((f) => [f.id, f]));
  const every = +sch.every || 0, within = every ? ((t - 1) % every) + 1 : t;
  const byT = (a, b) => a.t - b.t;
  // last period's later changes still hold, then this period's so far override them
  const applied = [...(every && t > every ? (sch.changes || []).filter((c) => c.t > within).sort(byT) : []),
                   ...(sch.changes || []).filter((c) => c.t <= within).sort(byT)];
  applied.forEach((c) => Object.entries(c.set || {}).forEach(([fid, rate]) => { if (byId[fid]) byId[fid].rate = rate; }));
  return flows;
}

export function prediction(result, truthModel, data, opts = {}) {
  const H = opts.horizon || 20, n = data.t.length, measured = Object.keys(data.levels);
  const all = data.all_levels || data.levels;
  const starts = []; const every = Math.max(1, Math.floor((n - H - 1) / (opts.starts || 150)));
  for (let s = 1; s + H < n; s += every) starts.push(s);
  const sd = Object.fromEntries(measured.map((k) => { const a = data.levels[k], m = a.reduce((x, y) => x + y, 0) / a.length; return [k, Math.sqrt(a.reduce((x, y) => x + (y - m) ** 2, 0) / a.length) || 1]; }));
  const err = { found: 0, truth: 0, still: 0 }; let count = 0;
  starts.forEach((s0) => {
    let found = Object.fromEntries(measured.map((k) => [k, data.levels[k][s0 - 1]]));
    let truth = Object.fromEntries(Object.keys(all).map((k) => [k, all[k][s0 - 1]]));
    for (let h = 0; h < H; h++) {
      const t = data.t[s0 + h];
      found = step(result.flows, found, t);
      truth = step(truthFlowsAt(truthModel, t), truth, t);
    }
    measured.forEach((k) => {
      const actual = data.levels[k][s0 + H - 1], z = sd[k];
      err.found += ((found[k] - actual) / z) ** 2; err.truth += ((truth[k] - actual) / z) ** 2; err.still += ((data.levels[k][s0 - 1] - actual) / z) ** 2;
      count++;
    });
  });
  const rms = (x) => Math.sqrt(x / Math.max(1, count));
  return { horizon: H, found: rms(err.found), truth: rms(err.truth), still: rms(err.still), ratio: rms(err.found) / Math.max(1e-9, rms(err.truth)) };
}

// How far apart two models' predictions drift, both fed the same outside inflows: the truth's
// schedule replaces the found model's outside inflow into every stock the truth feeds from outside,
// so only the models' own dynamics differ. From many moments, both run `horizon` steps from what was
// there; the result is the spread between them divided by how far the truth itself moved (0: the same
// behaviour; 1: as far apart as assuming nothing changes).
export function sameBehaviour(result, truthModel, data, opts = {}) {
  const H = opts.horizon || 20, n = data.t.length, measured = Object.keys(data.levels);
  const all = data.all_levels || data.levels;
  const fedByTruth = new Set(truthModel.flows.filter((f) => !f.from && f.to && (f.rate || {}).form === "constant").map((f) => f.to));
  const own = result.flows.filter((f) => !(!f.from && f.to && fedByTruth.has(f.to) && !f.driver && (f.rate || {}).form === "constant"));
  const starts = []; const every = Math.max(1, Math.floor((n - H - 1) / (opts.starts || 150)));
  for (let s = 1; s + H < n; s += every) starts.push(s);
  let apart = 0, moved = 0;
  starts.forEach((s0) => {
    let found = Object.fromEntries(Object.keys(all).map((k) => [k, all[k][s0 - 1]]));
    let truth = { ...found };
    for (let h = 0; h < H; h++) {
      const t = data.t[s0 + h], tf = truthFlowsAt(truthModel, t);
      const exo = tf.filter((f) => !f.from && f.to && fedByTruth.has(f.to) && (f.rate || {}).form === "constant");
      found = step([...own, ...exo], found, t);
      truth = step(tf, truth, t);
    }
    measured.forEach((k) => { apart += (found[k] - truth[k]) ** 2; moved += (truth[k] - all[k][s0 - 1]) ** 2; });
  });
  const ratio = Math.sqrt(apart / Math.max(1e-9, moved));
  // skill: the share of the true model's movement the found model predicts (1 - ratio², like R²)
  return { horizon: H, apart: ratio, skill: 1 - ratio * ratio };
}
