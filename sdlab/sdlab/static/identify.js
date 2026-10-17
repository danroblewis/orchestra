// Identifying a system dynamics model from its stocks' levels.
//
// In a model whose flows are linear in the levels (constant, proportional, gap and linear forms),
// every stock's change in a step is a linear function of the levels at the start of the step, plus
// what arrives from outside:
//
//     change of s at t  =  u_s(t)  +  Σ_j  B[s][j] × level of j at t-1   (+ noise)
//
// So the whole system is the matrix B and the outside inflows u. This module estimates them, one
// stock at a time, by least squares on single steps (summing steps into windows biases the
// estimates when stocks turn over within a few steps), then reads stock-and-flow structure off B:
//
//   - a move A -> B at rate k is -k in A's own column entry and +k in B's entry for A;
//   - a link (B's arrivals follow A's level, nothing leaves A) is +k for B with no matching -k;
//   - what A loses beyond what other stocks are seen to receive goes to outside;
//   - a gain in a stock of another unit is a link (things become other things only with a ratio).
//
// Each stock's outside inflow may change over time (demand rises, a budget is set, night falls): it
// is a series of pieces whose changes are found in the data (optimal partitioning). A stock gets a
// changing inflow only if it has an inflow at all, so that the chance "changes" a scan over thousands
// of places finds do not turn into flows.
//
// The result has the same shape as discover.js's, so the page and the bench can use either.
(function (root) {
  "use strict";

  // ---- the outside inflow's changes: optimal partitioning with pruning (PELT) ----
  function pelt(r, minLen, mult) {
    const n = r.length, pre = new Float64Array(n + 1), pre2 = new Float64Array(n + 1);
    for (let i = 0; i < n; i++) { const v = Number.isFinite(r[i]) ? r[i] : 0; pre[i + 1] = pre[i] + v; pre2[i + 1] = pre2[i] + v * v; }
    const sse = (a, b) => { const s = pre[b] - pre[a]; return pre2[b] - pre2[a] - s * s / (b - a); };
    let dv = 0; for (let i = 1; i < n; i++) dv += (r[i] - r[i - 1]) ** 2;
    const pen = mult * Math.log(n) * (dv / (2 * Math.max(1, n - 1)) || 1);
    const F = new Float64Array(n + 1), last = new Int32Array(n + 1);
    F[0] = -pen; let cand = [0];
    for (let t = 1; t <= n; t++) {
      let best = Infinity, arg = 0;
      for (const s0 of cand) { if (t - s0 < minLen && t !== n) continue; const v = F[s0] + sse(s0, t) + pen; if (v < best) { best = v; arg = s0; } }
      if (best === Infinity) { best = F[0] + sse(0, t) + pen; arg = 0; }
      F[t] = best; last[t] = arg;
      cand = cand.filter((s0) => F[s0] + sse(s0, t) <= F[t] + pen); cand.push(t);
    }
    const cuts = []; for (let t = n; t > 0; t = last[t]) cuts.push(t); cuts.push(0);
    return cuts.reverse();                                    // 0 = c0 < c1 < ... < ck = n
  }

  // ---- small dense algebra ----
  function solveWithInverse(G, b) {                           // returns { x, inv }
    const p = b.length, W = 2 * p + 1, A = Array.from({ length: p }, (_, i) => { const r = new Float64Array(W); for (let j = 0; j < p; j++) r[j] = G[i][j]; r[p] = b[i]; r[p + 1 + i] = 1; r[i] += 1e-9 * (Math.abs(G[i][i]) + 1); return r; });
    for (let i = 0; i < p; i++) {
      let m = i; for (let r = i + 1; r < p; r++) if (Math.abs(A[r][i]) > Math.abs(A[m][i])) m = r;
      [A[i], A[m]] = [A[m], A[i]];
      const piv = A[i][i] || 1e-12;
      for (let c = 0; c < W; c++) A[i][c] /= piv;
      for (let r = 0; r < p; r++) if (r !== i) { const f = A[r][i]; if (f) for (let c = 0; c < W; c++) A[r][c] -= f * A[i][c]; }
    }
    return { x: A.map((r) => r[p]), inv: A.map((r) => Array.from(r.slice(p + 1))) };
  }

  // One stock's regression with its outside inflow in pieces (cuts) or none (cuts null): the pieces are
  // removed by taking out each piece's mean (so only the levels' columns remain), and every candidate
  // set of levels is then fitted from precomputed sums.
  function rowSums(y, X, cuts) {
    const T = y.length, S = X.length;
    let yc = y, Xc = X;
    if (cuts) {
      yc = new Float64Array(T); Xc = X.map(() => new Float64Array(T));
      for (let k = 0; k + 1 < cuts.length; k++) {
        const a = cuts[k], b = cuts[k + 1], n = b - a;
        let my = 0; for (let t = a; t < b; t++) my += y[t]; my /= n;
        for (let t = a; t < b; t++) yc[t] = y[t] - my;
        for (let j = 0; j < S; j++) { let m = 0; const x = X[j]; for (let t = a; t < b; t++) m += x[t]; m /= n; const o = Xc[j]; for (let t = a; t < b; t++) o[t] = x[t] - m; }
      }
    }
    const G = Array.from({ length: S }, () => new Float64Array(S)), b = new Float64Array(S);
    let yy = 0; for (let t = 0; t < T; t++) yy += yc[t] * yc[t];
    for (let i = 0; i < S; i++) {
      const xi = Xc[i]; let sb = 0; for (let t = 0; t < T; t++) sb += xi[t] * yc[t]; b[i] = sb;
      for (let j = i; j < S; j++) { const xj = Xc[j]; let s = 0; for (let t = 0; t < T; t++) s += xi[t] * xj[t]; G[i][j] = s; G[j][i] = s; }
    }
    return { G, b, yy, T, pieces: cuts ? cuts.length - 1 : 0 };
  }
  function fitSubset(sums, set) {
    if (!set.length) return { beta: [], rss: sums.yy, se: [] };
    const G = set.map((i) => set.map((j) => sums.G[i][j])), b = set.map((i) => sums.b[i]);
    const { x, inv } = solveWithInverse(G, b);
    let rss = sums.yy; for (let i = 0; i < set.length; i++) rss -= x[i] * b[i];
    rss = Math.max(rss, 1e-12);
    const s2 = rss / Math.max(1, sums.T - set.length - sums.pieces);
    return { beta: x, rss, se: inv.map((r, i) => Math.sqrt(Math.max(0, r[i] * s2))) };
  }

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

  // ---- choosing among candidate models by how they behave ----
  // A model is judged as the goal judges it: run it forward from many moments in the measured data
  // and compare with what was measured (its own estimated outside inflows feed it). Only the data is
  // used. A model whose loop runs away loses on its own.
  function simulate(flows, level, t) {
    const rate = (r, lv) => {
      if (!r) return 0;
      const v = (x) => lv[x] || 0;
      if (r.form === "constant") return Math.max(0, +r.value || 0);
      if (r.form === "proportional") return Math.max(0, (+r.k || 0) * v(r.stock));
      if (r.form === "gap") return Math.max(0, ((+r.goal || 0) - v(r.stock)) / Math.max(1e-9, +r.time || 1));
      if (r.form === "linear") return Math.max(0, (+r.c || 0) + (r.terms || []).reduce((a, x) => a + (+x.k || 0) * v(x.stock), 0));
      return 0;
    };
    const amounts = flows.map((f) => {
      if (f.inflow && f.inflow.length) { const p = f.inflow.find((g) => t >= g.from && t <= g.to) || f.inflow[f.inflow.length - 1]; return Math.max(0, p.value); }
      return rate(f.rate, level);
    });
    const next = { ...level };
    flows.forEach((f, i) => { if (f.from) next[f.from] -= amounts[i] * (f.ratio || 1); if (f.to) next[f.to] += amounts[i]; });
    for (const k in next) if (!(next[k] >= 0)) next[k] = 0;
    return next;
  }
  function behaviourError(flows, stocks, run, opts) {
    const ids = stocks.map((s) => s.id), n = run.t.length, H = opts.horizon || 20;
    const sd = Object.fromEntries(ids.map((id) => { const a = run.levels[id] || []; let m = 0; a.forEach((v) => { m += v; }); m /= Math.max(1, a.length); let s2 = 0; a.forEach((v) => { s2 += (v - m) ** 2; }); return [id, Math.sqrt(s2 / Math.max(1, a.length)) || 1]; }));
    const every = Math.max(1, Math.floor((n - H - 1) / (opts.starts || 80)));
    let err = 0, moved = 0;
    for (let s0 = 1; s0 + H < n; s0 += every) {
      let lv = Object.fromEntries(ids.map((id) => [id, +run.levels[id][s0 - 1] || 0]));
      for (let h = 0; h < H; h++) lv = simulate(flows, lv, run.t[s0 + h]);
      ids.forEach((id) => {
        const obs = +run.levels[id][s0 + H - 1] || 0, z = sd[id];
        const e = (lv[id] - obs) / z; err += Number.isFinite(e) ? e * e : 1e6;
        moved += ((obs - (+run.levels[id][s0 - 1] || 0)) / z) ** 2;
      });
    }
    return err / Math.max(1e-9, moved);
  }

  // ---- the matrix, one stock at a time ----
  // identify() tries several ways of estimating the matrix and keeps the model that behaves best.
  const VARIANTS = [
    { name: "forward" }, { name: "backward", backwardMax: 20 },
    { name: "forward, constant inflows", changes: false }, { name: "backward, constant inflows", backwardMax: 20, changes: false },
  ];
  function identify(stocks, run, opts) {
    opts = opts || {};
    if (opts.variant) return identifyOne(stocks, run, opts);
    let best = null;
    const tried = [];
    for (const v of opts.variants || VARIANTS) {
      const r = identifyOne(stocks, run, { ...opts, ...v, variant: true });
      if (!r.flows) continue;
      const e = r.flows.length ? behaviourError(r.flows, stocks, run, opts) : Infinity;
      tried.push({ name: v.name, error: e });
      if (!best || e < best.error) best = { r, error: e, name: v.name };
    }
    best.r.chosen = best.name; best.r.tried = tried;
    return best.r;
  }
  function identifyOne(stocks, run, opts) {
    opts = opts || {};
    const ids = stocks.map((s) => s.id), S = ids.length, T = run.t.length - 1;
    if (T < 20) return { flows: [], unexplained: {}, hidden: [], rounds: [], windows: Math.max(0, T), window: 1, note: "Too few steps." };
    const known = opts.knownDelta || knownChanges(opts.moved, run.t.length);
    const lv = ids.map((id) => run.levels[id] || []);
    const prev = lv.map((a) => Float64Array.from({ length: T }, (_, t) => +a[t] || 0));
    const dy = lv.map((a, s) => Float64Array.from({ length: T }, (_, t) => (+a[t + 1] || 0) - (+a[t] || 0) - (known && known[t + 1] ? known[t + 1][ids[s]] || 0 : 0)));
    const final = new Set(stocks.filter((s) => s.final).map((s) => s.id));
    const unit = Object.fromEntries(stocks.map((s) => [s.id, s.unit || ""]));
    const group = Object.fromEntries(stocks.map((s) => [s.id, s.group]));
    const mayAffect = (j, s) => j === s || !group[ids[j]] || !group[ids[s]] || group[ids[j]] === group[ids[s]];
    const logT = Math.log(T);
    const bic = (rss, p) => T * Math.log(Math.max(rss, 1e-12) / T) + p * logT;
    const addGain = opts.addGain ?? logT;                      // a level joins a row only if clearly nonzero

    const rows = ids.map((id, s) => {
      const y = dy[s], allowed = ids.map((_, j) => j).filter((j) => mayAffect(j, s) && !(final.has(id) && j === s));
      const stepwise = (sums, start) => {
        let set = start.slice(), cur = fitSubset(sums, set), score = bic(cur.rss, set.length + sums.pieces);
        for (let guard = 0; guard < 4 * S; guard++) {
          let best = null;
          for (const j of allowed) if (!set.includes(j)) {
            const f = fitSubset(sums, [...set, j]), sc = bic(f.rss, set.length + 1 + sums.pieces);
            if (sc < score - addGain && (!best || sc < best.sc)) best = { set: [...set, j], sc };
          }
          for (const j of set) {
            const ns = set.filter((x) => x !== j), f = fitSubset(sums, ns), sc = bic(f.rss, ns.length + sums.pieces);
            if (sc < score - 2 && (!best || sc < best.sc)) best = { set: ns, sc };
          }
          if (!best) break;
          set = best.set; score = best.sc;
        }
        return set;
      };
      // fine pieces first (so the levels' numbers are not biased by unexplained changes), then the
      // usual price; the pieces are found in what the levels leave unexplained
      // start from every level when there are few (backward elimination: pairs of levels that only
      // explain a row together - a link and a drain on stocks that rise together - are kept), from
      // none when there are many
      let cuts = [0, T], set = allowed.length <= (opts.backwardMax ?? 0) ? allowed.slice() : [];
      for (let pass = 0; pass < 5; pass++) {
        const sums = rowSums(y, prev, cuts);
        set = stepwise(sums, set);
        const f = fitSubset(sums, set);
        const res = Float64Array.from(y, (v, t) => v - set.reduce((a, j, i) => a + f.beta[i] * prev[j][t], 0));
        const next = opts.changes === false ? [0, T] : pelt(res, opts.minPiece || 5, pass === 0 ? 0.5 : 1);
        if (opts.trace === id) console.log(`  ${id} pass ${pass}: ${cuts.length - 1} pieces;`, set.map((j, i) => `${ids[j]} ${f.beta[i].toFixed(4)}`).join(", "), `-> ${next.length - 1}`);
        if (next.join() === cuts.join() && pass >= 2) break;
        cuts = next;
      }
      // the outside inflow: none, constant, or changing (only a stock with an inflow on average
      // clearly one way may have it change)
      // (the levels chosen alongside the pieces stay: only the inflow's form is being decided)
      const tryForm = (c, extra) => { const sums = rowSums(y, prev, c), f = fitSubset(sums, set); return { cuts: c, set, f, sums, sc: bic(f.rss, set.length + extra) }; };
      const rawSums = (() => { const s0 = rowSums(y, prev, null); s0.pieces = 0; return s0; })();
      const none = (() => { const f = fitSubset(rawSums, set); return { cuts: null, set, f, sums: rawSums, sc: bic(f.rss, set.length) }; })();
      const constant = tryForm([0, T], 1);
      let pick = none.sc <= constant.sc ? none : constant;
      if (cuts.length > 2) {
        const pieces = tryForm(cuts, cuts.length - 1);
        const vals = pieceValues(y, prev, pieces.set, pieces.f.beta, cuts);
        const W = vals.reduce((x, p) => x + p.w, 0), mean = vals.reduce((x, p) => x + p.v * p.w, 0) / W;
        const sd = Math.sqrt(vals.reduce((x, p) => x + p.w * (p.v - mean) ** 2, 0) / W);
        if ((pick === constant || Math.abs(mean) > 0.5 * sd) && pieces.sc < pick.sc) pick = pieces;
      }
      const coef = {}, se = {};
      pick.set.forEach((j, i) => { coef[ids[j]] = pick.f.beta[i]; se[ids[j]] = pick.f.se[i]; });
      const inflow = pick.cuts ? pieceValues(y, prev, pick.set, pick.f.beta, pick.cuts).map((p) => ({ from: run.t[p.a + 1], to: run.t[p.b], value: p.v })) : [];
      return { id, coef, se, inflow, cuts: pick.cuts, rss: pick.f.rss, p: pick.set.length + (pick.cuts ? pick.cuts.length - 1 : 0) };
    });

    // Conservation unless the data clearly says otherwise: a stock's drain is what same-unit stocks
    // are seen to receive from it (measured, often more precisely, in their rows). A stock fed by a
    // changing outside inflow cannot separate its own drain from those changes (a misplaced change
    // looks like a slightly faster drain), so there the moves are trusted unless the drain is clearly
    // more than they take, or less than they take.
    rows.forEach((row, s) => {
      const a = row.id, drain = -(row.coef[a] || 0);
      const moves = rows.filter((r) => r.id !== a && (r.coef[a] || 0) > 0 && unit[r.id] === unit[a]).reduce((x, r) => x + r.coef[a], 0);
      if (moves <= 0 || final.has(a)) return;
      const changing = row.cuts && row.cuts.length > 2;
      if (changing && moves > drain) { row.coef[a] = -moves; row.conserved = true; return; }
      if (!(drain > moves)) return;
      const y2 = Float64Array.from(dy[s], (v, t) => v + moves * prev[s][t]);
      const others = Object.keys(row.coef).filter((j) => j !== a).map((j) => ids.indexOf(j));
      const cuts2 = row.cuts && row.cuts.length > 2 ? pelt(Float64Array.from(y2, (v, t) => v - others.reduce((x, j) => x + row.coef[ids[j]] * prev[j][t], 0)), opts.minPiece || 5, 1) : row.cuts;
      const sums = cuts2 ? rowSums(y2, prev, cuts2) : (() => { const s0 = rowSums(y2, prev, null); s0.pieces = 0; return s0; })();
      const fixed = fitSubset(sums, others).rss, p2 = others.length + (cuts2 ? cuts2.length - 1 : 0);
      if (bic(fixed, p2) <= bic(row.rss, row.p) + logT || (changing && (drain - moves) / drain < (opts.slack || 0.3))) { row.coef[a] = -moves; row.conserved = true; }
    });

    const flows = readFlows(stocks, rows, run, prev, opts);
    return { flows, unexplained: {}, hidden: [], rounds: [], windows: T, window: 1, matrix: rows, method: "identify" };
  }

  // each piece's level of the outside inflow, with the levels' part taken out
  function pieceValues(y, prev, set, beta, cuts) {
    const out = [];
    for (let k = 0; k + 1 < cuts.length; k++) {
      const a = cuts[k], b = cuts[k + 1];
      let m = 0; for (let t = a; t < b; t++) { let pr = 0; set.forEach((j, i) => { pr += beta[i] * prev[j][t]; }); m += y[t] - pr; }
      out.push({ a, b, w: b - a, v: m / (b - a) });
    }
    return out;
  }

  // ---- reading stock-and-flow structure off the matrix ----
  function readFlows(stocks, rows, run, prev, opts) {
    const ids = stocks.map((s) => s.id), B = Object.fromEntries(rows.map((r) => [r.id, r.coef]));
    const unit = Object.fromEntries(stocks.map((x) => [x.id, x.unit || ""]));
    const final = new Set(stocks.filter((s) => s.final).map((s) => s.id));
    const tol = opts.tol || 0.003, flows = [];
    const mean = (j) => { const a = prev[ids.indexOf(j)]; let s = 0; for (let t = 0; t < a.length; t++) s += a[t]; return s / Math.max(1, a.length); };
    const r4 = (v) => +(+v).toFixed(Math.abs(v) >= 10 ? 1 : Math.abs(v) >= 1 ? 3 : 4);
    const flow = (from, to, rate, extra) => {
      const k = rate.form === "proportional" ? rate.k : rate.form === "linear" ? rate.terms[0].k : 0;
      const src = rate.form === "proportional" ? rate.stock : rate.form === "linear" ? rate.terms[0].stock : null;
      const perStep = rate.form === "constant" ? rate.value : k * mean(src);
      flows.push({ from, to, ratio: 1, rate, rates: [rate], perStep, nearly: [], bothWays: false, ...extra });
    };
    ids.forEach((a) => {
      if (final.has(a) && !(B[a][a] > tol)) { /* nothing leaves a final stock */ }
      const drain = final.has(a) ? 0 : -(B[a][a] || 0);
      const gains = ids.filter((s) => s !== a && (B[s][a] || 0) > tol).map((s) => ({ s, k: B[s][a] })).sort((x, y) => y.k - x.k);
      let left = Math.max(0, drain);
      gains.forEach(({ s, k }) => {
        const move = unit[s] === unit[a] ? Math.max(0, Math.min(k, left)) : 0;
        if (move > tol) { flow(a, s, { form: "proportional", stock: a, k: r4(move) }); left -= move; }
        if (k - move > tol) flow(null, s, { form: "linear", c: 0, terms: [{ stock: a, k: r4(k - move) }] }, { driver: a });
      });
      if (left > tol) flow(a, null, { form: "proportional", stock: a, k: r4(left) });
      if ((B[a][a] || 0) > tol) flow(null, a, { form: "linear", c: 0, terms: [{ stock: a, k: r4(B[a][a]) }] }, { driver: a, note: "grows with itself" });
      ids.filter((s) => s !== a && (B[s][a] || 0) < -tol).forEach((s) => flow(s, null, { form: "linear", c: 0, terms: [{ stock: a, k: r4(-B[s][a]) }] }, { driver: a, note: `${s} drains faster when ${a} is high` }));
    });
    rows.forEach((r) => {
      if (!r.inflow.length) return;
      const W = r.inflow.reduce((x, g) => x + (g.to - g.from + 1), 0), m = r.inflow.reduce((x, g) => x + g.value * (g.to - g.from + 1), 0) / Math.max(1, W);
      if (Math.abs(m) <= tol) return;
      const rate = { form: "constant", value: r4(Math.abs(m)) }, changes = r.inflow.length - 1;
      if (m > 0) flow(null, r.id, rate, { inflow: r.inflow, changes });
      else flow(r.id, null, rate, { inflow: r.inflow.map((g) => ({ ...g, value: -g.value })), changes });
    });
    return flows;
  }

  const api = { identify, pelt, behaviourError, simulate };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SDIdentify = api;
})(typeof window !== "undefined" ? window : globalThis);
