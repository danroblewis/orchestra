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
  // the reasons a series is left out before it is considered (web/dynamics.py EARLY), as said in a count
  const EARLY = [["Orchestra's own", "Orchestra's own"], ["named orchestra_", "named orchestra_*"], ["no longer written", "no longer written"],
    ["not written", "not written in the window"], ["too new", "too new to measure"]];
  // the ``n`` series left out at once, by the reasons the record gives (``lo``), most first: "16 too
  // new to measure, 1 Orchestra's own"; those it does not name are counted as such, never guessed
  function early(lo, n) {
    const by = new Map();
    for (const why of Object.values(lo || {})) { const e = EARLY.find(([p]) => String(why).startsWith(p)); if (e) by.set(e[1], (by.get(e[1]) || 0) + 1); }
    const parts = [...by.entries()].sort((a, b) => b[1] - a[1]).map(([label, k]) => `${k} ${label}`);
    const named = [...by.values()].reduce((a, b) => a + b, 0);
    if (n > named) parts.push(`${n - named} without a reason in the record`);
    return parts.join(", ");
  }
  // what would help, for a group of left-out reasons a person can act on ("" for the rest), in the
  // words of sd/no_model.py's paragraph; ``d`` the discovery's record, for its window
  const SPAN = /^written for only (\d+) min of the (\d+) min/;
  function help(whys, d) {
    const first = String((whys || [])[0] || ""), win = d && d.end != null && d.start != null ? Math.max(1, Math.round((d.end - d.start) / 60)) : null;
    if (first.startsWith("written for only")) {
      const spans = whys.map((w) => SPAN.exec(String(w))).filter(Boolean).map((m) => [+m[1], +m[2]]);
      if (!spans.length) return "What would help: wait, or widen the match to series with history.";
      const lo = Math.min(...spans.map((x) => x[0])), hi = Math.max(...spans.map((x) => x[0])), held = Math.max(...spans.map((x) => x[1]));
      return `What would help: wait, or widen the match to series with history (the window holds ${held} min of data; `
        + `${spans.length === 1 ? "it was" : "they were"} written for ${lo === hi ? lo : `${lo}–${hi}`} min).`;
    }
    if (first.startsWith("no counters balance it")) return "What would help: a level with no matching counters: add the counters that fill and drain it, or a place count.";
    if (first.startsWith("a counter that did not move")) return `What would help: the counters were flat for ${win ? `${win} min` : "the whole window"}: wait for traffic or widen the match.`;
    if (first.startsWith("Orchestra's own")) return "Nothing to do: Orchestra's own series are never a stock of the system.";
    return "";
  }
  return { keyOf, used, counts, early, help };
})();
if (typeof module !== "undefined") module.exports = LeftOut;
