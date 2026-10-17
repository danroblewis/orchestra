// Discovering flows from stock levels alone.
//
// Every step, each stock's change is what flowed in minus what flowed out. Imagine a flow
// between every pair of stocks (and to and from outside), nearly all of them zero. Each
// candidate flow moves some amount q each step, and q follows a small equation:
//     q = c + a x (level of the stock it drains) + b x (level of the stock it fills)
// This covers a constant rate, a rate proportional to the source, and closing a gap in the
// target. A flow between stocks with different units has a ratio: it takes `ratio` units
// from its source for each unit it puts in its target (2 socks make 1 pair).
//
// The search is greedy and sparse. It starts with no flows. Each round it adds the one
// candidate flow that most improves the Bayesian information criterion (fit gained, minus a
// price for every number added), drops any of that flow's equation terms that do not pay for
// themselves, and stops when no candidate is worth its price. Steps are summed into windows
// first, so the whole-number counts of single steps do not swamp the signal.
//
// The structure (which flows exist) is shared by the whole run, but when the run has eras
// (opts.eras: [{start}]), each flow between stocks gets its own numbers in each era: changing a
// machine changes how fast a flow runs, not whether it exists. Flows to and from outside keep
// one set of numbers: eras are changes to our own machines, and the world does not notice them. Each stock is scored against its
// own scatter, so a stock that swings by hundreds does not drown out one that moves by one.
//
// With opts.moved, the measured flows are subtracted first (see `known` below), so the search
// looks only for what the model is missing.
//
// Several structures can explain the same data. The search returns one simple structure,
// plus the runners-up it nearly chose at each round.
(function (root) {
  "use strict";
  const OUT = null;

  function discover(stocks, run, opts) {
    opts = opts || {};
    // long runs are summed into wider windows (about 400 of them): a month of 5-minute steps is
    // examined in two-hour windows, which keeps the search fast and still sees days and incidents
    const w = Math.max(1, opts.window || 5, Math.ceil(run.t.length / (opts.maxWindows || 400)));
    const maxFlows = opts.maxFlows || 12;
    const ids = stocks.map((s) => s.id), S = ids.length, T = run.t.length;
    const unit = Object.fromEntries(stocks.map((s) => [s.id, s.unit || ""]));
    const start = opts.start || {};
    // before the first step: the given starting level, or else the first measurement (a run that
    // starts mid-stream did not jump there from zero)
    const prevLevel = (id, i) => (i === 0 ? +(id in start ? start[id] : (run.levels[id] || [])[0]) || 0 : +((run.levels[id] || [])[i - 1] || 0));

    // windows: summed change per stock, and summed equation inputs (so coefficients stay per step)
    const W = Math.floor(T / w);
    if (W < 4) return { flows: [], unexplained: {}, windows: W, note: "Too few steps to search." };
    // What is already known: when the run records what each measured flow took from and made into
    // each stock (opts.moved, one {flow: {took, made}} per step), that part of every stock's change
    // is subtracted first, and the search explains only what is left. A complete model leaves nothing.
    const knownDelta = opts.knownDelta || knownChanges(opts.moved, run.t.length);
    // (the first step, with no starting level given, has no change to explain, measured or not)
    const known = (i, id) => (knownDelta && knownDelta[i] && (i > 0 || id in start) ? knownDelta[i][id] || 0 : 0);
    const dY = [], lvl = [];
    for (let k = 0; k < W; k++) {
      const dy = {}, lv = {};
      ids.forEach((id) => {
        let d = 0, l = 0;
        for (let i = k * w; i < (k + 1) * w; i++) { d += ((run.levels[id] || [])[i] || 0) - prevLevel(id, i) - known(i, id); l += prevLevel(id, i); }
        dy[id] = d; lv[id] = l;
      });
      dY.push(dy); lvl.push(lv);
    }
    // Besides each stock, one row per unit holds the total change of all stocks in that unit. Flows
    // between measured stocks cancel in it, so it shows plainly what came in from, or went out to,
    // somewhere unmeasured: outside, or a hidden stock filling and draining.
    const units = S >= 2 && opts.totals !== false ? [...new Set(ids.map((id) => unit[id]))] : [];
    const unitIdx = Object.fromEntries(ids.map((id) => [id, units.indexOf(unit[id])]));
    const R = S + units.length, N = W * R;
    // which era each window belongs to (by its first step)
    // era boundaries; whatever comes before the first one given is an era of its own
    const starts = (opts.eras || []).map((e) => +e.start).filter((x) => isFinite(x)).sort((a, b) => a - b);
    if (starts.length && starts[0] > run.t[0]) starts.unshift(run.t[0]);
    const eraOf = (k) => { const t = run.t[k * w]; let e = 0; starts.forEach((st, i) => { if (t >= st) e = i; }); return e; };
    const E = Math.max(1, starts.length), winEra = Array.from({ length: W }, (_, k) => (starts.length ? eraOf(k) : 0));
    // each stock weighted by its jitter: how much its change differs from one window to the next
    // (real, explainable movement changes slowly; jitter does not), so every stock counts equally
    const wt = ids.map((id) => {
      const d = dY.map((r) => r[id]);
      let s2 = 0; for (let k = 1; k < W; k++) s2 += (d[k] - d[k - 1]) ** 2;
      return 1 / Math.max(Math.sqrt(s2 / Math.max(1, W - 1) / 2), 0.5);
    });
    const y = new Float64Array(N);
    const totalOf = (k, u) => ids.reduce((a, id) => a + (unitIdx[id] === u ? dY[k][id] : 0), 0);
    const wtTot = units.map((_, u) => {
      let s2 = 0; for (let k = 1; k < W; k++) s2 += (totalOf(k, u) - totalOf(k - 1, u)) ** 2;
      return 1 / Math.max(Math.sqrt(s2 / Math.max(1, W - 1) / 2), 0.5);
    });
    for (let k = 0; k < W; k++) {
      ids.forEach((id, j) => { y[k * R + j] = dY[k][id] * wt[j]; });
      units.forEach((_, u) => { y[k * R + S + u] = totalOf(k, u) * wtTot[u]; });
    }

    // candidate flows: every ordered pair, outside included, with ratios where units differ
    const nodes = [...ids, OUT];
    const cands = [];
    const final = new Set(stocks.filter((s) => s.final).map((s) => s.id));     // nothing ever leaves a final stock
    // Stocks in different groups never exchange things directly (one topic's lag cannot flow into
    // another's); stocks with no group may exchange with any stock.
    const group = Object.fromEntries(stocks.map((s) => [s.id, s.group]));
    const canExchange = (a, b) => a === OUT || b === OUT || !group[a] || !group[b] || group[a] === group[b];
    nodes.forEach((a) => nodes.forEach((b) => {
      if (a === b || (a === OUT && b === OUT) || final.has(a) || !canExchange(a, b)) return;
      if (opts.closed && (a === OUT || b === OUT)) return;    // everything that enters or leaves is measured
      const ratios = a !== OUT && b !== OUT && unit[a] !== unit[b] ? [2, 3, 0.5, 1 / 3] : [1];
      ratios.forEach((ratio) => cands.push({ from: a, to: b, ratio }));
    }));
    // a flow's columns: its effect on every stock, times each of its equation's inputs
    // Columns and their dot products are cached: the search tries thousands of sets of flows,
    // but they are all made of the same few hundred columns.
    const colCache = new Map(), dotCache = new Map(), ydot = new Map();
    function columns(c, terms) {
      const base = `${c.from}>${c.to}x${c.ratio}${tag(c)}`;
      const key = base + "|" + terms.join(",");
      if (colCache.has(key)) return colCache.get(key);
      const cols = makeColumns(c, terms);
      colCache.set(key, cols);
      return cols;
    }
    function makeColumns(c, terms) {
      if (c.delay) return delayedColumns(c);
      const eff = new Float64Array(S);
      if (c.from !== OUT) eff[ids.indexOf(c.from)] -= c.ratio;
      if (c.to !== OUT) eff[ids.indexOf(c.to)] += 1;
      const inputs = { c: () => w, a: (k) => lvl[k][c.from] || 0, b: (k) => lvl[k][c.to] || 0 };
      const shared = c.from === OUT || c.to === OUT;
      return terms.flatMap((term) => Array.from({ length: shared ? 1 : E }, (_, e) => {
        const ck = `${c.from}>${c.to}x${c.ratio}|${term}|${e}`;
        if (colCache.has(ck)) return colCache.get(ck);
        const col = new Float64Array(N);
        for (let k = 0; k < W; k++) {
          if (!shared && winEra[k] !== e) continue;
          const v = inputs[term](k);
          for (let j = 0; j < S; j++) col[k * R + j] = eff[j] * v * wt[j];
          for (let j = 0; j < S; j++) if (eff[j] && unitIdx[ids[j]] >= 0) col[k * R + S + unitIdx[ids[j]]] += eff[j] * v * wtTot[unitIdx[ids[j]]];
        }
        col._ck = ck;
        colCache.set(ck, col);
        return col;
      }).filter((col) => col.some((v) => v !== 0)));
    }
    function dot(a, b) {
      const k = a._ck < b._ck ? a._ck + "~" + b._ck : b._ck + "~" + a._ck;
      let v = dotCache.get(k);
      if (v === undefined) { v = 0; for (let r = 0; r < N; r++) v += a[r] * b[r]; dotCache.set(k, v); }
      return v;
    }
    function dotY(a) {
      let v = ydot.get(a._ck);
      if (v === undefined) { v = 0; for (let r = 0; r < N; r++) v += a[r] * y[r]; ydot.set(a._ck, v); }
      return v;
    }
    const termsFor = (c) => ["c", ...(c.from !== OUT ? ["a"] : []), ...(c.to !== OUT ? ["b"] : [])];
    // a rate that depends only on the level of the stock it fills, with no constant, means nothing
    const sensible = (terms) => !(terms.includes("b") && !terms.includes("c"));

    let yy = 0; for (let i = 0; i < N; i++) yy += y[i] * y[i];
    function solve(cols) {
      const p = cols.length;
      if (!p) return { theta: [], rss: yy };
      const norm = cols.map((c) => Math.sqrt(dot(c, c)) || 1);
      const G = Array.from({ length: p }, (_, i) => cols.map((c) => dot(cols[i], c)));
      const b = cols.map(dotY);
      const A = Array.from({ length: p }, () => new Float64Array(p + 1));
      for (let i = 0; i < p; i++) {
        for (let j = 0; j < p; j++) A[i][j] = G[i][j] / (norm[i] * norm[j]);
        A[i][p] = b[i] / norm[i];
        A[i][i] += 1e-9;
      }
      for (let i = 0; i < p; i++) {                         // Gaussian elimination, partial pivoting
        let m = i; for (let r = i + 1; r < p; r++) if (Math.abs(A[r][i]) > Math.abs(A[m][i])) m = r;
        [A[i], A[m]] = [A[m], A[i]];
        const piv = A[i][i] || 1e-12;
        for (let r = 0; r < p; r++) if (r !== i) { const f = A[r][i] / piv; for (let c = i; c <= p; c++) A[r][c] -= f * A[i][c]; }
      }
      const theta = A.map((row, i) => row[p] / (row[i] || 1e-12) / norm[i]);
      // residual from the cached sums: |y|^2 - 2 theta.Xty + theta.G.theta (no pass over the data)
      let rss = yy;
      for (let i = 0; i < p; i++) { rss -= 2 * theta[i] * b[i]; for (let j = 0; j < p; j++) rss += theta[i] * theta[j] * G[i][j]; }
      return { theta, rss: Math.max(rss, 0) };
    }
    const bic = (rss, p) => N * Math.log(Math.max(rss, 1e-9) / N) + p * Math.log(N);
    // Things are conserved unless shown otherwise: a flow that makes things appear or vanish
    // (to or from outside), or that converts units, costs a little more than a plain move.
    const extra = (set) => set.reduce((s, f) => s + (f.cand.from === OUT || f.cand.to === OUT ? 0.5 : 0) + (f.cand.ratio !== 1 ? 0.25 : 0) + (f.cand.delay ? 2 : 0), 0) * Math.log(N);
    // Least movement: a loop of flows changes no stock, so it fits any data for free. Charge each
    // flow for what it moves (at both ends), relative to how much the stocks actually changed.
    let totalChange = 0; for (let k = 0; k < W; k++) ids.forEach((id) => { totalChange += Math.abs(dY[k][id]); });
    totalChange = Math.max(totalChange, 1);
    function movement(set, theta) {
      let off2 = 0, m = 0;
      set.forEach((f) => {
        const n = columns(f.cand, f.terms).length, q = amounts(f.cand, f.terms, theta.slice(off2, off2 + n)); off2 += n;
        const ends = (f.cand.from !== OUT ? 1 : 0) + (f.cand.to !== OUT ? 1 : 0);   // not weighted by ratio: no ratio is cheaper than another
        m += q.reduce((a, b) => a + Math.abs(b), 0) * ends;
      });
      return (opts.movement === undefined ? 2 : opts.movement) * Math.log(N) * m / totalChange;
    }

    // a flow must move a sensible amount: on average forward, and rarely backwards
    const inputOf = (c, term, k) => (term === "c" ? w : term === "a" ? lvl[k][c.from] || 0 : term === "g" ? gainW(c.src)[k] : lvl[k][c.to] || 0);
    // flows to or from outside, and flows through a hidden stock (whose contents span eras), keep one set of numbers
    const sharedFlow = (c) => c.from === OUT || c.to === OUT || !!c.delay;
    function columnUsed(c, term, e) {
      if (sharedFlow(c)) { if (e > 0) return false; for (let k = 0; k < W; k++) if (inputOf(c, term, k) !== 0) return true; return false; }
      for (let k = 0; k < W; k++) if (winEra[k] === e && inputOf(c, term, k) !== 0) return true;
      return false;
    }
    // the amount a flow moves in each window, from its fitted numbers (columns go term by term, era by era)
    function amounts(c, terms, theta) {
      const idx = {}; let i = 0;
      terms.forEach((term) => { for (let e = 0; e < E; e++) if (columnUsed(c, term, e)) idx[term + ":" + e] = i++; });
      return Array.from({ length: W }, (_, k) => terms.reduce((q, term) => {
        const j = idx[term + ":" + (sharedFlow(c) ? 0 : winEra[k])];
        return j === undefined ? q : q + theta[j] * inputOf(c, term, k);
      }, 0));
    }
    // a flow must move a sensible amount: on average forward, and rarely backwards
    let strict = false;                                      // during the search a flow may run both ways (a net exchange)
    function plausible(c, terms, theta) {
      if (!strict) return true;
      const q = amounts(c, terms, theta);
      return q.reduce((a, b) => a + b, 0) > 0 && q.filter((v) => v < -0.5).length <= 0.1 * W;
    }
    const ncols = (set) => set.reduce((s, f) => s + columns(f.cand, f.terms).length, 0);

    const fitOf = (set) => solve(set.flatMap((f) => columns(f.cand, f.terms)));
    const total = (set, r) => bic(r.rss, ncols(set)) + extra(set) + movement(set, r.theta);

    // ---- flows through a stock nobody measures ----
    // Things leave one stock and arrive in another (or back in the same one) some time later: they
    // waited somewhere unmeasured. Such a flow takes k x (level of its source) each step, as any
    // proportional flow does, and delivers it after a delay: the arrivals are the departures pushed
    // through a hidden stock. Three shapes of delay:
    //   exp     the hidden stock drains in proportion to what it holds (a lab, a vendor, a backlog)
    //   erlang  two such stocks in a row: arrivals bunch around the mean delay (a follow-up visit)
    //   pipe    everything waits the same time (a pipeline, a fixed-length process)
    // An "echo" is an arrival timed by another stock's gains rather than taken from a stock: things
    // that come back (from outside) some time after they first arrived there, such as a discharged
    // patient returning. For a fixed shape and delay the flow is one more column, so the same search
    // and the same price decide whether the hidden stock pays for itself.
    const stepCache = new Map();
    const levelsOf = (id) => {
      const key = "L" + id; if (stepCache.has(key)) return stepCache.get(key);
      const u = new Float64Array(T); for (let i = 0; i < T; i++) u[i] = prevLevel(id, i);
      stepCache.set(key, u); return u;
    };
    const gainsOf = (id) => {
      const key = "G" + id; if (stepCache.has(key)) return stepCache.get(key);
      const u = new Float64Array(T), L = run.levels[id] || [];
      for (let i = 0; i < T; i++) u[i] = Math.max(0, (+L[i] || 0) - prevLevel(id, i));
      stepCache.set(key, u); return u;
    };
    function gainW(id) {
      const key = "GW" + id; if (stepCache.has(key)) return stepCache.get(key);
      const u = gainsOf(id), out = new Float64Array(W);
      for (let k = 0; k < W; k++) for (let i = k * w; i < (k + 1) * w; i++) out[k] += u[i];
      stepCache.set(key, out); return out;
    }
    // The arrivals, and what waits, when u enters a hidden stock each step, starting empty; and the
    // same for one unit already waiting when measuring began (how much was waiting is fitted too).
    function delayed(u, shape, tau) {
      const key = `D${shape}${tau}`;
      if (!u._d) u._d = new Map();
      if (u._d.has(key)) return u._d.get(key);
      const n = u.length, arr = new Float64Array(n), held = new Float64Array(n), arr0 = new Float64Array(n), held0 = new Float64Array(n);
      if (shape === "pipe") {
        for (let i = 0; i < n; i++) { arr[i] = i >= tau ? u[i - tau] : 0; arr0[i] = i < tau ? 1 / tau : 0; }
        let h = 0, h0 = 1;
        for (let i = 0; i < n; i++) { h += u[i] - arr[i]; h0 -= arr0[i]; held[i] = h; held0[i] = Math.max(0, h0); }
      } else {
        const stages = shape === "erlang" ? 2 : 1, a = Math.min(1, stages / tau);   // drains stages/tau of itself a step, as a proportional flow does
        const H = new Float64Array(stages), H0 = new Float64Array(stages).fill(1 / stages);
        for (let i = 0; i < n; i++) {
          let inflow = u[i], inflow0 = 0;
          for (let st = 0; st < stages; st++) {
            const q = a * H[st], q0 = a * H0[st];
            H[st] += inflow - q; H0[st] += inflow0 - q0; inflow = q; inflow0 = q0;
          }
          arr[i] = inflow; arr0[i] = inflow0;
          held[i] = H.reduce((x, y2) => x + y2, 0); held0[i] = H0.reduce((x, y2) => x + y2, 0);
        }
      }
      const r = { arr, held, arr0, held0 };
      u._d.set(key, r); return r;
    }
    const sourceSeries = (c) => (c.from !== OUT ? levelsOf(c.from) : gainsOf(c.src));
    // two columns: what the flow takes and delivers, and what was already waiting arriving
    function delayedColumns(c) {
      const ck = `${c.from}>${c.to}${tag(c)}|a|0`;
      if (colCache.has(ck)) return colCache.get(ck);
      const u = sourceSeries(c), { arr, arr0 } = delayed(u, c.delay.shape, c.delay.tau);
      const col = new Float64Array(N), col0 = new Float64Array(N), jf = c.from !== OUT ? ids.indexOf(c.from) : -1, jt = ids.indexOf(c.to);
      const ut = units.length ? unitIdx[ids[jt]] : -1, uf = units.length && jf >= 0 ? unitIdx[ids[jf]] : -1;
      for (let k = 0; k < W; k++) {
        let U = 0, V = 0, V0 = 0;
        for (let i = k * w; i < (k + 1) * w; i++) { U += u[i]; V += arr[i]; V0 += arr0[i]; }
        if (jf >= 0) col[k * R + jf] -= U * wt[jf];
        col[k * R + jt] += V * wt[jt]; col0[k * R + jt] += V0 * wt[jt];
        if (uf >= 0) col[k * R + S + uf] -= U * wtTot[uf];
        if (ut >= 0) { col[k * R + S + ut] += V * wtTot[ut]; col0[k * R + S + ut] += V0 * wtTot[ut]; }
      }
      col._ck = ck; col0._ck = ck + "|start";
      const cols = [col, col0];
      colCache.set(ck, cols);
      return cols;
    }

    // Moves that add a flow through a hidden stock. Candidates are the (source, target) pairs where a
    // delayed copy of the source best matches what the target still lacks; for each, every shape and
    // delay is tried, alone or in place of the flows it would explain (out to outside, in from
    // outside, or straight between the two).
    const latentOn = opts.latent !== false && T >= 40;
    const latentTaus = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 27, 33, 40, 48, 60, 72, 90, 110, 135, 165, 200, 240, 300, 360].filter((t) => t <= T / 4);
    // an echo is timed by a final stock's gains: things that ended (were discharged, delivered) and come back
    const elsewhere = (opts.sources || []).filter((x) => x.final && !ids.includes(x.id) && run.levels[x.id] && ids.some((id) => canExchange(id, x.id) && (!x.group || x.group === group[id]))).map((x) => x.id);
    const echoSources = opts.closed ? [] : [...ids.filter((id) => final.has(id)), ...elsewhere];
    function latentMoves(consider) {
      if (!latentOn) return;
      const fit = fitOf(chosen), cols = chosen.flatMap((f) => columns(f.cand, f.terms));
      const res = ids.map((_, j) => { const r = new Float64Array(W); for (let k = 0; k < W; k++) r[k] = y[k * R + j]; return r; });
      cols.forEach((col, i) => { for (let k = 0; k < W; k++) for (let j = 0; j < S; j++) res[j][k] -= col[k * R + j] * fit.theta[i]; });
      const pairs = [];
      ids.forEach((to, jt) => {
        const options = [];
        // (not back into the same stock: a delayed copy of a stock's own level fits any slow wiggle)
        ids.forEach((from) => { if (from !== to && !final.has(from) && unit[from] === unit[to] && canExchange(from, to)) options.push({ from, to, src: null }); });
        echoSources.forEach((src) => { if (src !== to) options.push({ from: OUT, to, src }); });
        options.forEach((o) => {
          const u = o.from !== OUT ? levelsOf(o.from) : gainsOf(o.src);
          let bestC = 0;
          [2, 12, 72].filter((t) => t === 2 || t <= T / 4).forEach((tau) => {
            const { arr } = delayed(u, "exp", tau), v = new Float64Array(W);
            for (let k = 0; k < W; k++) for (let i = k * w; i < (k + 1) * w; i++) v[k] += arr[i];
            bestC = Math.max(bestC, corrOf(v, res[jt]));
          });
          if (bestC > 0.15) pairs.push({ ...o, corr: bestC });
        });
      });
      pairs.sort((a, b) => b.corr - a.corr).slice(0, opts.latentPairs || 8).forEach((o) => {
        // flows it might replace: one through a hidden stock between the same two (another delay), one out
        // of the source to outside, one into the target from outside, or a direct one between them
        const same = chosen.filter((f) => f.cand.delay && f.cand.from === o.from && f.cand.to === o.to && f.cand.src === o.src);
        const rivals = chosen.filter((f) => !f.cand.delay && ((f.cand.to === o.to && (f.cand.from === OUT || f.cand.from === o.from)) || (o.from !== OUT && f.cand.from === o.from && f.cand.to === OUT)));
        const base = [same];
        const drops = [...base, ...rivals.map((f) => [...same, f])];
        rivals.filter((f) => f.cand.from === OUT).forEach((a) => rivals.filter((f) => f.cand.to === OUT).forEach((b) => drops.push([...same, a, b])));
        ["exp", "erlang", "pipe"].forEach((shape) => latentTaus.forEach((tau) => {
          if (shape === "pipe" && tau < 2) return;
          const cand = { from: o.from, to: o.to, ratio: 1, src: o.src, delay: { shape, tau } };
          const terms = [o.from !== OUT ? "a" : "g"];
          drops.forEach((d) => consider([...chosen.filter((f) => !d.includes(f)), { cand, terms }], `added ${label(cand)}`));
        }));
      });
    }

    // ---- local search over structures ----
    // Moves each round: add a flow; add two flows that share a stock (a chain, such as an inflow
    // and an outflow of the same stock, which only pay off together); remove a flow; reroute a
    // flow's start or end. Every flow must run forwards. The best improving move is kept; the
    // search stops when no move improves the score.
    strict = true;
    const keyOf = (c) => `${c.from}>${c.to}${tag(c)}`;
    const fitTerms = (c) => {                                 // the simplest equation shapes worth trying for a new flow
      const opts2 = [["c"]];
      if (c.from !== OUT) opts2.push(["a"]);
      if (c.to !== OUT) opts2.push(["c", "b"]);
      return opts2;
    };
    function evaluate(set) {
      const r = fitOf(set);
      let off2 = 0;
      for (const f of set) {
        const n = columns(f.cand, f.terms).length;
        if (!plausible(f.cand, f.terms, r.theta.slice(off2, off2 + n))) return null;
        off2 += n;
      }
      return { set, score: total(set, r) };
    }
    const has = (set, c) => set.some((f) => keyOf(f.cand) === keyOf(c));
    // a score for ranking candidates, without the forwards-only check
    function evaluateLoose(set) { const r = fitOf(set); return { set, score: total(set, r) }; }
    let chosen = [], cur = evaluate([]);
    const rounds = [];
    const byNode = (node) => cands.filter((c) => c.from === node || c.to === node);
    for (let round = 0; round < 3 * maxFlows; round++) {
      let best = null, how = "";
      const consider = (set, label2) => { const e = evaluate(set); if (e && e.score < cur.score - 2 && (!best || e.score < best.score)) { best = e; how = label2; } };
      // add one
      if (chosen.length < maxFlows) cands.forEach((c) => { if (!has(chosen, c)) fitTerms(c).forEach((t) => consider([...chosen, { cand: c, terms: t }], `added ${label(c)}`)); });
      // add a chain of two through one stock (only the 6 most promising flows in and out of it)
      const prune = cands.length > 200;                     // small models try every chain
      const single = new Map();
      if (prune) cands.forEach((c) => { if (!has(chosen, c)) { const e = evaluateLoose([...chosen, { cand: c, terms: ["c"] }]); if (e) single.set(c, e.score); } });
      const topk = (list) => (prune ? list.filter((c) => single.has(c)).sort((a, b) => single.get(a) - single.get(b)).slice(0, 6) : list);
      if (chosen.length < maxFlows - 1) ids.forEach((node) => {
        const ins = topk(byNode(node).filter((c) => c.to === node && !has(chosen, c))), outs = topk(byNode(node).filter((c) => c.from === node && !has(chosen, c)));
        ins.forEach((i) => outs.forEach((o) => { if (i.from === null || i.from !== o.to) consider([...chosen, { cand: i, terms: ["c"] }, { cand: o, terms: ["c"] }], `added ${label(i)} and ${label(o)}`); }));
      });
      // remove one
      chosen.forEach((f, i) => consider(chosen.filter((_, j) => j !== i), `dropped ${label(f.cand)}`));
      // reroute one end
      chosen.forEach((f, i) => cands.forEach((c) => {
        if (has(chosen, c) || (c.from !== f.cand.from && c.to !== f.cand.to)) return;
        const terms = f.terms.filter((t) => termsFor(c).includes(t));
        consider(chosen.map((g, j) => (j === i ? { cand: c, terms: terms.length ? terms : ["c"] } : g)), `rerouted ${label(f.cand)} as ${label(c)}`);
      }));
      // pass a flow through a stock: a -> c becomes a -> b -> c (the stock in the middle can now fill and drain)
      chosen.forEach((f, i) => ids.forEach((mid) => {
        if (mid === f.cand.from || mid === f.cand.to) return;
        const first = cands.filter((c) => c.from === f.cand.from && c.to === mid), second = cands.filter((c) => c.from === mid && c.to === f.cand.to);
        first.forEach((x) => second.forEach((y) => {
          if (has(chosen, x) || has(chosen, y)) return;
          consider([...chosen.filter((_, j) => j !== i), { cand: x, terms: ["c"] }, { cand: y, terms: ["c"] }], `passed ${label(f.cand)} through ${mid}`);
        }));
      }));
      if (chosen.length < maxFlows) latentMoves(consider);
      if (!best) break;
      chosen = best.set; cur = best;
      rounds.push({ added: how, nearly: [] });
    }
    // simplify each flow's equation: drop terms that do not pay, try adding the level terms that do
    for (let i = 0; i < chosen.length; i++) {
      const f = chosen[i];
      if (f.cand.delay) continue;
      for (const terms of [...fitTerms(f.cand), ["c", "a"]].filter((t) => sensible(t) && t.every((x) => termsFor(f.cand).includes(x)))) {
        const e = evaluate(chosen.map((g, j) => (j === i ? { cand: g.cand, terms } : g)));
        if (e && e.score < cur.score - 2) { chosen = e.set; cur = e; }
      }
    }

    // How sure the delay is: the delays (of the same shape) that fit nearly as well as the one chosen.
    const delays = new Map();
    chosen.forEach((f, i) => {
      if (!f.cand.delay) return;
      const near = [];
      latentTaus.forEach((tau) => {
        if (f.cand.delay.shape === "pipe" && tau < 2) return;
        const cand = { ...f.cand, delay: { shape: f.cand.delay.shape, tau } };
        const e = tau === f.cand.delay.tau ? cur : evaluate(chosen.map((g, j) => (j === i ? { cand, terms: f.terms } : g)));
        if (e && e.score <= cur.score + 4) near.push(tau);
      });
      delays.set(keyOf(f.cand), { min: Math.min(...near), max: Math.max(...near) });
    });

    // Ambiguity: for each flow found, the alternatives (another ratio, another start or end) that
    // explain the data nearly as well. Many alternatives means the run cannot tell them apart.
    const alternatives = chosen.map((f, i) => {
      const alts = [];
      if (f.cand.delay) return [];
      cands.forEach((c) => {
        if (keyOf(c) === keyOf(f.cand) && c.ratio === f.cand.ratio) return;
        if (c.from !== f.cand.from && c.to !== f.cand.to) return;
        if (chosen.some((g, j) => j !== i && keyOf(g.cand) === keyOf(c))) return;
        const terms = f.terms.filter((t) => termsFor(c).includes(t));
        const e = evaluate(chosen.map((g, j) => (j === i ? { cand: c, terms: terms.length ? terms : ["c"] } : g)));
        if (e && e.score <= cur.score + 4) alts.push(label(c));
      });
      return alts;
    });

    // results: each flow's equation, how much it moves, and what is left unexplained per stock
    const fit = fitOf(chosen);
    let off = 0;
    const flows = chosen.map((f) => {
      const n = columns(f.cand, f.terms).length, theta = fit.theta.slice(off, off + n);
      off += n;
      const perEra = Array.from({ length: E }, () => ({}));
      let i = 0;
      f.terms.forEach((term) => { for (let e = 0; e < E; e++) if (columnUsed(f.cand, term, e)) perEra[e][term] = theta[i++]; });
      const q = amounts(f.cand, f.terms, theta);
      if (f.cand.delay) {
        // what waits in the hidden stock, and the rate in the model's own terms
        const k = theta[0] || 0, h0 = Math.max(0, theta[1] || 0), d = delayed(sourceSeries(f.cand), f.cand.delay.shape, f.cand.delay.tau);
        let tot = 0; for (let i = 0; i < T; i++) tot += k * d.held[i] + h0 * d.held0[i];
        const holds = tot / T, perStep = q.reduce((a, b) => a + b, 0) / (W * w);
        const rate = f.cand.from !== OUT ? toRate(f.cand, { a: k }) : { form: "constant", value: +perStep.toFixed(3) };
        const range = delays.get(keyOf(f.cand)) || { min: f.cand.delay.tau, max: f.cand.delay.tau };
        return { from: f.cand.from, to: f.cand.to, ratio: 1, perStep, bothWays: false, nearly: [], rates: [rate], rate,
                 via: { shape: f.cand.delay.shape, delay: f.cand.delay.tau, delayMin: range.min, delayMax: range.max, holds, atStart: h0, share: k, echo: f.cand.src || null } };
      }
      return { from: f.cand.from, to: f.cand.to, ratio: f.cand.ratio, perStep: q.reduce((a, b) => a + b, 0) / (W * w),
               bothWays: q.filter((v) => v < -0.5).length > 0.1 * W, nearly: alternatives[chosen.indexOf(f)] || [],
               rates: sharedFlow(f.cand) ? [toRate(f.cand, perEra[0])] : perEra.map((coef) => toRate(f.cand, coef)),
               rate: toRate(f.cand, perEra[sharedFlow(f.cand) ? 0 : winEra[W - 1]]) };
    });
    const pred = new Float64Array(N);
    const cols = chosen.flatMap((f) => columns(f.cand, f.terms));
    cols.forEach((col, i) => { for (let r = 0; r < N; r++) pred[r] += col[r] * fit.theta[i]; });
    for (let k = 0; k < W; k++) for (let j = 0; j < S; j++) { y[k * R + j] /= wt[j]; pred[k * R + j] /= wt[j]; }
    const unexplained = {};
    // drift: a steady change no flow explains (the sign of a missing flow or stock);
    // wobble: the step-to-step scatter that no simple equation should chase
    ids.forEach((id, j) => {
      let sum = 0, se = 0;
      for (let k = 0; k < W; k++) { const e = y[k * R + j] - pred[k * R + j]; sum += e; se += e * e; }
      const mean = sum / W, sd = Math.sqrt(Math.max(0, se / W - mean * mean));
      unexplained[id] = { drift: mean / w, wobble: sd / w, persistent: Math.abs(mean) > 2 * sd / Math.sqrt(W) && Math.abs(mean / w) > 0.02 };
    });
    // Hidden stocks: when one flow carries things out of the model and another brings things in,
    // and the two match in size (with the arrivals following the departures after some delay),
    // the things are probably waiting somewhere nobody measures: a stock between them, holding
    // about rate x delay (Little's law). Measure it, and it becomes part of the model.
    const series = chosen.map((f, i) => ({ f: flows[i], q: amounts(f.cand, f.terms, (() => { let o = 0; for (let j = 0; j < i; j++) o += columns(chosen[j].cand, chosen[j].terms).length; return fit.theta.slice(o, o + columns(f.cand, f.terms).length); })()) }));
    const outsOf = series.filter((x) => x.f.to === OUT && x.f.from !== OUT && !x.f.via), insOf = series.filter((x) => x.f.from === OUT && x.f.to !== OUT && !x.f.via);
    const hidden = [];
    outsOf.forEach((o) => insOf.forEach((i) => {
      const mo = o.q.reduce((a, b) => a + b, 0) / W, mi = i.q.reduce((a, b) => a + b, 0) / W;
      const outUnits = mo * o.f.ratio, inUnits = mi;                // things leaving vs things arriving, per window
      if (!(outUnits > 0 && inUnits > 0)) return;
      const balance = Math.min(outUnits, inUnits) / Math.max(outUnits, inUnits);
      if (balance < 0.5) return;
      // the delay comes from the data: what the first stock lost and the second gained beyond the
      // known flows, window by window (the fitted amounts can be constant and show no delay)
      const lost = dY.map((r) => -r[o.f.from]), gained = dY.map((r) => r[i.f.to]);
      let best = { lag: null, corr: 0 };
      const maxLag = Math.max(1, Math.floor(W / 3));
      for (let lag = 0; lag <= maxLag; lag++) {
        const a = lost.slice(0, W - lag), c = gained.slice(lag);
        const ma = a.reduce((x, y) => x + y, 0) / a.length, mc = c.reduce((x, y) => x + y, 0) / c.length;
        let sab = 0, saa = 0, scc = 0;
        a.forEach((v, k) => { sab += (v - ma) * (c[k] - mc); saa += (v - ma) ** 2; scc += (c[k] - mc) ** 2; });
        const corr = saa > 1e-9 && scc > 1e-9 ? sab / Math.sqrt(saa * scc) : 0;
        if (corr > best.corr) best = { lag, corr };
      }
      const rate = inUnits / w, delay = best.corr >= 0.3 ? best.lag * w : null;
      hidden.push({ from: o.f.from, to: i.f.to, rate, delay, holds: delay !== null ? rate * delay : null, balance, corr: best.corr });
    }));
    hidden.sort((a, b) => b.balance + b.corr - (a.balance + a.corr));

    // for tests: the score of given structures ([{from, to, terms, delay?}]) next to the one found
    const scored = (opts.score || []).map((set) => { const e = evaluateLoose(set.map((f) => ({ cand: { ratio: 1, ...f }, terms: f.terms }))); const r2 = fitOf(e.set); return { score: e.score, rss: r2.rss, theta: r2.theta }; });
    return { flows, unexplained, rounds, windows: W, window: w, hidden, score: cur.score, scored };
  }

  function label(c) {
    const via = c.delay ? ` via a hidden stock (${c.delay.shape}, ${c.delay.tau} steps${c.src ? `, after ${c.src} gains` : ""})` : "";
    return `${c.from || "outside"} → ${c.to || "outside"}${c.ratio !== 1 ? ` (×${+c.ratio.toFixed(2)})` : ""}${via}`;
  }
  const tag = (c) => (c.delay ? `~${c.delay.shape}${c.delay.tau}${c.src ? "<" + c.src : ""}` : "");
  function corrOf(a, b) {
    const n = a.length; let ma = 0, mb = 0;
    for (let k = 0; k < n; k++) { ma += a[k]; mb += b[k]; }
    ma /= n; mb /= n;
    let sab = 0, saa = 0, sbb = 0;
    for (let k = 0; k < n; k++) { sab += (a[k] - ma) * (b[k] - mb); saa += (a[k] - ma) ** 2; sbb += (b[k] - mb) ** 2; }
    return saa > 1e-12 && sbb > 1e-12 ? sab / Math.sqrt(saa * sbb) : 0;
  }

  // the model's own equation forms, where a discovered equation is one of them; otherwise "linear"
  function toRate(c, coef) {
    const r = (v) => +(+v).toFixed(Math.abs(v) >= 10 ? 1 : Math.abs(v) >= 1 ? 2 : 3);
    const keys = Object.keys(coef);
    if (keys.length === 1 && keys[0] === "c") return { form: "constant", value: r(coef.c) };
    if (keys.length === 1 && keys[0] === "a") return { form: "proportional", stock: c.from, k: r(coef.a) };
    if (keys.length === 2 && "c" in coef && coef.c > 0) {
      const other = keys.find((k) => k !== "c"), m = coef[other], stock = other === "a" ? c.from : c.to;
      if (m < 0) return { form: "gap", stock, goal: r(-coef.c / m), time: r(-1 / m) };
    }
    const terms = keys.filter((k) => k !== "c").map((k) => ({ stock: k === "a" ? c.from : c.to, k: r(coef[k]) }));
    return { form: "linear", c: r(coef.c || 0), terms };
  }

  // The measured change of every stock at every step, added up once (moved: [{flow: {took, made}}]).
  function knownChanges(moved, n) {
    if (!moved) return null;
    const out = new Array(n);
    for (let i = 0; i < n; i++) {
      const d = {};
      Object.values(moved[i] || {}).forEach((a) => {
        Object.entries(a.made || {}).forEach(([id, v]) => { d[id] = (d[id] || 0) + v; });
        Object.entries(a.took || {}).forEach(([id, v]) => { d[id] = (d[id] || 0) - v; });
      });
      out[i] = d;
    }
    return out;
  }

  // ---------- discovering across a whole model ----------
  // Searching every stock at once is too slow for hundreds of stocks, and searching a hand-picked
  // handful gives poor answers. So: (1) subtract the measured flows from every stock's change and
  // set aside stocks with nothing left to explain; (2) split what remains into small independent
  // groups: stocks that may not exchange (different groups) are searched separately, and among the
  // rest, stocks whose unexplained changes mirror each other (one loses about what another gains,
  // at the same time) are kept together, since only they could be joined by a flow; (3) search
  // each group and combine the answers.
  function discoverAll(stocks, run, opts) {
    opts = opts || {};
    const maxGroup = opts.maxGroup || 40;
    const T = run.t.length;
    const w = Math.max(1, opts.window || 5, Math.ceil(T / (opts.maxWindows || 400))), W = Math.floor(T / w);
    const knownDelta = knownChanges(opts.moved, T);
    const known = (i, id) => (knownDelta && knownDelta[i] && (i > 0 || id in (opts.start || {})) ? knownDelta[i][id] || 0 : 0);
    const prevLevel = (id, i) => (i === 0 ? +(id in (opts.start || {}) ? opts.start[id] : (run.levels[id] || [])[0]) || 0 : +((run.levels[id] || [])[i - 1] || 0));
    // each stock's unexplained change per window, and how much it moves at all
    const resid = {}, size = {}, measured = {};
    stocks.forEach((s) => {
      const r = new Float64Array(W); let moved = 0, kn = 0;
      for (let k = 0; k < W; k++) for (let i = k * w; i < (k + 1) * w; i++) {
        const d = ((run.levels[s.id] || [])[i] || 0) - prevLevel(s.id, i);
        r[k] += d - known(i, s.id);
        moved += Math.abs(known(i, s.id)) + Math.abs(d);
        kn += Math.abs(known(i, s.id));
      }
      resid[s.id] = r; size[s.id] = moved / Math.max(1, W); measured[s.id] = kn > 0;
    });
    // stocks with something left to explain: a stock no measured flow touches, whenever it moves;
    // otherwise a steady drift, or swings well beyond its noise
    const active = stocks.filter((s) => {
      const r = resid[s.id], m = r.reduce((a, b) => a + b, 0) / W;
      if (!measured[s.id]) return r.some((v) => Math.abs(v) > 1e-9);
      let jit = 0; for (let k = 1; k < W; k++) jit += (r[k] - r[k - 1]) ** 2;
      jit = Math.sqrt(jit / Math.max(1, W - 1) / 2);
      const sd = Math.sqrt(r.reduce((a, b) => a + (b - m) ** 2, 0) / W);
      return Math.abs(m) > Math.max(0.5 * jit / Math.sqrt(W), 0.002 * size[s.id], 1e-9) || sd > Math.max(2 * jit, 0.02 * size[s.id], 1e-9);
    });
    const explained = stocks.length - active.length;
    // link stocks that may exchange and whose unexplained changes mirror each other
    const canExchange = (a, b) => !a.group || !b.group || a.group === b.group;
    const parent = new Map(active.map((s) => [s.id, s.id]));
    const find = (x) => { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; };
    const corr = corrOf;
    const links = [];
    // ...at the same time, or one some windows after the other (things that waited in a stock nobody measures)
    const maxLag = active.length <= 300 ? Math.min(12, Math.floor(W / 4)) : 0;
    const lagged = (a, b, lag) => corr(a.slice(0, W - lag), b.slice(lag));
    for (let i = 0; i < active.length; i++) for (let j = i + 1; j < active.length; j++) {
      if (!canExchange(active[i], active[j])) continue;
      const a = resid[active[i].id], b = resid[active[j].id];
      let c = corr(a, b);
      for (let lag = 1; lag <= maxLag; lag++) c = Math.min(c, lagged(a, b, lag), lagged(b, a, lag));
      if (c < -(opts.linkCorrelation || 0.3)) links.push([c, active[i].id, active[j].id]);
    }
    links.sort((a, b) => a[0] - b[0]);                       // strongest mirroring first
    const count = new Map(active.map((s) => [s.id, 1]));
    links.forEach(([, a, b]) => {
      const ra = find(a), rb = find(b);
      if (ra === rb || count.get(ra) + count.get(rb) > maxGroup) return;
      parent.set(rb, ra); count.set(ra, count.get(ra) + count.get(rb));
    });
    const groups = new Map();
    active.forEach((s) => { const r = find(s.id); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(s); });
    // search each group; small singletons are batched together when they cannot exchange anyway
    const flows = [], unexplained = {}, hidden = [], rounds = [];
    const batches = [], singles = [];
    groups.forEach((g) => (g.length === 1 ? singles.push(g[0]) : batches.push(g)));
    // a stock with no partner can only gain flows to or from outside: a tiny search of its own
    singles.forEach((s) => batches.push([s]));
    batches.forEach((g) => {
      const r = discover(g, run, { ...opts, knownDelta, window: w, sources: stocks, maxFlows: Math.max(opts.maxFlows || 12, 2 * g.length + 2) });
      flows.push(...r.flows); hidden.push(...(r.hidden || [])); rounds.push(...r.rounds);
      Object.assign(unexplained, r.unexplained);
    });
    return { flows, unexplained, hidden, rounds, windows: W, window: w, searched: active.length, explained, groups: batches.length,
             together: batches.filter((g) => g.length > 1).length };
  }

  const api = { discover, discoverAll };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SDDiscover = api;
})(typeof window !== "undefined" ? window : globalThis);
