// Whether a flow moves as its fitted equation says, judged like for like: the observed rate is a
// count over a bucket (the history's flow step), so the equation is the mean of what it says at
// each level sample inside the same bucket, never its value at one instant (a proportional outflow
// from a stock that is usually empty reads 0 at most instants and 30/min at the rest). Pure
// functions of the flow, its points and a level reader, used by the Dynamics page (dynamics-live.js)
// and its tests (tests/evidence).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.FlowCheck = factory();
})(typeof self !== "undefined" ? self : this, function () {
  // what the flow's fitted equation says its rate is, given the levels at time t (``levelAt(id, t)``)
  function predicted(f, t, levelAt) {
    const e = f && f.current; if (!e) return null;
    const sp = e.spec && e.spec.form ? e.spec : null;
    if (sp) {                                  // SD Lab's rate (effects left out: their curves are not shown here)
      const L = (x) => levelAt(x, t);
      if (sp.form === "constant") return sp.value;
      if (sp.form === "proportional") { const x = L(sp.stock); return x == null ? null : sp.k * x; }
      if (sp.form === "linear") { let r = sp.c || 0; for (const tm of sp.terms || []) { const x = L(tm.stock); if (x == null) return null; r += tm.k * x; } return Math.max(0, r); }
      if (sp.form === "gap") { const x = L(sp.stock); return x == null ? null : Math.max(0, (sp.goal - x) / sp.time); }
      return null;
    }
    const p = e.params || {}, x = e.inputs && e.inputs[0] ? levelAt(e.inputs[0], t) : null;
    if (e.form === "constant") return p.c;
    if (x == null) return null;
    return e.form === "proportional" ? p.k * x : Math.max(0, p.c + p.k * x);
  }
  // what an equation reads: the stocks and measured inputs whose levels it needs
  function reads(f) {
    const e = (f && f.current) || {}, sp = e.spec && e.spec.form ? e.spec : null;
    if (sp) return [...new Set([sp.stock, ...(sp.terms || []).map((t) => t.stock), ...(sp.effects || []).map((x) => x.stock)].filter(Boolean))];
    return (e.inputs || []).slice(0, 1);
  }
  const mean = (xs) => (xs.length ? xs.reduce((a, x) => a + x, 0) / xs.length : null);
  // the equation over the bucket (t − step, t]: the mean of what it says at each level sample in it
  // (``samplesIn(a, b)``: the times the levels it reads were sampled, a < time ≤ b), at t when none was
  function bucketMean(f, t, step, levelAt, samplesIn) {
    const ts = samplesIn ? samplesIn(t - step, t) : [];
    return mean((ts.length ? ts : [t]).map((x) => predicted(f, x, levelAt)).filter((v) => v != null));
  }
  // the equation beside each observed point, over that point's bucket: the line a chart draws
  function line(f, pts, step, levelAt, samplesIn) {
    return (pts || []).map(([t]) => [t, bucketMean(f, t, step, levelAt, samplesIn)]).filter((p) => p[1] != null);
  }
  // observed against the equation over the last ``n`` points: {obs, eq, differs, quiet, window}.
  // They differ when nothing moved and the equation says something should, or by more than chance
  // would explain (the equation's count over the window, spread by its fitted dispersion, at two
  // standard deviations). ``minutes``: how long the points span
  function against(f, pts, { step = 30, levelAt, samplesIn, minutes = 2, n = 4 } = {}) {
    const h = (pts || []).slice(-n), obs = h.length ? mean(h.map((p) => p[1])) : null;
    const eqs = line(f, h, step, levelAt, samplesIn), eq = eqs.length ? mean(eqs.map((p) => p[1])) : null;
    if (obs == null || eq == null) return { obs, eq, differs: false, quiet: obs === 0 };
    const q = (f.current && f.current.quality) || {}, disp = Math.max(1, q.dispersion || 1);
    const tol = Math.max(0.25 * eq, 2 * Math.sqrt(Math.max(eq, 0.05) * disp / minutes));
    return { obs, eq, differs: (obs === 0 && eq > 0.01) || Math.abs(obs - eq) > tol, quiet: obs === 0, window: minutes };
  }
  return { predicted, reads, bucketMean, line, against };
});
