// The model as a graph to draw: pure functions of the model, used by the Dynamics page and by the
// layout tests (tests/layout), so what is tested is what is drawn.
//
// Stocks are boxes, each flow is one arrow from its source to its destination (a cloud when either
// is outside), influences are dashed links from what a rate reads to the middle of its flow, and
// measured levels a rate reads that no counters balance are auxiliaries (round boxes). Feedback
// loops are cycles of the causal graph: a flow adds to its destination (+) and takes from its
// source (−); a rate depends on what it reads with the sign of its coefficient.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.SDGraph = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const nice = (s) => s || "outside";
  const count = (v) => (Number.isInteger(+v) ? String(+v) : (+v).toFixed(1));     // a level of things: "5", "2.5"
  const num = (v, short) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(short ? 2 : 3));
  // What to call each stock and flow. A series' name says what kind of thing it counts ("beads
  // issues"); its labels say which ones ("status: in_progress"). So a stock is named by the label
  // values that tell it apart from the other stocks of the same series, with the series' name as
  // its family, said apart (a caption): "in progress", family "beads issues".
  // - only labels whose values differ within the family are said; the one with the most values
  //   first and always, the others only where they are not the family's usual value ("open" and
  //   "open · cake" beside "closed", not "open · loaf");
  // - a series alone in its family is named by the series;
  // - a series alone in its family whose first word other stocks' series share (a namespace, by
  //   Prometheus' convention: bakery_orders_baking, bakery_shelf_items) has that word as its family;
  // - a flow is named by its counter: its series' name, then who moved what from where to where
  //   ("queue item moves · packer: WAITING → PACKING"), a lone end with its key ("from
  //   REJECTED"), and any other label that tells the family's flows apart, with its key ("status
  //   landed"). A counter several flows share says so ("one counter, 2 flows"); a flow whose events
  //   another counter also counts (evidence.same_as) says so beside its name (sameAs), not in it;
  // - a stock named by a label that also names the stocks of another series (pods by region, for
  //   two services) says its machine too ("search · eu-west"), so two services' regions never
  //   look alike. A remote machine's source prefix is left out (rig.search: "search").
  // - a part the server named by its instrument's places or in words (``evidence.named``,
  //   sd/titles.py: "items held at write", a move "write → open_pr", a hidden state "deliveries
  //   between write and sail_check"; "commits on main") is shown by that name, as every page shows it; the
  //   sentence its instrument's view gives it (``describes``, collect/views.py; the model carries
  //   the views) is its description (``about``), never part of its name (the owner, 2026-11-01:
  //   "write.held" read as a disk write); two such series of one name are told apart by their families;
  // - a stock no series measures (a passage, sd/passing.py, or a hidden stock a strategy found) is
  //   otherwise named by its neighbours: "between write (held) and outside", never by the counter
  //   that fills it nor by its id.
  // - a part's tags (``tags``, sd/titles.py: "workflow=delivery_sail", a view's noun "deliveries")
  //   are drawn beside its name as chips, never in it (the owner, 2026-11-02); two parts the server
  //   named alike are told apart by the tags they do not share, said after the name in text
  //   ("held at write · workflow=hotfix") and drawn as chips;
  // - a part a declaration names (``declared_name``: a declared stock linked to it, a declared flow
  //   found as it; sd/intended/display.py) is shown by that name, the name it would have had kept
  //   beneath it as its identifier (``generated``) with who named it (``namedBy``).
  // Label values keep their spelling (sail_check, delivery_sail); a series' name is said in words.
  // Names are {name, family, about, tags}; ``label`` is the name, with the family only where the name
  // alone is not unique in the model. The model's own ``name`` stays the full record.
  const IGNORE = new Set(["project", "machine", "instrument", "instance", "source"]);
  // the view the series' instrument declared of it (collect/views.py; ``views``: by instrument, then
  // series name, each a list whose first match wins): how it was made, and its sentence
  function viewOf(views, r, instrument) {
    const l = (r && r.labels) || {}, inst = instrument || l.instrument, list = views && inst && views[inst] && views[inst][r.name];
    return (list || []).find((v) => Object.entries(v.where || {}).every(([k, w]) => l[k] === w)) || null;
  }
  // a part the server named by its instrument's places: its name as it is, its view's sentence beside it
  const named = (x) => !!(x && x.evidence && x.evidence.named);
  // a part's tags (sd/titles.py): what narrows its name, said beside it
  const tagsOf = (x) => (x && (x.tags || (x.evidence && x.evidence.tags))) || [];
  // the chips of a part's tags, as HTML (``esc``: the page's escaper)
  const tagsHtml = (tags, esc) => (tags || []).map((t) => `<span class="ptag" title="a tag: ${esc(String(t).includes("=") ? "a label of its series" : "what its instrument says it counts")}">${esc(t)}</span>`).join("");
  // who named a part, from its declaration's provenance: "you", "the owner (quoted), per supervisor", "integrator"
  function namedBy(p) {
    p = p || {};
    if (p.author === "owner") return !p.via || p.via === "page" ? "you" : `the owner (quoted), per ${p.source || (p.via === "endpoint" ? "a caller of the endpoint" : "a plugin")}`;
    return p.source || p.author || "a declaration";
  }
  const aboutOf = (r, views, instrument) => { const v = viewOf(views, r, instrument); return (v && v.describes) || ""; };
  const words = (v) => String(v);
  const seriesOf = (x) => x.series || x.counter || (x.measured_by && x.measured_by[0]) || null;
  const familyName = (n) => n.replace(/_total$/, "").replace(/_/g, " ");
  // a machine as a stock's name says it: without its source's prefix when the series has it
  const machineWord = (s) => { const mc = (s.labels || {}).machine; if (!mc) return null;
    const pre = s.name.includes(":") ? s.name.split(":")[0] + "." : null;
    return words(pre && mc.startsWith(pre) ? mc.slice(pre.length) : mc); };
  function nameFamily(items, drop = null, views = null) {
    const out = {}, fams = new Map(), said_by = {};
    for (const x of items) { const s = seriesOf(x); if (!s || (!drop && named(x))) continue; const k = s.name; fams.set(k, [...(fams.get(k) || []), x]); }
    for (const [fname, xs] of fams) {
      const labels = (x) => Object.fromEntries(Object.entries(seriesOf(x).labels || {}).filter(([k]) => !IGNORE.has(k)));
      const keys = [...new Set(xs.flatMap((x) => Object.keys(labels(x))))].map((k) => {
        const counts = new Map(); for (const x of xs) { const v = labels(x)[k] ?? ""; counts.set(v, (counts.get(v) || 0) + 1); }
        const top = [...counts.entries()].sort((a, b) => b[1] - a[1]);
        return { k, n: counts.size, usual: top.length > 1 && top[0][1] > top[1][1] ? top[0][0] : null };
      }).filter((c) => c.n > 1).sort((a, b) => b.n - a.n || a.k.localeCompare(b.k));
      const said = (x, all) => { const l = labels(x), gone = drop ? drop(x) : new Set();
        return keys.filter((c, i) => l[c.k] != null && !gone.has(l[c.k]) && (all || drop || i === 0 || l[c.k] !== c.usual)).map((c) => words(l[c.k])); };
      const fam = familyName(fname);
      let names = xs.map((x) => said(x, false).join(" · "));
      // leaving a usual value out must never make two names the same
      names = names.map((nm, i) => (names.filter((o) => o === nm).length > 1 ? said(xs[i], true).join(" · ") : nm));
      // a series alone in its family keeps the qualifier the model's own name gives it, when that is
      // all that narrows it ("orders open (web)": the one series of a family several machines write)
      const qualified = (x) => (!drop && typeof x.name === "string" && x.name.startsWith(fam + " (") && x.name.endsWith(")") ? x.name : fam);
      xs.forEach((x, i) => { out[x.id] = drop ? { name: fam + (names[i] ? " · " + names[i] : ""), family: "" }
        : names[i] ? { name: names[i], family: fam } : { name: qualified(x), family: "" };
        if (names[i]) said_by[x.id] = { fam: fname, keys: keys.map((c) => c.k), machine: machineWord(seriesOf(x)) }; });
    }
    if (!drop) {                        // a label that names the stocks of several series: say whose
      const famsOf = new Map();
      for (const v of Object.values(said_by)) for (const k of v.keys) famsOf.set(k, new Set([...(famsOf.get(k) || []), v.fam]));
      for (const [id, v] of Object.entries(said_by)) {
        if (v.machine && v.keys.some((k) => famsOf.get(k).size > 1) && !out[id].name.split(" · ").includes(v.machine)) out[id].name = `${v.machine} · ${out[id].name}`;
      }
    }
    if (!drop) {
      const mine = items.filter(named);
      for (const x of mine) out[x.id] = { name: x.name, family: "", about: seriesOf(x) ? aboutOf(seriesOf(x), views) : "", stepped: true };
      // two parts of one name: the tags they do not share tell them apart, else their families
      for (const x of mine) {
        const like = mine.filter((y) => y !== x && out[y.id].name === out[x.id].name);
        if (!like.length) continue;
        const apart = tagsOf(x).filter((t) => like.some((y) => !tagsOf(y).includes(t)));
        out[x.id].family = apart.length ? apart.join(" · ") : seriesOf(x) ? familyName(seriesOf(x).name) : "";
        out[x.id].byTags = apart.length > 0;          // its chips tell it apart: the family is for text only
      }
    }
    // what no series measures: a stock by its own name; a flow is a balance's remainder, named by
    // what it does (its ends are always shown beside it)
    for (const x of items) if (!out[x.id]) out[x.id] = drop ? { name: `unmeasured ${x.from && x.to ? "flow" : x.from ? "outflow" : "inflow"}`, family: "" } : { name: x.name || nice(x.id), family: "" };
    if (!drop) {
      const first = (n) => n.split(" ")[0], alone = Object.values(out).filter((v) => !v.family && !v.stepped && v.name.includes(" "));
      const shared = alone.map((v) => alone.filter((o) => first(o.name) === first(v.name)).length > 1);
      alone.forEach((v, i) => { if (shared[i]) { v.family = first(v.name); v.name = v.name.slice(v.family.length + 1); } });
    }
    return out;
  }
  const MOVE = new Set(["by", "from", "to"]);
  const labelsOf = (r) => Object.fromEntries(Object.entries((r && r.labels) || {}).filter(([k]) => !IGNORE.has(k)));
  // what a counter says of the move it counts: "worker: OPEN → IN PROGRESS", "from REJECTED", "planner"
  function moveText(l) {
    const move = l.from != null && l.to != null ? `${words(l.from)} → ${words(l.to)}` : l.from != null ? `from ${words(l.from)}` : l.to != null ? `to ${words(l.to)}` : "";
    const by = l.by != null ? words(l.by) : "";
    return by && move ? `${by}: ${move}` : by || move;
  }
  const refKey = (r) => r.name + JSON.stringify(Object.entries(labelsOf(r)).sort());
  function flowNames(fs) {
    const out = {}, fams = new Map(), byKey = new Map();
    for (const f of fs) { const c = seriesOf(f); if (!c) continue; fams.set(c.name, [...(fams.get(c.name) || []), f]); byKey.set(refKey(c), [...(byKey.get(refKey(c)) || []), f.id]); }
    for (const [fname, xs] of fams) {
      // the other labels that tell this family's flows apart, said with their key
      // (a family of one counter says every other label it has: "deploy runs · status landed")
      const one = new Set(xs.map((f) => refKey(seriesOf(f)))).size === 1;
      const differ = [...new Set(xs.flatMap((f) => Object.keys(labelsOf(seriesOf(f)))))].filter((k) => !MOVE.has(k) && (one || new Set(xs.map((f) => labelsOf(seriesOf(f))[k] ?? "")).size > 1)).sort();
      for (const f of xs) {
        const l = labelsOf(seriesOf(f)), parts = [moveText(l), ...differ.filter((k) => l[k] != null).map((k) => `${words(k)} ${words(l[k])}`)].filter(Boolean);
        const shared = byKey.get(refKey(seriesOf(f))).length;
        out[f.id] = { name: familyName(fname) + (parts.length ? " · " + parts.join(", ") : "") + (shared > 1 ? ` (one counter, ${shared} flows)` : ""), family: "" };
      }
    }
    for (const f of fs) if (!out[f.id]) out[f.id] = { name: `unmeasured ${f.from && f.to ? "flow" : f.from ? "outflow" : "inflow"}`, family: "" };
    return out;
  }
  // one series by itself, as the Instruments page lists an instrument's series: by the title the
  // server gave it (``title``, sd/titles.py, as a stock or a flow of it would be named), else by its
  // labels, with the sentence its view gives it (``views``: by instrument, as the model carries them)
  // and its tags (``tags``, with its title): {name, family, about, tags?}
  function seriesName(r, views = null, instrument = null) {
    const fam = familyName(r.name);
    if (r.title) return { name: r.title, family: fam, about: aboutOf(r, views, instrument), ...(r.tags ? { tags: r.tags } : {}) };
    const l = labelsOf(r), rest = Object.entries(l).filter(([k]) => !MOVE.has(k)).sort(([x], [y]) => x.localeCompare(y)).map(([k, v]) => `${words(k)} ${words(v)}`);
    const parts = [moveText(l), ...rest].filter(Boolean);
    return { name: parts.length ? parts.join(", ") : fam, family: parts.length ? fam : "", about: "" };
  }
  // a stock no series measures between others (a passage): named by its neighbours, their shared
  // qualifier said once ("between write (held) and open pr (waiting) · delivery sail")
  function betweenName(m, s, stocks) {
    const nm = (id) => (id && stocks[id] ? stocks[id].name + (stocks[id].stepped && stocks[id].family ? " · " + stocks[id].family : "") : "outside");
    const ins = [...new Set((m.flows || []).filter((f) => f.to === s.id && f.from !== s.id).map((f) => nm(f.from)))];
    const outs = [...new Set((m.flows || []).filter((f) => f.from === s.id && f.to !== s.id).map((f) => nm(f.to)))];
    if (!ins.length && !outs.length) return null;
    const a = ins.length ? ins : ["outside"], b = outs.length ? outs : ["outside"];
    const tails = [...a, ...b].map((n) => n.split(" · ").slice(1).join(" · "));
    const tail = tails.every((t) => t && t === tails[0]) ? tails[0] : "";
    const cut = (n) => (tail ? n.slice(0, n.length - tail.length - 3) : n);
    return `between ${a.map(cut).join(" or ")} and ${b.map(cut).join(" or ")}${tail ? " · " + tail : ""}`;
  }
  // when the ends a flow's counter names are not the ends it is drawn between (a co-flow drawn
  // through a stock it passes, a move whose place is no stock), why, in words: "counted as
  // triage.held → write.waiting, drawn from outside"; "" when they agree or it names none. A value in
  // angle brackets (<start>, <end>) is outside; a stock agrees with a value its series carries or
  // its name says.
  function drawnApart(m, f) {
    const l = (f && f.counter && f.counter.labels) || {};
    if (l.from == null || l.to == null) return "";
    const outside = (v) => /^<.*>$/.test(String(v));
    const fold = (t) => String(t).toLowerCase().replace(/[\W_]+/g, " ").trim();
    const agrees = (id, v) => { if (!id) return outside(v); if (outside(v)) return false;
      const s = (m.stocks || []).find((x) => x.id === id), ser = s && seriesOf(s);
      return (ser && Object.values(ser.labels || {}).includes(v)) || fold(stockName(m, id)).includes(fold(v)); };
    const end = (id) => (id ? stockName(m, id) : "outside");
    const apart = [!agrees(f.from, l.from) ? `from ${end(f.from)}` : "", !agrees(f.to, l.to) ? `into ${end(f.to)}` : ""].filter(Boolean);
    const said = (v) => String(v).replace(/^<(.*)>$/, "$1");
    return apart.length ? `counted as ${said(l.from)} → ${said(l.to)}, drawn ${apart.join(" and ")}` : "";
  }
  // the other counters that count a flow's events (evidence.same_as), named as flows are: "same events as …"
  function sameAs(m, f) {
    const same = (f && f.evidence && f.evidence.same_as) || [];
    return same.map((r) => { const g = (m.flows || []).find((x) => x !== f && seriesOf(x) && refKey(seriesOf(x)) === refKey(r));
      return g ? flowName(m, g) : familyName(r.name) + (moveText(labelsOf(r)) ? " · " + moveText(labelsOf(r)) : ""); });
  }
  const NAMES = new WeakMap();
  function names(m) {
    if (!m) return { stocks: {}, flows: {} };
    if (NAMES.has(m)) return NAMES.get(m);
    const stocks = nameFamily(m.stocks || [], null, m.views || null);
    for (const s of m.stocks || []) { if (seriesOf(s) || named(s) || !(s.evidence && (s.evidence.passing || s.evidence.hidden))) continue;
      const b = betweenName(m, s, stocks); if (b) stocks[s.id] = { name: b, family: "", about: "", between: true }; }
    const flows = flowNames(m.flows || []);
    const namedFlows = (m.flows || []).filter(named);
    for (const f of namedFlows) {
      const like = namedFlows.filter((g) => g !== f && g.name === f.name), apart = tagsOf(f).filter((t) => like.some((g) => !tagsOf(g).includes(t)));
      flows[f.id] = { name: f.name, family: like.length ? apart.join(" · ") : "", byTags: like.length > 0 && apart.length > 0 };
    }
    for (const [group, xs] of [[stocks, m.stocks || []], [flows, m.flows || []]]) {
      for (const x of xs) if (group[x.id]) group[x.id].tags = tagsOf(x);
      const seen = new Map(); for (const v of Object.values(group)) seen.set(v.name, (seen.get(v.name) || 0) + 1);
      for (const v of Object.values(group)) v.label = v.family && seen.get(v.name) > 1 ? `${v.name} · ${v.family}` : v.name;
    }
    // two flows of one name are told apart by where each goes ("sail_check → end · into commits on
    // main"), then where each comes from: the one name used everywhere a flow is named
    const end = (id, fallback) => (id ? (stocks[id] ? stocks[id].label : nice(id)) : fallback);
    for (const of of [(f) => (f.to ? `into ${end(f.to)}` : "to outside"), (f) => `from ${end(f.from, "outside")}`]) {
      const seen = new Map(); for (const f of m.flows || []) { const l = flows[f.id] && flows[f.id].label; if (l) seen.set(l, (seen.get(l) || 0) + 1); }
      for (const f of m.flows || []) { const v = flows[f.id]; if (v && seen.get(v.label) > 1) v.label = `${v.label} · ${of(f)}`; }
    }
    // a part a declaration names: by that name, the one it would have had kept as its identifier
    for (const [group, xs] of [[stocks, m.stocks || []], [flows, m.flows || []]]) for (const x of xs) {
      const d = x.declared_name, v = group[x.id]; if (!d || !d.name || !v) continue;
      group[x.id] = { ...v, name: d.name, label: d.name, family: "", generated: v.label, namedBy: namedBy(d.provenance), declared: d };
    }
    const out = { stocks, flows }; NAMES.set(m, out); return out;
  }
  const stockName = (m, id) => { const n = names(m).stocks[id]; return n ? n.label : nice(id); };
  const flowName = (m, f) => { if (!f) return null; const n = names(m).flows[f.id]; return n ? n.label : f.name; };
  // what an equation reads, by name: a stock, or a measured input (input:<name>)
  const readName = (m, x) => { if (!x) return "?"; const n = x.startsWith("input:") ? x.slice(6) : x;
    return m && m.stocks.some((s) => s.id === n) ? stockName(m, n) : n.replace(/_/g, " "); };
  const refOf = (m, x) => (m && m.stocks.some((s) => s.id === x) ? x : "input:" + x);

  function eqText(m, f, short) {
    const e = f.current; if (!e) return "no equation yet";
    const unit = (m && m.time_unit) || "hour", per = `/${unit === "minute" ? "min" : unit === "hour" ? "h" : "s"}`;
    const sp = e.spec && e.spec.form ? e.spec : null, p = e.params;
    if (sp) {                                   // SD Lab's rate, in full
      const fx = (sp.effects || []).map((ef) => ` × f(${readName(m, ef.stock)})`).join("");
      const t = { constant: () => num(sp.value, short),
        proportional: () => `${num(sp.k, short)} × ${readName(m, sp.stock)}`,
        linear: () => [num(sp.c || 0, short), ...(sp.terms || []).map((t) => `${t.k < 0 ? "−" : "+"} ${num(Math.abs(t.k), short)} × ${readName(m, t.stock)}`)].join(" "),
        gap: () => `(${num(sp.goal, short)} − ${readName(m, sp.stock)}) / ${num(sp.time, short)}`,
        available: () => `all of ${f.from ? stockName(m, f.from) : "it"}`,
        expr: () => sp.expr }[sp.form];
      return (t ? t() : sp.form) + fx + (sp.form === "expr" ? "" : " " + per);
    }
    const x = (e.inputs && e.inputs[0]) || f.from;
    if (e.form === "constant") return `${num(p.c, short)} ${per}`;
    if (e.form === "proportional") return `${num(p.k, short)} × ${readName(m, x)} ${per}`;
    if (e.form === "linear") return `${num(p.c, short)} ${p.k < 0 ? "−" : "+"} ${num(Math.abs(p.k), short)} × ${readName(m, x)} ${per}`;
    return JSON.stringify(p);
  }

  // a flow into or out of a stock no counters balance, whose rate reads another series: its driver
  // was found by fitting the level's changes, a correlation that no experiment has tested
  const UNTESTED = "fitted from correlation; untested: no experiment has moved its driver";
  // what a flow's current equation reads other than its own ends: its drivers by correlation
  function drivers(f) {
    const e = f && f.current; if (!e) return [];
    const sp = e.spec && e.spec.form ? e.spec : null;
    const reads = [...(e.inputs || []), ...(sp ? [sp.stock, ...(sp.terms || []).map((t) => t.stock), ...(sp.effects || []).map((x) => x.stock)] : [])].filter(Boolean)
      .map((x) => String(x).replace(/^input:/, ""));
    return [...new Set(reads)].filter((x) => x !== f.from && x !== f.to);
  }
  // a flow whose rate reads anything but its own source and destination was fitted from a correlation
  // no experiment has tested, however its stocks were found
  function correlational(m, f) { return drivers(f).length > 0; }
  // the caveat, naming the driver: "reads jobs waiting at review, not its source: fitted from correlation; untested"
  function untestedText(m, f) {
    const ds = drivers(f); if (!ds.length) return "";
    return `reads ${ds.map((x) => readName(m, x)).join(" and ")}, not its source: fitted from correlation; untested`;
  }

  // the sign of each thing a rate reads: + more of it, more flow; − more of it, less flow; ~ unknown
  function readsWithSign(m, f) {
    const e = f.current; if (!e) return [];
    const sp = e.spec && e.spec.form ? e.spec : null, out = [];
    if (sp) {
      if (sp.form === "proportional" && sp.stock) out.push([refOf(m, sp.stock), 1]);
      if (sp.form === "gap" && sp.stock) out.push([refOf(m, sp.stock), -1]);
      for (const t of sp.terms || []) out.push([refOf(m, t.stock), Math.sign(t.k) || 1]);
      for (const ef of sp.effects || []) out.push([refOf(m, ef.stock), 0]);
      return out;
    }
    const x = e.inputs && e.inputs[0];
    if (x && e.form === "proportional") out.push([x, 1]);
    if (x && e.form === "linear") out.push([x, Math.sign(e.params.k) || 1]);
    return out;
  }

  const shorten = (t, n = 44) => (t.length > n ? t.slice(0, n - 2) + "…" : t);
  // a caption in at most two lines of ``n`` characters, cut only after the second, at a word: [line, line?]
  function wrap(text, n) {
    const words = String(text).split(/\s+/).filter(Boolean), out = [""];
    for (const w of words) {
      const cur = out[out.length - 1], next = cur ? cur + " " + w : w;
      if (next.length <= n || !cur) out[out.length - 1] = next;
      else if (out.length < 2) out.push(w);
      else { out[1] = out[1] + "…"; return out; }
    }
    if (out[out.length - 1].length > n) out[out.length - 1] = out[out.length - 1].slice(0, n - 1).trimEnd() + "…";
    return out[0] ? (out.length > 1 ? out : out[0]) : "";
  }
  // the machines a flow's label names: one, only when its hypothesis beats the next by a clear
  // MARGIN and chance alone would not half make it ("worker?"); hypotheses within the margin of each
  // other: "3 machines?", said once under the diagram for every flow they share (``untoldGroups``:
  // "3 machines: timing cannot tell them apart"); otherwise, and on a flow with too few events to
  // fit, nothing. Never a percentage on the diagram, and never one name as a fact.
  const MARGIN = 0.15, CHANCE = 0.3;
  function machineLabel(f, nameOf = (id) => id) {
    const hs = (f.machines || []).filter((h) => h.machine && h.confidence != null).sort((a, b) => b.confidence - a.confidence);
    if (!hs.length) return "";
    if (typeof Evidence !== "undefined" && Evidence.tooFew(f)) return "";     // too few events to fit: no machine either (evidence-text.js)
    const near = untoldOf(f);
    if (near.length > 1) return `${near.length} machines?`;
    return (hs[0].chance ?? 0) > CHANCE ? "" : `${nameOf(hs[0].machine)}?`;
  }
  // the machines within the margin of a flow's best hypothesis, when more than one: [] otherwise
  function untoldOf(f) {
    const hs = (f.machines || []).filter((h) => h.machine && h.confidence != null).sort((a, b) => b.confidence - a.confidence);
    if (!hs.length || (typeof Evidence !== "undefined" && Evidence.tooFew(f))) return [];
    const near = hs.filter((h) => hs[0].confidence - h.confidence < MARGIN).map((h) => h.machine);
    return near.length > 1 ? near : [];
  }
  // the groups of machines timing cannot tell apart on the flows drawn, each once with its flows:
  // [{machines, flows}] (the diagram's labels say only "3 machines?")
  function untoldGroups(flows) {
    const by = new Map();
    for (const f of flows) { const ms = untoldOf(f); if (!ms.length) continue; const k = [...ms].sort().join("\u0000");
      by.set(k, { machines: [...ms].sort(), flows: [...((by.get(k) || {}).flows || []), f.id] }); }
    return [...by.values()];
  }

  // the graph: {nodes, edges, causal, flowEdge, flows, acc, rare}. ``opts``: showAll (flows with no
  // events, and rare ones), showAcc (stocks that only fill that nothing shown feeds), keep (stock ids
  // never hidden), keepFlows (flow ids drawn with no events), rare (f -> true for a flow with too few
  // events to fit: not drawn unless showAll; ``rare`` is those left out), and the colours
  // (stockColor(id)). A flow is drawn in one neutral ink, never in a machine's colour: which machine
  // moves it is a hypothesis (its label says it, when one stands out).
  function build(m, opts = {}) {
    const stockColor = opts.stockColor || (() => "#cbd5e1");
    const byMachine = Object.fromEntries((m.machines || []).map((x) => [x.id, x]));
    // ``keepFlows``: flow ids drawn whatever their events (expected ones: an expectation stays on the diagram)
    const isRare = (f) => !!(opts.rare && opts.rare(f));
    // a rare flow that moves now (``opts.moving``) and feeds or drains a stock is drawn, dashed and
    // unfitted: the main input, running now, is never hidden for having few events in the fit window
    const movingRare = (f) => isRare(f) && !!(opts.moving && opts.moving(f)) && !!(f.from || f.to);
    const shown = (f) => ((f.current && f.current.quality && f.current.quality.events > 0) && (!isRare(f) || movingRare(f))) || opts.showAll || !!(opts.keepFlows && opts.keepFlows.has(f.id));
    // a stock that only fills is where another stock's material ends up (the orders delivered) when a
    // flow shown drains a stock into it: drawn. One that no such flow feeds (the event bus's
    // length, a tally) starts hidden, with its flows; ``acc`` is those.
    const filling = new Set(m.stocks.filter((s) => s.evidence && s.evidence.accumulator).map((s) => s.id));
    const fed = new Set(m.flows.filter((f) => shown(f) && f.from && filling.has(f.to) && !filling.has(f.from)).map((f) => f.to));
    // ``keep``: stocks never hidden (one a declared part is placed beside)
    const acc = new Set([...filling].filter((id) => !fed.has(id) && !(opts.keep && opts.keep.has(id))));
    const hiddenStock = (id) => !opts.showAcc && acc.has(id);
    const flows = m.flows.filter((f) => shown(f) && !hiddenStock(f.from) && !hiddenStock(f.to));
    const nodes = [], edges = [], causal = [], flowEdge = {};
    const has = (id) => nodes.some((n) => n.id === id);
    const nm = names(m).stocks;
    for (const s of m.stocks.filter((s) => !hiddenStock(s.id))) { const { name, family, about, generated, byTags } = nm[s.id] || { name: s.name, family: "" };
      // a stepped stock's caption is its sentence, cut to the box (the drawer and the hover say it all);
      // a stock a declaration names, the name it would have had (its identifier)
      const fit = Math.max(180, s.name.length * 7 + 30) / 6.2 - 2, cap = generated ? wrap(generated, fit) : (!byTags && family) || wrap(about || "", fit);
      // its tags, chips under the box (sd/titles.py), after "exact by definition"
      const chips = tagsOf(s).map((t) => ({ text: t, cls: "ng-t-tag", below: true, row: true }));
      nodes.push({ id: "s:" + s.id, kind: "box", sid: s.id, label: name, lines: [name], caption: cap,
      // sized by the full name, as before the short names: the layout search is sensitive to box
      // sizes (narrower boxes break the layout tests' fixtures), which is its own open problem
      w: Math.max(180, s.name.length * 7 + 30), h: Array.isArray(cap) && cap.length > 1 ? 102 : 92, dashed: !!(s.evidence && s.evidence.hidden), color: stockColor(s.id),
      fill: "#0b0e14", charge: -1600, sub: " ",
      // a stock that holds by construction (its level is the count of its own moves): tagged, so it
      // never reads as trusted as one the evidence balances
      // (under the box: above it is where a version's marks go)
      ...(byConstruction(s) || chips.length ? { tags: [...(byConstruction(s) ? [{ text: "exact by definition", ...(typeof Evidence !== "undefined" ? { title: Evidence.BY_CONSTRUCTION } : {}), cls: "ng-t-bc", below: true }] : []), ...chips] } : {}) }); }
    // a place no stock was kept for, drawn named and unmeasured: with its level when its count holds
    // items now (``discovery.held_levels``), so the diagram never leaves out what a pile holds
    const placeBox = (v, p) => { const id = "p:" + v, title = placeTitle(v, p), lv = p.level != null ? `${count(p.level)} now · ` : "";
      if (!has(id)) nodes.push({ id, kind: "box", place: v, label: title, lines: [title], caption: lv ? `${count(p.level)} now · not a stock` : "not a stock",
        sub: p.why ? shorten(p.why, 40) : " ", why: (lv ? `holds ${count(p.level)} now; ` : "") + (p.why || ""), series: p.series, level: p.level, inert: true, w: Math.max(160, title.length * 6.6 + 30), h: 62, dashed: true, color: "#64748b", fill: "#0e1118", charge: -600, textColor: "var(--text2)" }); return id; };
    for (const f of flows) {
      // in the causal graph used for loops, a flow is a node between its ends ("f:<id>")
      const col = FLOW_INK, v = "f:" + f.id, e = f.current || {};
      // an end its counter names as a place (its from/to label) where discovery kept no stock is drawn
      // as that place, named and unmeasured (``opts.place(value)``: {title, why}); only the counter's
      // own outside ends (<start>, <end>) are clouds: one per stock and direction, named for the stock
      // (flow ids change between discoveries; a stock's place outside does not), just outside the
      // frame by its stock (tethered)
      const cl = (f.counter && f.counter.labels) || {};
      const placeEnd = (v) => (v != null && !/^<.*>$/.test(String(v)) ? (opts.place || ((x) => placeOf(m, x)))(String(v)) : null);
      // a place a drawn stock's own series measures is that stock: drawn as one box, never twice
      const stockAt = (v) => { const st = v != null && m.stocks.find((x) => !hiddenStock(x.id) && x.series && Object.values(x.series.labels || {}).includes(String(v))); return st ? "s:" + st.id : null; };
      const sFrom = !f.from ? stockAt(cl.from) : null, sTo = !f.to ? stockAt(cl.to) : null;
      const pFrom = !f.from && !sFrom ? placeEnd(cl.from) : null, pTo = !f.to && !sTo ? placeEnd(cl.to) : null;
      // named as a stock of it would be (its level series' title), else its value in words ("sail_check (waiting)");
      // ``inert``: no drawer of its own, so it is no tab stop (its tooltip says why it is no stock)
      const placeNode = (v, p) => placeBox(v, p);
      const outsideName = (v) => (/^<(.*)>$/.test(String(v || "")) ? "outside" : "");     // one word for one idea, never "the start"
      const src = f.from ? "s:" + f.from : sFrom || (pFrom ? placeNode(cl.from, pFrom) : "c:in:" + (f.to || f.id));
      const dst = f.to ? "s:" + f.to : sTo || (pTo ? placeNode(cl.to, pTo) : "c:out:" + (f.from || f.id));
      if (!f.from && !sFrom && !pFrom && f.to && !has(src)) nodes.push({ id: src, kind: "cloud", charge: -20, tether: "s:" + f.to, label: outsideName(cl.from) });
      if (!f.to && !sTo && !pTo && f.from && !has(dst)) nodes.push({ id: dst, kind: "cloud", charge: -20, tether: "s:" + f.from, label: outsideName(cl.to) });
      const fe = `${src}>${dst}:${f.id}`, outside = src.startsWith("c:") || dst.startsWith("c:"), few = isRare(f);
      // a flow with too few events to fit, drawn because it feeds or drains a drawn stock: dashed, no equation
      edges.push({ id: fe, source: src, target: dst, color: col, width: few ? 1.4 : outside ? 2 : 3.4, distance: outside ? 60 : 230, strength: outside ? 0.05 : 0.6,
        cls: (outside ? "ng-outside" : "") + (few ? " ng-unfitted" : ""), fid: f.id, flowPart: true, bend: outside ? 10 : 18, labelMuted: true, ...(few ? { dash: "4 4" } : {}),
        label: few ? ["too few events to fit"] : [shorten(eqText(m, f, true)), machineLabel(f, (id) => (byMachine[id] || {}).name || id)] });
      flowEdge[v] = fe;
      if (f.to) causal.push({ source: v, target: "s:" + f.to, sign: 1 });
      if (f.from) causal.push({ source: v, target: "s:" + f.from, sign: -1 });
      for (const [x, sign] of readsWithSign(m, f)) {
        const isInput = x.startsWith("input:"), name = isInput ? x.slice(6) : x, node = (isInput ? "i:" : "s:") + name;
        if (!isInput && hiddenStock(name)) continue;
        // a measured level the rate reads that no counters balance: an auxiliary, inside the system
        // like everything but the clouds, drawn round so it does not read as a stock
        if (isInput && !has(node)) nodes.push({ id: node, kind: "box", input: name, label: name.replace(/_/g, " "), lines: [name.replace(/_/g, " ")],
          w: Math.max(140, name.length * 6.2 + 30), h: 52, rx: 26, color: "#64748b", fill: "#0e1118", charge: -600, sub: " " });
        if (sign !== 0) causal.push({ source: node, target: v, sign });
        // an influence: a dashed link to the middle of the flow it drives (not a flow's plain dependence on its own source)
        const plain = !isInput && name === f.from && (e.form === "proportional" || (e.spec && e.spec.form === "proportional"));
        if (!plain && has(node)) edges.push({ id: `${node}>${fe}:info`, source: node, toEdge: fe, color: col, dashed: true, width: 1.4,
          sign: (sign < 0 ? "−" : sign > 0 ? "+" : "~") + (correlational(m, f) ? " untested" : ""), bend: 36, fid: f.id });
      }
    }
    // a pile that holds items and is no stock, which no drawn flow reaches: drawn as its place all the same
    for (const [k, h] of Object.entries(((m.discovery || {}).held_levels) || {})) {
      if (!h || h.place == null || has("p:" + h.place) || m.stocks.some((x) => x.series && Object.values(x.series.labels || {}).includes(String(h.place)))) continue;
      const p = placeOf(m, String(h.place)); placeBox(String(h.place), p.series === k ? p : { ...p, level: h.level });
    }
    // stocks with flows from or to outside are drawn toward the frame's edge, so those stubs stay short
    for (const n of nodes) if (n.sid) n.edgeward = edges.some((e) => e.flowPart && ((e.target === n.id && e.source.startsWith("c:")) || (e.source === n.id && e.target.startsWith("c:"))));
    const places = nodes.filter((n) => n.place).map((n) => n.label);
    const rare = m.flows.filter((f) => isRare(f) && !flows.includes(f) && !(f.current && f.current.quality && !f.current.quality.events));
    return { nodes, edges, causal, flowEdge, flows, acc, rare, places };
  }
  const FLOW_INK = "#a3adbd";
  const byConstruction = (s) => !!(s.evidence && (s.evidence.by_construction || (s.evidence.trust && s.evidence.trust.kind === "by_construction")));

  // a place a flow's counter names (its from or to label value) where discovery kept no stock: its
  // title and why it was left out, from the level series that measures it (a left-out series carrying
  // that value); the value itself when none does. Names come from the series' labels and titles only
  function placeOf(m, v) {
    const d = (m && m.discovery) || {}, lo = d.left_out || {}, titles = d.titles || {};
    const k = Object.keys(lo).find((key) => key.includes(`="${v}"`) && !/_total\{/.test(key) && titles[key] && !/^age of /.test(titles[key]));
    const held = k && (d.held_levels || {})[k];
    return k ? { title: titles[k], why: lo[k], series: k, ...(held ? { level: held.level } : {}) } : { title: v, why: "no series measures it" };
  }
  // where a flow comes from or goes (``which``: "from" or "to"), as the diagram draws it: its stock; a
  // stock whose series measures the place its counter names; that place, "(not a stock)"; or, only
  // where the arrow ends at a cloud, "outside"
  function endName(m, f, which) {
    if (!f) return "outside";
    if (f[which]) return stockName(m, f[which]);
    const v = ((f.counter || {}).labels || {})[which];
    if (v == null || /^<.*>$/.test(String(v))) return "outside";
    const st = (m.stocks || []).find((x) => x.series && Object.values(x.series.labels || {}).includes(String(v)));
    if (st) return stockName(m, st.id);
    const p = placeOf(m, String(v));
    return `${placeTitle(v, p)} (${p.level != null ? `${count(p.level)} now, ` : ""}not a stock)`;
  }
  // a place's name, as a stock of it is named: its level series' title, else its value in words
  // ("sail_check.waiting": "sail_check (waiting)"), never the raw value
  function placeTitle(v, p) {
    if (p && p.title && p.title !== v) return p.title;
    const parts = String(v).split(".").filter(Boolean);
    return parts.length > 1 ? `${parts[0]} (${parts.slice(1).join(", ")})` : String(v);
  }
  return { tagsOf, tagsHtml, namedBy, build, eqText, readsWithSign, readName, refOf, stockName, flowName, names, seriesName, sameAs, drawnApart, nice, num, correlational, untestedText, drivers, machineLabel, untoldGroups, placeTitle, placeOf, endName, wrap, UNTESTED, FLOW_INK, byConstruction };
});
