// The window and step a discovery was fitted over, said as the record has them (web/dynamics.py's
// discovery.fitted): discovery may widen the configured window (to the history a source holds,
// until a counter has enough events, or for sparse own data: `sparse`, how many levels asked), and the step with it, so
// the page says what was fitted, never only what orchestra.toml configures.
const DiscoveryWindow = (() => {
  // a duration in the unit that reads best: 30 s, 84 min, 10 h, 7 d
  const dur = (s) => (s < 120 ? `${Math.round(s)} s` : s < 2 * 3600 ? `${Math.round(s / 60)} min`
    : s < 2 * 86400 ? `${+(s / 3600).toFixed(1)} h` : `${+(s / 86400).toFixed(1)} d`);
  const text = (w) => (w && w.window_s && w.step_s ? `${dur(w.window_s)} · ${dur(w.step_s)} steps` : "");
  const levels = (n) => `${n} level${n === 1 ? "" : "s"}`;
  // the strategy that made the shown discovery (its record's ``ran``; ``strategy`` is the one asked
  // for, which SD Lab may not have run: ``sdlab`` says why), and the configured one only when it differs
  function strategy(discovery, configured) {
    const d = discovery || {}, ran = d.ran || (d.sdlab && /^not run|conservation's fits are kept/.test(d.sdlab) ? "conservation" : d.strategy) || configured || "";
    return ran + (configured && ran && configured !== ran ? ` (configured: ${configured})` : "");
  }
  // the settings' summary: the strategy and what was fitted, and the configured window when it differs
  function summary(discovery, configured) {
    const f = discovery && discovery.fitted, c = configured || {};
    if (!f || !text(f)) return [discovery ? strategy(discovery, c.strategy) : c.strategy, text(c)].filter(Boolean).join(" · ");
    const differs = text(c) && text(c) !== text(f);
    return [strategy(discovery, c.strategy), text(f)].filter(Boolean).join(" · ")
      + (differs ? ` (${f.sparse ? `widened for sparse data (${levels(f.sparse)}); ` : ""}configured ${text(c)})` : "");
  }
  return { dur, text, strategy, summary };
})();
if (typeof module !== "undefined") module.exports = DiscoveryWindow;
