// The ladder's comparison diagrams, shared by the ladder page (ladder.js, ladder-board.js) and the
// strategy page (ladder-strategy.js): the true model, the found one and their differences, all in
// the truth's layout (sharedLayout), drawn with SDDiagram; and the differences as a list (diffHtml).
//
//   diagrams(c, cmp, found)     the three diagrams' models {tD, fD, dD, vias, alias}
//   sharedLayout(c, found, vias, cols, layout?)   one layout from the truth, the found model's own stocks placed near theirs
//   drawPair(c, r, svgTrue, svgFound, cmp, cols, svgDiff)   draw them; returns {vb, alias, cmp}
//   drawRepairs(c, r, svg, repairs, opts)   only what would make the found model right (the strategy page)
(function (root) {
  "use strict";
  const D = root.SDDiagram, L = root.SDLadder, fmt = L.fmt;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const BOX = { w: 96, h: 46 };
  const LAYOUT = { box: BOX, colw: BOX.w + 150, rowh: BOX.h + 100 };
  // git colours (the user, 2026-10-21): the true model is the original, the found model the change. Green: added by the change
  // (in the found model, not the truth); red: removed by it (in the truth, not found); amber: in both, values wrong; grey: unchanged
  const CLS_COLOR = { ok: "var(--muted)", wrong: "var(--warn)", missing: "var(--bad)", missed: "var(--bad)", spurious: "var(--good)", equiv: "var(--eq)", small: "var(--muted)", unscored: "var(--muted)", plain: "var(--fg)", claim: "var(--warn)" };
  const CLS_WORD = { ok: "found, right", wrong: "found, a number off", missing: "missed", missed: "missed", spurious: "spurious", equiv: "equivalent", small: "too small to count", unscored: "not scored", claim: "a boundary claim (no boundary declared)" };

  // The three diagrams' models, from the comparison, all in the truth's layout: the true model and
  // the found one each plain (neither is marked: the truth is the reference), and the differences:
  // every flow of either model marked ✓ matched, ~ a number off, − missed, + invented, ≈ equivalent.
  function diagrams(c, cmp, found) {
    const truth = c.model, measured = new Set(cmp.measured);
    // the case's declared boundary (2026-10-20): {stock: {in: [kinds], out: [kinds]}}, or null (undeclared)
    const B = c.boundary || null;
    const sideOf = (f) => (!f.from && f.to ? [f.to, "in"] : f.from && !f.to ? [f.from, "out"] : null);
    const kindAt = (f) => { const sd = sideOf(f); return sd && B && B[sd[0]] && (B[sd[0]][sd[1]] || [])[0]; };
    // an outside flow at an unmeasured stock is inside the boundary unless the model's flows carry it on to a measured stock
    // on a side the case does not declare (the scorer's rule: score.py, parts.outside_ends); "hidden" then (2026-10-21)
    const reached = (flows, start, side) => {
      const seen = new Set(), todo = [start], hit = new Set();
      while (todo.length) {
        const x = todo.pop(); if (seen.has(x)) continue; seen.add(x);
        if (measured.has(x)) { hit.add(x); continue; }
        flows.forEach((g) => { if (g.from && g.to) { if (side === "in" && g.from === x) todo.push(g.to); if (side === "out" && g.to === x) todo.push(g.from); } });
      }
      return hit;
    };
    const crossing = (f, flows) => {
      const sd = sideOf(f);
      if (!sd) return null;
      if (B && kindAt(f)) return "declared";
      if (!measured.has(sd[0]) && flows) {
        const hit = [...reached(flows, sd[0], sd[1])];
        if (!hit.length) return "hidden";
        if (B && hit.every((st) => B[st] && (B[st][sd[1]] || []).length)) return "declared";
      }
      return !B ? "claim" : "invented";
    };
    const readsOf = (f, extra) => [...L.readers(f)].filter((x) => x !== "const" && x !== f.from).map((stock) => ({ stock })).concat(extra || []);
    const extrasOf = (f, cls) => [...(f.effects || []).map((e) => ({ stock: e.stock, label: "effect", dash: "5 4", cls })), ...(f.uses || []).map((u) => ({ stock: u.stock, label: `uses ${fmt(+u.per)}`, dash: "1 3", cls }))];
    const tStocks = truth.stocks.map((s) => ({ id: s.id, name: s.id, dashed: !measured.has(s.id), sub: measured.has(s.id) ? "" : "not measured", title: `${s.id}: starts at ${fmt(s.initial)}${measured.has(s.id) ? "" : ", not measured"}` }));
    const tD = {
      stocks: tStocks,
      flows: cmp.truth.map((t) => ({ from: t.flow.from, to: t.flow.to, cls: "plain", cloud: kindAt(t.flow), label: t.flow.id, label2: short2(L.rateText(t.flow.rate)),
        title: `${t.flow.id}: ${t.equation}`, reads: readsOf(t.flow, extrasOf(t.flow, "plain")) })),
    };
    // a stock only the found model names (an inferred one) may have a long id: short names in the drawing
    const alias = {};
    cmp.extraStocks.forEach((id, i) => { alias[id] = id.length <= 6 ? id : `h${i + 1}`; });
    const al = (t) => cmp.extraStocks.reduce((acc, id) => acc.split(id).join(alias[id]), t);
    const usedH = new Set(found.flatMap((f) => [f.from, f.to]).filter((x) => x && !measured.has(x)));   // a true hidden stock the found model has (its own, matched: scores.hidden_match)
    const fStocks = truth.stocks.filter((s) => measured.has(s.id) || usedH.has(s.id))
      .map((s) => (measured.has(s.id) ? { id: s.id, name: s.id } : { id: s.id, name: s.id, dashed: true, sub: "hidden, matched", title: `${s.id}: the found model's own hidden stock, matched to the truth's by its level` }))
      .concat(cmp.extraStocks.map((id) => ({ id, name: alias[id], dashed: true, sub: "inferred", title: `${alias[id]}: ${id}, a stock the found model infers (not measured)` })));
    const fFlows = [], vias = {}, viaOf = new Map(), foundFlows = cmp.found.map((x) => x.flow);
    const rateLabel = (f) => short2(al(f.inflow && f.inflow.length > 1 ? L.equation(f).split(" on average")[0] : f.byTime && f.byTime.length > 1 ? `${L.rateText(f.rate)} (by time)` : L.rateText(f.rate)));
    cmp.found.forEach((x, k) => {
      const f = x.flow, cr = crossing(f, foundFlows);
      const common = { cls: cr === "invented" ? "spurious" : cr === "claim" ? "claim" : "plain", cloud: kindAt(f), label: rateLabel(f),
        label2: cr === "invented" ? "invented boundary" : cr === "claim" ? "boundary claim" : "", title: `${L.equation(f)}${f.note ? "\n" + f.note : ""}` };
      if (f.via) {
        const id = `via:${k}`;
        vias[id] = { from: f.from, to: f.to }; viaOf.set(x, id);
        fStocks.push({ id, name: "hidden", dashed: true, sub: `delay ${fmt(+f.via.delay)}` });
        fFlows.push({ ...common, from: f.from || f.via.echo, to: id, reads: [] }, { ...common, label: "", from: id, to: f.to, reads: [] });
      } else fFlows.push({ ...common, from: f.from, to: f.to, reads: readsOf(f, extrasOf(f, "plain")) });
    });
    // the differences
    const off = (t) => t.parts.filter((p) => p.found && !p.ok && p.kind !== "effect").map((p) => `${fmt(p.true)} → ${fmt(p.found_value)}`).join(", ");
    const missedParts = (t) => t.parts.filter((p) => !p.found).map((p) => L.partName(p.key).replace(/^the /, "")).join(", ");
    const dFlows = cmp.truth.map((t, i) => {
      const sign = { ok: "", wrong: "~", missing: "−", equiv: "≈" }[t.cls] ?? "·", cls = t.cls === "missing" ? "missed" : t.cls === "unscored" ? "plain" : t.cls;
      const label2 = t.cls === "wrong" ? (off(t) || `missed ${missedParts(t)}`) : t.cls === "missing" ? `missed ${short2(L.rateText(t.flow.rate))}` : short2(L.rateText(t.flow.rate));
      return { src: `truth:${i}`, from: t.flow.from, to: t.flow.to, cls, cloud: kindAt(t.flow), dashed: t.cls === "missing", thin: t.cls === "ok" || t.cls === "unscored",
        label: `${sign}${t.cls === "missing" && kindAt(t.flow) ? " (declared, not used)" : ""}`, label2,
        title: `${t.flow.id}: ${t.equation}\n${CLS_WORD[t.cls] || t.cls}${t.notes.length ? "\n" + t.notes.join("\n") : ""}`,
        reads: readsOf(t.flow, t.reads.map((x) => ({ stock: x.stock, label: x.kind === "uses" ? `uses ${fmt(x.per)}` : "effect", dash: x.kind === "uses" ? "1 3" : "5 4", cls: x.cls === "missing" ? "missed" : x.cls || "plain" }))) };
    });
    const dStocks = [...tStocks, ...fStocks.filter((s) => !tStocks.some((t) => t.id === s.id)).map((s) => ({ ...s }))];   // copies: the diff colours them
    cmp.found.forEach((x, k) => {
      const src = `found:${k}`;
      const f = x.flow, invented = x.cls === "spurious", reread = x.cls === "equiv" && !x.parts.length, extra = x.spurious.length && x.parts.length;
      if (!invented && !reread && !extra) return;
      const cr = crossing(f, foundFlows);
      const cls = reread || (x.cls === "equiv") ? "equiv" : cr === "claim" && !extra ? "claim" : "spurious";
      const label = reread ? "≈ read as" : extra ? "+ extra term" : cr === "invented" ? "+ invented boundary" : cr === "claim" ? "? boundary claim" : "+ invented";
      const label2 = extra ? x.spurious.map((p) => `${p.reader || ""} ${fmt(p.value)}`.trim()).join(", ") : rateLabel(f);
      const title = `${L.equation(f)}\n${x.notes.join("\n")}`;
      if (viaOf.has(x)) {
        const id = viaOf.get(x);
        dFlows.push({ src, cls, label, label2, title, from: f.from || f.via.echo, to: id, reads: [] }, { src, cls, label: "", from: id, to: f.to, reads: [] });
      } else dFlows.push({ src, cls, thin: !!extra, cloud: kindAt(f), label, label2, title, from: f.from, to: f.to, reads: readsOf(f, extrasOf(f, cls)) });
    });
    // a stock only the found model has (an inferred or hidden stage) takes the colour of the flows that
    // make it: red when every one of them is invented, the equivalent colour when one is a re-reading
    dStocks.forEach((st) => {
      if (tStocks.some((t) => t.id === st.id)) return;
      const touch = dFlows.filter((f) => f.from === st.id || f.to === st.id);
      if (touch.length && touch.every((f) => f.cls === "spurious")) st.cls = "spurious";
      else if (touch.some((f) => f.cls === "equiv")) st.cls = "equiv";
    });
    return { tD, fD: { stocks: fStocks, flows: fFlows }, dD: { stocks: dStocks, flows: dFlows }, vias, alias };
  }
  const short2 = (s) => (s.length > 30 ? s.slice(0, 29) + "…" : s);

  function maxCols() { return innerWidth >= 1150 ? 3 : innerWidth >= 600 ? 2 : 1; }
  // one layout for both sides, made from the truth alone (so a case always looks the same); a stock
  // only the found model names (an inferred hidden stock, or a flow's hidden stock) sits where the
  // true hidden stock between the same two stocks sits, or below the stocks it connects
  function sharedLayout(c, found, vias, cols, lay = LAYOUT) {
    const pos = D.layout(c.model.stocks.map((s) => s.id), c.model.flows, { ...lay, maxCols: cols || maxCols() });
    const truthIds = new Set(c.model.stocks.map((s) => s.id)), taken = new Set();
    const between = (a, b) => c.model.stocks.find((s) => s.measured === false && !taken.has(s.id) && c.model.flows.some((f) => f.to === s.id && f.from === a) && c.model.flows.some((f) => f.from === s.id && f.to === b));
    let k = 0;
    const place = (id, a, b) => {
      const h = between(a, b);
      if (h && pos[h.id]) { taken.add(h.id); pos[id] = { ...pos[h.id] }; return; }
      const pa = pos[a] || pos[b], pb = pos[b] || pa;
      if (!pa) { pos[id] = { x: k * lay.colw, y: -lay.rowh }; k++; return; }
      pos[id] = { x: Math.round((pa.x + pb.x) / 2 + (k % 2 ? 40 : 0)), y: Math.max(pa.y, pb.y) + lay.rowh * (1 + Math.floor(k / 2)) }; k++;
    };
    const extras = [...new Set(found.filter((f) => !f.via).flatMap((f) => [f.from, f.to]).filter((x) => x && !truthIds.has(x)))];
    extras.forEach((id) => {
      const a = (found.find((f) => f.to === id && f.from && truthIds.has(f.from)) || {}).from;
      const b = (found.find((f) => f.from === id && f.to && truthIds.has(f.to)) || {}).to;
      place(id, a, b);
    });
    Object.entries(vias || {}).forEach(([id, v]) => place(id, v.from, v.to));
    return pos;
  }

  // the true model and the found one, drawn the same way into two svgs; returns {vb, alias, cmp}
  // the true model, the found one and their differences, drawn the same way into three svgs (the
  // differences only once there is a result); returns {vb, alias, cmp}
  function drawPair(c, r, svgTrue, svgFound, cmp, cols, svgDiff) {
    const found = L.foundOf(r);
    cmp = cmp || L.compare(c.model, found, r && r.scores);
    const { tD, fD, dD, vias, alias } = diagrams(c, cmp, found);
    const pos = sharedLayout(c, found, vias, cols);
    const bs = [D.bounds(pos, tD.flows, BOX), D.bounds(pos, r ? fD.flows : [], BOX), D.bounds(pos, r ? dD.flows : [], BOX)];
    const x0 = Math.min(...bs.map((b) => b.x)), y0 = Math.min(...bs.map((b) => b.y));
    const vb = { x: x0, y: y0, w: Math.max(...bs.map((b) => b.x + b.w)) - x0, h: Math.max(...bs.map((b) => b.y + b.h)) - y0 };
    const color = (cls) => CLS_COLOR[cls] || "var(--fg)";
    const outline = { label: c.boundary ? "system boundary" : "boundary not declared" };
    const o = { box: BOX, viewBox: { ...vb, y: vb.y - 26, h: vb.h + 26 }, color, maxScale: 1.3, outline };
    D.draw(svgTrue, tD, pos, o);
    D.draw(svgFound, r ? fD : { stocks: fD.stocks, flows: [] }, pos, o);
    if (svgDiff) {
      D.draw(svgDiff, r ? focus(dD, tStockIds(c), cmp.api && cmp.api.hunk) : { stocks: dD.stocks, flows: [] }, pos, o);
      const cap = svgDiff.closest("figure") && svgDiff.closest("figure").querySelector("figcaption");
      if (cap && r) cap.textContent = diffStat(cmp);
    }
    return { vb, alias, cmp };
  }

  // only the differences, in the truth's layout (the Now page's running cards): before a result, the true stocks alone.
  // Returns {caption, alias}.
  function drawDiff(c, r, svg, cmp, cols) {
    const found = L.foundOf(r);
    cmp = cmp || L.compare(c.model, found, r && r.scores);
    const { dD, vias, alias } = diagrams(c, cmp, found);
    const pos = sharedLayout(c, found, vias, cols);
    const vb = D.bounds(pos, r ? dD.flows : [], BOX);
    const color = (cls) => CLS_COLOR[cls] || "var(--fg)";
    D.draw(svg, r ? focus(dD, tStockIds(c), cmp.api && cmp.api.hunk) : { stocks: dD.stocks, flows: [] }, pos,
      { box: BOX, viewBox: { ...vb, y: vb.y - 26, h: vb.h + 26 }, color, outline: { label: c.boundary ? "system boundary" : "boundary not declared" } });
    return { caption: r ? diffStat(cmp) : "", alias };
  }

  // The differences show only what changed, like a git diff's hunks (the user, 2026-10-21): a changed flow (removed, added,
  // value wrong, equivalent, a claim) with the stocks at its ends; a stock only the found model has, with every flow into or
  // out of it. Everything else stays where it is (one layout for all three panels), faded, without labels.
  const CHANGED = new Set(["missed", "missing", "spurious", "wrong", "equiv", "claim"]);
  const tStockIds = (c) => new Set(c.model.stocks.map((s) => s.id));
  // hunk: the server's (diff.py), when the comparison came from it: what to draw at full strength, by flow and stock.
  function focus(dD, trueIds, hunk) {
    if (hunk) {
      const flows = new Set(hunk.flows.map((h) => `${h.side}:${h.index}`)), stocks = new Set(hunk.stocks);
      return { stocks: dD.stocks.map((s) => ({ ...s, faded: !stocks.has(s.id) })), flows: dD.flows.map((f) => ({ ...f, faded: !flows.has(f.src) })) };
    }
    const keep = new Set(), newStocks = new Set(dD.stocks.filter((s) => !trueIds.has(s.id)).map((s) => s.id));
    const shown = (f) => CHANGED.has(f.cls) || newStocks.has(f.from) || newStocks.has(f.to);
    dD.flows.forEach((f) => { if (shown(f)) { if (f.from) keep.add(f.from); if (f.to) keep.add(f.to); } });
    newStocks.forEach((id) => keep.add(id));
    return { stocks: dD.stocks.map((s) => ({ ...s, faded: !keep.has(s.id) })), flows: dD.flows.map((f) => ({ ...f, faded: !shown(f) })) };
  }
  // "Differences: 2 removed · 1 added · 1 value wrong", like git diff --stat
  function diffStat(cmp) {
    if (cmp.api) return cmp.api.caption;
    const n = { missed: 0, spurious: 0, wrong: 0, equiv: 0 };
    L.diffLines(cmp).forEach((l) => { if (l.cls in n) n[l.cls] += 1; });
    const parts = [n.missed && `${n.missed} removed`, n.spurious && `${n.spurious} added`, n.wrong && `${n.wrong} value${n.wrong > 1 ? "s" : ""} wrong`, n.equiv && `${n.equiv} equivalent`].filter(Boolean);
    return `Differences: ${parts.length ? parts.join(" · ") : "none"}`;
  }
  // The comparison for a result, its verdicts from the server's diff (GET /api/ladder/diff/...; diff.py), so the page and
  // `sdlab-ladder diff` never disagree. Cached by result id (a stored result never changes); if the endpoint fails, the
  // page's own comparison (L.compare), said so in the console.
  const DIFFS = new Map();
  async function compareOf(c, r) {
    const found = L.foundOf(r), cmp = L.compare(c.model, found, r && r.scores);
    if (!r || r.id === undefined || r.id === null || !r.variant || !r.strategy) return cmp;
    let dif = DIFFS.get(r.id);
    if (!dif) {
      try {
        const res = await fetch(`/api/ladder/diff/${encodeURIComponent(c.id)}/${encodeURIComponent(r.variant)}/${encodeURIComponent(r.strategy)}?result=${encodeURIComponent(r.id)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        dif = await res.json();
        DIFFS.set(r.id, dif);
      } catch (e) {
        console.warn(`diff of result ${r.id}: the server's diff failed (${e.message}); using the page's own comparison`);
        return cmp;
      }
    }
    return L.withDiff(cmp, dif, r.scores);
  }
  const LEGEND = `<span class="d-missed">− removed: in the true model, not the found one</span> · <span class="d-spurious">+ added: in the found model, not the true one</span> · <span class="d-wrong">~ in both, values wrong (true → found)</span> · <span class="d-ok">grey: unchanged</span> · <span class="d-equiv">≈ equivalent reading</span><br><span class="muted">outside: ☁ solid measured input · ☁ dashed rate estimated · <span class="d-spurious">green: invented boundary</span> (none declared there) · <span class="d-wrong">amber: boundary claim</span> (no boundary declared)</span>`;
  // the differences as a list, one line per flow
  function diffHtml(cmp) {
    const lines = L.diffLines(cmp), same = (l) => ["ok", "small", "plain", "unscored"].includes(l.cls);
    const row = (l) => `<div class="dline d-${l.cls}" role="listitem"><span class="dsign">${esc(same(l) ? "" : l.sign)}</span><span class="dends">${esc(l.ends)}</span><span class="dtrue">${esc(l.truth)}</span><span class="dnote">${esc(l.note)}</span></div>`;
    const changed = lines.filter((l) => !same(l)), kept = lines.filter(same);
    if (!lines.length) return '<div class="muted small">nothing to compare</div>';
    return `<div class="dlist" role="list">${changed.map(row).join("") || '<div class="muted small">No differences.</div>'}</div>`
      + (kept.length ? `<details class="dsame"><summary class="small muted">${kept.length} unchanged</summary><div class="dlist" role="list">${kept.map(row).join("")}</div></details>` : "");
  }

  // The repairs as a diagram (the strategy page): only what matters. The truth's layout; right flows
  // faint, a flow with a number off labelled with found − true, a missed flow dashed (add), an
  // invented one (remove), an equivalent reading in its own colour. repairs: repairs.py's items.
  const REPAIR_COLOR = { faint: "var(--faint)", wrong: "var(--warn)", add: "var(--add)", remove: "var(--bad)", equiv: "var(--eq)", plain: "var(--fg)" };
  function drawRepairs(c, r, svg, rep, opts = {}) {
    const found = L.foundOf(r).map((f) => (f.via ? { ...f, via: null, note: "via a hidden stock" } : f));
    const cmp = L.compare(c.model, found, r && r.scores);
    const items = (rep && rep.items) || [];
    const measured = new Set(cmp.measured);
    const keysOf = (ps) => new Set((ps || []).map((p) => p.key));
    const about = (ps) => { const ks = keysOf(ps); return items.filter((it) => (it.key && ks.has(it.key)) || (it.keys || []).some((k) => ks.has(k))); };
    const readsOf = (f) => [...L.readers(f)].filter((x) => x !== "const" && x !== f.from).map((stock) => ({ stock }));
    const rate = (f) => short2(f.inflow && f.inflow.length > 1 ? L.equation(f).split(" on average")[0] : f.byTime && f.byTime.length > 1 ? `${L.rateText(f.rate)} (by time)` : L.rateText(f.rate));
    const stocks = c.model.stocks.map((s) => ({ id: s.id, name: s.id.length > 9 ? s.id.slice(0, 8) + "…" : s.id, dashed: !measured.has(s.id), title: s.id, cls: "faint" }))
      .concat(cmp.extraStocks.map((id, i) => ({ id, name: id.length <= 6 ? id : `h${i + 1}`, dashed: true, sub: "inferred", title: id, cls: "remove" })));
    const flows = [];
    cmp.truth.forEach((t) => {
      const f = t.flow, its = about(t.parts), title = `${f.id}: ${t.equation}${its.length ? "\n" + its.map((x) => x.text).join("\n") : ""}`;
      if (t.cls === "ok" || t.cls === "unscored") flows.push({ from: f.from, to: f.to, cls: "faint", thin: true, label: opts.full ? f.id : "", title, reads: [] });
      else if (t.cls === "missing") flows.push({ from: f.from, to: f.to, cls: "add", dashed: true, label: "+ add", label2: rate(f), title, reads: readsOf(f).map((x) => ({ ...x, cls: "add" })) });
      else if (t.cls === "equiv") flows.push({ from: f.from, to: f.to, cls: "equiv", dashed: t.parts.every((p) => !p.found), label: `≈ ${f.id}`, label2: its.map((x) => x.short).join(", ") || rate(f), title, reads: readsOf(f).map((x) => ({ ...x, cls: "equiv" })) });
      else flows.push({ from: f.from, to: f.to, cls: "wrong", label: opts.full ? f.id : "~ off", label2: its.filter((x) => x.type === "number").map((x) => x.short).join(", ") || its.map((x) => x.short).join(", "), title, reads: readsOf(f).map((x) => ({ ...x, cls: "wrong" })) });
    });
    cmp.found.forEach((x) => {
      const f = x.flow, its = about(x.spurious), title = `${L.equation(f)}${its.length ? "\n" + its.map((i) => i.text).join("\n") : ""}`;
      const eq = x.cls === "equiv";
      if (x.cls === "spurious" || (eq && !x.parts.length)) flows.push({ from: f.from, to: f.to, cls: eq ? "equiv" : "remove", label: eq ? "≈ read as" : "− remove", label2: rate(f), title, reads: readsOf(f).map((q) => ({ ...q, cls: eq ? "equiv" : "remove" })) });
      else if (x.spurious.length && x.parts.length) flows.push({ from: f.from, to: f.to, cls: eq ? "equiv" : "remove", thin: true, label: "− term", label2: its.map((i) => i.short.replace(/^remove /, "")).join(", "), title, reads: [] });
    });
    const pos = sharedLayout(c, found, {}, opts.cols || 3, opts.layout || LAYOUT);
    const box = (opts.layout || LAYOUT).box;
    const vb = D.bounds(pos, flows, box, opts.pad == null ? 50 : opts.pad);
    return D.draw(svg, { stocks, flows }, pos, { box, viewBox: vb, color: (k) => REPAIR_COLOR[k] || "var(--fg)", maxScale: opts.maxScale });
  }

  root.SDLadderDraw = { BOX, LAYOUT, CLS_COLOR, CLS_WORD, LEGEND, short2, maxCols, diagrams, sharedLayout, drawPair, drawDiff, diffHtml, drawRepairs, compareOf, focus, diffStat };
})(window);
