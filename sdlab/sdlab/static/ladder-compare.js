// The ladder page's comparison of a true model with a found one, flow by flow, from the scorer's
// parts (sdlab/ladder/score.py): pure functions, tested with node (tests/ladder_compare.test.mjs).
//
// A part's key names its ends and what it reads: "A -> B [A]", "outside -> A [const]",
// "uses R on A -> B", "effect C on A -> B", "A -> (hidden) -> B". A flow owns the parts with its
// ends whose reader its equation reads (all of them for co-flows, effects and hidden stocks).
//
// Classes: ok (found and right), wrong (found, a number is off, or an extra term rides on it),
// missing (true, not found), spurious (found, not true), equiv (the result is "equivalent": the
// found flows make the same system, so a flow that differs is blue, not red), small (found, too
// small to count), unscored (a true flow the scorer does not read).
(function (root) {
  "use strict";
  const OUT = "outside";

  function fmt(v) {
    if (v === null || v === undefined) return "–";
    if (typeof v === "number") {
      if (!Number.isFinite(v)) return String(v);
      const a = Math.abs(v);
      if (a === 0) return "0";
      if (a >= 1000) return Math.round(v).toLocaleString("en-US");
      if (a >= 1) return String(+v.toPrecision(4));
      return String(+v.toPrecision(3));
    }
    if (typeof v === "object") {
      if (Array.isArray(v.per_window)) return v.per_window.map(fmt).join(" / ");
      if ("k_in" in v) return `k ${fmt(v.k_in)}, delay ${fmt(v.delay)}`;
      if ("delay" in v) return `delay ${fmt(v.delay)}`;
      if (v.shape === "linear") return `linear (normal ${fmt(v.normal)}, max ${fmt(v.max)})`;
      if (v.shape === "table") return `table (${(v.points || []).length} points)`;
      if ("mean" in v) return fmt(v.mean);
    }
    return String(v);
  }

  function parseKey(key) {
    const end = (x) => (x === OUT ? null : x);
    let m = /^outside -> \(hidden\) -> (.+?) \[(.+)\]$/.exec(key);              // what feeds a hidden path from outside
    if (m) return { kind: "via", from: null, to: m[1], reader: m[2] };
    m = /^effect (\S+) on outside -> \(hidden\) -> (.+)$/.exec(key);
    if (m) return { kind: "viaeffect", stock: m[1], from: null, to: m[2] };
    m = /^(.+?) -> \(hidden\) -> (.+)$/.exec(key);
    if (m) return { kind: "hidden", from: end(m[1]), to: end(m[2]) };
    m = /^(uses|effect) (\S+) on (.+?) -> (.+)$/.exec(key);
    if (m) return { kind: m[1], stock: m[2], from: end(m[3]), to: end(m[4]) };
    m = /^(.+?) -> (.+?) \[(.+)\]$/.exec(key);
    if (m) return { kind: "flow", from: end(m[1]), to: end(m[2]), reader: m[3] };
    return null;
  }

  // what an equation reads: "const" and stock ids (byTime spans and inflow pieces included)
  function readers(f) {
    const out = new Set();
    const one = (r) => {
      r = r || {};
      if (r.form === "constant") out.add("const");
      else if (r.form === "proportional" || r.form === "available") { if (r.stock) out.add(r.stock); }
      else if (r.form === "gap") { out.add("const"); out.add(r.stock); }
      else if (r.form === "linear") { if (+r.c) out.add("const"); (r.terms || []).forEach((t) => out.add(t.stock)); }
    };
    if (f.inflow && f.inflow.length) out.add("const");
    else if (f.byTime && f.byTime.length) f.byTime.forEach((g) => one(g.rate));
    else one(f.rate);
    return out;
  }

  function rateText(r) {
    r = r || {};
    switch (r.form) {
      case "constant": return fmt(+r.value);
      case "proportional": return `${fmt(+r.k)}·${r.stock}`;
      case "gap": return `(${fmt(+r.goal)} − ${r.stock}) / ${fmt(+r.time || 1)}`;
      case "available": return `all of ${r.stock || "it"}`;
      case "linear": {
        const t = (r.terms || []).map((x) => `${fmt(+x.k)}·${x.stock}`);
        return [...(+r.c || !t.length ? [fmt(+r.c || 0)] : []), ...t].join(" + ").replace(/\+ -/g, "− ");
      }
      default: return r.form || "?";
    }
  }

  // A flow's whole equation in a line: its rate, then how it changes over time, effects, co-flows,
  // a hidden stock. schedule: the case's schedule (true flows), whose changes set rates by flow id.
  function equation(f, schedule) {
    let s;
    if (f.inflow && f.inflow.length > 1) {
      const vals = f.inflow.map((p) => +p.value), lens = f.inflow.map((p) => Math.max(1, (+p.to || 0) - (+p.from || 0) + 1));
      const mean = vals.reduce((a, v, i) => a + v * lens[i], 0) / lens.reduce((a, b) => a + b, 0);
      s = `≈ ${fmt(mean)} on average, in ${f.inflow.length} pieces (${fmt(Math.min(...vals))} to ${fmt(Math.max(...vals))})`;
    } else if (f.byTime && f.byTime.length > 1) {
      const seen = [];
      f.byTime.forEach((g) => { const t = rateText(g.rate); if (!seen.includes(t)) seen.push(t); });
      s = `by time: ${seen.slice(0, 4).join(" | ")}${seen.length > 4 ? " | …" : ""} (${f.byTime.length} spans)`;
    } else s = rateText(f.rate);
    const ch = ((schedule && schedule.changes) || []).filter((c) => c.set && c.set[f.id]);
    if (ch.length) s = `${ch.map((c) => `${c.label || "t" + c.t}: ${rateText(c.set[f.id])}`).join(", ")}${schedule.every ? ` (repeats every ${schedule.every})` : ""}${ch.some((c) => c.announce) ? ", announced" : ""}`;
    (f.effects || []).forEach((e) => { s += ` × effect(${e.stock})`; });
    (f.uses || []).forEach((u) => { s += `, uses ${fmt(+u.per)} ${u.stock} each`; });
    if (f.via) s += ` via a hidden stock (delay ${fmt(+f.via.delay)})`;
    if (f.ratio && f.ratio !== 1) s += ` (${fmt(+f.ratio)} in per 1 out)`;
    if (f.merged && f.merged.note) s += ` [${f.merged.note}]`;       // flows between the same two stocks are one flow (merge.py)
    if (f.apart) s += ` [${f.apart}]`;
    return s;
  }

  // A result's found flows as the scorer reads them: the same-pair flows merged into one
  // (sdlab/ladder/merge.py; the API's found_merged), else as stored.
  // the found flows, a hidden stock the scorer matched to the truth's (scores.hidden_match) named as the truth's: drawn in
  // its place, not as a stock only the found model has (2026-10-21; diff.py matched_names does the same)
  function foundOf(r) {
    const f = (r && (r.found_merged || r.found)) || [];
    const hm = (r && r.scores && r.scores.hidden_match) || {};
    const pairs = Object.entries(hm).filter(([t, m]) => m && m.found && m.found !== t).map(([t, m]) => [m.found, t]);
    if (!pairs.length) return f;
    let text = JSON.stringify(f);
    pairs.forEach(([old, nu]) => { text = text.replace(new RegExp(`(?<![A-Za-z0-9_])${old.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Za-z0-9_])`, "g"), nu); });
    return JSON.parse(text);
  }

  const endKey = (a, b) => `${a || OUT} → ${b || OUT}`;

  // truth: the case's model ({stocks, flows, schedule}); found: the found flows; scores: the result's scores
  function compare(truth, found, scores) {
    scores = scores || {};
    found = found || [];
    const measured = new Set(truth.stocks.filter((s) => s.measured !== false).map((s) => s.id));
    const status = scores.status || null, equivalent = status === "equivalent";
    const parts = (scores.parts || []).map((p) => ({ ...p, ...parseKey(p.key) }));
    const spurious = (scores.spurious || []).map((p) => ({ ...p, ...parseKey(p.key) }));
    const hiddenOf = (id) => !measured.has(id) && truth.stocks.some((s) => s.id === id);
    // a stock nobody measures: the truth's own hidden stocks, or (found side) any stock the found
    // model names that is not measured, such as an inferred one; a chain through it is one hidden part
    const foundHidden = (id) => !!id && !measured.has(id);
    const mine = (f, list, hidden = hiddenOf) => {
      const fr = f.from, to = f.to;
      if (f.via) return list.filter((p) => p.kind === "hidden" && p.from === fr && p.to === to);
      if (hidden(fr) || hidden(to)) {
        return list.filter((p) => p.kind === "hidden" && (hidden(to) ? p.from === fr : p.to === to));
      }
      const rd = readers(f);
      return list.filter((p) => p.from === (fr || null) && p.to === (to || null) &&
        (p.kind === "flow" ? rd.has(p.reader) : p.kind === "uses" || p.kind === "effect"));
    };
    const classOf = (ps, sp) => {
      let cls;
      if (!ps.length && !sp.length) return null;
      if (!ps.length) cls = "spurious";
      else if (ps.every((p) => p.ok) && !sp.length) cls = "ok";
      else if (ps.every((p) => !p.found)) cls = "missing";
      else cls = "wrong";
      return cls !== "ok" && equivalent ? "equiv" : cls;
    };
    const why = (ps, sp, side) => [
      ...ps.filter((p) => !p.ok).map((p) => p.found ? `${p.key}: found ${fmt(p.found_value)}, true ${fmt(p.true)}` : `${p.key}: not found (true ${fmt(p.true)})`),
      ...sp.map((p) => `${p.key}: ${side === "truth" ? "found too" : "not in the truth"} (${fmt(p.value)})`),
    ];
    const tFlows = truth.flows.map((f) => {
      const ps = mine(f, parts);
      const cls = classOf(ps, []) || "unscored";
      const off = ps.filter((p) => !p.ok && p.found && p.kind === "flow");
      const linkCls = (kind, stock) => {
        const p = ps.find((q) => q.kind === kind && q.stock === stock);
        if (!p) return null;
        const c = p.ok ? "ok" : p.found ? "wrong" : "missing";
        return c !== "ok" && equivalent ? "equiv" : c;
      };
      return { flow: f, cls, parts: ps, equation: equation(f, truth.schedule), notes: why(ps, [], "truth"),
        badge: off.length ? `found ${off.map((p) => fmt(p.found_value)).join(", ")}` : cls === "missing" ? "not found" : "",
        reads: [...(f.effects || []).map((e) => ({ stock: e.stock, kind: "effect", cls: linkCls("effect", e.stock) })),
          ...(f.uses || []).map((u) => ({ stock: u.stock, kind: "uses", per: u.per, cls: linkCls("uses", u.stock) }))] };
    });
    const fFlows = found.map((f) => {
      const ps = mine(f, parts.filter((p) => p.found), foundHidden), sp = mine(f, spurious, foundHidden);
      const cls = classOf(ps, sp) || "small";
      const off = ps.filter((p) => !p.ok && p.kind !== "effect");
      return { flow: f, cls, parts: ps, spurious: sp, equation: equation(f), notes: why(ps, sp, "found"),
        badge: off.length ? off.map((p) => `true ${fmt(p.true)}`).join(", ") : sp.length && ps.length ? "extra term" : "" };
    });
    // the equations side by side, one row per pair of ends (truth order first)
    const rows = [], byKey = {};
    const row = (f) => {
      const k = f.via ? `${f.from} → (hidden) → ${f.to}` : endKey(f.from, f.to);
      if (!byKey[k]) { byKey[k] = { ends: k, truth: [], found: [] }; rows.push(byKey[k]); }
      return byKey[k];
    };
    tFlows.forEach((t) => {
      const f = t.flow;
      if (hiddenOf(f.from) || hiddenOf(f.to)) {
        const a = hiddenOf(f.to) ? f.from : truth.flows.find((g) => g.to === f.from) && truth.flows.find((g) => g.to === f.from).from;
        const b = hiddenOf(f.to) ? (truth.flows.find((g) => g.from === f.to) || {}).to : f.to;
        const k = `${a} → (hidden) → ${b}`;
        if (!byKey[k]) { byKey[k] = { ends: k, truth: [], found: [] }; rows.push(byKey[k]); }
        byKey[k].truth.push(t);
      } else row(f).truth.push(t);
    });
    fFlows.forEach((x) => {
      const f = x.flow;
      if (!f.via && (foundHidden(f.from) || foundHidden(f.to))) {             // a chain through a stock the found model infers
        const a = foundHidden(f.to) ? f.from : (found.find((g) => g.to === f.from) || {}).from;
        const b = foundHidden(f.to) ? (found.find((g) => g.from === f.to) || {}).to : f.to;
        const k = `${a || OUT} → (hidden) → ${b || OUT}`;
        if (!byKey[k]) { byKey[k] = { ends: k, truth: [], found: [] }; rows.push(byKey[k]); }
        byKey[k].found.push(x);
      } else row(f).found.push(x);
    });
    const rank = { missing: 5, spurious: 5, wrong: 4, equiv: 3, unscored: 2, small: 1, ok: 0 };
    rows.forEach((r) => {
      const all = [...r.truth, ...r.found].map((x) => x.cls);
      r.cls = all.sort((a, b) => (rank[b] || 0) - (rank[a] || 0))[0] || "ok";
    });
    const book = equivalent && scores.algebra && scores.algebra.bookkeeping ? scores.algebra.bookkeeping : null;   // (2026-10-21) how a proven equivalent drawing differs
    return { status, equivalent, bookkeeping: book, truth: tFlows, found: fFlows, rows, measured: [...measured],
      extraStocks: [...new Set(found.flatMap((f) => [f.from, f.to]).filter((x) => x && !truth.stocks.some((s) => s.id === x)))] };
  }

  // The comparison with its verdicts from the server's diff (sdlab/ladder/diff.py, GET /api/ladder/diff/...), so the page
  // and `sdlab-ladder diff` can never disagree: every flow's class, its parts, notes and badge, the rows, the lines, the
  // stat and the hunk come from dif; cmp (compare()'s) keeps the flows and equations. No dif, or one that does not fit
  // these flows: cmp unchanged (the page's own logic, the fallback).
  function withDiff(cmp, dif, scores) {
    if (!dif || !dif.flows || dif.flows.truth.length !== cmp.truth.length || dif.flows.found.length !== cmp.found.length) return cmp;
    scores = scores || {};
    const byKey = {};
    [...(scores.parts || []), ...(scores.spurious || [])].forEach((p) => { byKey[p.key] = { ...p, ...parseKey(p.key) }; });
    const pick = (keys) => (keys || []).map((k) => byKey[k]).filter(Boolean);
    const truth = cmp.truth.map((t, i) => {
      const v = dif.flows.truth[i];
      return { ...t, cls: v.cls, parts: pick(v.parts), notes: v.notes, badge: v.badge, reads: t.reads.map((x, j) => ({ ...x, cls: v.reads && v.reads[j] ? v.reads[j].cls : x.cls })) };
    });
    const found = cmp.found.map((x, k) => {
      const v = dif.flows.found[k];
      return { ...x, cls: v.cls, parts: pick(v.parts), spurious: pick(v.spurious), notes: v.notes, badge: v.badge };
    });
    const rows = (dif.rows || []).map((w) => ({ ends: w.ends, cls: w.cls, truth: w.truth.map((i) => truth[i]), found: w.found.map((k) => found[k]) }));
    return { ...cmp, truth, found, rows, extraStocks: dif.extra_stocks || cmp.extraStocks, api: dif };
  }
  const GLYPH = { " ": "✓", "-": "−", "=": "≈", ".": "·", "+": "+", "~": "~" };

  // ---------- error measures and a plain-language explanation, from the scorer's parts ----------
  // A part in words: "the move A → B", "the drain of B", "the inflow to A", "the link B ⇒ A", ...
  function partName(key) {
    const k = parseKey(key) || {}, end = (x) => x || "outside";
    if (k.kind === "hidden") return `the hidden stock between ${k.from} and ${k.to}`;
    if (k.kind === "uses") return `the co-flow (${k.from} → ${k.to} uses ${k.stock})`;
    if (k.kind === "effect") return `the effect of ${k.stock} on ${end(k.from)} → ${end(k.to)}`;
    if (k.kind !== "flow") return key;
    const r = k.reader === "const" ? "" : k.reader;
    if (k.from && k.to) return `the move ${k.from} → ${k.to}${r && r !== k.from ? ` (reading ${r})` : ""}`;
    if (k.to) return r ? `the link ${r} ⇒ ${k.to}` : `the inflow to ${k.to}`;
    return r && r !== k.from ? `the outflow from ${k.from} reading ${r}` : `the drain of ${k.from}${r ? "" : " (constant)"}`;
  }
  const num = (v) => (typeof v === "number" ? v : v && typeof v === "object" && typeof v.mean === "number" ? v.mean : null);

  // The measures a card shows. errorScore, the headline: the share of the equations' numbers that
  // are wrong, (true parts missing + true parts off + spurious parts) / true parts; 0 = the true
  // equations exactly (within tolerance), 1 = as many wrong numbers as there are true ones.
  function measures(scores) {
    const s = scores || {}, parts = s.parts || [], sp = s.spurious || [];
    const b = s.behaviour || {}, sk = (w, h) => (b[w] || {})[String(h)] || {};
    const matched = parts.filter((p) => p.found && typeof p.error === "number" && Number.isFinite(p.error) && p.kind !== "effect");
    const worst = matched.reduce((w, p) => (!w || p.error > w.error ? p : w), null);
    const missing = parts.filter((p) => !p.found).length, off = parts.filter((p) => p.found && !p.ok).length;
    const of = parts.length || s.of || 0;
    return {
      status: s.status || null, recall: s.recall ?? null, precision: s.precision ?? null, right: s.right ?? null, of,
      missing, off, spurious: sp.length, spuriousSize: sp.reduce((a, p) => a + (num(p.size) || 0), 0),
      rateMean: matched.length ? matched.reduce((a, p) => a + p.error, 0) / matched.length : null,
      rateMax: worst ? worst.error : null, rateWorst: worst ? partName(worst.key) : null,
      skill20: sk("in_sample", 20).skill ?? null, skill20ci: sk("in_sample", 20).ci || null,
      skill100: sk("in_sample", 100).skill ?? null, skill100ci: sk("in_sample", 100).ci || null,
      fresh20: sk("fresh", 20).skill ?? null,
      errorScore: of ? (missing + off + sp.length) / of : null,
    };
  }

  const pc = (x) => `${Math.round(100 * x)}%`;
  const list = (xs) => (xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  // 1-3 sentences: what was right, what was missed, what was invented, and why the verdict
  function explain(scores) {
    const s = scores || {}, parts = s.parts || [], sp = s.spurious || [];
    if (!s.status) return "";
    const ok = parts.filter((p) => p.ok), off = parts.filter((p) => p.found && !p.ok), miss = parts.filter((p) => !p.found);
    const out = [];
    const errs = ok.map((p) => p.error).filter((e) => typeof e === "number" && Number.isFinite(e));
    if (ok.length) {
      const within = errs.length ? ` within ${Math.max(1, Math.ceil(100 * Math.max(...errs)))}%` : "";
      out.push(ok.length === parts.length ? `Found ${parts.length === 1 ? "the one true number" : `all ${parts.length} true numbers`}${within}.` : `Found ${list(ok.slice(0, 3).map((p) => partName(p.key)))}${ok.length > 3 ? ` and ${ok.length - 3} more` : ""}${within}.`);
    }
    const bits = [];
    if (miss.length) bits.push(`missed ${list(miss.slice(0, 3).map((p) => partName(p.key)))}${miss.length > 3 ? ` and ${miss.length - 3} more` : ""}`);
    if (off.length) {
      const worst = [...off].sort((a, b) => (b.error || 0) - (a.error || 0)).slice(0, 2);
      bits.push(`got ${list(worst.map((p) => typeof num(p.found_value) === "number" && typeof num(p.true) === "number"
        ? `${partName(p.key)} ${num(p.found_value) > num(p.true) ? "too high" : "too low"} (${fmt(p.found_value)} for ${fmt(p.true)}${typeof p.error === "number" ? `, ${pc(p.error)} off` : ""})`
        : `${partName(p.key)} wrong (${fmt(p.found_value)} for ${fmt(p.true)})`))}${off.length > 2 ? ` and ${off.length - 2} more off` : ""}`);
    }
    if (sp.length) bits.push(`invented ${list(sp.slice(0, 3).map((p) => `${partName(p.key)} (${fmt(p.value)})`))}${sp.length > 3 ? ` and ${sp.length - 3} more` : ""}`);
    if (bits.length) out.push(`${cap(list(bits))}.`);
    if (s.status === "pass") out.push("Pass: every true number is right in every window and nothing is invented.");
    else if (s.status === "equivalent") {
      const read = miss.length || sp.length ? `It read ${list(miss.map((p) => partName(p.key))) || "the truth"} as ${list(sp.map((p) => partName(p.key))) || "other numbers"}: ` : "";
      const book = s.algebra && s.algebra.bookkeeping ? ` (${s.algebra.bookkeeping})` : "";
      out.push(`Equivalent, not a pass. ${read}every stock's net rate is proven the same function of the stocks and inputs for every state${book}.`);
    } else if (s.status === "fits") {
      const why = (s.notes || []).find((n) => n.startsWith("fits, not proven equivalent: "));
      out.push(`Fits, not proven: the data cannot tell it from the truth, but its equations differ${why ? ` (${why.slice("fits, not proven equivalent: ".length)})` : ""}. Not a pass, not equivalent.`);
    } else if (s.status === "fail") {
      const why = [miss.length && `${miss.length} true number${miss.length === 1 ? "" : "s"} missing`, off.length && `${off.length} off`, sp.length && `${sp.length} invented`].filter(Boolean);
      out.push(`Fail: ${list(why) || "the equations differ"}${why.length ? "" : ""}.`);
    } else out.push(`${cap(s.status)}: the strategy did not finish.`);
    return out.join(" ");
  }

  // The comparison as a diff, one line per flow, like a code diff:
  //   ✓ outside → A   in 20                 found 20.1
  //   ~ A → B         ab 0.3·A              found 0.24·A (20% low)
  //   − B → outside   b_out 0.2·B           missed
  //   + A → outside                         invented 0.16·A
  //   ≈ outside → B                         read as 0.2·A (equivalent to the link A ⇒ B)
  // {sign, cls, ends, truth, note}; truth is the true flow's id and equation ("" for an invented one).
  function diffLines(cmp) {
    if (cmp.api) {                                  // the server's lines (diff.py), in the page's order: truth flows, then found ones
      const all = [...cmp.api.lines, ...cmp.api.unchanged].sort((a, b) => (a.side === b.side ? a.index - b.index : a.side === "truth" ? -1 : 1));
      return all.map((x) => ({ sign: GLYPH[x.sign] || x.sign, cls: x.cls, ends: x.ends.replace(/ -> /g, " → "), truth: x.truth, note: x.note }));
    }
    const lines = [];
    const endsOf = (f) => `${f.from || "outside"} → ${f.to || "outside"}`;
    const foundFor = (t) => cmp.found.filter((x) => x.parts.some((p) => t.parts.some((q) => q.key === p.key)));
    const dir = (p) => {
      const a = num(p.found_value), b = num(p.true);
      return typeof a === "number" && typeof b === "number" && b ? ` (${Math.round(100 * Math.abs(a - b) / Math.abs(b))}% ${a < b ? "low" : "high"})` : "";
    };
    cmp.truth.forEach((t) => {
      const fs = foundFor(t), feq = fs.map((x) => x.equation).join("; ");
      const off = t.parts.filter((p) => p.found && !p.ok), miss = t.parts.filter((p) => !p.found);
      let sign = "·", note = "not scored";
      if (t.cls === "ok") { sign = "✓"; note = feq ? `found ${feq}` : "found"; }
      else if (t.cls === "missing") { sign = "−"; note = "missed"; }
      else if (t.cls === "wrong") {
        sign = "~";
        const bits = [...off.map((p) => `${p.kind === "effect" || p.kind === "hidden" ? partName(p.key) + " " : ""}${fmt(p.found_value)} for ${fmt(p.true)}${dir(p)}`), ...miss.map((p) => `missed ${partName(p.key)}`)];
        note = `${feq ? `found ${feq}` : "found"}: ${bits.join("; ")}`;
      } else if (t.cls === "equiv") {
        sign = "≈";
        note = `${feq ? `found ${feq}; ` : ""}${miss.length ? `missed ${miss.map((p) => partName(p.key)).join(", ")}, ` : ""}${cmp.bookkeeping ? `the same equations drawn another way (proven equivalent: ${cmp.bookkeeping})` : "read another way with the same behaviour (equivalent)"}`;
      }
      lines.push({ sign, cls: t.cls === "missing" ? "missed" : t.cls, ends: t.flow.via ? `${t.flow.from} → (hidden) → ${t.flow.to}` : endsOf(t.flow), truth: `${t.flow.id} ${t.equation}`, note });
    });
    const missedNames = cmp.truth.flatMap((t) => t.parts.filter((p) => !p.found).map((p) => partName(p.key)));
    cmp.found.forEach((x) => {
      const f = x.flow, ends = f.via ? `${f.from} → (hidden) → ${f.to}` : endsOf(f);
      if (x.cls === "spurious") lines.push({ sign: "+", cls: "spurious", ends, truth: "", note: `invented ${x.equation}` });
      else if (x.cls === "equiv" && !x.parts.length) lines.push({ sign: "≈", cls: "equiv", ends, truth: "", note: `read as ${x.equation}${missedNames.length ? ` (equivalent to ${missedNames.join(", ")})` : " (equivalent)"}${cmp.bookkeeping ? `; ${cmp.bookkeeping}` : ""}` });
      else if (x.spurious.length && x.parts.length) lines.push({ sign: "+", cls: x.cls === "equiv" ? "equiv" : "spurious", ends, truth: "", note: `extra term on ${x.equation}: ${x.spurious.map((p) => `${partName(p.key)} ${fmt(p.value)}`).join(", ")}` });
      else if (x.cls === "small") lines.push({ sign: "·", cls: "small", ends, truth: "", note: `too small to count: ${x.equation}` });
    });
    return lines;
  }

  const api = { fmt, parseKey, readers, rateText, equation, foundOf, compare, withDiff, partName, measures, explain, diffLines };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SDLadder = api;
})(typeof window !== "undefined" ? window : globalThis);
