// A series read from another store ([[sources]]), as the store spells it: its selector, copyable
// as text beside Orchestra's name (which is prefixed, lower-cased and has ":" turned into "_", so
// it cannot be pasted back into the store), and a link that opens the Core page's External
// stores box with the view's query prefilled and run: a counter as rate(<selector>[<step>]), a
// gauge as the bare selector (sources/selector.py gives both, from the series' definition). The
// Core page reads the link's hash (parse) and its guard still applies to the query.
// Pure functions: tests/source_view/source-view.test.mjs.
const SourceView = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const WINDOWS = [15, 60, 360, 1440];          // the Core page's windows, minutes
  // the Core page's window that holds the fitting window: the smallest at least as long, a day at most
  const minutes = (windowS) => { const m = (windowS || 3600) / 60; return WINDOWS.find((w) => w >= m - 0.5) || WINDOWS[WINDOWS.length - 1]; };
  function href(source, query, windowS, mode = "range") {
    return "/core#" + new URLSearchParams({ store: source, q: query, mode, minutes: String(minutes(windowS)) }).toString();
  }
  // a hash this page made, read back: null when it is not one
  function parse(hash) {
    const h = String(hash || "").replace(/^#/, "");
    if (!/(^|&)store=/.test(h)) return null;
    const p = new URLSearchParams(h), store = p.get("store"), q = p.get("q");
    if (!store || !q) return null;
    const m = +p.get("minutes");
    return { store, q, mode: p.get("mode") === "instant" ? "instant" : "range", minutes: WINDOWS.includes(m) ? m : minutes(m * 60) };
  }
  // a row's line: the store's selector (or its query as written), selectable, and the view link
  function html(rec, windowS) {
    if (!rec || !rec.source) return "";
    const text = rec.selector || rec.store_query || "";
    if (!text) return "";
    const q = rec.store_query || rec.selector;
    const what = rec.selector ? "the selector as the store spells it: copy it into the store" : "the query as written for the store";
    return `<div class="sv"><code class="sv-sel" title="${esc(what)}" style="user-select:all;font-size:11px;overflow-wrap:anywhere">${esc(text)}</code>`
      + ` <a class="sv-view" href="${esc(href(rec.source, q, windowS))}" onclick="event.stopPropagation()" title="open the Core page's External stores box with ${esc(q)} over the fitting window, and run it">view in ${esc(rec.source)}</a>`
      + `${(rec.summed || []).length ? ` <span class="muted" style="font-size:11px">summed over ${esc(rec.summed.join(", "))}</span>` : ""}</div>`;
  }
  return { minutes, href, parse, html };
})();
if (typeof window !== "undefined") window.SourceView = SourceView;
