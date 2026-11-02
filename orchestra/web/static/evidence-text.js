// What the Dynamics tables say of the evidence behind the model: a stock's trust (sd/stocktrust.py),
// whether a flow had events enough to be fitted, and how many of a machine's events matched a
// flow's counter (sd/attribute.py). A missing number reads "—", never an error.
const Evidence = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fix = (v) => (typeof v === "number" && isFinite(v) ? v.toFixed(2) : "—");
  const BY_CONSTRUCTION = "holds by construction: its level is the count of its own moves, so the balance proves nothing";
  const byConstruction = (t) => !!t && t.kind === "by_construction";
  // the drawer's and "How it was found"'s line: " · trust 0.42 (low; weakest: …) · behaviour …"
  function trust(ev) {
    const t = (ev || {}).trust, b = t && t.behaviour;
    if (!t) return "";
    const head = byConstruction(t) ? ` · ${BY_CONSTRUCTION}`
      : ` · trust ${fix(t.score)} (${esc(t.level || "—")}${t.weakest ? `; weakest: ${esc(String(t.weakest).replace("_", " "))}` : ""})`;
    return head + (b ? ` · behaviour ${fix(b.score)} (${esc(b.level || "—")}; replay off by ${fix(b.error)} × its spread)` : "");
  }
  // the Stocks table's trust cell
  function trustCell(s) {
    const t = ((s || {}).evidence || {}).trust;
    if (!t) return '<span class="muted">—</span>';
    if (byConstruction(t)) return `<span class="muted">${BY_CONSTRUCTION}</span>`;
    return `<span class="num">${fix(t.score)}</span> <span class="muted">${esc(t.level || "")}</span>`;
  }
  // a stock by how far it can be trusted, in one word: "by construction" (its balance is its own
  // moves), "hidden" (no series measures it), "evidenced" (medium or high trust), else "weakly evidenced"
  function trustClass(s) {
    const ev = (s || {}).evidence || {}, t = ev.trust || {};
    if (byConstruction(t) || ev.by_construction) return "by construction";
    if (ev.hidden || t.kind === "unmeasured") return "hidden";
    return (t.score ?? 0) >= 0.5 ? "evidenced" : "weakly evidenced";
  }
  // "5 stocks: 0 evidenced, 3 by construction, 2 hidden" (evidenced always said, the rest when any)
  function trustCounts(stocks) {
    const by = {}; for (const s of stocks || []) { const c = trustClass(s); by[c] = (by[c] || 0) + 1; }
    const n = (stocks || []).length, parts = ["evidenced", "weakly evidenced", "by construction", "hidden"].filter((c) => c === "evidenced" || by[c]).map((c) => `${by[c] || 0} ${c}`);
    return { n, by, text: `${n} stock${n === 1 ? "" : "s"}: ${parts.join(", ")}`, none: !by.evidenced };
  }
  // a flow "fitted" from fewer events than this has no fit to speak of
  const MIN_EVENTS = 5;
  const eventsOf = (f) => ((((f || {}).current || {}).quality || {}).events ?? 0);
  const tooFew = (f) => !!(f && f.current && f.current.origin === "fitted" && eventsOf(f) < MIN_EVENTS);
  const tooFewText = (f) => `${eventsOf(f)} event${eventsOf(f) === 1 ? "" : "s"} in the window: too few to fit, no equation`;
  // a hypothesis' confidence beside its machine, " 87%": none on a flow with too few events to fit,
  // as its equation and fit show none
  const confidence = (f, h) => (tooFew(f) || (h || {}).confidence == null ? "" : ` ${Math.round(100 * h.confidence)}%`);
  // beside it, what chance alone would pair (sd/attribute.py's ``chance``): ", 41% by chance"
  const chance = (f, h) => (tooFew(f) || (h || {}).chance == null || !confidence(f, h) ? "" : `, ${Math.round(100 * h.chance)}% by chance`);
  // beside a hypothesis' confidence: how much of the evidence matched
  function matched(h) {
    const c = (h || {}).counts;
    if (!c || c.events == null) return "";
    const m = Math.round(c.events);
    if (h.paired && h.paired.events != null) return `${Math.round(h.paired.events * c.events)} of ${m} events matched`;
    if (h.test === "step by step" && h.equal_steps_moving === 1) return `${m} of ${m} events matched`;
    return `${m} events to ${Math.round(c.flow ?? 0)} counted`;
  }
  // a match in time cannot tell apart machines whose events all come within one step of each other
  // (sd/attribute.py: a hypothesis is a match in time): two or more hypotheses within MARGIN of the
  // best, or a best that chance alone would half make (CHANCE), says so once beside the flow's
  // hypotheses; then no one machine is named on the diagram (sd-graph.js)
  const MARGIN = 0.15, CHANCE = 0.3;
  const UNTOLD = "timing cannot tell these machines apart";
  const ranked = (f) => ((f || {}).machines || []).filter((h) => h.machine && h.confidence != null).sort((a, b) => b.confidence - a.confidence);
  // one machine listed whose match chance alone would half make: "chance alone would pair 48%"
  function untold(m, f) {
    const hs = ranked(f);
    if (!hs.length) return "";
    if (hs.length > 1 && hs[0].confidence - hs[1].confidence < MARGIN) return UNTOLD;
    if ((hs[0].chance ?? 0) <= CHANCE) return "";
    return hs.length === 1 ? `chance alone would pair ${Math.round(100 * hs[0].chance)}%` : UNTOLD;
  }
  return { trust, trustCell, trustClass, trustCounts, UNTOLD, byConstruction, tooFew, tooFewText, confidence, chance, matched, untold, ranked, MARGIN, MIN_EVENTS, BY_CONSTRUCTION };
})();
if (typeof module !== "undefined") module.exports = Evidence;
