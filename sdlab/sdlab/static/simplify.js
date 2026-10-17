// Suggestions that make a model simpler without making it worse.
//
// Flows:
//   dead        a measured flow that moved essentially nothing in every era
//   no effect   an unmeasured flow (an equation only): replaying the run without it fits as well
//   duplicate   two flows between the same two stocks: merge them into one
//   pass-through a stock that is nearly always empty with exactly one flow in from a stock and one
//               out to a stock: connect those directly (and hide the stock)
// Stocks (hidden, not removed: their data and equations stay):
//   constant    it never moves: it acts like a setting, not a stock
//   empty       it is (nearly) always empty and nothing measurable passes through it
//   twin        it moves exactly like another stock: probably the same thing measured twice
//   alone       no flow touches it and it has no goal
// Anything marked `keep` is left alone, and so is a stock with a goal. A flow that mattered in any
// era is not dead: rare is not useless (an outage drain moves nothing for weeks, then everything).
(function (root) {
  "use strict";

  function suggest(model, run, opts) {
    opts = opts || {};
    const sim = (typeof module !== "undefined" && module.exports) ? require("./sim.js") : root.SDSim;
    const only = opts.stocks ? new Set(opts.stocks) : null;
    const inScope = (id) => !only || only.has(id);
    const stocks = (model.stocks || []).filter((s) => inScope(s.id));
    const flows = (model.flows || []).filter((f) => (f.from && inScope(f.from)) || (f.to && inScope(f.to)));
    const n = run && run.t ? run.t.length : 0;
    const eras = (opts.eras && opts.eras.length ? opts.eras : [{ start: n ? run.t[0] : 0 }]).map((e) => e.start);
    const eraOf = (i) => { let e = 0; eras.forEach((st, k) => { if (run.t[i] >= st) e = k; }); return e; };
    const out = [];
    const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
    const keep = (x) => !!x.keep;
    const hasGoal = (s) => s.target && s.target.value !== undefined && s.target.value !== "";
    const name = (id) => ((model.stocks || []).find((s) => s.id === id) || {}).name || id || "outside";

    // ---- flows ----
    if (n) {
      // how much moves through the stocks in scope, per step: the yardstick for "essentially nothing"
      const typical = mean(flows.map((f) => mean((run.rates[f.id] || []).map(Math.abs))).filter((v) => v > 0)) || 1;
      flows.forEach((f) => {
        if (keep(f) || !run.rates[f.id]) return;
        const r = run.rates[f.id];
        const perEra = eras.map((_, e) => mean(r.filter((_, i) => eraOf(i) === e).map(Math.abs)));
        const peak = Math.max(...r.map(Math.abs));
        if (Math.max(...perEra) < 0.001 * typical && peak < 0.01 * typical) {
          out.push({ kind: "remove-flow", flows: [f.id], title: `Remove ${f.name}`,
            reason: `It moved essentially nothing in every era (at most ${fmt(peak)} in one step, where flows here usually move ${fmt(typical)}).` });
        }
      });
    }
    // unmeasured flows that change nothing in a replay
    if (n >= 20) {
      const unmeasured = flows.filter((f) => !keep(f) && f.machine && !(run.rates[f.id] || []).some((v) => v));
      if (unmeasured.length) {
        const from = Math.max(0, n - 600), len = n - from;
        const start = Object.fromEntries((model.stocks || []).map((s) => [s.id, from ? (run.levels[s.id] || [])[from - 1] || 0 : 0]));
        const err = (m) => {
          const s = sim.simulate(m, { horizon: len, start, t0: run.t[from] - 1 }).series;
          const errs = stocks.map((st) => {
            const live = (run.levels[st.id] || []).slice(from), rep = s.levels[st.id] || [];
            let se = 0; live.forEach((v, i) => { se += ((rep[i + 1] || 0) - v) ** 2; });
            return Math.sqrt(se / Math.max(1, live.length)) / (mean(live.map(Math.abs)) + 1);
          });
          return mean(errs);
        };
        const base = err(model);
        unmeasured.slice(0, opts.maxReplays || 40).forEach((f) => {
          const without = err({ ...model, flows: model.flows.filter((g) => g.id !== f.id) });
          if (without <= base * 1.02 + 1e-6) {
            out.push({ kind: "remove-flow", flows: [f.id], title: `Remove ${f.name}`,
              reason: `Replaying the run without it fits the stocks ${without < base - 1e-6 ? "better" : "just as well"} (${pct(base)} → ${pct(without)} off), so its equation is not explaining anything.` });
          }
        });
      }
    }
    // duplicates: two flows between the same stocks
    const pairs = new Map();
    flows.forEach((f) => { const k = `${f.from}>${f.to}`; if (!pairs.has(k)) pairs.set(k, []); pairs.get(k).push(f); });
    pairs.forEach((list) => {
      if (list.length < 2 || list.some(keep)) return;
      out.push({ kind: "merge-flows", flows: list.map((f) => f.id), title: `Merge ${list.map((f) => f.name).join(" and ")}`,
        reason: `They all move things from ${name(list[0].from)} to ${name(list[0].to)}; one flow can carry them.` });
    });

    // ---- stocks ----
    stocks.forEach((s) => {
      if (keep(s) || hasGoal(s) || s.hide) return;
      const touching = (model.flows || []).filter((f) => f.from === s.id || f.to === s.id || (f.outputs || []).includes(s.id));
      const lv = n ? (run.levels[s.id] || []) : [];
      if (!touching.length) {
        out.push({ kind: "hide-stock", stocks: [s.id], title: `Hide ${s.name}`, reason: "No flow touches it and it has no goal." });
        return;
      }
      if (lv.length < 20) return;
      const lo = Math.min(...lv), hi = Math.max(...lv), m = mean(lv.map(Math.abs));
      if (hi - lo <= Math.max(1e-9, 0.001 * m) && m > 0) {
        out.push({ kind: "hide-stock", stocks: [s.id], title: `Hide ${s.name}`, reason: `It never changed (${fmt(lo)} the whole time): it acts like a setting rather than a stock.` });
        return;
      }
      const emptyShare = lv.filter((v) => Math.abs(v) < 0.5).length / lv.length;
      if (emptyShare >= 0.95) {
        const ins = touching.filter((f) => f.to === s.id && f.from), outs = touching.filter((f) => f.from === s.id && f.to);
        if (ins.length === 1 && outs.length === 1 && !keep(ins[0]) && !keep(outs[0]) && ins[0].from !== outs[0].to) {
          out.push({ kind: "pass-through", stocks: [s.id], flows: [ins[0].id, outs[0].id],
            title: `Connect ${name(ins[0].from)} straight to ${name(outs[0].to)}`,
            reason: `${s.name} is empty at ${Math.round(emptyShare * 100)}% of steps: things pass straight through it. One flow can replace ${ins[0].name} and ${outs[0].name}, and the stock can be hidden.` });
        } else {
          out.push({ kind: "hide-stock", stocks: [s.id], title: `Hide ${s.name}`, reason: `It is empty at ${Math.round(emptyShare * 100)}% of steps: what flows through it does not stay.` });
        }
      }
    });
    // twins: stocks that move together exactly
    if (n >= 20 && stocks.length <= 200) {
      const cand = stocks.filter((s) => !keep(s) && !hasGoal(s) && !s.hide);
      const series = cand.map((s) => run.levels[s.id] || []);
      for (let i = 0; i < cand.length; i++) for (let j = i + 1; j < cand.length; j++) {
        const a = series[i], b = series[j];
        if (!a.length || !b.length) continue;
        const ma = mean(a), mb = mean(b);
        let sab = 0, saa = 0, sbb = 0;
        a.forEach((v, k) => { sab += (v - ma) * (b[k] - mb); saa += (v - ma) ** 2; sbb += (b[k] - mb) ** 2; });
        if (saa < 1e-9 || sbb < 1e-9) continue;
        const corr = sab / Math.sqrt(saa * sbb), scale = Math.sqrt(sbb / saa);
        if (corr > 0.999 && Math.abs(Math.log(scale)) < 0.05) {
          out.push({ kind: "hide-stock", stocks: [cand[j].id], title: `Hide ${cand[j].name}`,
            reason: `It moves exactly like ${cand[i].name} (correlation ${corr.toFixed(4)}): probably the same thing measured twice.` });
        }
      }
    }
    return out;
  }

  // Apply a suggestion to a copy of the model.
  function apply(model, sg) {
    const m = JSON.parse(JSON.stringify(model));
    if (sg.kind === "remove-flow") m.flows = m.flows.filter((f) => !sg.flows.includes(f.id));
    if (sg.kind === "hide-stock") m.stocks.forEach((s) => { if (sg.stocks.includes(s.id)) s.hide = true; });
    if (sg.kind === "merge-flows") {
      const [first, ...rest] = sg.flows.map((id) => m.flows.find((f) => f.id === id));
      first.name = `${first.name} (merged)`;
      const rates = [first, ...rest].map((f) => f.rate);
      if (rates.every((r) => r && r.form === "constant")) first.rate = { form: "constant", value: rates.reduce((x, r) => x + (+r.value || 0), 0) };
      if (rest.some((f) => f.query) || first.query) {
        const qs = [first, ...rest].map((f) => f.query).filter(Boolean);
        first.query = qs.length > 1 ? qs.map((q) => `(${q})`).join(" + ") : qs[0];
      }
      m.flows = m.flows.filter((f) => !rest.includes(f));
    }
    if (sg.kind === "pass-through") {
      const [a, b] = sg.flows.map((id) => m.flows.find((f) => f.id === id));
      a.to = b.to; a.name = `${a.name} (through)`;
      if (b.cloud) a.cloud = b.cloud;
      m.flows = m.flows.filter((f) => f !== b);
      m.stocks.forEach((s) => { if (sg.stocks.includes(s.id)) s.hide = true; });
    }
    return m;
  }

  function fmt(v) { v = +v || 0; return Math.abs(v) >= 100 ? Math.round(v).toLocaleString("en-US") : Math.abs(v) >= 1 ? v.toFixed(1) : (+v.toPrecision(2)).toString(); }
  function pct(x) { return `${Math.round(x * 100)}%`; }

  const api = { suggest, apply };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SDSimplify = api;
})(typeof window !== "undefined" ? window : globalThis);
