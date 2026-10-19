// Simulator and equation fitting for an SD Lab model. Pure functions, shared by the page and
// by tests/sim.test.mjs.
//
// Each step (flowRates):
//   1. every flow asks for its rate from its equation; a flow with no machine asks for nothing;
//   2. no flow asks for more than its source stock holds;
//   3. each machine shares its time fairly among its flows: each gets an equal share, capped at
//      what it asks for, and time one flow cannot use goes to the others (the live runner
//      schedules the same way: the flow that has had the least time goes next);
//   4. outflows that share a source are scaled down together if they would overdraw it;
//   5. stocks move by rate x dt (the source loses rate x ratio).
//
// Stocks can also shape flows they are not part of:
//   effects  a flow's speed multiplied by a curve of a stock's level ("effect of bits on milling
//            speed"). For a flow a machine runs (it has `work`), the effect changes how long each
//            unit takes the machine; for any other flow it multiplies the rate.
//   uses     a co-flow: each unit moved also uses up `per` units of another stock, and the flow
//            stops when that stock runs out ("each part wears 0.01 bits").
//   a machine's capacity can be per unit of a stock (`capacity_stock`): capacity x level.
//
// Added 2026-10-18 (MODEL.md; the ground-truth engine's features, so a ladder case's model runs here):
//   inputs   model.inputs {name: {values?, repeat?, terms?}}: measured inputs a rate or effect reads by
//            name as it reads a stock (series value per time unit, plus step/pulse/ramp/pulse_train/
//            sin/constant terms), at time unit floor(t) + 1 (the engine's step numbering)
//   max      a stock's ceiling: its inflows share the room left (max - level), as outflows share
//            what a stock holds
//
// fit() takes a live run (measured levels and rates each time unit) and, for every flow, tries
// each equation form against what happened, one step at a time, from the measured levels.
// leverage() speeds up each flow by 10% in turn and ranks which ones move the goals most.
(function (root) {
  "use strict";

  const FORMS = ["constant", "proportional", "gap", "available"];

  function ratio(f) { return f.ratio === undefined || f.ratio === null || f.ratio === "" ? 1 : Math.max(0, +f.ratio); }

  // An effect's multiplier at a stock level: "linear" is level / normal, kept between `min` and `max`
  // (defaults 0 and 1); "table" reads a curve through [level, multiplier] points.
  function effectValue(e, level) {
    const x = (level && e.stock in level) ? level[e.stock] : 0;
    if (e.shape === "table" && Array.isArray(e.points) && e.points.length) {
      const pts = e.points.map((p) => [+p[0], +p[1]]).sort((a, b) => a[0] - b[0]);
      if (x <= pts[0][0]) return Math.max(0, pts[0][1]);
      for (let i = 1; i < pts.length; i++) {
        if (x <= pts[i][0]) { const [x0, y0] = pts[i - 1], [x1, y1] = pts[i]; return Math.max(0, y0 + (y1 - y0) * (x - x0) / Math.max(1e-9, x1 - x0)); }
      }
      return Math.max(0, pts[pts.length - 1][1]);
    }
    const normal = Math.max(1e-9, +e.normal || 1), lo = e.min === undefined ? 0 : +e.min, hi = e.max === undefined ? 1 : +e.max;
    return Math.min(hi, Math.max(lo, x / normal));
  }
  function multiplier(f, level) { return (f.effects || []).reduce((m, e) => m * effectValue(e, level), 1) * (f.boost || 1); }
  function machineCapacity(m, level) {
    const c = Math.max(0, +m.capacity || 0);
    return m.capacity_stock ? c * Math.max(0, (level && level[m.capacity_stock]) || 0) : c;
  }

  function desiredRate(rate, level, f, dt, avail) {
    if (!rate) return 0;
    const lv = (id) => (id in level ? level[id] : 0);
    const av = (id) => (avail && id in avail ? avail[id] : lv(id));
    switch (rate.form) {
      case "constant": return Math.max(0, +rate.value || 0);
      case "proportional": return Math.max(0, (+rate.k || 0) * lv(rate.stock));
      case "gap": {
        const time = Math.max(1e-9, +rate.time || 1);
        return Math.max(0, ((+rate.goal || 0) - lv(rate.stock)) / time);
      }
      case "linear": {                               // c + k1 x level1 + k2 x level2 ... (what discovery finds)
        return Math.max(0, (+rate.c || 0) + (rate.terms || []).reduce((x, t) => x + (+t.k || 0) * lv(t.stock), 0));
      }
      case "available": {                            // take everything there is, as fast as the step allows
        const src = rate.stock || (f && f.from);
        return src ? av(src) / (Math.max(1e-9, ratio(f || {})) * (dt || 1)) : 0;
      }
      default: return 0;
    }
  }

  // A measured input's value at simulation time t (time unit k = floor(t) + 1, as the engine numbers
  // its steps; the terms at k + the fraction of the unit), as sdlab/sdtruth.py's input_value.
  function inputValue(spec, t) {
    if (Array.isArray(spec)) spec = { values: spec };
    spec = spec || {};
    const k = Math.floor(t) + 1, tau = t + 1;
    let v = 0;
    const vals = spec.values || [];
    if (vals.length) v = +(spec.repeat ? vals[(k - 1) % vals.length] : vals[Math.min(Math.max(k - 1, 0), vals.length - 1)]) || 0;
    (spec.terms || []).forEach((x) => {
      const n = (key, d) => (x[key] === undefined || x[key] === null ? d : +x[key]);
      switch (x.fn) {
        case "constant": v += n("value", 0); break;
        case "step": v += tau >= n("start", 0) ? n("height", 0) : 0; break;
        case "pulse": v += tau >= n("start", 0) && tau < n("start", 0) + n("width", 1) ? n("height", 0) : 0; break;
        case "ramp": v += tau > n("start", 0) ? n("slope", 0) * (Math.min(tau, n("end", Infinity)) - n("start", 0)) : 0; break;
        case "pulse_train": {
          const first = n("first", 0), every = Math.max(1e-9, n("every", 1));
          v += tau >= first && tau <= n("last", Infinity) && ((tau - first) % every) < n("width", 1) ? n("height", 0) : 0;
          break;
        }
        case "sin": v += n("amplitude", 0) * Math.sin(2 * Math.PI * (tau - n("phase", 0)) / Math.max(1e-9, n("period", 1))); break;
        default: break;
      }
    });
    return v;
  }
  // The levels a rate reads: the stocks' levels and, when the model has inputs, their values at t.
  function readable(model, level, t) {
    const inputs = model.inputs;
    if (!inputs || !Object.keys(inputs).length) return level;
    const out = Object.assign({}, level);
    Object.keys(inputs).forEach((k) => { if (!(k in level)) out[k] = inputValue(inputs[k], t || 0); });
    return out;
  }

  function describeRate(rate, stockName, timeUnit) {
    if (!rate) return "no equation";
    switch (rate.form) {
      case "constant": return `${fmt(rate.value)} per ${timeUnit || "step"}`;
      case "proportional": return `${fmt(rate.k)} × ${stockName(rate.stock)}`;
      case "gap": return `gap to ${fmt(rate.goal)} in ${stockName(rate.stock)}`;
      case "available": return rate.stock ? `everything in ${stockName(rate.stock)}` : "everything available";
      case "linear": return [...(+rate.c || !(rate.terms || []).length ? [fmt(rate.c || 0)] : []), ...(rate.terms || []).map((t) => `${fmt(t.k)} \u00d7 ${stockName(t.stock)}`)].join(" + ");
      default: return rate.form;
    }
  }

  function fmt(v) {
    v = +v || 0;
    if (Math.abs(v) >= 100) return Math.round(v).toLocaleString("en-US");
    if (Math.abs(v) >= 10) return v.toFixed(1).replace(/\.0$/, "");
    return (+v.toFixed(2)).toString();
  }

  // Rates for one step from the current levels: { rate: {flow: r}, asked: {machine: demand/capacity}, busy: {machine: used/capacity} }
  // `avail` (optional) is what each stock can give during the step, when that differs from its level.
  // Which flows belong to which machine and which drain or use each stock, worked out once per
  // simulation (which asks for rates thousands of times), so large models stay fast.
  function prep(model) {
    let p;
    const flows = model.flows || [], machines = model.machines || [], stocks = model.stocks || [];
    const mids = new Set(machines.map((m) => m.id));
    const byMachine = new Map(machines.map((m) => [m.id, []]));
    const touching = new Map(stocks.map((s) => [s.id, []]));
    flows.forEach((f) => {
      if (byMachine.has(f.machine)) byMachine.get(f.machine).push(f);
      const ids = new Set([f.from, ...(f.uses || []).map((u) => u.stock)].filter((x) => x && touching.has(x)));
      ids.forEach((id) => touching.get(id).push(f));
    });
    p = { flows, machines, stocks, byMachine, touching, onMachine: (f) => f.machine && f.machine !== "environment" && +f.work > 0 && mids.has(f.machine) };
    return p;
  }

  function flowRates(model, level, dt, avail, prepared) {
    const P = prepared || prep(model), flows = P.flows, machines = P.machines, stocks = P.stocks;
    avail = avail || level;
    const rate = {}, mult = {};
    const onMachine = P.onMachine;
    flows.forEach((f) => {
      mult[f.id] = multiplier(f, level);
      let r = f.machine ? desiredRate(f.rate, level, f, dt, avail) : 0;
      if (!onMachine(f)) r *= mult[f.id];                // the effect changes the rate itself
      if (f.from && f.from in avail) r = Math.min(r, avail[f.from] / (Math.max(1e-9, ratio(f)) * dt));
      (f.uses || []).forEach((u) => { if (+u.per > 0 && u.stock in avail) r = Math.min(r, avail[u.stock] / (+u.per * dt)); });
      rate[f.id] = Math.max(0, r);
    });

    const asked = {}, busy = {};
    machines.forEach((m) => {
      const cap = machineCapacity(m, level);
      const mine = P.byMachine.get(m.id).filter((f) => +f.work > 0 && rate[f.id] > 0)
        .map((f) => ({ f, need: rate[f.id] * +f.work / Math.max(1e-6, mult[f.id]) }))   // or the machine time per unit
        .sort((a, b) => a.need - b.need);
      const demand = mine.reduce((x, y) => x + y.need, 0);
      let left = cap;
      mine.forEach((it, k) => {                       // water-filling: equal shares, capped at need
        const give = Math.min(it.need, left / (mine.length - k));
        left -= give;
        rate[it.f.id] *= it.need > 0 ? give / it.need : 0;
      });
      asked[m.id] = cap > 0 ? demand / cap : (demand > 0 ? Infinity : 0);
      busy[m.id] = cap > 0 ? (cap - left) / cap : 0;
    });

    stocks.forEach((s) => {
      const all = P.touching.get(s.id);
      if (!all.length) return;
      const per = (f) => (f.from === s.id ? ratio(f) : 0) + (f.uses || []).filter((u) => u.stock === s.id).reduce((x, u) => x + (+u.per || 0), 0);
      const take = all.reduce((x, f) => x + rate[f.id] * per(f) * dt, 0);
      if (take > avail[s.id] && take > 0) all.forEach((f) => { rate[f.id] *= avail[s.id] / take; });
    });
    stocks.forEach((s) => {                           // a ceiling: inflows share the room left under it
      if (s.max === undefined || s.max === null || s.max === "") return;
      const ins = flows.filter((f) => f.to === s.id);
      const give = ins.reduce((x, f) => x + rate[f.id] * dt, 0), room = Math.max(0, +s.max - (level[s.id] || 0));
      if (give > room && give > 0) ins.forEach((f) => { rate[f.id] *= room / give; });
    });
    return { rate, asked, busy };
  }

  function move(model, level, rate, dt) {
    (model.flows || []).forEach((f) => {
      const amt = rate[f.id] * dt;
      if (f.from && f.from in level) level[f.from] = Math.max(0, level[f.from] - amt * ratio(f));
      (f.uses || []).forEach((u) => { if (u.stock in level) level[u.stock] = Math.max(0, level[u.stock] - amt * (+u.per || 0)); });
      if (f.outputs && f.outputs.length) {            // a flow that can fill several stocks splits by its weights
        const outs = [f.to, ...f.outputs].filter((id) => id && id in level);
        const w = outs.map((id) => (f.split && f.split[id] !== undefined ? Math.max(0, +f.split[id]) : 1));
        const total = w.reduce((x, y) => x + y, 0) || 1;
        outs.forEach((id, k) => { level[id] += amt * w[k] / total; });
      } else if (f.to && f.to in level) level[f.to] += amt;
    });
  }

  function simulate(model, opts) {
    opts = opts || {};
    const dt = +model.dt > 0 ? +model.dt : 0.25;
    const horizon = +(opts.horizon ?? model.horizon ?? 168);
    const steps = Math.max(1, Math.round(horizon / dt));
    const every = Math.max(1, Math.round(1 / dt));          // record once per time unit
    const stocks = model.stocks || [], flows = model.flows || [], machines = model.machines || [];

    // opts.start: levels to start from (e.g. the live run's current state); opts.t0: the time they are at
    const level = {};
    stocks.forEach((s) => {
      const v = opts.start && s.id in opts.start ? opts.start[s.id] : (opts.fromZero ? 0 : +s.initial || 0);
      level[s.id] = Math.max(0, +v || 0);
    });
    const t0 = +opts.t0 || 0;

    const out = { t: [], levels: {}, rates: {}, load: {}, busy: {} };
    stocks.forEach((s) => { out.levels[s.id] = []; });
    flows.forEach((f) => { out.rates[f.id] = []; });
    machines.forEach((m) => { out.load[m.id] = []; out.busy[m.id] = []; });

    const P = prep(model);
    for (let step = 0; step <= steps; step++) {
      const { rate, asked, busy } = model.inputs ? flowRates(model, readable(model, level, t0 + step * dt), dt, level, P) : flowRates(model, level, dt, undefined, P);
      if (step % every === 0) {
        out.t.push(+(t0 + step * dt).toFixed(6));
        stocks.forEach((s) => out.levels[s.id].push(level[s.id]));
        flows.forEach((f) => out.rates[f.id].push(rate[f.id]));
        machines.forEach((m) => { out.load[m.id].push(asked[m.id]); out.busy[m.id].push(busy[m.id]); });
      }
      if (step === steps) break;
      move(model, level, rate, dt);
    }
    return { series: out, summary: summarize(model, out) };
  }

  function summarize(model, out) {
    const targets = [];
    (model.stocks || []).forEach((s) => {
      if (!s.target || s.target.value === undefined || s.target.value === null || s.target.value === "") return;
      const vals = out.levels[s.id], goal = +s.target.value, by = s.target.by === undefined || s.target.by === "" ? null : +s.target.by;
      let reachedAt = null;
      for (let i = 0; i < vals.length; i++) if (vals[i] >= goal) { reachedAt = out.t[i]; break; }
      let atBy = null;
      if (by !== null) {
        let i = out.t.findIndex((t) => t >= by);
        if (i < 0) i = vals.length - 1;
        atBy = vals[i];
      }
      targets.push({ stock: s.id, goal, by, reachedAt, atBy, met: reachedAt !== null && (by === null || reachedAt <= by) });
    });
    const machines = (model.machines || []).map((m) => {
      const l = out.load[m.id].filter((x) => isFinite(x));
      const b = out.busy[m.id] || [];
      const avg = l.length ? l.reduce((a, c) => a + c, 0) / l.length : 0;
      const over = l.length ? l.filter((x) => x > 1.0001).length / l.length : 0;
      return { machine: m.id, avgLoad: avg, avgBusy: b.length ? b.reduce((a, c) => a + c, 0) / b.length : 0,
               peakLoad: l.length ? Math.max(...l) : 0, overloadedShare: over };
    });
    const unassigned = (model.flows || []).filter((f) => !f.machine).map((f) => f.id);
    return { targets, machines, unassigned };
  }

  // ---------- fitting equations to a live run ----------
  // run: { t: [...], levels: {stock: [...]}, rates: {flow: [...]}, load: {machine: [...] (share of time busy)} }
  // The rate measured in time unit i is predicted from what that time unit had to work with:
  // the levels at the end of the one before (empty before the first) plus whatever arrived during
  // it, since a flow can pass on an item in the same minute it arrives. Predictions use the
  // model's own machine rule, so a flow whose machine was the limit is judged with that limit.
  // Counts per time unit are whole numbers, so errors are measured on averages over windows.
  function fit(model, run, opts) {
    opts = opts || {};
    const stockName = (id) => ((model.stocks || []).find((s) => s.id === id) || {}).name || id;
    const n = run.t.length;
    const stocks = model.stocks || [], flows = model.flows || [];
    const prev = [], avail = [];
    for (let i = 0; i < n; i++) {
      const start = {};
      stocks.forEach((s) => { start[s.id] = i === 0 ? ((opts.start || {})[s.id] || 0) : ((run.levels[s.id] || [])[i - 1] || 0); });
      prev.push(start);
      const lv = { ...start };
      flows.forEach((g) => {                           // add what arrived during this time unit
        const r = (run.rates[g.id] || [])[i] || 0;
        const outs = g.outputs && g.outputs.length ? [g.to, ...g.outputs].filter(Boolean) : (g.to ? [g.to] : []);
        if (!outs.length || !r) return;
        const w = outs.map((id) => (g.split && g.split[id] !== undefined ? +g.split[id] : 1)), tot = w.reduce((x, y) => x + y, 0) || 1;
        outs.forEach((id, k) => { if (id in lv) lv[id] += r * w[k] / tot; });
      });
      avail.push(lv);
    }
    const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
    const win = Math.max(1, Math.min(10, Math.floor(n / 6)));
    const windows = (a) => { const out = []; for (let i = 0; i + win <= a.length; i += win) out.push(mean(a.slice(i, i + win))); return out; };

    function score(variant, fid) {
      const meas = (run.rates[fid] || []).slice(0, n);
      const pred = [];
      const P = prep(variant);
      for (let i = 0; i < n; i++) pred.push(flowRates(variant, prev[i], 1, avail[i], P).rate[fid] || 0);
      const pw = windows(pred), mw = windows(meas);
      const se = pw.reduce((x, p, k) => x + (p - mw[k]) ** 2, 0);
      return { rmse: Math.sqrt(se / Math.max(1, pw.length)), pred };
    }

    // Replaying the whole run: how far each stock's simulated path ends up from the measured one.
    function pathError(variant) {
      const sim = simulate({ ...variant, horizon: n }, { horizon: n, fromZero: true, start: opts.start }).series;
      const errs = stocks.map((s) => {
        const live = run.levels[s.id] || [], simL = sim.levels[s.id] || [];
        let se = 0;
        for (let i = 0; i < n; i++) se += ((simL[i + 1] || 0) - (live[i] || 0)) ** 2;
        return Math.sqrt(se / Math.max(1, n)) / (mean(live.slice(0, n)) + 1);
      });
      return mean(errs);
    }

    const rows = (model.flows || []).map((f) => {
      const meas = (run.rates[f.id] || []).slice(0, n);
      const avg = mean(meas);
      const scale = Math.max(avg, 0.05);
      const withRate = (rate) => ({ ...model, flows: model.flows.map((g) => (g.id === f.id ? { ...g, rate } : g)) });
      const notes = [];

      const cands = [];
      cands.push({ rate: { form: "constant", value: round(avg) }, params: 1 });
      const isStock = (id) => id && stocks.some((s) => s.id === id);
      const propOn = [...new Set([f.rate && f.rate.stock, f.from].filter(isStock))];     // a rate that grows with what it reads or drains
      const gapOn = [...new Set([f.rate && f.rate.stock, f.to, f.from].filter(isStock))]; // a rate that closes a gap in a stock
      propOn.forEach((sid) => {
        const L = prev.map((p) => p[sid]);
        const sLL = L.reduce((x, l) => x + l * l, 0), sRL = L.reduce((x, l, i) => x + l * meas[i], 0);
        if (sLL > 0) cands.push({ rate: { form: "proportional", stock: sid, k: round(sRL / sLL) }, params: 1 });
      });
      gapOn.forEach((sid) => {
        const L = prev.map((p) => p[sid]), mL = mean(L), mR = avg, hi = Math.max(...L);
        const vL = L.reduce((x, l) => x + (l - mL) ** 2, 0);
        if (vL > 0) {
          const b = L.reduce((x, l, i) => x + (l - mL) * (meas[i] - mR), 0) / vL, a = mR - b * mL;
          if (b < 0 && a > 0 && -a / b <= 3 * Math.max(1, hi)) cands.push({ rate: { form: "gap", stock: sid, goal: round(-a / b), time: round(-1 / b) }, params: 2 });
        }
      });
      if (f.from) cands.push({ rate: { form: "available" }, params: 0 });

      const cur = { rate: f.rate, ...score(model, f.id) };
      cands.forEach((c) => Object.assign(c, score(withRate(c.rate), f.id)));
      cands.sort((x, y) => x.rmse * (1 + 0.04 * x.params) - y.rmse * (1 + 0.04 * y.params));
      let best = cands[0];
      // On a machine that was the limit, a constant only repeats this run's share of the machine.
      // Prefer "everything available" when it fits nearly as well: the machine then sets the pace,
      // and a change of machine shows up in the simulation.
      const mach = f.machine && f.machine !== "environment" ? (model.machines || []).find((x) => x.id === f.machine) : null;
      const machBusy = mach ? mean((run.load[mach.id] || []).slice(0, n)) : 0;
      const avail = cands.find((c) => c.rate.form === "available");
      if (machBusy >= 0.85 && best.rate.form === "constant" && avail && avail.rmse <= Math.max(best.rmse * 2, 0.2 * scale)) best = avail;
      const events0 = meas.reduce((x, y) => x + y, 0);
      const noisy = events0 < 3 * Math.max(1, n / win);           // too few events to trust small differences
      const keep = cur.rmse <= best.rmse * (noisy ? 1.5 : 1.1) + 0.02 * scale;   // the current equation is nearly as good
      const choice = keep ? cur : best;

      // what to tell the person
      const m = f.machine && f.machine !== "environment" ? (model.machines || []).find((x) => x.id === f.machine) : null;
      if (m) {
        const busy = mean((run.load[m.id] || []).slice(0, n));
        if (busy >= 0.85) {
          notes.push(`${m.name} was busy ${Math.round(busy * 100)}% of the time, so this flow's speed was set by how much of ${m.name}'s time was left, as much as by its equation.`);
          if (choice.rate.form === "constant") notes.push(`A constant matches this run, but it fixes today's share of ${m.name}'s time; if this flow gets more machine time, the real rate will rise and the constant will not.`);
        }
      }
      if (f.from) {
        const src = prev.map((p) => p[f.from]);
        const emptyShare = src.filter((x) => x < 0.5).length / Math.max(1, n);
        if (emptyShare > 0.6 && avg > 0) notes.push(`Its source was empty at ${Math.round(emptyShare * 100)}% of the time marks, yet it kept moving ${fmt(avg)} per step: it takes things as fast as they arrive.`);
      }
      const used = (choice.rate && choice.rate.stock) || f.from;
      if (used && choice.rate && choice.rate.form !== "available") {
        const L = prev.map((p) => p[used]), lo = Math.min(...L), hi = Math.max(...L);
        if (hi - lo <= Math.max(2, 0.15 * mean(L))) notes.push(`${stockName(used)} hardly changed in this run (${fmt(lo)} to ${fmt(hi)}), so this run cannot show how ${choice.rate.form === "constant" ? "the rate would respond if it did" : "the rate depends on it"}; a run where it varies would tell.`);
      }
      const events = meas.reduce((x, y) => x + y, 0);
      if (events < 3 * Math.max(1, n / win)) notes.push(`Only ${fmt(events)} of these happened in ${n} steps, so a few more or fewer by chance moves the numbers a lot. Keep the current equation unless it is far off.`);
      const spread = cands.length > 1 ? cands[cands.length - 1].rmse - cands[0].rmse : 0;
      if (cands.length > 1 && spread <= 0.1 * scale) notes.push("Every equation tried fits about equally well, so this run cannot tell them apart.");

      return {
        flow: f.id, n, window: win, measuredMean: avg,
        current: { rate: f.rate, rmse: cur.rmse, relErr: cur.rmse / scale, pred: cur.pred },
        proposed: { rate: choice.rate, rmse: choice.rmse, relErr: choice.rmse / scale, pred: choice.pred },
        change: !keep, notes,
        tried: cands.map((c) => ({ rate: c.rate, relErr: c.rmse / scale })),
        measured: meas, _cands: cands, _cur: cur, _scale: scale,
      };
    });

    // Second pass: with every other flow at its first-pass choice, replay the whole run for each
    // candidate. An equation that fits each minute but lets a stock drift away loses here.
    const chosen = Object.fromEntries(rows.map((r) => [r.flow, r.proposed.rate]));
    const historyOut = {};
    const withAll = (over) => ({ ...model, flows: model.flows.map((g) => ({ ...g, rate: over[g.id] || chosen[g.id] || g.rate })) });
    rows.forEach((r) => {
      const opts2 = [{ rate: r.current.rate, rmse: r._cur.rmse, current: true }, ...r._cands];
      opts2.forEach((c) => { c.path = pathError(withAll({ [r.flow]: c.rate })); c.total = c.rmse / r._scale + c.path; });
      // Judge each form on its running average score across refits (opts.history), not on one
      // refit: a single noisy replay should not flip the choice, and with more data the averages
      // settle. Then stay with last time's form unless another is clearly better.
      const hist = (opts.history || {})[r.flow] || {};
      const formKey = (c) => (c.current ? "current:" + JSON.stringify(c.rate) : `${c.rate.form}:${c.rate.stock || ""}`);
      const nextHist = {};
      opts2.forEach((c) => { const k = formKey(c); c.score = k in hist ? 0.7 * hist[k] + 0.3 * c.total : c.total; nextHist[k] = c.score; });
      historyOut[r.flow] = nextHist;
      const cur = opts2[0];
      let best = opts2.slice(1).reduce((x, y) => (y.score < x.score ? y : x), opts2[1] || cur);
      const prev = (opts.prefer || {})[r.flow];
      const incumbent = prev && opts2.slice(1).find((c) => c.rate.form === prev.form && (c.rate.stock || "") === (prev.stock || ""));
      if (incumbent && incumbent !== best && incumbent.score <= best.score * 1.15) best = incumbent;
      const keep = !best || cur.score <= best.score * 1.1;
      const pick = keep ? cur : best;
      r.change = !keep && JSON.stringify(pick.rate) !== JSON.stringify(r.current.rate);
      r.proposed = { ...r.proposed, rate: pick.rate, relErr: pick.rmse / r._scale, pathErr: pick.path };
      r.current.pathErr = cur.path;
      r.tried = opts2.slice(1).map((c) => ({ rate: c.rate, relErr: c.rmse / r._scale, pathErr: c.path }));
      chosen[r.flow] = pick.rate;
      const f = model.flows.find((g) => g.id === r.flow), m = f && (model.machines || []).find((x) => x.id === f.machine);
      const busy = m ? mean((run.load[m.id] || []).slice(0, n)) : 0;
      r.notes = r.notes.filter((t) => !t.startsWith("A constant matches this run"));
      if (m && busy >= 0.85 && pick.rate.form === "constant") r.notes.push(`A constant matches this run, but it fixes today's share of ${m.name}'s time; if this flow gets more machine time, the real rate will rise and the constant will not.`);
      delete r._cands; delete r._cur; delete r._scale;
    });
    // the whole run replayed with the current and the proposed equations, for the side-by-side view
    const replay = (variant) => simulate({ ...variant, horizon: n }, { horizon: n, fromZero: true, start: opts.start }).series;
    rows.history = historyOut;
    rows.pathBefore = pathError(model);
    rows.pathAfter = pathError(withAll({}));
    rows.replayBefore = replay(model);
    rows.replayAfter = replay(withAll({}));
    return rows;
  }
  function round(v) { const a = Math.abs(v); return +(a >= 10 ? v.toFixed(1) : a >= 1 ? v.toFixed(2) : v.toFixed(3)); }

  // ---------- leverage: where would more speed help the goals most? ----------
  // Each flow in turn is made 10% faster (its machine takes 10% less time per unit, or its rate is
  // 10% higher) and the model is run again. Goals are the stocks with a target (or opts.goals).
  function leverage(model, opts) {
    opts = opts || {};
    const sim = (m) => simulate(m, { horizon: opts.horizon, start: opts.start, t0: opts.t0 }).series;
    const base = sim(model), last = base.t.length - 1;
    const goals = opts.goals || (model.stocks || []).filter((s) => s.target && s.target.value !== undefined && s.target.value !== "").map((s) => s.id);
    if (!goals.length) return { goals: [], rows: [] };
    const only = opts.flows ? new Set(opts.flows) : null;
    const rows = (model.flows || []).filter((f) => f.machine && (!only || only.has(f.id))).map((f) => {
      const faster = { ...model, flows: model.flows.map((g) => (g.id === f.id ? { ...g, boost: (g.boost || 1) * 1.1 } : g)) };
      const s = sim(faster);
      const effect = Object.fromEntries(goals.map((id) => {
        const b = base.levels[id][last], a = s.levels[id][last];
        return [id, { before: b, after: a, change: a - b, pct: b ? (a - b) / Math.abs(b) : 0 }];
      }));
      return { flow: f.id, effect, score: goals.reduce((x, id) => x + effect[id].pct, 0) / goals.length };
    }).sort((a, b) => b.score - a.score);
    return { goals, rows, horizon: base.t[last] };
  }

  const api = { simulate, flowRates, desiredRate, describeRate, fit, fmt, FORMS, effectValue, multiplier, machineCapacity, leverage, inputValue };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SDSim = api;
})(typeof window !== "undefined" ? window : globalThis);
