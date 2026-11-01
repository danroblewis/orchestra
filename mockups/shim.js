// The mockups' stand-in for the server: loaded first on a page (after fixtures/bundle.js, which
// sets window.FIX), before any of Orchestra's own scripts. It
//   - answers fetch() from the captured fixtures (FIX.api), after the page's scripts have all run,
//     so additions.js (loaded last) can edit an answer per frame with MOCK.on(path, fn);
//   - stops the clock at the moment the fixtures were captured (plus MOCK.clockShift seconds), so
//     every "3 min ago" reads the same on every render;
//   - seeds Math.random and the saved graph layouts (localStorage), so the graphs land the same way;
//   - stubs WebSocket and EventSource (nothing live behind a mockup).
(() => {
  const qs = new URLSearchParams(location.search);
  const FRAME = qs.get("frame") || "";
  const hooks = [];
  const MOCK = window.MOCK = {
    frame: FRAME, page: location.pathname, missing: [],
    on(re, fn) { hooks.push([re, fn]); },
    clockShift: 0,
  };
  // ---- the clock: the capture's moment, standing still ----
  const T0 = FIX.capturedAt * 1000;
  const RealDate = Date;
  class MockDate extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(T0 + MOCK.clockShift * 1000); }
    static now() { return T0 + MOCK.clockShift * 1000; }
  }
  window.Date = MockDate;
  // ---- randomness: the same every render ----
  let seed = 20261031;
  Math.random = () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  // ---- the browser's saved state: the captured layouts, nothing else ----
  try {
    localStorage.clear();
    for (const [k, v] of Object.entries(FIX.layouts || {})) if (v) localStorage.setItem("orchestra.netgraph." + k, v);
  } catch (e) {}
  MOCK.layout = (key, id, x, y) => {             // pin one node of a graph's saved layout
    const k = "orchestra.netgraph." + key; let s = {};
    try { s = JSON.parse(localStorage.getItem(k) || "{}"); } catch (e) {}
    s[id] = [Math.round(x), Math.round(y), 1]; localStorage.setItem(k, JSON.stringify(s));
  };
  MOCK.saved = (key) => { try { return JSON.parse(localStorage.getItem("orchestra.netgraph." + key) || "{}"); } catch (e) { return {}; } };
  // ---- fetch ----
  const ready = new Promise((r) => document.addEventListener("DOMContentLoaded", () => setTimeout(r, 0)));
  const clone = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
  function answer(key) {
    const u = new URL(key, location.href), path = u.pathname, full = path + u.search;
    let body = FIX.api[full];
    if (body === undefined) body = FIX.api[path];
    if (body === undefined) { const alt = Object.keys(FIX.api).find((k) => k.split("?")[0] === path); if (alt) body = FIX.api[alt]; }
    body = clone(body);
    for (const [re, fn] of hooks) if (re.test(full)) { const out = fn(body, u); if (out !== undefined) body = out; }
    return body;
  }
  window.fetch = async (input, init) => {
    await ready;
    const key = typeof input === "string" ? input : input.url;
    const body = answer(key);
    if (body === undefined) { MOCK.missing.push(key); return new Response(JSON.stringify({ ok: false, error: "not in the mockup's fixtures" }), { status: 404, headers: { "content-type": "application/json" } }); }
    return new Response(typeof body === "string" ? body : JSON.stringify(body), { status: 200, headers: { "content-type": typeof body === "string" ? "text/plain" : "application/json" } });
  };
  // ---- nothing live ----
  class Quiet { constructor() { this.readyState = 0; } close() {} send() {} addEventListener() {} removeEventListener() {} }
  window.WebSocket = Quiet; window.EventSource = Quiet;
})();
