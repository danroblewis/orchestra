// What a discovery left out, counted honestly (the Dynamics page's "How it was found"): of the
// series it looked at, those the model uses (a stock's series, a flow's counter, a balance's term)
// and those it considered and kept were not left out; the rest were, named in its record by why
// or not named (left out at once, or folded into a sum over instances). The buckets add up.
const LeftOut = (() => {
  // a series as the record names it: name{labels}, sorted, without the project label
  const keyOf = (ref) => ref.name + (Object.keys(ref.labels || {}).filter((k) => k !== "project").length
    ? "{" + Object.entries(ref.labels).filter(([k]) => k !== "project").sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => `${k}="${v}"`).join(",") + "}" : "");
  // the series the model is drawn from
  function used(m) {
    const keys = new Set();
    for (const s of (m && m.stocks) || []) {
      if (s.series) keys.add(keyOf(s.series));
      for (const b of ((s.evidence || {}).balance) || []) if (b.series) keys.add(b.series);
    }
    for (const f of (m && m.flows) || []) if (f.counter) keys.add(keyOf(f.counter));
    return keys;
  }
  // {n, used, kept, named, left, unnamed, all}: left = n − used − kept; unnamed = left − named
  function counts(d, lo, m) {
    const n = d.looked_at ?? d.series, names = Object.keys(lo || {});
    const u = [...used(m)].filter((k) => !(lo || {})[k]).length, kept = (d.kept || []).length;
    if (n == null) return { n: null, used: u, kept, named: names.length, left: names.length, unnamed: 0, all: false };
    const left = Math.max(names.length, n - u - kept);
    return { n, used: u, kept, named: names.length, left, unnamed: left - names.length, all: left === n };
  }
  return { keyOf, used, counts };
})();
if (typeof module !== "undefined") module.exports = LeftOut;
