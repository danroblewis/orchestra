// What the Dynamics tables say of the evidence behind the model: a stock's trust (sd/stocktrust.py),
// whether a flow had events enough to be fitted, and how many of a machine's events matched a
// flow's counter (sd/attribute.py). A missing number reads "—", never an error.
const Evidence = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fix = (v) => (typeof v === "number" && isFinite(v) ? v.toFixed(2) : "—");
  const BY_CONSTRUCTION = "by construction: no evidence (D33)";
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
  // a flow "fitted" from fewer events than this has no fit to speak of
  const MIN_EVENTS = 5;
  const eventsOf = (f) => ((((f || {}).current || {}).quality || {}).events ?? 0);
  const tooFew = (f) => !!(f && f.current && f.current.origin === "fitted" && eventsOf(f) < MIN_EVENTS);
  const tooFewText = (f) => `${eventsOf(f)} event${eventsOf(f) === 1 ? "" : "s"}: too few to fit`;
  // a hypothesis' confidence beside its machine, " 87%": none on a flow with too few events to fit,
  // as its equation and fit show none
  const confidence = (f, h) => (tooFew(f) || (h || {}).confidence == null ? "" : ` ${Math.round(100 * h.confidence)}%`);
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
  // (sd/attribute.py: a hypothesis is a match in time): one machine that matches 3 or more flows at
  // STRONG, or 3 or more machines that match one flow so, says so once beside the flow's hypotheses
  const STRONG = 0.85, MANY = 3;
  const UNTOLD = "events within one step: timing cannot tell these apart";
  function untold(m, f) {
    const strong = (g) => ((g || {}).machines || []).filter((h) => h.machine && (h.confidence ?? 0) >= STRONG);
    const mine = strong(f);
    if (mine.length >= MANY) return UNTOLD;
    const flowsOf = (mc) => ((m || {}).flows || []).filter((g) => strong(g).some((h) => h.machine === mc)).length;
    return mine.some((h) => flowsOf(h.machine) >= MANY) ? UNTOLD : "";
  }
  return { trust, trustCell, byConstruction, tooFew, tooFewText, confidence, matched, untold, MIN_EVENTS };
})();
if (typeof module !== "undefined") module.exports = Evidence;
