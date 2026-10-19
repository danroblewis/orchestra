// SD Lab editor. Two modes over one canvas:
//   Edit - draw stocks and flows (the system dynamics model) and apply machines to flows,
//          the way a drawing program applies colours: select, then pick a machine
//   Run  - run the model's real programs, and see what happened so far beside what the model
//          projects from now on. With no run yet, the projection starts from the starting values.
//
// Selecting: click selects one thing, shift-click adds, ctrl-click removes, dragging on
// empty canvas draws a selection box (shift adds, ctrl removes), Cmd/Ctrl-A selects all.
// Applying: with flows selected, click a machine in the panel, press M, or right-click.
(function () {
  "use strict";
  const { simulate, describeRate, fmt } = window.SDSim;
  const { BOX, center, clip, shorten, el, text, arrowHead, columns } = window.SDDiagram;
  const PALETTE = ["#6d5bd0", "#c2410c", "#0f766e", "#2563eb", "#be185d", "#15803d", "#b45309", "#7e22ce"];

  const S = {
    model: null, mode: "edit",
    sel: new Set(),            // "s:<stock id>" and "f:<flow id>"
    editMachine: null,         // machine shown in the inspector when nothing is selected
    pending: null,             // flow being drawn: { from, cloud }
    recent: [],                // machine ids, most recently applied first
    filter: "",                // machine panel filter
    sim: null, tIndex: null, saveTimer: null, drag: null, marquee: null, pointer: { x: 200, y: 200 },
    proj: null,                // the model's projection from the current state: { series, summary, t0 }
    tab: "stocks",             // Run panel: "stocks" (levels) or "flows" (how much moved each step)
    win: 60, endAt: null,      // charts show the last `win` steps (0: all) ending at `endAt` (null: now)
    hover: null, fitCache: null,
    live: null, liveItems: null, poll: null, programs: [],
    firing: null,              // one program run, shown in the inspector: its command, stdin, stdout
    undo: null,                // the equations replaced by the last "Update equations", for Undo
    discovery: null,           // flows found from stock levels alone, shown over the canvas and in the inspector
  };
  const $ = (id) => document.getElementById(id);
  const svg = $("canvas");

  // ---------- data helpers ----------
  const stock = (id) => S.model.stocks.find((s) => s.id === id);
  const flow = (id) => S.model.flows.find((f) => f.id === id);
  const machine = (id) => S.model.machines.find((m) => m.id === id);
  const stockName = (id) => (stock(id) || {}).name || "?";
  const unitOf = (f) => (stock(f.to) || stock(f.from) || {}).unit || "units";
  const tu = () => S.model.time_unit || "hour";

  const selStocks = () => [...S.sel].filter((k) => k[0] === "s").map((k) => k.slice(2));
  const selFlows = () => [...S.sel].filter((k) => k[0] === "f").map((k) => k.slice(2));
  const isSel = (key) => S.sel.has(key);

  try { S.autoDiscover = localStorage.getItem("sdlab.autoDiscover") === "1"; } catch { /* off without storage */ }
  function uniqueId(base) {
    base = (base || "item").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "item";
    if (!/^[a-z]/.test(base)) base = "x_" + base;
    const used = new Set([...S.model.stocks, ...S.model.flows, ...S.model.machines].map((x) => x.id));
    let id = base, n = 2;
    while (used.has(id)) id = `${base}_${n++}`;
    return id;
  }
  function machineColor(id) {
    if (!id) return "var(--unassigned)";
    if (id === "environment") return "var(--env)";
    return (machine(id) || {}).color || "var(--unassigned)";
  }
  function machineName(id) {
    if (!id) return "no machine";
    if (id === "environment") return "environment";
    return (machine(id) || {}).name || "?";
  }

  // ---------- persistence ----------
  // Examples always open as shipped. The first edit to one saves a copy of the user's own (its
  // run goes with it), and from then on the copy is what is edited.
  async function fetchList() { S.list = await fetch("/api/models").then((x) => x.json()); return S.list; }
  // a run going on right now is marked, so it is never a guess which ones are running
  const runSign = (r) => [...r.models, ...r.examples].filter((m) => m.running).map((m) => m.id).sort().join();
  // The ladder's cases are the basic models, listed first; the older models (the examples and the
  // user's own) are behind "Show older models", off by default and remembered per browser.
  try { S.showOld = localStorage.getItem("sdlab.showOld") === "1"; } catch { S.showOld = false; }
  function setShowOld(on) {
    S.showOld = !!on;
    try { localStorage.setItem("sdlab.showOld", S.showOld ? "1" : ""); } catch { /* fine without it */ }
  }
  const basicsOf = (r) => r.basics || [];
  const allModels = (r) => [...basicsOf(r), ...(r.draws || []), ...r.models, ...r.examples];
  // The model picker: our own list rather than a native select, so a running model can stand out
  // (a green background and its step), and the list can be filtered by typing.
  function renderPick(id) {
    const r = S.list;
    if (id) S.pickId = id;
    S.listSign = runSign(r);
    const all = allModels(r), cur = all.find((m) => m.id === S.pickId);
    const btn = $("model-pick");
    btn.innerHTML = `${cur && cur.running ? '<span class="dot" aria-hidden="true"></span>' : ""}<span class="pname">${esc(cur ? cur.name : "Choose a model")}</span><span class="caret" aria-hidden="true">\u25be</span>`;
    btn.classList.toggle("running", !!(cur && cur.running));
    const menu = $("model-menu");
    if (menu.hidden) return;
    const q = (S.pickFilter || "").toLowerCase(), hit = (m) => !q || m.name.toLowerCase().includes(q) || m.id.includes(q) || (m.tests || "").toLowerCase().includes(q);
    const item = (m) => `<div role="option" class="pickitem${m.running ? " running" : ""}${m.id === S.pickId ? " cur" : ""}${m.case ? " basic" : ""}" data-pick="${m.id}" aria-selected="${m.id === S.pickId}"${m.tests ? ` title="${esc(`Tests: ${m.tests}`)}"` : ""}>
        ${m.case ? `<span class="plevel" title="Level ${esc(m.level)}">${esc(m.case.slice(0, 3))}</span>` : ""}<span class="pname">${esc(m.name)}${m.tests ? `<span class="ptests">${esc(m.tests)}</span>` : ""}</span>${m.running ? `<span class="ptag">\u25b6 running \u00b7 step ${m.t}</span>` : ""}</div>`;
    const group = (label, list) => (list.filter(hit).length ? `<div class="pickgroup">${label}</div>${list.filter(hit).map(item).join("")}` : "");
    const keep = menu.querySelector(".pickfind");
    const older = S.showOld ? group("My models", r.models) + group("Examples (open as shipped)", r.examples) : "";
    // a parametric case's random draws: listed when the filter asks (or one is open), to keep the list short
    const draws = (r.draws || []).filter((m) => q || m.id === S.pickId);
    const body = group("Basic models (ladder)", basicsOf(r)) + group("Random draws (ladder)", draws) + older
      || `<div class="pickgroup">No model matches</div>`;
    const toggle = (r.draws || []).length ? `<div class="pickgroup small">Type to find the ${r.draws.length} random draws too (e.g. “043”)</div>` : "";
    const toggleOld = `<label class="pickold" title="The examples and your own models"><input type="checkbox" data-show-old ${S.showOld ? "checked" : ""}> Show older models (${r.models.length + r.examples.length})</label>`;
    if (!keep) menu.innerHTML = `<input class="pickfind" placeholder="Filter models" aria-label="Filter models"><div class="picklist">${body}</div>${toggle}${toggleOld}`;
    else { menu.querySelector(".picklist").innerHTML = body; menu.querySelector("[data-show-old]").checked = S.showOld; }
    const items = [...menu.querySelectorAll("[data-pick]")];
    if (!items.some((x) => x.classList.contains("hl"))) (items.find((x) => x.classList.contains("cur")) || items[0] || { classList: { add() {} } }).classList.add("hl");
  }
  function openPick() {
    const menu = $("model-menu");
    menu.hidden = false; $("model-pick").setAttribute("aria-expanded", "true");
    S.pickFilter = ""; menu.innerHTML = "";
    renderPick();
    const f = menu.querySelector(".pickfind"); f.focus();
    const cur = menu.querySelector(".cur"); if (cur) cur.scrollIntoView({ block: "nearest" });
    fetchList().then(() => { if (!menu.hidden) renderPick(); }).catch(() => {});   // fresh running marks
  }
  function closePick() { $("model-menu").hidden = true; $("model-pick").setAttribute("aria-expanded", "false"); }
  $("model-pick").addEventListener("click", () => ($("model-menu").hidden ? openPick() : closePick()));
  $("model-menu").addEventListener("click", (e) => {
    const it = e.target.closest("[data-pick]"); if (!it) return;
    closePick();
    if (it.dataset.pick !== S.model.id) loadModel(it.dataset.pick);
  });
  $("model-menu").addEventListener("input", (e) => { if (e.target.classList.contains("pickfind")) { S.pickFilter = e.target.value; renderPick(); } });
  $("model-menu").addEventListener("change", (e) => { if (e.target.matches("[data-show-old]")) { setShowOld(e.target.checked); renderPick(); } });
  $("model-menu").addEventListener("keydown", (e) => {
    const items = [...$("model-menu").querySelectorAll("[data-pick]")], at = items.findIndex((x) => x.classList.contains("hl"));
    if (e.key === "Escape") { closePick(); $("model-pick").focus(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = items[Math.max(0, Math.min(items.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))];
      items.forEach((x) => x.classList.remove("hl")); if (next) { next.classList.add("hl"); next.scrollIntoView({ block: "nearest" }); }
    }
    if (e.key === "Enter" && items[at]) { e.preventDefault(); items[at].click(); }
  });
  document.addEventListener("pointerdown", (e) => { if (!$("model-menu").hidden && !e.target.closest(".picker")) closePick(); }, true);
  async function loadList(selectId) {
    const r = await fetchList();
    const all = allModels(r);
    let fromUrl = new URLSearchParams(location.search).get("model");
    // ?model=ladder-043-x#2 (a draw named as the ladder names it): the draw's model is ladder-043-x~2
    if (fromUrl && /^#\d+$/.test(location.hash) && !all.some((m) => m.id === fromUrl)) fromUrl = `${fromUrl}~${location.hash.slice(1)}`;
    let remembered = null; try { remembered = localStorage.getItem("sdlab.model"); } catch { /* storage may be blocked */ }
    const known = (id) => id && all.some((m) => m.id === id) ? id : null;
    const id = known(selectId) || known(fromUrl) || known(remembered) || (basicsOf(r)[0] || all.find((m) => m.id === "bakery") || all[0] || {}).id;
    renderPick(id);
    if (id) await loadModel(id);
  }
  function rememberModel(id) {
    const u = new URL(location.href); u.searchParams.set("model", id); history.replaceState(null, "", u);
    try { localStorage.setItem("sdlab.model", id); } catch { /* fine without it */ }
  }
  async function loadModel(id) {
    await flushSave();
    S.model = await fetch(`/api/models/${id}`).then((x) => x.json());
    S.isExample = !!S.model.example; delete S.model.example;
    rememberModel(id);
    renderPick(id);
    S.model.stocks ||= []; S.model.flows ||= []; S.model.machines ||= [];
    if (S.model.basic) layoutBasic();
    S.truth = null; if (!S.model.basic) loadTruth(id);
    S.sel.clear(); S.editMachine = null; S.pending = null; S.recent = []; S.live = null; S.paceLog = null; S.liveItems = null; S.undo = null;
    S.discovery = null; S.discovering = null; S.discToken = (S.discToken || 0) + 1; S.lastAutoN = 0; S.lastAutoAt = 0; S.leverage = null; S.fitCache = null; S.fitPrev = null; S.fitHist = null; S.view = null; S.find = "";
    S.simplify = null; S.preview = null; S.previewIdx = null; S.undoSimplify = null; S.showHidden = false; S.undoLayout = null;
    if ($("unarrange")) $("unarrange").hidden = true;
    if ($("find")) $("find").value = "";
    if (S.poll) { clearTimeout(S.poll.timer); S.poll = null; }
    changed(false);
    renderSaveState();
    syncPolling();
  }
  // An example with a known truth (each sd-* example is a realistic ladder case, known_truth.py): its
  // true flows and the stocks its data hides, drawn while the truth is shown. Without one, or before
  // the server knows the endpoint, the page is as it was.
  async function loadTruth(id) {
    let t = null;
    try { const r = await fetch(`/api/models/${encodeURIComponent(id)}/truth`); if (r.ok) t = await r.json(); } catch { /* no truth */ }
    if (!t || !Array.isArray(t.flows) || !Array.isArray(t.stocks) || !S.model || S.model.id !== id || S.model.basic) return;
    const mine = new Set(S.model.stocks.map((s) => s.id)), placed = [];
    t.ghostList = t.stocks.filter((s) => !mine.has(s.id));
    t.big = t.flows.length > TRUTH_DRAW_MAX;
    t.ghosts = {};
    if (!t.big) t.ghostList.forEach((s, k) => {        // where the truth puts it, moved down until it covers no stock
      let q = { x: Number.isFinite(+s.x) ? +s.x : 80 + 300 * (k % 4), y: Number.isFinite(+s.y) ? +s.y : 400 + 140 * Math.floor(k / 4) };
      const hits = (o) => [...S.model.stocks, ...placed].some((st) => Math.abs(st.x - o.x) < BOX.w + 16 && Math.abs(st.y - o.y) < BOX.h + 12);
      for (let i = 0; i < 40 && hits(q); i++) q = { x: q.x, y: q.y + BOX.h + 24 };
      placed.push(q); t.ghosts[s.id] = { ...s, x: q.x, y: q.y };
    });
    S.truth = t;
    renderToolbar(); renderCanvas();
    if (S.discovery) compareWithTruth(S.discovery, id);
  }
  // A basic model (a ladder case) comes without positions: the ladder page's layout, at the
  // editor's box size. Its run is the case's recorded data in one variant (counting noise, long, by
  // default; the choice is remembered per browser).
  function layoutBasic() {
    const pos = window.SDDiagram.layout(S.model.stocks.map((s) => s.id), S.model.flows, { maxCols: 3, colw: 360, rowh: 200 });
    S.model.stocks.forEach((s) => { const p = pos[s.id] || { x: 0, y: 0 }; s.x = p.x; s.y = p.y; });
    let v = null, live = null; try { v = localStorage.getItem("sdlab.basicVariant"); live = localStorage.getItem("sdlab.basicLive"); } catch { /* fine */ }
    S.basicVariant = S.model.basic.variants.includes(v) ? v : S.model.basic.variant;
    S.basicLive = live === "1";
    S.estHist = null;
  }
  // a basic model's run: its recorded data (the ladder's), or live (its true model stepped by the engine, from step 0)
  const liveQuery = () => (S.model && S.model.basic ? `&variant=${encodeURIComponent(S.basicVariant)}${S.basicLive ? "&live=1" : ""}` : "");
  async function setBasicLive(on, start) {
    S.basicLive = !!on;
    try { localStorage.setItem("sdlab.basicLive", S.basicLive ? "1" : ""); } catch { /* fine */ }
    S.discovery = null; S.discovering = null; S.discToken = (S.discToken || 0) + 1; S.fitCache = null; S.fitPrev = null; S.fitHist = null; S.estHist = null; S.lastAutoN = 0;
    S.live = null;
    if (S.basicLive && !S.autoDiscover) { S.autoDiscover = true; try { localStorage.setItem("sdlab.autoDiscover", "1"); } catch { /* fine */ } }
    if (start) await liveAct("start"); else await refetchLive();
    setStatus(S.basicLive ? `Live run of the true model (${S.basicVariant}): it steps as the clock ticks; discovery re-estimates as data arrives` : `Recorded data: ${S.basicVariant}`);
  }
  async function setBasicVariant(v) {
    S.basicVariant = v;
    try { localStorage.setItem("sdlab.basicVariant", v); } catch { /* fine */ }
    clearEstimate(); S.fitCache = null; S.fitPrev = null; S.fitHist = null; S.estHist = null; S.live = null;
    await refetchLive();
    setStatus(`Recorded data: ${v} (${S.live ? S.live.series.t.length : 0} ${tu()}s)`);
  }

  // Save as: a copy of the current model (with its run) under a new name, which is then what is edited.
  async function saveCopy(name) {
    const r = await fetch(`/api/models/${S.model.id}/copy`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(name ? { name } : {}) });
    if (!r.ok) { setStatus("Could not save a copy", true); return null; }
    const c = await r.json();
    S.model.id = c.id; S.model.name = c.name; S.isExample = false;
    rememberModel(c.id);
    await fetchList(); renderPick(c.id); renderSaveState();
    return c;
  }
  async function writeModel() {
    S.saveTimer = null;
    if (S.model.basic) {                       // a ladder case stays as it is: changes are for looking only
      setStatus("A basic model is not saved: your changes last until you open another model (Save as keeps a copy, without the recorded data)");
      return;
    }
    if (S.isExample) {
      const shipped = S.model.name;
      S.forking = S.forking || saveCopy(`${S.model.name} (my copy)`);
      const c = await S.forking; S.forking = null;
      if (!c) return;
      setStatus(`Saved as your own copy, “${c.name}”. The example “${shipped}” stays as shipped.`);
    }
    const r = await fetch(`/api/models/${S.model.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(S.model) });
    if (r.ok) { if ($("status").textContent === "Unsaved changes") setStatus("Saved"); }   // keep a more useful message
    else {
      const body = await r.json().catch(() => ({}));
      const errs = (body.detail && body.detail.errors) || [typeof body.detail === "string" ? body.detail : r.statusText];
      setStatus("Not saved: " + errs.join("; "), true);
    }
  }
  function save() {
    clearTimeout(S.saveTimer);
    setStatus("Unsaved changes");
    S.saveTimer = setTimeout(writeModel, 400);
  }
  // write any pending change now (before switching models, or starting a run)
  async function flushSave() {
    if (!S.saveTimer) return;
    clearTimeout(S.saveTimer);
    await writeModel();
  }
  function renderSaveState() {
    const b = $("model-kind"); if (!b) return;
    b.hidden = !S.isExample;
    const basic = S.model && S.model.basic;
    b.textContent = basic ? `ladder ${basic.case.slice(0, 3)}` : "example";
    b.title = basic ? `A basic model: ladder case ${basic.case}, level ${basic.level}. Tests: ${basic.tests} It plays back the case's recorded data; changes are not saved.`
      : "An example always opens as shipped. Your first change saves a copy of your own, and that copy is what you edit.";
  }
  function setStatus(text, err) { const el = $("status"); el.textContent = text; el.classList.toggle("error", !!err); }

  // Everything that changes the model goes through here.
  function changed(persist = true, opts = {}) {
    project();
    renderCanvas();
    if (!opts.keepInspector) renderInspector();
    renderMachineList();
    renderToolbar();
    renderRunPanel();
    if (persist) save();
  }
  function selectionChanged() {
    S.editMachine = null; S.firing = null; renderCanvas(); renderInspector(); renderMachineList(); renderToolbar();
    if (S.mode === "run" && S.model.stocks.length > 24) renderRunPanel();
    if (hasData()) fetchLive();
  }

  // The present: the live run's latest levels if there is a run, otherwise the starting values.
  // The projection runs the model's equations forward from there.
  const hasData = () => !!(S.live && S.live.series.t.length > 0);
  // The projection starts from the average of the last few steps of the current era, not the
  // last single value: a stock that flips between 0 and 1 should not make the projection jump.
  function nowState() {
    if (hasData()) {
      const L = S.live.series, i = L.t.length - 1, era = currentEra();
      const k = Math.max(1, Math.min(10, L.t[i] - era.start + 1));
      const avg = (a) => a.slice(-k).reduce((x, y) => x + y, 0) / Math.min(k, a.length || 1);
      return { t: L.t[i], levels: Object.fromEntries(S.model.stocks.map((s) => [s.id, avg(L.levels[s.id] || [0])])) };
    }
    return { t: 0, levels: Object.fromEntries(S.model.stocks.map((s) => [s.id, Math.max(0, +s.initial || 0)])) };
  }
  function project() {
    const now = nowState(), ahead = Math.max(1, +S.model.horizon || 100);
    const r = simulate(S.model, { start: now.levels, t0: now.t, horizon: ahead });
    S.proj = { ...r, t0: now.t };
  }

  // ---------- geometry ----------
  // center, clip and shorten come from diagram.js (shared with the ladder page)
  function cloudPos(f) {
    if (f.cloud) return f.cloud;
    if (!f.from && f.to) { const s = stock(f.to); return { x: s.x - 90, y: s.y + BOX.h / 2 }; }
    const s = stock(f.from); return { x: s.x + BOX.w + 90, y: s.y + BOX.h / 2 };
  }
  function ends(f) {
    const fromS = f.from && stock(f.from), toS = f.to && stock(f.to);
    const a0 = fromS ? center(fromS) : cloudPos(f), b0 = toS ? center(toS) : cloudPos(f);
    let a = fromS ? clip(fromS, b0) : { ...a0 }, b = toS ? clip(toS, a0) : { ...b0 };
    if (!fromS) a = shorten(a, b, 16);
    if (!toS) b = shorten(b, a, 16);
    const twin = f.from && f.to && S.model.flows.some((g) => g.from === f.to && g.to === f.from);
    if (twin) {
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1, ox = -dy / L * 9, oy = dx / L * 9;
      a = { x: a.x + ox, y: a.y + oy }; b = { x: b.x + ox, y: b.y + oy };
    }
    return { a, b };
  }
  function segmentHitsRect(a, b, r) {
    const inside = (p) => p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;
    if (inside(a) || inside(b)) return true;
    const edges = [[{ x: r.x, y: r.y }, { x: r.x + r.w, y: r.y }], [{ x: r.x + r.w, y: r.y }, { x: r.x + r.w, y: r.y + r.h }],
      [{ x: r.x + r.w, y: r.y + r.h }, { x: r.x, y: r.y + r.h }], [{ x: r.x, y: r.y + r.h }, { x: r.x, y: r.y }]];
    const cross = (p, q, s) => (q.x - p.x) * (s.y - p.y) - (q.y - p.y) * (s.x - p.x);
    return edges.some(([c, d]) => cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0);
  }

  // ---------- canvas ----------
  // el, text and arrowHead come from diagram.js

  // The numbers on the canvas are the present: the live run's latest step, or the start of the projection.
  const isLive = hasData;
  // The most each stock has held in a series, kept up to date as the series grows (a month of
  // steps for hundreds of stocks is not rescanned on every redraw).
  const maxMemo = new WeakMap();
  function maxSeen(ser, id) {
    const a = ser.levels[id] || [];
    let m = maxMemo.get(ser);
    if (!m) { m = {}; maxMemo.set(ser, m); }
    const e = m[id] || (m[id] = { n: 0, max: -Infinity, arr: a });
    if (e.arr !== a || a.length < e.n) { e.n = 0; e.max = -Infinity; e.arr = a; }
    for (let i = e.n; i < a.length; i++) if (a[i] > e.max) e.max = a[i];
    e.n = a.length;
    return e.max;
  }
  function cur() {
    if (hasData()) return { ser: S.live.series, i: S.live.series.t.length - 1 };
    return { ser: S.proj.series, i: 0 };
  }
  // a stock marked hidden (and the flows touching it) is not drawn unless "show hidden" is on;
  // its data and equations stay in the model and the simulation
  const shown = (id) => !id || S.showHidden || !(stock(id) || {}).hide;
  function renderHiddenButton() {
    const n = S.model.stocks.filter((x) => x.hide).length;
    $("showhidden").hidden = !n;
    const sh = $("showhidden"), tip = S.showHidden ? `Hide the ${n} hidden stock${n === 1 ? "" : "s"} again` : `Show the ${n} hidden stock${n === 1 ? "" : "s"}`;
    sh.textContent = `${S.showHidden ? "\u{1F648}" : "\u{1F441}\uFE0F"} ${n}`; sh.title = tip; sh.setAttribute("aria-label", tip);
  }
  function renderCanvas() {
    renderHiddenButton();
    if (!S.drag && !S.marquee) fitView();
    svg.innerHTML = "";
    const { ser, i: ti } = cur();
    const lv = (id) => ser.levels[id] ? ser.levels[id][ti] || 0 : 0;
    const rt = (id) => ser.rates[id] ? ser.rates[id][ti] || 0 : 0;
    const gLinks = el("g", {}, svg), gFlows = el("g", {}, svg), gStocks = el("g", {}, svg), gLabels = el("g", {}, svg);
    const visFlows = S.hideTruth && S.model.basic ? [] : S.model.flows.filter((f) => shown(f.from) && shown(f.to)), visStocks = S.model.stocks.filter((x) => shown(x.id));

    // information links: a flow's equation reads a stock; an effect reads one (dashed, labelled);
    // a co-flow uses one up (dotted, labelled "uses")
    visFlows.forEach((f) => {
      [...(f.effects || []).map((e) => [e.stock, "effect", "3 4"]), ...(f.uses || []).map((u) => [u.stock, `uses ${fmt(u.per)}`, "1 3"])].forEach(([sid, label, dash], k) => {
        const src = stock(sid); if (!src || !shown(sid)) return;
        const { a, b } = ends(f), mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const c = center(src), start = clip(src, mid);
        const dx = mid.x - c.x, dy = mid.y - c.y, L = Math.hypot(dx, dy) || 1;
        const bend = 36 * (k % 2 ? -1 : 1) * (1 + Math.floor(k / 2) * 0.7);     // links side by side bend apart
        const ctl = { x: (start.x + mid.x) / 2 + dy / L * bend, y: (start.y + mid.y) / 2 - dx / L * bend };
        const end = shorten(mid, ctl, 8);
        el("path", { d: `M${start.x} ${start.y} Q${ctl.x} ${ctl.y} ${end.x} ${end.y}`, fill: "none", stroke: "var(--pred)", "stroke-width": 1.5, "stroke-dasharray": dash }, gLinks);
        arrowHead(gLinks, ctl, end, "var(--pred)", 6);
        text(gLinks, ctl.x, ctl.y - 3, label, { "text-anchor": "middle", "font-size": 10.5, fill: "var(--pred)", "font-weight": 600 });
      });
    });
    visFlows.forEach((f) => {
      const src = f.rate && f.rate.stock && stock(f.rate.stock);
      if (!src || !shown(src.id)) return;
      const { a, b } = ends(f), mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const c = center(src), start = clip(src, mid);
      const dx = mid.x - c.x, dy = mid.y - c.y, L = Math.hypot(dx, dy) || 1;
      const ctl = { x: (start.x + mid.x) / 2 - dy / L * 46, y: (start.y + mid.y) / 2 + dx / L * 46 };
      const end = shorten(mid, ctl, 8);
      el("path", { d: `M${start.x} ${start.y} Q${ctl.x} ${ctl.y} ${end.x} ${end.y}`, fill: "none", stroke: "var(--muted)", "stroke-width": 1.2, "stroke-dasharray": "3 4" }, gLinks);
      arrowHead(gLinks, ctl, end, "var(--muted)", 6);
    });

    visFlows.forEach((f) => {
      const { a, b } = ends(f), col = machineColor(f.machine);
      const g = el("g", { class: "flow" + (isSel("f:" + f.id) ? " sel" : ""), "data-flow": f.id }, gFlows);
      const d = `M${a.x} ${a.y} L${b.x} ${b.y}`;
      el("path", { d, class: "halo" }, g);
      const tip = shorten(b, a, 10);
      el("path", { d: `M${a.x} ${a.y} L${tip.x} ${tip.y}`, stroke: col, "stroke-width": 3.2, fill: "none", "stroke-dasharray": f.machine ? null : "7 5" }, g);
      arrowHead(g, a, b, col, 12);
      el("path", { d, class: "hit" }, g);
      (f.outputs || []).forEach((o) => {                 // a flow that can fill other stocks too
        const os = stock(o); if (!os) return;
        const m0 = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, e = clip(os, m0), etip = shorten(e, m0, 10);
        el("path", { d: `M${m0.x} ${m0.y} L${etip.x} ${etip.y}`, stroke: col, "stroke-width": 2.6, fill: "none", "stroke-dasharray": f.machine ? null : "7 5" }, g);
        arrowHead(g, m0, e, col, 11);
        el("path", { d: `M${m0.x} ${m0.y} L${e.x} ${e.y}`, class: "hit" }, g);
      });
      if (!f.from || !f.to) drawCloud(gFlows, f);

      // label: the flow's name, then its machine (Edit) or its rate now (Run)
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const vertical = Math.abs(b.x - a.x) < Math.abs(b.y - a.y);
      const lx = vertical ? mid.x + 14 : mid.x, ly = vertical ? mid.y - 4 : mid.y - 30;
      const anchor = vertical ? "start" : "middle";
      const line2 = S.mode === "run" && S.model.basic ? `${eqText(f.rate)}  ≈${fmt(rt(f.id))}/${tu()} now`
        : S.mode === "run" ? `${fmt(rt(f.id))}/${tu()} · ${machineName(f.machine)}` : machineName(f.machine);
      const w = Math.max(f.name.length * 7, line2.length * 6.4) + 12;
      el("rect", { x: anchor === "middle" ? lx - w / 2 : lx - 5, y: ly - 13, width: w, height: 32, rx: 4, fill: "var(--canvas)", opacity: 0.88, "data-flow": f.id, class: "flow" }, gLabels);
      text(gLabels, lx, ly, f.name, { "text-anchor": anchor, "font-size": 12.5, "font-weight": 600, fill: isSel("f:" + f.id) ? "var(--accent)" : "var(--fg)", "data-flow": f.id, class: "flow" });
      text(gLabels, lx, ly + 15, line2, { "text-anchor": anchor, "font-size": 11.5, "font-weight": 700, fill: col, "data-flow": f.id, class: "flow" });
    });

    visStocks.forEach((s) => {
      const found = S.find && (s.name + " " + s.id + " " + (s.group || "")).toLowerCase().includes(S.find);
      const g = el("g", { class: "stock" + (isSel("s:" + s.id) ? " sel" : "") + (S.pending ? " pick" : "") + (found ? " found" : "") + (s.measured === false ? " unmeasured" : ""), "data-stock": s.id, transform: `translate(${s.x} ${s.y})` }, gStocks);
      el("rect", { class: "box", width: BOX.w, height: BOX.h, rx: 3 }, g);
      // How full it is: the box fills from the bottom, like a tank. "Full" is the most it has held
      // so far (or its goal, if that is higher), until we know its real capacity.
      const v = lv(s.id), max = Math.max(1e-9, maxSeen(ser, s.id), (s.target && +s.target.value) || 0);
      const frac = Math.max(0, Math.min(1, v / max)), fh = (BOX.h - 2) * frac;
      if (fh > 0.5) {
        el("rect", { class: "fill", x: 1, y: BOX.h - 1 - fh, width: BOX.w - 2, height: fh }, g);
        el("line", { class: "fill-top", x1: 1, x2: BOX.w - 1, y1: BOX.h - 1 - fh, y2: BOX.h - 1 - fh }, g);
      }
      el("title", {}, g).textContent = `${s.name}: ${fmt(v)} ${s.unit || ""}, ${Math.round(frac * 100)}% of the most seen (${fmt(max)})`;
      text(g, 10, 20, s.name, { "font-size": 13, "font-weight": 600, fill: "var(--fg)" });
      text(g, 10, 40, `${fmt(v)} ${s.unit || ""}`, { "font-size": 13, "font-family": "var(--mono)", fill: "var(--fg)" });
      text(g, BOX.w - 8, BOX.h - 7, `${Math.round(frac * 100)}%`, { "text-anchor": "end", "font-size": 10, "font-family": "var(--mono)", fill: "var(--muted)" });
      if (s.target && s.target.value !== undefined && s.target.value !== "") {
        const by = s.target.by !== undefined && s.target.by !== "" ? ` by ${fmt(s.target.by)}` : "";
        text(g, 10, 55, `goal ${fmt(s.target.value)}${by}`, { "font-size": 10.5, fill: "var(--muted)" });
      }
    });
    drawTruth(gFlows, gStocks);
    drawDiscovered();
    drawMarquee();
    renderLegend();
  }
  // What the canvas's lines mean, in run mode on a basic model or with an estimate on screen.
  function renderLegend() {
    let box = $("canvas-legend");
    const want = S.mode === "run" && (S.model.basic || S.discovery || truthOn());
    if (!want) { if (box) box.hidden = true; return; }
    if (!box) { box = document.createElement("div"); box.id = "canvas-legend"; svg.parentElement.appendChild(box); }
    box.hidden = false;
    const sw = (stroke, dash, w) => `<svg width="30" height="10" aria-hidden="true"><line x1="1" y1="5" x2="29" y2="5" stroke="${stroke}" stroke-width="${w}" ${dash ? `stroke-dasharray="${dash}"` : ""}/></svg>`;
    const truth = (S.model.basic && !S.hideTruth) || truthOn();
    const html = `${truth ? `<span>${sw("var(--env)", "7 5", 3)} true flow</span>${S.model.basic ? `<span>${sw("var(--muted)", "3 4", 1.2)} its rate depends on that stock</span>` : truthLegend()}` : ""}
      ${S.discovery ? `<span>${sw("var(--fit)", "6 4", 2.2)} found flow</span><span>${sw("var(--fit)", "2 4", 1.2)} found rate depends on that stock</span>` : ""}
      <span class="muted">labels: the equation (0.5·A = 0.5 × A per ${esc(tu())}), then ≈ the amount now</span>`;
    if (box.dataset.html !== html) { box.dataset.html = html; box.innerHTML = html; }
  }
  // ---------- an example's known truth, over the canvas ----------
  const TRUTH_DRAW_MAX = 250;          // more true flows than this: only those between the stocks on the page are drawn
  const truthOn = () => !!(S.truth && S.model && !S.model.basic && !S.hideTruth && S.mode === "run");
  const truthBox = (id) => (!id ? null : stock(id) && shown(id) ? stock(id) : (S.truth.ghosts[id] || null));
  const truthFlows = () => S.truth.flows.filter((f) => (f.from || f.to) && (!f.from || truthBox(f.from)) && (!f.to || truthBox(f.to)));
  function truthLegend() {
    const T = S.truth, n = Object.keys(T.ghosts).length, drawn = truthFlows().length;
    return `${n ? `<span><svg width="30" height="12" aria-hidden="true"><rect x="1" y="1" width="28" height="10" rx="2" fill="none" stroke="var(--env)" stroke-dasharray="4 3"/></svg> a true stock hidden in the data</span>` : ""}`
      + (drawn < T.flows.length ? `<span class="muted">${drawn} of the truth's ${T.flows.length} flows drawn: the ${T.flows.length - drawn} through its ${T.ghostList.length} hidden stocks are too many to draw</span>` : "");
  }
  function truthEnds(f) {
    const A = truthBox(f.from), B = truthBox(f.to);
    const cp = A ? { x: A.x + BOX.w + 90, y: A.y + BOX.h / 2 } : { x: B.x - 90, y: B.y + BOX.h / 2 };
    const a0 = A ? center(A) : cp, b0 = B ? center(B) : cp;
    let a = A ? clip(A, b0) : { ...a0 }, b = B ? clip(B, a0) : { ...b0 };
    if (!A) a = shorten(a, b, 16);
    if (!B) b = shorten(b, a, 16);
    if (A && B && S.truth.flows.some((g) => g.from === f.to && g.to === f.from)) {
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1, ox = -dy / L * 9, oy = dx / L * 9;
      a = { x: a.x + ox, y: a.y + oy }; b = { x: b.x + ox, y: b.y + oy };
    }
    return { a, b, cloud: A && B ? null : cp };
  }
  function drawTruth(gFlows, gStocks) {
    const gLabels = gFlows;                     // under the stocks: a true flow's label never hides a stock's name
    if (!truthOn()) return;
    const col = "var(--env)", fl = truthFlows(), labels = fl.length <= 80, maxc = Math.floor((BOX.w - 16) / 7);
    Object.values(S.truth.ghosts).forEach((s) => {
      const g = el("g", { class: "truth-ghost", transform: `translate(${s.x} ${s.y})` }, gStocks);
      el("rect", { width: BOX.w, height: BOX.h, rx: 3, fill: "var(--canvas)", stroke: col, "stroke-width": 1.6, "stroke-dasharray": "5 4", opacity: 0.9 }, g);
      el("title", {}, g).textContent = `${s.name}: a stock of the true model that the data does not show (hidden in the data)`;
      text(g, 10, 20, s.name.length > maxc ? `${s.name.slice(0, maxc - 1)}…` : s.name, { "font-size": 12.5, "font-weight": 600, fill: "var(--muted)" });
      text(g, 10, 40, "hidden in the data", { "font-size": 11, "font-style": "italic", fill: col });
    });
    fl.forEach((f) => {
      const { a, b, cloud } = truthEnds(f), g = el("g", { class: "truth-flow" }, gFlows), tip = shorten(b, a, 10);
      el("path", { d: `M${a.x} ${a.y} L${tip.x} ${tip.y}`, stroke: col, "stroke-width": 3.2, fill: "none", "stroke-dasharray": "7 5", opacity: 0.85 }, g);
      arrowHead(g, a, b, col, 12);
      el("title", {}, g).textContent = `True flow: ${f.name}, ${eqText(f.rate)}`;
      if (cloud) window.SDDiagram.cloud(g, cloud, {});
      if (!labels) return;
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, vertical = Math.abs(b.x - a.x) < Math.abs(b.y - a.y);
      const lx = vertical ? mid.x + 14 : mid.x, ly = vertical ? mid.y - 4 : mid.y - 30, anchor = vertical ? "start" : "middle";
      const line2 = `true: ${eqText(f.rate)}`, w = Math.max(f.name.length * 7, line2.length * 6.4) + 12;
      el("rect", { x: anchor === "middle" ? lx - w / 2 : lx - 5, y: ly - 13, width: w, height: 32, rx: 4, fill: "var(--canvas)", opacity: 0.88 }, gLabels);
      text(gLabels, lx, ly, f.name, { "text-anchor": anchor, "font-size": 12.5, "font-weight": 600, fill: "var(--fg)" });
      text(gLabels, lx, ly + 15, line2, { "text-anchor": anchor, "font-size": 11.5, "font-weight": 700, fill: col });
    });
  }
  // An equation in a few characters, as the ladder writes it: "0.5·A", "20", "0.1 + 0.2·B".
  function eqText(r) {
    if (!r) return "";
    if (window.SDLadder && window.SDLadder.rateText) return window.SDLadder.rateText(r);
    return describeRate(r, (id) => id, tu());
  }
  // the stocks a rate reads (a dependency: drawn as a dotted arrow to the flow)
  function foundReads(r) {
    r = r || {};
    if (r.form === "proportional" || r.form === "gap" || r.form === "available") return r.stock ? [r.stock] : [];
    if (r.form === "linear") return (r.terms || []).map((t) => t.stock).filter(Boolean);
    return [];
  }
  // A found flow to or from outside: the cloud of the model's flow with the same ends (so the two
  // read as a pair), else one beside its stock, level with it (never above, under the toolbar).
  function foundCloud(fake) {
    const twin = S.model.flows.find((g) => (g.from || null) === fake.from && (g.to || null) === fake.to);
    if (twin) return cloudPos(twin);
    const st = stock(fake.from || fake.to);
    return fake.from ? { x: st.x + BOX.w + 90, y: st.y + BOX.h + 30 } : { x: st.x - 90, y: st.y + BOX.h + 30 };
  }
  function drawDiscovered() {
    if (!S.discovery) return;
    const g = el("g", { class: "found" }, svg);
    S.discovery.flows.forEach((f, k) => {
      if (f.via) return drawHiddenFound(g, f);
      // an end the model does not have (a stock the strategy inferred without proposing it as one) is drawn as outside
      const fake = { id: `found${k}`, from: f.from && stock(f.from) ? f.from : null, to: f.to && stock(f.to) ? f.to : null };
      if (!fake.from && !fake.to) return;
      if (!fake.from || !fake.to) fake.cloud = foundCloud(fake);
      const { a, b } = ends(fake), dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1;
      const bend = 26 + 8 * (k % 3), mx = (a.x + b.x) / 2 - dy / L * bend, my = (a.y + b.y) / 2 + dx / L * bend;
      const tip = shorten(b, { x: mx, y: my }, 10);
      el("path", { d: `M${a.x} ${a.y} Q${mx} ${my} ${tip.x} ${tip.y}`, fill: "none", stroke: "var(--fit)", "stroke-width": 2.2, "stroke-dasharray": "6 4" }, g);
      arrowHead(g, { x: mx, y: my }, b, "var(--fit)", 10);
      if (!fake.from || !fake.to) drawCloud(g, fake);
      // labelled by its equation (what was found), with the amount it moves now in smaller print
      const txt = `${eqText(currentRate(f))}${f.ratio !== 1 ? ` \u00b7 ${fmtRatio(f.ratio)}` : ""}`, sub = `≈${fmt(f.perStep)}/${tu()} now`;
      const w = Math.max(txt.length * 6.6, sub.length * 5.4) + 8;
      el("rect", { x: mx - w / 2, y: my - 10, width: w, height: 28, rx: 3, fill: "var(--canvas)", opacity: 0.9 }, g);
      text(g, mx, my + 2, txt, { "text-anchor": "middle", "font-size": 11.5, "font-weight": 700, fill: "var(--fit)" });
      text(g, mx, my + 14, sub, { "text-anchor": "middle", "font-size": 9.5, fill: "var(--fit)", opacity: 0.85 });
      foundReads(currentRate(f)).forEach((sid) => {          // what its rate depends on: a dotted arrow, in the found colour
        const src = stock(sid); if (!src) return;
        const m = { x: mx, y: my }, c = center(src), start = clip(src, m);
        const ddx = m.x - c.x, ddy = m.y - c.y, LL = Math.hypot(ddx, ddy) || 1;
        const ctl = { x: (start.x + m.x) / 2 + ddy / LL * 40, y: (start.y + m.y) / 2 - ddx / LL * 40 };
        const end = shorten(m, ctl, 12);
        el("path", { d: `M${start.x} ${start.y} Q${ctl.x} ${ctl.y} ${end.x} ${end.y}`, fill: "none", stroke: "var(--fit)", "stroke-width": 1.2, "stroke-dasharray": "2 4", opacity: 0.8 }, g);
        arrowHead(g, ctl, end, "var(--fit)", 6);
      });
    });
  }
  // Where a stock nobody measures goes: between the stocks it sits between, a little to the side
  // (several hidden stocks are spread apart, alternating sides, so their boxes do not overlap)
  function hiddenPos(f) {
    if (f.via.pos) return f.via.pos;                         // dragged or arranged
    const a = stock(f.from || f.via.echo), b = stock(f.to);
    const ca = a ? center(a) : center(b), cb = center(b);
    const dx = cb.x - ca.x, dy = cb.y - ca.y, L = Math.hypot(dx, dy);
    const n = S.discovery ? S.discovery.flows.filter((g) => g.via).indexOf(f) : 0, k = Math.max(0, n);
    const side = k % 2 ? -1 : 1, off = 110 + Math.floor(k / 2) * (BOX.h + 30);
    let p = L < 1 ? { x: cb.x - BOX.w / 2, y: cb.y + BOX.h / 2 + 70 + k * (BOX.h + 20) }
      : { x: (ca.x + cb.x) / 2 - side * dy / L * off - BOX.w / 2, y: (ca.y + cb.y) / 2 + side * dx / L * off - BOX.h / 2 };
    // move it down until it covers no stock
    const hits = (q) => S.model.stocks.some((st) => shown(st.id) && Math.abs(st.x - q.x) < BOX.w + 20 && Math.abs(st.y - q.y) < BOX.h + 16);
    for (let i = 0; i < 30 && hits(p); i++) p = { x: p.x, y: p.y + BOX.h + 20 };
    return p;
  }
  function drawHiddenFound(g, f) {
    const p = hiddenPos(f), box = { x: p.x, y: p.y }, k = S.discovery.flows.indexOf(f), picked = S.foundPick === k;
    const hg = el("g", { class: "found-stock" + (picked ? " sel" : ""), "data-found-stock": k }, g);
    el("rect", { x: p.x, y: p.y, width: BOX.w, height: BOX.h, rx: 8, fill: "var(--canvas)", stroke: "var(--fit)", "stroke-width": picked ? 3.5 : 2, "stroke-dasharray": "6 4" }, hg);
    text(hg, p.x + BOX.w / 2, p.y + 25, "not measured", { "text-anchor": "middle", "font-size": 11, fill: "var(--fit)", "font-weight": 700 });
    text(hg, p.x + BOX.w / 2, p.y + 44, `holds ~${fmt(f.via.holds)}, ${fmt(f.via.delay)} ${tu()}s`, { "text-anchor": "middle", "font-size": 11, fill: "var(--fit)" });
    const line = (from, to, dashed) => {
      const a = from.box ? clip(from.box, center(to.box || to.s)) : clip(from.s, center(to.box || to.s));
      const b = to.box ? clip(to.box, center(from.box || from.s)) : clip(to.s, center(from.box || from.s));
      const tip = shorten(b, a, 10);
      el("path", { d: `M${a.x} ${a.y} L${tip.x} ${tip.y}`, fill: "none", stroke: "var(--fit)", "stroke-width": 2.2, "stroke-dasharray": dashed ? "2 4" : "6 4" }, g);
      arrowHead(g, a, b, "var(--fit)", 10);
    };
    if (f.from) line({ s: stock(f.from) }, { box }, false);
    else if (f.via.echo && stock(f.via.echo)) line({ s: stock(f.via.echo) }, { box }, true);   // timed by, not taken from
    line({ box }, { s: stock(f.to) }, false);
  }
  function fmtRatio(r) { return r >= 1 ? `${+r.toFixed(2)} in per 1 out` : `1 in per ${+(1 / r).toFixed(2)} out`; }

  // Fit the drawing to the canvas: actual size when it fits, scaled down when it does not.
  // The view is frozen while dragging so the thing under the pointer does not move.
  function fitView() {
    if (!S.model) return;                                     // not loaded yet
    const r = svg.getBoundingClientRect(), W = Math.max(300, r.width), H = Math.max(200, r.height);
    if (S.view) { svg.setAttribute("viewBox", `${S.view.x} ${S.view.y} ${S.view.w} ${S.view.w * H / W}`); return; }
    const pts = [];
    S.model.stocks.forEach((s) => { pts.push([s.x, s.y], [s.x + BOX.w, s.y + BOX.h]); });
    if (truthOn()) Object.values(S.truth.ghosts).forEach((s) => { pts.push([s.x, s.y], [s.x + BOX.w, s.y + BOX.h]); });
    S.model.flows.forEach((f) => { if (!f.from || !f.to) { const c = cloudPos(f); pts.push([c.x - 20, c.y - 20], [c.x + 20, c.y + 20]); } });
    if (S.discovery) S.discovery.flows.forEach((f) => {
      const fake = { from: f.from && stock(f.from) ? f.from : null, to: f.to && stock(f.to) ? f.to : null };
      if (!f.via && (fake.from || fake.to) && !(fake.from && fake.to)) { const c = foundCloud(fake); pts.push([c.x - 20, c.y - 20], [c.x + 20, c.y + 30]); }
    });
    if (!pts.length) { svg.setAttribute("viewBox", `0 0 ${W} ${H}`); return; }
    const pad = 60, top = S.mode === "run" ? 130 : 70;
    const minX = Math.min(0, ...pts.map((p) => p[0])) - 10, minY = Math.min(0, ...pts.map((p) => p[1])) - 10;
    const maxX = Math.max(...pts.map((p) => p[0])) + pad, maxY = Math.max(...pts.map((p) => p[1])) + pad;
    const scale = Math.min(1, W / (maxX - minX), (H - top) / (maxY - minY + top));
    svg.setAttribute("viewBox", `${minX} ${minY - top / scale} ${W / scale} ${H / scale}`);
  }
  function drawCloud(parent, f) { window.SDDiagram.cloud(parent, cloudPos(f), { "data-cloud": f.id }); }
  function marqueeRect() {
    const m = S.marquee; if (!m) return null;
    return { x: Math.min(m.x0, m.x1), y: Math.min(m.y0, m.y1), w: Math.abs(m.x1 - m.x0), h: Math.abs(m.y1 - m.y0) };
  }
  function drawMarquee() {
    const r = marqueeRect(); if (!r || !S.marquee.moved) return;
    el("rect", { x: r.x, y: r.y, width: r.w, height: r.h, class: "marquee" }, svg);
  }
  function itemsInRect(r) {
    const keys = [];
    S.model.stocks.forEach((s) => {
      if (shown(s.id) && s.x < r.x + r.w && s.x + BOX.w > r.x && s.y < r.y + r.h && s.y + BOX.h > r.y) keys.push("s:" + s.id);
    });
    S.model.flows.forEach((f) => { const { a, b } = ends(f); if (segmentHitsRect(a, b, r)) keys.push("f:" + f.id); });
    return keys;
  }

  // ---------- pointer handling ----------
  function svgPoint(evt) {
    const pt = svg.createSVGPoint(); pt.x = evt.clientX; pt.y = evt.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }
  document.addEventListener("pointermove", (e) => { S.pointer = { x: e.clientX, y: e.clientY }; });

  // Pinch (or ctrl/cmd + scroll) zooms around the pointer; scrolling pans. "Fit" in the corner goes back.
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const vb = svg.viewBox.baseVal, r = svg.getBoundingClientRect();
    const v = S.view || { x: vb.x, y: vb.y, w: vb.width };
    const k = v.w / r.width;
    if (e.ctrlKey || e.metaKey) {
      const f = Math.exp(Math.max(-0.5, Math.min(0.5, e.deltaY * 0.01)));
      const px = v.x + (e.clientX - r.left) * k, py = v.y + (e.clientY - r.top) * k;
      const w = Math.max(80, Math.min(200000, v.w * f));
      S.view = { x: px - (px - v.x) * w / v.w, y: py - (py - v.y) * w / v.w, w };
    } else {
      S.view = { x: v.x + e.deltaX * k, y: v.y + e.deltaY * k, w: v.w };
    }
    moveView();
  }, { passive: false });
  function renderViewButton() { $("fitview").classList.toggle("on", !S.view); }
  // Panning and zooming only move the window onto the drawing: the drawing itself stays as it is,
  // so a model with hundreds of stocks moves as smoothly as a small one.
  let viewFrame = 0;
  function moveView() {
    if (viewFrame) return;
    viewFrame = requestAnimationFrame(() => { viewFrame = 0; fitView(); renderViewButton(); });
  }
  $("fitview").addEventListener("click", () => { S.view = null; moveView(); });
  // The bottom panel's height: drag the line above it; double-click puts it back. Remembered per browser.
  (function splitter() {
    const bar = $("splitter"), panel = $("run-panel");
    const setH = (h) => {
      if (!h) { document.body.classList.remove("sized"); document.body.style.removeProperty("--run-h"); }
      else {
        const max = window.innerHeight - 160;
        document.body.style.setProperty("--run-h", `${Math.round(Math.max(90, Math.min(max, h)))}px`);
        document.body.classList.add("sized");
      }
      moveView();
    };
    try { const h = +localStorage.getItem("sdlab.runPanelHeight"); if (h) setH(h); } catch (e) { /* no storage */ }
    bar.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const y0 = e.clientY, h0 = panel.getBoundingClientRect().height;
      bar.setPointerCapture(e.pointerId); bar.classList.add("dragging"); document.body.classList.add("resizing");
      const onMove = (ev) => setH(h0 + (y0 - ev.clientY));
      const onUp = () => {
        bar.removeEventListener("pointermove", onMove); bar.removeEventListener("pointerup", onUp);
        bar.classList.remove("dragging"); document.body.classList.remove("resizing");
        try { localStorage.setItem("sdlab.runPanelHeight", String(Math.round(panel.getBoundingClientRect().height))); } catch (err) { /* no storage */ }
      };
      bar.addEventListener("pointermove", onMove); bar.addEventListener("pointerup", onUp);
    });
    bar.addEventListener("dblclick", () => { setH(0); try { localStorage.removeItem("sdlab.runPanelHeight"); } catch (e) { /* no storage */ } });
  })();
  function zoomBy(f, cx, cy) {
    const vb = svg.viewBox.baseVal, r = svg.getBoundingClientRect();
    const v = S.view || { x: vb.x, y: vb.y, w: vb.width };
    const k = v.w / r.width;
    const px = v.x + (cx === undefined ? r.width / 2 : cx - r.left) * k, py = v.y + (cy === undefined ? r.height / 2 : cy - r.top) * k;
    const w = Math.max(80, Math.min(400000, v.w * f));
    S.view = { x: px - (px - v.x) * w / v.w, y: py - (py - v.y) * w / v.w, w };
    moveView();
  }
  $("zoomin").addEventListener("click", () => zoomBy(1 / 1.4));
  $("zoomout").addEventListener("click", () => zoomBy(1.4));
  // pan: drag with the middle button, or with the space bar held
  function startPan(evt) {
    const vb = svg.viewBox.baseVal;
    S.panning = { cx: evt.clientX, cy: evt.clientY, v: S.view || { x: vb.x, y: vb.y, w: vb.width } };
    svg.setPointerCapture(evt.pointerId);
    svg.classList.add("panning");
  }
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select")) return;
    if (e.code === "Space") { S.space = true; svg.classList.add("grab"); e.preventDefault(); }
    if (e.key === "+" || e.key === "=") zoomBy(1 / 1.4);
    if (e.key === "-" || e.key === "_") zoomBy(1.4);
    if (e.key === "0" && !e.metaKey && !e.ctrlKey) { S.view = null; moveView(); }
  });
  document.addEventListener("keyup", (e) => { if (e.code === "Space") { S.space = false; svg.classList.remove("grab"); } });
  // Find: highlight the stocks whose name matches; Enter selects them and zooms to them.
  $("find").addEventListener("input", (e) => { S.find = e.target.value.trim().toLowerCase(); renderCanvas(); });
  $("find").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.target.value = ""; S.find = ""; renderCanvas(); e.target.blur(); }
    if (e.key !== "Enter" || !S.find) return;
    const hits = S.model.stocks.filter((x) => (x.name + " " + x.id + " " + (x.group || "")).toLowerCase().includes(S.find));
    if (!hits.length) { setStatus("No stock matches", true); return; }
    S.sel = new Set(hits.map((x) => "s:" + x.id)); selectionChanged();
    const xs = hits.map((x) => x.x), ys = hits.map((x) => x.y);
    const minX = Math.min(...xs) - 60, maxX = Math.max(...xs) + BOX.w + 60, minY = Math.min(...ys) - 80;
    S.view = { x: minX, y: minY, w: Math.max(700, maxX - minX) };
    renderCanvas(); renderViewButton(); renderRunPanel();
    setStatus(`${hits.length} stock${hits.length === 1 ? "" : "s"} selected`);
  });

  svg.addEventListener("pointerdown", (evt) => {
    if (evt.button === 1 || (evt.button === 0 && S.space)) { evt.preventDefault(); return startPan(evt); }
    if (evt.button !== 0) return;                    // right-click opens a menu instead
    const p = svgPoint(evt);
    const fs = evt.target.closest("[data-found-stock]");
    if (fs && S.discovery) {                                  // a stock discovery proposes: drag it, or click to see it
      const f = S.discovery.flows[+fs.dataset.foundStock], at = hiddenPos(f);
      S.drag = { sx: p.x, sy: p.y, moving: [], found: { f, x: at.x, y: at.y, k: +fs.dataset.foundStock }, moved: false };
      svg.setPointerCapture(evt.pointerId);
      return;
    }
    const st = evt.target.closest("[data-stock]"), cl = evt.target.closest("[data-cloud]"), fl = evt.target.closest("[data-flow]");
    const key = st ? "s:" + st.dataset.stock : cl ? "f:" + cl.dataset.cloud : fl ? "f:" + fl.dataset.flow : null;

    if (S.pending) {
      if (st) pickEnd({ stock: st.dataset.stock });
      else if (!key) pickEnd({ point: { x: Math.round(p.x), y: Math.round(p.y) } });
      return;
    }
    if (evt.ctrlKey) {                               // ctrl removes; on a Mac this also raises a context menu, which is ignored
      if (key) { S.sel.delete(key); selectionChanged(); }
      else startMarquee(p, "remove", evt);
      return;
    }
    if (!key) return startMarquee(p, evt.shiftKey ? "add" : "replace", evt);

    const wasSelected = isSel(key);
    if (evt.shiftKey) S.sel.add(key);
    else if (!wasSelected) S.sel = new Set([key]);
    selectionChanged();

    if (st || cl) {                                  // drag every selected stock, or the one cloud
      const moving = cl ? [] : selStocks().map((id) => { const s = stock(id); return { id, x: s.x, y: s.y }; });
      const c = cl ? cloudPos(flow(cl.dataset.cloud)) : null;
      S.drag = { sx: p.x, sy: p.y, moving, cloud: cl ? { id: cl.dataset.cloud, x: c.x, y: c.y } : null, moved: false, key, wasSelected, shift: evt.shiftKey };
      svg.setPointerCapture(evt.pointerId);
    } else if (!evt.shiftKey && wasSelected && S.sel.size > 1) {
      S.sel = new Set([key]); selectionChanged();
    }
  });
  function startMarquee(p, mode, evt) {
    S.marquee = { x0: p.x, y0: p.y, x1: p.x, y1: p.y, mode, moved: false };
    svg.setPointerCapture(evt.pointerId);
  }
  svg.addEventListener("pointermove", (evt) => {
    if (S.panning) {
      const r = svg.getBoundingClientRect(), P = S.panning, k = P.v.w / r.width;
      S.view = { x: P.v.x - (evt.clientX - P.cx) * k, y: P.v.y - (evt.clientY - P.cy) * k, w: P.v.w };
      moveView();
      return;
    }
    const p = svgPoint(evt);
    if (S.marquee) {
      const m = S.marquee; m.x1 = p.x; m.y1 = p.y;
      if (!m.moved && Math.hypot(m.x1 - m.x0, m.y1 - m.y0) > 4) m.moved = true;
      if (m.moved) renderCanvas();
      return;
    }
    const d = S.drag; if (!d) return;
    if (!d.moved && Math.hypot(p.x - d.sx, p.y - d.sy) < 4) return;
    d.moved = true;
    const dx = p.x - d.sx, dy = p.y - d.sy;
    d.moving.forEach((m) => { const s = stock(m.id); s.x = Math.round(m.x + dx); s.y = Math.round(m.y + dy); });
    if (d.cloud) flow(d.cloud.id).cloud = { x: Math.round(d.cloud.x + dx), y: Math.round(d.cloud.y + dy) };
    if (d.found) d.found.f.via.pos = { x: Math.round(d.found.x + dx), y: Math.round(d.found.y + dy) };
    renderCanvas();
  });
  svg.addEventListener("pointerup", () => {
    if (S.panning) { S.panning = null; svg.classList.remove("panning"); return; }
    if (S.marquee) {
      const m = S.marquee, r = marqueeRect(); S.marquee = null;
      if (!m.moved) { if (m.mode === "replace") { S.sel.clear(); selectionChanged(); } else renderCanvas(); return; }
      const hits = itemsInRect(r);
      if (m.mode === "replace") S.sel = new Set(hits);
      if (m.mode === "add") hits.forEach((k) => S.sel.add(k));
      if (m.mode === "remove") hits.forEach((k) => S.sel.delete(k));
      return selectionChanged();
    }
    const d = S.drag; S.drag = null; if (!d) return;
    if (d.found) {                                            // not part of the model yet: nothing to save
      if (!d.moved) { S.foundPick = S.foundPick === d.found.k ? null : d.found.k; renderInspector(); }
      renderCanvas(); return;
    }
    if (d.moved) { save(); renderCanvas(); return; }
    if (!d.shift && d.wasSelected && S.sel.size > 1) { S.sel = new Set([d.key]); selectionChanged(); }
  });

  // flow creation: pick where it starts, then where it ends
  function pickEnd(where) {
    const P = S.pending;
    if (P.from === undefined) {
      P.from = where.stock || null;
      if (!where.stock) P.cloud = where.point;
      return renderAll();
    }
    const to = where.stock || null;
    if (!P.from && !to) return;                      // a flow must touch a stock
    if (to && to === P.from) return;
    const name = P.from && to ? `${stockName(P.from)} to ${stockName(to)}` : (to ? `Into ${stockName(to)}` : `Out of ${stockName(P.from)}`);
    const f = { id: uniqueId(name), name, from: P.from, to, rate: { form: "constant", value: 1 }, work: 0.1, machine: null };
    if (!P.from) f.cloud = P.cloud;
    if (!to) f.cloud = where.point;
    S.model.flows.push(f);
    S.pending = null;
    S.sel = new Set(["f:" + f.id]); S.editMachine = null;
    changed();
  }
  function addStock(at) {
    const s = { id: uniqueId("stock"), name: "New stock", unit: "units", initial: 0, x: Math.round(at.x - BOX.w / 2), y: Math.round(at.y - BOX.h / 2) };
    S.model.stocks.push(s);
    S.sel = new Set(["s:" + s.id]); S.editMachine = null;
    changed();
  }
  function newMachine(name) {
    const used = new Set(S.model.machines.map((m) => m.color));
    const color = PALETTE.find((c) => !used.has(c)) || PALETTE[S.model.machines.length % PALETTE.length];
    const m = { id: uniqueId(name || "machine"), name: name || `Machine ${S.model.machines.length + 1}`, kind: "agent", color, capacity: 1, description: "" };
    S.model.machines.push(m);
    return m;
  }
  function applyMachine(flowIds, id) {
    flowIds.forEach((fid) => { const f = flow(fid); if (f) f.machine = id; });
    if (id && id !== "environment") S.recent = [id, ...S.recent.filter((x) => x !== id)].slice(0, 5);
    changed();
    setStatus(`${machineName(id)} applied to ${flowIds.length} flow${flowIds.length === 1 ? "" : "s"}`);
    save();
  }
  function deleteSelection() {
    const st = new Set(selStocks()), fl = new Set(selFlows());
    if (!st.size && !fl.size) return;
    S.model.stocks = S.model.stocks.filter((s) => !st.has(s.id));
    S.model.flows = S.model.flows.filter((f) => !fl.has(f.id) && !st.has(f.from) && !st.has(f.to));
    S.model.flows.forEach((f) => { if (f.rate && st.has(f.rate.stock)) f.rate = { form: "constant", value: 0 }; });
    S.sel.clear();
    changed();
  }
  function deleteMachine(id) {
    S.model.machines = S.model.machines.filter((m) => m.id !== id);
    S.model.flows.forEach((f) => { if (f.machine === id) f.machine = null; });
    S.recent = S.recent.filter((x) => x !== id);
    S.editMachine = null;
    changed();
  }

  // ---------- arrange: lay the stocks out from their flows ----------
  // Stocks that are related go in columns from upstream to downstream (the longest chain leading to
  // a stock decides its column), ordered within a column so related stocks sit side by side.
  // Related means any of: a flow moves things from one to the other; a flow into or out of one has
  // an equation that reads the other (a link: B's arrivals follow A's level), an effect, or a
  // co-flow that uses it up; the flows an open discovery found count too. Stocks related to
  // nothing are packed into a grid, by group and then by name.
  function relations(set) {
    const pairs = [];
    const add = (a, b) => { if (a && b && a !== b && set.has(a) && set.has(b)) pairs.push([a, b]); };
    const found = S.discovery ? S.discovery.flows.map((f) => ({ from: f.from, to: f.to, rate: f.rate })) : [];
    [...S.model.flows, ...found].forEach((f) => {
      add(f.from, f.to);
      (f.outputs || []).forEach((o) => add(f.from, o));
      const end = f.to || f.from;                              // the stock the flow's equation acts on
      const reads = [f.rate && f.rate.stock, ...((f.rate && f.rate.terms) || []).map((t) => t.stock),
                     ...(f.effects || []).map((e) => e.stock), ...(f.uses || []).map((u) => u.stock)];
      reads.forEach((r) => { if (r !== f.from && r !== f.to) add(r, end); });
    });
    return pairs;
  }
  function arrange() {
    const pick = selStocks();
    const ids = pick.length > 1 ? pick : S.model.stocks.map((x) => x.id);
    const set = new Set(ids), list = ids.map(stock);
    // stocks discovery proposes (not in the model yet) are laid out with the rest, between the
    // stocks they connect; their places are kept on the proposal
    const virt = {}, extra = [];
    if (S.discovery) S.discovery.flows.forEach((f, k) => {
      if (!f.via || !(set.has(f.to) && (set.has(f.from) || set.has(f.via.echo)))) return;
      const id = `found:${k}`, at = hiddenPos(f);
      virt[id] = { id, x: at.x, y: at.y, name: "not measured", f };
      ids.push(id);
      extra.push([f.from || f.via.echo, id], [id, f.to]);
    });
    const node = (a) => virt[a] || stock(a);
    const out = new Map(ids.map((i) => [i, []])), inn = new Map(ids.map((i) => [i, []]));
    const seenPair = new Set();
    [...relations(set), ...extra].forEach(([a, b]) => {
      const k = `${a}>${b}`; if (seenPair.has(k)) return; seenPair.add(k);
      out.get(a).push(b); inn.get(b).push(a);
    });
    const old = Object.fromEntries(list.map((x) => [x.id, { x: x.x, y: x.y }]));
    const oldClouds = Object.fromEntries(S.model.flows.filter((f) => f.cloud && (set.has(f.from) || set.has(f.to))).map((f) => [f.id, f.cloud]));
    const x0 = Math.min(...list.map((x) => x.x)), y0 = Math.min(...list.map((x) => x.y));
    // connected groups of stocks (ignoring direction)
    const comp = new Map(); let nc = 0;
    ids.forEach((id) => {
      if (comp.has(id)) return;
      const stack = [id]; comp.set(id, nc);
      while (stack.length) { const a = stack.pop(); [...out.get(a), ...inn.get(a)].forEach((b) => { if (!comp.has(b)) { comp.set(b, nc); stack.push(b); } }); }
      nc++;
    });
    const groups = Array.from({ length: nc }, () => []);
    ids.forEach((id) => groups[comp.get(id)].push(id));
    const connected = groups.filter((g) => g.length > 1).sort((a, b) => b.length - a.length), alone = groups.filter((g) => g.length === 1).map((g) => g[0]);
    let y = y0;
    const COLW = 260, ROWH = 120;
    connected.forEach((g) => {
      // columns from upstream to downstream, ordered by neighbours (diagram.js)
      const cols = columns(g, inn, out, stockName);
      const tall = Math.max(...cols.map((c) => c.length));
      cols.forEach((c, ci) => c.forEach((a, i) => {
        const st = node(a); st.x = Math.round(x0 + ci * COLW); st.y = Math.round(y + (i + (tall - c.length) / 2) * ROWH);
      }));
      y += tall * ROWH + 80;
    });
    S.model.flows.forEach((f) => { if (set.has(f.from) || set.has(f.to)) delete f.cloud; });
    if (alone.length) {
      // a grid shaped like the canvas; each stock's clouds sit diagonally above-left and below-right
      alone.sort((a, b) => (node(a).group || "").localeCompare(node(b).group || "") || stockName(a).localeCompare(stockName(b)));
      const CW = 300, CH = 175, rect = svg.getBoundingClientRect(), aspect = Math.max(0.5, rect.width / Math.max(1, rect.height));
      const per = Math.max(1, Math.min(alone.length, Math.round(Math.sqrt(alone.length * aspect * CH / CW))));
      alone.forEach((a, i) => {
        const st = node(a); st.x = Math.round(x0 + (i % per) * CW); st.y = Math.round(y + 40 + Math.floor(i / per) * CH);
        S.model.flows.forEach((f) => {
          if (f.to === a && !f.from) f.cloud = { x: st.x - 50, y: st.y - 40 };
          if (f.from === a && !f.to) f.cloud = { x: st.x + BOX.w + 50, y: st.y + BOX.h + 40 };
        });
      });
    }
    Object.values(virt).forEach((v) => { v.f.via.pos = { x: v.x, y: v.y }; });
    S.undoLayout = { old, oldClouds };
    S.view = null;
    $("unarrange").hidden = false;
    changed();
    setStatus(`Arranged ${ids.length} stock${ids.length === 1 ? "" : "s"}${pick.length > 1 ? " (the selection)" : ""}`);
  }
  $("arrange").addEventListener("click", arrange);
  $("showhidden").addEventListener("click", () => { S.showHidden = !S.showHidden; renderCanvas(); });
  $("unarrange").addEventListener("click", () => {
    const u = S.undoLayout; if (!u) return;
    Object.entries(u.old).forEach(([id, p]) => { const st = stock(id); if (st) { st.x = p.x; st.y = p.y; } });
    Object.entries(u.oldClouds).forEach(([id, c]) => { const f = flow(id); if (f) f.cloud = c; });
    S.undoLayout = null; $("unarrange").hidden = true; S.view = null;
    changed();
  });

  // ---------- popups: a plain menu, and the machine picker ----------
  const pop = document.createElement("div");
  pop.className = "ctx"; pop.hidden = true;
  document.body.appendChild(pop);
  function closePop() { pop.hidden = true; pop.onkeydown = null; }
  function place(x, y) {
    pop.hidden = false;
    const w = pop.offsetWidth, h = pop.offsetHeight;
    pop.style.left = Math.max(8, Math.min(x, innerWidth - w - 8)) + "px";
    pop.style.top = Math.max(8, Math.min(y, innerHeight - h - 8)) + "px";
  }
  function itemsHtml(items, offset = 0) {
    return items.map((it, i) => it === "-" ? `<hr>` :
      `<button role="menuitem" data-i="${i + offset}" class="${it.danger ? "danger" : ""}"><i class="ck">${it.check || ""}</i>${it.swatch ? `<i class="sw" style="background:${it.swatch}"></i>` : ""}<span>${esc(it.label)}</span></button>`).join("");
  }
  function wireItems(items, offset = 0) {
    pop.querySelectorAll("button[data-i]").forEach((b) => {
      const i = +b.dataset.i - offset; if (i < 0 || i >= items.length) return;
      b.addEventListener("click", () => {
        const it = items[i];
        if (it.confirm && !b.dataset.armed) { b.dataset.armed = "1"; b.querySelector("span").textContent = it.confirm; return; }
        closePop(); it.act();
      });
    });
  }
  function openMenu(x, y, items) {
    pop.setAttribute("role", "menu");
    pop.innerHTML = itemsHtml(items);
    wireItems(items);
    place(x, y);
  }

  // The picker: a search box over every machine, recent ones first. Choosing applies it to flowIds.
  function openPicker(x, y, flowIds, extra = []) {
    pop.setAttribute("role", "dialog");
    pop.innerHTML = `<input class="q" placeholder="Find or create a machine" aria-label="Machine"><div class="opts" role="listbox"></div>${extra.length ? "<hr>" + itemsHtml(extra, 1000) : ""}`;
    const q = pop.querySelector(".q"), opts = pop.querySelector(".opts");
    const using = new Set(flowIds.map((id) => (flow(id) || {}).machine || ""));
    let active = 0, choices = [];
    const mark = (id) => (using.has(id || "") ? (using.size === 1 ? "✓" : "–") : "");
    function build() {
      const term = q.value.trim().toLowerCase();
      const rank = (m) => { const r = S.recent.indexOf(m.id); return r < 0 ? 99 : r; };
      const ms = S.model.machines.filter((m) => m.name.toLowerCase().includes(term))
        .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
      choices = ms.map((m) => ({ label: m.name, swatch: m.color, check: mark(m.id), act: () => applyMachine(flowIds, m.id) }));
      if ("environment".includes(term)) choices.push({ label: "Environment (happens on its own)", swatch: "var(--env)", check: mark("environment"), act: () => applyMachine(flowIds, "environment") });
      if ("no machine".includes(term) || "none".includes(term)) choices.push({ label: "No machine", swatch: "var(--unassigned)", check: mark(null), act: () => applyMachine(flowIds, null) });
      const exact = S.model.machines.some((m) => m.name.toLowerCase() === term);
      if (term && !exact) choices.push({ label: `New machine “${q.value.trim()}”`, act: () => { const m = newMachine(q.value.trim()); applyMachine(flowIds, m.id); } });
      if (!term) choices.push({ label: "New machine…", act: () => { const m = newMachine(); applyMachine(flowIds, m.id); S.sel.clear(); S.editMachine = m.id; renderAll(); } });
      active = Math.min(active, Math.max(0, choices.length - 1));
      opts.innerHTML = choices.map((c, i) => `<button role="option" data-c="${i}" class="${i === active ? "act" : ""}" aria-selected="${i === active}"><i class="ck">${c.check || ""}</i>${c.swatch ? `<i class="sw" style="background:${c.swatch}"></i>` : '<i class="sw"></i>'}<span>${esc(c.label)}</span></button>`).join("");
      opts.querySelectorAll("[data-c]").forEach((b) => b.addEventListener("click", () => { closePop(); choices[+b.dataset.c].act(); }));
    }
    q.addEventListener("input", () => { active = 0; build(); });
    q.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { active = Math.min(choices.length - 1, active + 1); build(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { active = Math.max(0, active - 1); build(); e.preventDefault(); }
      else if (e.key === "Enter") { const c = choices[active]; if (c) { closePop(); c.act(); } e.preventDefault(); }
      else if (e.key === "Escape") { closePop(); e.preventDefault(); }
      e.stopPropagation();
    });
    build();
    wireItems(extra, 1000);
    place(x, y);
    q.focus();
  }
  document.addEventListener("pointerdown", (e) => { if (!pop.hidden && !pop.contains(e.target)) closePop(); }, true);

  svg.addEventListener("contextmenu", (evt) => {
    evt.preventDefault();
    if (evt.ctrlKey && evt.button === 0) return;     // Mac ctrl-click: handled as "remove from selection"
    if (S.pending) { S.pending = null; renderAll(); }
    const p = svgPoint(evt), at = { x: Math.round(p.x), y: Math.round(p.y) };
    const st = evt.target.closest("[data-stock]"), fl = evt.target.closest("[data-flow]") || evt.target.closest("[data-cloud]");
    const key = st ? "s:" + st.dataset.stock : fl ? "f:" + (fl.dataset.flow || fl.dataset.cloud) : null;
    if (key && !isSel(key)) { S.sel = new Set([key]); selectionChanged(); }
    const n = S.sel.size, del = { label: n > 1 ? `Delete ${n} selected` : "Delete", danger: true, act: deleteSelection };
    if (fl) {
      openPicker(evt.clientX, evt.clientY, selFlows(), [del]);
    } else if (st) {
      const s = stock(st.dataset.stock);
      const items = [
        { label: "Draw a flow out of this stock", act: () => { S.pending = { from: s.id }; renderAll(); } },
        { label: s.hide ? "Show this stock" : `Hide ${S.sel.size > 1 ? `${selStocks().length} selected stocks` : "this stock"}`, act: () => { (selStocks().length ? selStocks() : [s.id]).forEach((id) => { const st = stock(id); if (st.hide) delete st.hide; else st.hide = true; }); S.sel.clear(); changed(); } },
        { label: "Draw a flow into this stock from outside", act: () => { S.pending = { from: null, cloud: { x: s.x - 90, y: s.y + BOX.h / 2 } }; pickEnd({ stock: s.id }); } },
      ];
      if (selFlows().length) items.push({ label: `Choose a machine for ${selFlows().length} selected flow${selFlows().length === 1 ? "" : "s"}…`, act: () => openPicker(evt.clientX, evt.clientY, selFlows()) });
      openMenu(evt.clientX, evt.clientY, [...items, "-", del]);
    } else {
      openMenu(evt.clientX, evt.clientY, [
        { label: "Add a stock here", act: () => addStock(at) },
        { label: "Start a flow from outside, here", act: () => { S.pending = { from: null, cloud: at }; S.sel.clear(); renderAll(); } },
      ]);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select")) return;
    if (e.key === "Escape") { closePop(); S.pending = null; S.sel.clear(); S.editMachine = null; renderAll(); }
    else if ((e.key === "Delete" || e.key === "Backspace") && S.sel.size) { e.preventDefault(); deleteSelection(); }
    else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
      e.preventDefault();
      S.sel = new Set([...S.model.stocks.map((s) => "s:" + s.id), ...S.model.flows.map((f) => "f:" + f.id)]);
      selectionChanged();
    } else if (e.key.toLowerCase() === "m" && !e.metaKey && !e.ctrlKey && !e.altKey && selFlows().length) {
      e.preventDefault();
      openPicker(S.pointer.x, S.pointer.y, selFlows());
    }
  });

  // ---------- live runs ----------
  // A model runs live when its machines (or environment flows) name programs. The server owns
  // the stocks and the clock; the page polls it once a second while the Live view is open.
  const runnable = () => S.model.machines.some((m) => m.program) || S.model.flows.some((f) => f.program) || !!(S.model.sensors && S.model.sensors.length) || !!S.model.history || !!S.model.recorded;
  // Polled once a second for a model that can run. Only what changed is redrawn, in place.
  // The first fetch brings the whole run; after that only the steps since the last one, which are
  // appended here, so a run of thousands of steps and hundreds of stocks is not resent every second.
  async function fetchLive() {
    const have = S.live && S.live.series && S.live.series.t.length ? S.live.series.t[S.live.series.t.length - 1] : 0;
    const r = await fetch(`/api/models/${S.model.id}/live?since=${have}${liveQuery()}`);
    if (!r.ok) return;
    const before = S.live ? `${S.live.t}:${S.live.running}:${(S.live.errors || []).length}` : "";
    const fresh = await r.json();
    if (!have || !S.live || fresh.t < have || fresh.length < S.live.series.t.length) {
      if (have && (fresh.t < have || !S.live)) return refetchLive();          // the run was emptied or replaced
      S.live = fresh;
    } else {
      const L = S.live.series, n0 = L.t.length, add = fresh.series;
      L.t.push(...add.t);
      ["levels", "rates", "load"].forEach((key) => {
        const cols = L[key] || (L[key] = {});
        Object.keys(add[key] || {}).forEach((k) => { if (!cols[k]) cols[k] = new Array(n0).fill(0); });
        Object.keys(cols).forEach((k) => { const a = (add[key] || {})[k]; if (a) cols[k].push(...a); else cols[k].push(...new Array(add.t.length).fill(0)); });
      });
      if (add.moved) (L.moved || (L.moved = [])).push(...add.moved);
      const models = Object.fromEntries((S.live.eras || []).map((e) => [e.n, e.model]));
      if (fresh.eras.some((e) => !models[e.n] && !e.model)) return refetchLive();   // a new era: fetch its configuration
      S.live = { ...fresh, series: L, eras: fresh.eras.map((e) => ({ ...e, model: e.model || models[e.n] })) };
    }
    fillInferred();
    // how fast the run is really going, over the last few seconds
    const at = performance.now();
    S.paceLog = [...(S.paceLog || []), [at, S.live.t]].filter(([w]) => at - w < 6000);
    maybeRediscover();
    const one = inspected();
    if (one.type === "stock") await fetchItems(one.obj.id);
    if (`${S.live.t}:${S.live.running}:${(S.live.errors || []).length}` === before) return;
    project();
    if (!S.drag && !S.marquee) renderCanvas();
    renderRunPanel(); renderToolbar(); renderMachineList();
    refreshLiveParts(one);
  }
  async function refetchLive() {
    const r = await fetch(`/api/models/${S.model.id}/live?since=0${liveQuery()}`);
    if (!r.ok) return;
    S.live = await r.json(); fillInferred();
    project(); renderAll();
  }
  // A stock found from the data but never measured has no levels of its own: show what its flows
  // say it holds, step by step, from the measured stocks around it.
  function fillInferred() {
    const L = S.live && S.live.series, inf = S.model.stocks.filter((st) => st.inferred);
    if (!L || !L.t.length || !inf.length) return;
    const flows = S.model.flows.filter((f) => inf.some((st) => st.id === f.from || st.id === f.to));
    const hold = Object.fromEntries(inf.map((st) => [st.id, +st.initial || 0]));
    inf.forEach((st) => { L.levels[st.id] = new Array(L.t.length).fill(0); });
    for (let i = 0; i < L.t.length; i++) {
      const prev = Object.fromEntries(S.model.stocks.map((st) => [st.id, st.id in hold ? hold[st.id] : i ? (L.levels[st.id] || [])[i - 1] || 0 : (L.levels[st.id] || [])[0] || 0]));
      const d = {};
      flows.forEach((f) => {
        const q = window.SDSim.desiredRate(f.rate, prev, f, 1);
        if (f.from in hold) d[f.from] = (d[f.from] || 0) - q;
        if (f.to in hold) d[f.to] = (d[f.to] || 0) + q;
      });
      Object.keys(hold).forEach((id) => { hold[id] = Math.max(0, hold[id] + (d[id] || 0)); L.levels[id][i] = hold[id]; });
    }
  }
  async function fetchItems(stockId) {
    const r = await fetch(`/api/models/${S.model.id}/live/stocks/${stockId}`);
    S.liveItems = r.ok ? { stock: stockId, ...(await r.json()) } : null;
  }
  async function liveAct(action, speed) {
    const body = action === "start" ? JSON.stringify({ seconds_per_tick: speed ?? S.speed ?? (S.live && S.live.seconds_per_tick) ?? 1 }) : "{}";
    if (action === "start") await flushSave();
    const r = await fetch(`/api/models/${S.model.id}/live/${action}${liveQuery().replace(/^&/, "?")}`, { method: "POST", headers: { "Content-Type": "application/json" }, body });
    if (r.ok) S.live = await r.json();
    await refetchLive();
    pollSoon();
    if (action === "start" || action === "stop" || action === "reset") { await fetchList(); renderPick(S.model.id); }
    if (S.discovery && (action === "start" || action === "stop")) renderInspector();   // approving is for a paused run
  }
  function syncPolling() {
    const want = S.model && runnable();
    if (want && !S.poll) { S.poll = {}; pollLoop(S.poll); }
    if (!want && S.poll) { clearTimeout(S.poll.timer); S.poll = null; }
  }
  // While a run goes, ask for news as often as new steps arrive (at most about ten times a second);
  // while it is paused, once a second. Never spend more than about a third of the time fetching and
  // drawing, so a model with hundreds of stocks slows the updates rather than the page.
  async function pollLoop(token) {
    if (S.poll !== token) return;
    const began = performance.now();
    try { await fetchLive(); } catch { /* the server may be restarting: try again later */ }
    if (S.poll !== token) return;
    if (!S.listAt || began - S.listAt > 5000) {             // which models are running, every few seconds
      S.listAt = began;
      fetchList().then((r) => { if (runSign(r) !== S.listSign) renderPick(S.model.id); if ($("files").open) renderFiles(); }).catch(() => {});
    }
    const cost = performance.now() - began, L = S.live;
    let wait = 1000;
    if (L && L.running) wait = Math.min(1000, Math.max(100, 1000 * (L.seconds_per_tick ?? 1)));
    token.timer = setTimeout(() => pollLoop(token), Math.max(wait, 2 * cost));
  }
  // after Start, Pause or a step: the next update now, not at the end of a slow wait
  function pollSoon() {
    const token = S.poll; if (!token) return;
    clearTimeout(token.timer);
    token.timer = setTimeout(() => pollLoop(token), 50);
  }

  // ---------- toolbar and hint ----------
  // an icon button whose words are its tooltip (and what a screen reader says)
  // (a class among the attributes joins "icon": a second class attribute would be ignored)
  const ib = (attrs, icon, tip) => {
    let cls = "icon";
    attrs = attrs.replace(/\s*class="([^"]*)"/, (m, c) => { cls += ` ${c}`; return ""; });
    return `<button class="${cls}" ${attrs} title="${esc(tip)}" aria-label="${esc(tip)}">${icon}</button>`;
  };
  function renderToolbar() {
    const tb = $("toolbar");
    let h = "";
    if (S.mode === "run") {
      if (S.model.recorded && S.model.basic) {
        const b = S.model.basic;
        h += `<label title="Recorded: play back the ladder's recorded data for this case. Live: run the true model now, step by step, through the same engine and seed (its first steps are the recorded data), and keep going past it."><select id="basic-mode" aria-label="Run source">${options([["rec", "Recorded data"], ["live", "Live run"]], S.basicLive ? "live" : "rec")}</select></label>`;
        h += `<label title="The variant: noise none (the engine's exact flows) or counts (whole things), short or long (the recorded length; a live run goes on past it)">\ud83d\udcbe <select id="basic-variant" aria-label="Variant">${options(b.variants.map((v) => [v, v]), S.basicVariant)}</select></label>`;
        h += ib(`data-truth${S.hideTruth ? "" : ' class="on"'}`, "\ud83d\udc41\ufe0f", S.hideTruth ? "Show the truth: draw the case's true flows again" : "Hide the truth: draw only the stocks (and what Discover finds), to compare");
        h += `<a class="btn icon" href="/ladder?view=cases&case=${encodeURIComponent(b.case)}" target="_blank" rel="noopener" title="This case in the ladder view: what every strategy found" aria-label="Open in the ladder view">\ud83e\ude9c</a>`;
        h += `<span class="tsep"></span>`;
      } else if (S.truth) {
        h += ib(`data-truth${S.hideTruth ? "" : ' class="on"'}`, "\ud83d\udc41\ufe0f", S.hideTruth ? `Show the known truth: draw this example's true flows (ladder case ${S.truth.case}), and the stocks its data hides` : "Hide the truth: draw only the stocks (and what Discover finds), to compare");
        h += `<a class="btn icon" href="/ladder?view=cases&case=${encodeURIComponent(S.truth.case)}" target="_blank" rel="noopener" title="This example's case in the ladder view: its true model and what every strategy found" aria-label="Open in the ladder view">\ud83e\ude9c</a>`;
        h += `<span class="tsep"></span>`;
      }
      if (runnable()) {
        const L = S.live || {}, n = L.series ? L.series.t.length : 0;
        const recorded = !!S.model.recorded && !(S.model.basic && S.basicLive);
        if (recorded && S.model.basic) h += ib('data-golive', "▶️", "Run it live: the true model steps through the engine as the clock ticks, with discovery re-estimating as data arrives");
        // a model measured only by its history has nothing to run: a live run would record nothing
        const nothingLive = !S.model.sensors && !!S.model.history && !S.model.machines.some((m) => m.program) && !S.model.flows.some((f) => f.program);
        const why = nothingLive ? "Nothing measures this model live: it only has a history. Use Import history." : "";
        if (!recorded) {
        h += L.running ? ib('data-live="stop"', "⏸️", "Pause the run")
          : ib(`data-live="start"${why ? " disabled" : ""}`, "▶️", why || "Start the run");
        h += ib(`data-live="step"${L.running || why ? " disabled" : ""}`, "⏭️", why || `Step one ${tu()}`);
        // speed is how much model time passes per real second: one step of the model is one time unit
        const u = tu(), us = `${u}s`, per = L.seconds_per_tick ?? 1;
        const speeds = [[60, `1 ${u} every 60 s`], [10, `1 ${u} every 10 s`], [2, `1 ${u} every 2 s`], [1, `1 ${u} a second`], [0.5, `2 ${us} a second`],
          [0.25, `4 ${us} a second`], [0.1, `10 ${us} a second`], [0.04, `25 ${us} a second`], [0, "full speed"]]
          .map(([v, l]) => [v, v && v === stepSeconds() ? `${l} (real time)` : l]);
        h += `<label title="How fast the run goes: how many ${esc(us)} of the model pass each real second. Full speed runs as fast as the programs answer.">\u23f1\ufe0f <select id="speed" aria-label="Speed">${options(speeds, speeds.some(([v]) => v === per) ? per : 1)}</select></label>`;
        if (S.model.history) h += ib("data-import", "📥", "Import history: run this model's history program and replace the run with the levels it reports");
        h += ib('data-live="reset" class="danger"', "🗑️", "Empty every stock: throw the run away and start again");
        }
        const eraLen = n ? (S.live.series.t[n - 1] - currentEra().start + 1) : 0;
        h += `<span class="tsep"></span>`;
        h += ib(`data-upd${eraLen >= 15 ? "" : " disabled"}`, "📐", eraLen >= 15 ? "Fit all equations to this era: fit every flow and save the better equations" : `Fit all equations to this era (run at least 15 ${tu()}s in this era first)`);
        if (S.undo) h += ib("data-undo", "↩️", "Undo the saved fits");
        h += strategyPicker();
        const busy = S.discovering ? ` class="busy"` : "";
        h += ib(`data-discover${busy}${n >= 40 ? "" : " disabled"}`, "🔍", S.discovering ? `Discovering on the server, with ${S.discovering.steps} ${tu()}s of data… Click to start again with the latest data.`
          : n >= 40 ? "Discover flows from stock levels: the simplest flows that explain how the stocks changed" : "Discover flows from stock levels (run at least 40 steps first)");
        h += ib(`data-autodisc${S.autoDiscover ? ' class="on"' : ""}${n >= 40 ? "" : " disabled"}`, "\ud83d\udd04", S.autoDiscover
          ? "Keep discovering is on: discovery runs again as new data arrives. Click to stop."
          : "Keep discovering: run discovery again as new data arrives, and keep its suggestions on screen. Pause the run to approve them.");
        h += ib("data-simplify", "✂️", "Simplify: flows that could go or be merged, and stocks that could be hidden");
      }
      h += `<label title="How far ahead to project, in ${esc(tu())}s">🔭 <input id="horizon" type="number" min="1" value="${S.model.horizon || 100}" aria-label="Project ahead"></label>`;
      h += ib("data-leverage", "🎯", "Where would more speed help? Speed up each flow by 10% in turn and see which one moves your goals most");
    }
    if (tb.dataset.html === h) { renderHint(); return; }   // unchanged: keep it, so an open dropdown stays open
    tb.dataset.html = h;
    tb.innerHTML = h;
    tb.querySelectorAll("[data-upd]").forEach((b) => b.addEventListener("click", updateEquations));
    tb.querySelectorAll("[data-undo]").forEach((b) => b.addEventListener("click", undoEquations));
    tb.querySelectorAll("[data-discover]").forEach((b) => b.addEventListener("click", () => runDiscovery()));
    tb.querySelectorAll("[data-autodisc]").forEach((b) => b.addEventListener("click", () => {
      S.autoDiscover = !S.autoDiscover;
      try { localStorage.setItem("sdlab.autoDiscover", S.autoDiscover ? "1" : ""); } catch { /* fine without it */ }
      renderToolbar();
      if (S.autoDiscover) runDiscovery(true); else if (S.discovery) renderInspector();
    }));
    tb.querySelectorAll("[data-simplify]").forEach((b) => b.addEventListener("click", runSimplify));
    tb.querySelectorAll("[data-leverage]").forEach((b) => b.addEventListener("click", runLeverage));
    tb.querySelectorAll("[data-import]").forEach((b) => b.addEventListener("click", async () => {
      setStatus("Importing history\u2026");
      const r = await fetch(`/api/models/${S.model.id}/live/import`, { method: "POST" });
      if (!r.ok) { setStatus("Could not import: " + ((await r.json().catch(() => ({}))).detail || r.statusText), true); return; }
      S.live = await r.json(); fillInferred(); project(); renderAll(); setStatus(`Imported ${S.live.series.t.length} ${tu()}s of history`);
    }));
    tb.querySelectorAll("[data-live]").forEach((b) => b.addEventListener("click", () => liveAct(b.dataset.live)));
    const bv = $("basic-variant"); if (bv) bv.addEventListener("change", () => setBasicVariant(bv.value));
    const bm = $("basic-mode"); if (bm) bm.addEventListener("change", () => setBasicLive(bm.value === "live"));
    tb.querySelectorAll("[data-golive]").forEach((b) => b.addEventListener("click", () => setBasicLive(true, true)));
    const sg = $("strategy"); if (sg) sg.addEventListener("change", () => setStrategy(sg.value));
    tb.querySelectorAll("[data-truth]").forEach((b) => b.addEventListener("click", () => { S.hideTruth = !S.hideTruth; renderToolbar(); renderCanvas(); const box = $("inspector"), top = box.scrollTop; renderInspector(); box.scrollTop = top; }));
    const sp = $("speed"); if (sp) sp.addEventListener("change", () => { if (S.live && S.live.running) liveAct("start", +sp.value); else S.speed = +sp.value; });
    const hz = $("horizon"); if (hz) hz.addEventListener("change", () => { S.model.horizon = Math.max(1, +hz.value || 1); changed(); });

    renderHint();
  }
  function renderHint() {
    const hint = $("hint");
    const nf = selFlows().length;
    let msg = "";
    if (S.pending) msg = S.pending.from === undefined ? "Click the stock this flow drains, or empty space if it comes from outside the model. Esc cancels." : "Click the stock this flow fills, or empty space if it leaves the model. Esc cancels.";
    else if (!S.model.stocks.length) msg = "Right-click the canvas to add a stock.";
    else if (nf) msg = `${nf} flow${nf === 1 ? "" : "s"} selected. Click a machine on the left, or press M, to apply one.`;
    hint.hidden = !msg; hint.textContent = msg;
  }

  // ---------- inspector ----------
  function field(label, html) { return `<label class="field"><span>${label}</span>${html}</label>`; }
  function input(key, value, type = "text", extra = "") { return `<input data-k="${key}" type="${type}" value="${esc(value ?? "")}" ${extra}>`; }
  function options(list, value) { return list.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(value) ? "selected" : ""}>${esc(l)}</option>`).join(""); }

  function inspected() {
    const st = selStocks(), fl = selFlows();
    const sameSel = S.panelSel === [...S.sel].sort().join();
    if (S.discovery && S.foundPick !== null && S.foundPick !== undefined && S.discovery.flows[S.foundPick]) return { type: "found-stock", obj: S.discovery.flows[S.foundPick] };
    if (S.autoDiscover && S.mode === "run" && S.discovery) return { type: "discovery", obj: S.discovery };   // it stays open
    if (S.mode === "run" && !S.discovery && S.discovering && S.discovering.strategy && !st.length && !fl.length) return { type: "discovering", obj: S.discovering };
    if (S.leverage && sameSel) return { type: "leverage", obj: S.leverage };
    if (S.discovery && sameSel) return { type: "discovery", obj: S.discovery };
    if (S.simplify && sameSel) return { type: "simplify", obj: S.simplify };
    if (st.length + fl.length === 1) return st.length ? { type: "stock", obj: stock(st[0]) } : { type: "flow", obj: flow(fl[0]) };
    if (st.length + fl.length > 1) return { type: "many" };
    if (S.editMachine && machine(S.editMachine)) return { type: "machine", obj: machine(S.editMachine) };
    if (S.firing) return { type: "firing", obj: S.firing };
    if (S.discovery) return { type: "discovery", obj: S.discovery };
    if (S.leverage) return { type: "leverage", obj: S.leverage };
    return { type: "model" };
  }
  function renderInspector() {
    const box = $("inspector"), it = inspected();
    if (it.type === "model") box.innerHTML = overview();
    if (it.type === "many") box.innerHTML = manyForm();
    if (it.type === "stock") box.innerHTML = stockForm(it.obj);
    if (it.type === "flow") box.innerHTML = flowForm(it.obj);
    if (it.type === "machine") box.innerHTML = machineForm(it.obj);
    if (it.type === "firing") box.innerHTML = firingView(it.obj);
    if (it.type === "discovery") { box.innerHTML = discoveryView(it.obj); wireDiscovery(box); }
    if (it.type === "discovering") box.innerHTML = `<h2>Flows found from stock levels</h2><p class="note discrunning" data-disc-pending>⏳ Discovering with <b>${esc(it.obj.strategy)}</b> on ${it.obj.steps} ${esc(tu())}s… Nothing found earlier is shown: the estimate appears here when this strategy has made it.</p>`;
    if (it.type === "found-stock") { box.innerHTML = foundStockView(it.obj); wireFoundStock(box, it.obj); }
    if (it.type === "simplify") { box.innerHTML = simplifyView(it.obj); wireSimplify(box); }
    if (it.type === "leverage") { box.innerHTML = leverageView(it.obj); const c = box.querySelector("[data-lev-close]"); if (c) c.addEventListener("click", () => { S.leverage = null; renderInspector(); }); }
    wireFirings(box);
    box.querySelectorAll("[data-k]").forEach((inp) => {
      const ev = inp.tagName === "SELECT" ? "change" : "input";
      inp.addEventListener(ev, () => applyField(inp, it.obj));
      if (ev === "input") inp.addEventListener("change", () => renderInspector());
    });
    box.querySelectorAll("[data-eff]").forEach((inp) => inp.addEventListener(inp.tagName === "SELECT" ? "change" : "change", () => {
      const e = it.obj.effects[+inp.dataset.eff], key = inp.dataset.ek;
      if (key === "points") e.points = inp.value.split(",").map((p) => p.split(":").map(Number)).filter((p) => p.length === 2 && p.every((x) => isFinite(x)));
      else if (key === "normal" || key === "max") e[key] = inp.value === "" ? undefined : +inp.value;
      else e[key] = inp.value;
      if (key === "shape" && e.shape === "table" && !e.points) e.points = [[0, 0], [+(e.normal || 1), 1]];
      changed(true, { keepInspector: inp.tagName !== "SELECT" });
    }));
    box.querySelectorAll("[data-flag]").forEach((c) => c.addEventListener("change", () => { if (c.checked) it.obj[c.dataset.flag] = true; else delete it.obj[c.dataset.flag]; changed(true, { keepInspector: true }); }));
    box.querySelectorAll("[data-final]").forEach((c) => c.addEventListener("change", () => { if (c.checked) it.obj.final = true; else delete it.obj.final; changed(true, { keepInspector: true }); }));
    box.querySelectorAll("[data-rule]").forEach((c) => c.addEventListener("change", () => { if (c.checked) it.obj.rule = true; else delete it.obj.rule; changed(true, { keepInspector: true }); }));
    box.querySelectorAll("[data-use]").forEach((inp) => inp.addEventListener("change", () => {
      const u = it.obj.uses[+inp.dataset.use];
      u[inp.dataset.uk] = inp.dataset.uk === "per" ? +inp.value : inp.value;
      changed(true, { keepInspector: inp.tagName !== "SELECT" });
    }));
    box.querySelectorAll("[data-out]").forEach((c) => c.addEventListener("change", () => {
      const f = it.obj, set = new Set(f.outputs || []);
      if (c.checked) set.add(c.dataset.out); else set.delete(c.dataset.out);
      if (set.size) f.outputs = [...set]; else { delete f.outputs; delete f.split; }
      changed(true, { keepInspector: true });
    }));
    box.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", (e) => {
      const act = b.dataset.act;
      if (act === "delete") deleteSelection();
      if (act === "delete-machine") deleteMachine(it.obj.id);
      if (act === "fill") { const ids = S.model.flows.filter((f) => !f.machine).map((f) => f.id); if (ids.length) applyMachine(ids, it.obj.id); }
      if (act === "pick") { const r = b.getBoundingClientRect(); openPicker(r.left, r.bottom + 4, selFlows()); }
      const first = (S.model.stocks.find((x) => x.id !== it.obj.from && x.id !== it.obj.to) || S.model.stocks[0] || {}).id;
      if (act === "add-effect") { (it.obj.effects ||= []).push({ stock: first, shape: "linear", normal: 1 }); changed(); }
      if (act === "add-use") { (it.obj.uses ||= []).push({ stock: first, per: 0.01 }); changed(); }
      if (act && act.startsWith("del-effect:")) { it.obj.effects.splice(+act.split(":")[1], 1); if (!it.obj.effects.length) delete it.obj.effects; changed(); }
      if (act && act.startsWith("del-use:")) { it.obj.uses.splice(+act.split(":")[1], 1); if (!it.obj.uses.length) delete it.obj.uses; changed(); }
      if (act === "select-flows") { S.sel = new Set(S.model.flows.filter((f) => f.machine === it.obj.id).map((f) => "f:" + f.id)); selectionChanged(); }
      e.preventDefault();
    }));
  }
  function flowRunsHtml(f) {
    if (!isLive()) return "";
    const rs = (S.live.recent || []).filter((r) => r.flow === f.id).slice(-6).reverse();
    return `<h2 style="margin-top:16px">Its last program runs</h2>${rs.length ? `<ul class="recent">${rs.map(firingRow).join("")}</ul>` : `<p class="note">None kept yet.</p>`}`;
  }
  // The poll updates these two boxes in place; rebuilding the whole panel would steal focus from its inputs.
  function refreshLiveParts(one) {
    const items = $("live-items"), runs = $("flow-runs");
    if (items && one.type === "stock") items.innerHTML = liveItemsHtml(one.obj);
    if (runs && one.type === "flow") { runs.innerHTML = flowRunsHtml(one.obj); wireFirings(runs); }
  }
  function describeTake(f) {
    const spec = f.take && f.take.length ? f.take : (f.from ? [{ as: "item", from: f.from }] : []);
    if (!spec.length) return "Takes nothing: it brings new items in from outside.";
    const parts = spec.map((inp) => {
      const which = inp.order === "oldest" ? "the oldest item" : inp.order === "newest" ? "the newest item" : "any item";
      const where = Object.entries(inp.where || {}).map(([k, v]) => `${esc(k)} = ${esc(v)}`).join(" and ");
      return `<b>${esc(inp.as)}</b>: ${which} in ${esc(stockName(inp.from))}${where ? ` whose ${where}` : ""}`;
    });
    return `Each run takes ${parts.join("; then ")}.`;
  }
  function liveItemsHtml(s) {
    if (!isLive()) return "";
    const L = S.liveItems && S.liveItems.stock === s.id ? S.liveItems : null;
    if (!L) return `<p class="note" style="margin-top:12px">Loading items…</p>`;
    const rows = L.items.slice(0, 25).map((it) => {
      const fields = Object.entries(it).filter(([k]) => !k.startsWith("_")).map(([k, v]) => `${esc(k)}: ${esc(typeof v === "object" ? JSON.stringify(v) : v)}`).join(", ");
      return `<li><span class="iid">${esc(it._id)}</span> ${fields || "<span class=muted>no fields</span>"}</li>`;
    }).join("");
    return `<h2 style="margin-top:16px">Items now (${L.count})</h2>${rows ? `<ul class="items">${rows}</ul>` : `<p class="note">Empty.</p>`}${L.count > 25 ? `<p class="note">Newest 25 shown.</p>` : ""}`;
  }
  // One run of a program: the command line, what it read on stdin, what it wrote.
  function firingView(r) {
    const f = flow(r.flow) || { name: r.flow }, m = machine(f.machine);
    const pretty = (txt) => { try { return JSON.stringify(JSON.parse(txt), null, 2); } catch { return txt; } };
    const out = (r.stdout || "").split("\n").filter((x) => x.trim()).map(pretty).join("\n");
    const prog = (r.program || "").split("/").pop() + ".py";
    return `<h2>Program run</h2><h3>${esc(f.name)} \u00b7 ${esc(tu())} ${r.t}</h3>
      <p class="note">${r.ok ? "Finished" : '<b style="color:var(--bad)">Failed</b>, so its items went back'} in ${r.ms} ms${m ? `, run by ${esc(m.name)}` : f.machine === "environment" ? ", run by the environment" : ""}.</p>
      <div class="field"><span>Command</span><pre class="io">$ python ${esc(prog)} ${esc(r.argv.join(" "))}</pre></div>
      <div class="field"><span>stdin (the items it was given)</span><pre class="io">${esc(pretty(r.stdin || ""))}</pre></div>
      <div class="field"><span>stdout (what it wrote)</span><pre class="io">${esc(out) || '<span class="muted">nothing</span>'}</pre></div>
      ${r.stderr ? `<div class="field"><span>stderr</span><pre class="io err">${esc(r.stderr)}</pre></div>` : ""}
      <p class="note">Program file: sdlab/examples/${esc((r.program || "").split("/")[0])}/machines/${esc(prog)}</p>`;
  }
  function overview() {
    const m = S.model;
    return `<h2>Model</h2><h3>${esc(m.name)}</h3>
      ${field("Name", `<input data-model="name" value="${esc(m.name)}">`)}
      ${field("Time unit", `<input data-model="time_unit" value="${esc(tu())}">`)}
      ${field("Description", `<textarea data-model="description">${esc(m.description || "")}</textarea>`)}
      <div class="stat"><span>Stocks</span><b>${m.stocks.length}</b></div>
      <div class="stat"><span>Flows</span><b>${m.flows.length}</b></div>
      <div class="stat"><span>Machines</span><b>${m.machines.length}</b></div>
      <div class="stat"><span>Flows with no machine</span><b>${m.flows.filter((f) => !f.machine).length}</b></div>
      <p class="note" style="margin-top:12px">Right-click the canvas to add a stock or start a flow. Click to select; shift-click adds, ctrl-click removes, drag on empty space to select an area. With flows selected, click a machine on the left or press M.</p>`;
  }
  document.addEventListener("input", (e) => {
    const k = e.target.dataset && e.target.dataset.model;
    if (!k) return;
    S.model[k] = e.target.value;
    if (k === "name") { const m = [...S.list.models, ...S.list.examples].find((x) => x.id === S.model.id); if (m) { m.name = e.target.value; renderPick(); } }
    changed(true, { keepInspector: true });
  });

  function manyForm() {
    const st = selStocks(), fl = selFlows();
    const parts = [];
    if (fl.length) parts.push(`${fl.length} flow${fl.length === 1 ? "" : "s"}`);
    if (st.length) parts.push(`${st.length} stock${st.length === 1 ? "" : "s"}`);
    const counts = {};
    fl.forEach((id) => { const m = (flow(id) || {}).machine || ""; counts[m] = (counts[m] || 0) + 1; });
    const rows = Object.entries(counts).sort((a, b) => b[1] - a[1])
      .map(([m, n]) => `<div class="stat"><span><i class="dot" style="background:${machineColor(m || null)}"></i>${esc(machineName(m || null))}</span><b>${n}</b></div>`).join("");
    return `<h2>Selection</h2><h3>${parts.join(", ")}</h3>
      ${fl.length ? `<p class="note">Machines on the selected flows:</p>${rows}
      <p style="margin-top:12px"><button class="btn" data-act="pick">Choose a machine… <span class="kbd">M</span></button></p>` : `<p class="note">Select flows to apply a machine to them.</p>`}
      <p style="margin-top:14px"><button class="btn danger" data-act="delete">Delete ${S.sel.size} selected</button></p>`;
  }
  function stockForm(s) {
    const t = s.target || {};
    const ins = S.model.flows.filter((f) => f.to === s.id).map((f) => f.name), outs = S.model.flows.filter((f) => f.from === s.id).map((f) => f.name);
    return `<h2>Stock</h2><h3>${esc(s.name)}</h3>
      ${field("Name", input("name", s.name))}
      <div class="row">${field("Unit", input("unit", s.unit))}${field("Starts at", input("initial", s.initial, "number", 'min="0"'))}</div>
      <div class="row">${field("Goal", input("target.value", t.value, "number"))}${field(`By (${esc(tu())})`, input("target.by", t.by, "number"))}</div>
      <label class="note" style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-final ${s.final ? "checked" : ""}> Final: nothing ever leaves this stock (done, shipped, cancelled)</label>
      <label class="note" style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-flag="hide" ${s.hide ? "checked" : ""}> Hidden on the canvas (it stays in the model)</label>
      <label class="note" style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-flag="keep" ${s.keep ? "checked" : ""}> Keep: Simplify never suggests hiding it</label>
      ${field("Measured by", input("sensor", s.sensor, "text", 'placeholder="not connected (simulated)"'))}
      <p class="note">Later a stock can be measured from outside: a SQL count, a queue's depth, a folder of files.</p>
      <div class="stat"><span>Filled by</span><b>${esc(ins.join(", ") || "nothing")}</b></div>
      <div class="stat"><span>Drained by</span><b>${esc(outs.join(", ") || "nothing")}</b></div>
      <div id="live-items">${liveItemsHtml(s)}</div>
      <p style="margin-top:14px"><button class="btn danger" data-act="delete">Delete stock</button></p>`;
  }
  function flowForm(f) {
    const r = f.rate || { form: "constant" };
    const stocks = S.model.stocks.map((s) => [s.id, s.name]);
    const endsList = [["", "outside the model"], ...stocks];
    let eq = field("Equation", `<select data-k="rate.form">${options([["constant", "Constant rate"], ["proportional", "Proportional to a stock"], ["gap", "Close the gap to a goal"], ["available", "Everything available"]], r.form)}</select>`);
    if (r.form === "available") eq += `<p class="note">Takes everything in ${esc(stockName(f.from) || "its source")} each step, so its machine sets the pace.</p>`;
    if (r.form === "constant") eq += field(`Rate (${esc(unitOf(f))} per ${esc(tu())})`, input("rate.value", r.value, "number"));
    if (r.form === "proportional") eq += `<div class="row">${field("Fraction per " + esc(tu()), input("rate.k", r.k, "number", 'step="0.01"'))}${field("of stock", `<select data-k="rate.stock">${options(stocks, r.stock)}</select>`)}</div>`;
    if (r.form === "gap") eq += field("Stock it watches", `<select data-k="rate.stock">${options(stocks, r.stock)}</select>`) +
      `<div class="row">${field("Goal level", input("rate.goal", r.goal, "number"))}${field(`Closes over (${esc(tu())}s)`, input("rate.time", r.time, "number", 'min="0.01"'))}</div>`;
    const { ser: cs, i } = cur(), rate = cs.rates[f.id] ? cs.rates[f.id][i] || 0 : 0;
    return `<h2>Flow</h2><h3>${esc(f.name)}</h3>
      ${field("Name", input("name", f.name))}
      <div class="row">${field("From", `<select data-k="from">${options(endsList, f.from || "")}</select>`)}${field("To", `<select data-k="to">${options(endsList, f.to || "")}</select>`)}</div>
      ${f.fitted ? `<p class="note">Equation fitted ${esc(f.fitted.when)}. It was: ${esc(describeRate(f.fitted.before, stockName, tu()))}.${(f.fitted.notes || []).map((t) => `<br>${esc(t)}`).join("")}</p>` : ""}
      ${f.from && f.to ? field(`${esc(stockName(f.from))} used per ${esc(stockName(f.to))}`, input("ratio", f.ratio ?? 1, "number", 'step="0.1" min="0"')) : ""}
      ${eq}
      ${f.machine && f.machine !== "environment" ? `<label class="note" style="display:flex;gap:6px;align-items:flex-start"><input type="checkbox" data-rule ${f.rule ? "checked" : ""}> The machine follows this equation as a rule (in a live run it runs this flow no more often than the equation says). Leave it off when the equation only describes what the machine does.</label>` : ""}
      <label class="note" style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-flag="keep" ${f.keep ? "checked" : ""}> Keep: Simplify never suggests removing or merging it</label>
      <h2 style="margin-top:16px">Shaped by other stocks</h2>
      <p class="note">An <b>effect</b> speeds this flow up or slows it down with a stock's level (in proportion to a normal level, or along a curve). A <b>use</b> means each unit moved also uses up some of another stock; the flow stops when it runs out.</p>
      ${(f.effects || []).map((e, i) => `<div class="mini">
        <div class="row">${field("Effect of", `<select data-eff="${i}" data-ek="stock">${options(stocks, e.stock)}</select>`)}${field("Shape", `<select data-eff="${i}" data-ek="shape">${options([["linear", "In proportion"], ["table", "Curve"]], e.shape || "linear")}</select>`)}</div>
        ${(e.shape || "linear") === "linear"
          ? `<div class="row">${field("Full speed at", `<input data-eff="${i}" data-ek="normal" type="number" step="any" value="${esc(e.normal ?? 1)}">`)}${field("Most it can multiply by", `<input data-eff="${i}" data-ek="max" type="number" step="any" value="${esc(e.max ?? 1)}">`)}</div>`
          : field("Curve: level:multiplier, \u2026", `<input data-eff="${i}" data-ek="points" class="code" value="${esc((e.points || []).map((p) => p.join(":")).join(", "))}" placeholder="0:0, 2:0.5, 10:1">`)}
        <button class="btn small" data-act="del-effect:${i}">Remove effect</button></div>`).join("")}
      ${(f.uses || []).map((u, i) => `<div class="mini"><div class="row">${field("Uses up", `<select data-use="${i}" data-uk="stock">${options(stocks, u.stock)}</select>`)}${field(`Per ${esc(unitOf(f))}`, `<input data-use="${i}" data-uk="per" type="number" step="any" min="0" value="${esc(u.per ?? 0)}">`)}</div>
        <button class="btn small" data-act="del-use:${i}">Remove</button></div>`).join("")}
      <p style="display:flex;gap:6px"><button class="btn small" data-act="add-effect">+ Effect</button><button class="btn small" data-act="add-use">+ Uses up a stock</button></p>
      <h2 style="margin-top:16px">Items</h2>
      <p class="note">${describeTake(f)}</p>
      ${field("Takes (advanced)", `<textarea data-k="take" class="code" spellcheck="false" placeholder='[{"as": "item", "from": "${esc(f.from || "")}", "order": "oldest"}]'>${esc(f.take ? "[\n" + f.take.map((x) => " " + JSON.stringify(x)).join(",\n") + "\n]" : "")}</textarea>`)}
      ${f.from || f.to ? `<div class="field"><span>Can also fill</span><div class="checks">${S.model.stocks.filter((x) => x.id !== f.to && x.id !== f.from).map((x) => `<label><input type="checkbox" data-out="${esc(x.id)}" ${(f.outputs || []).includes(x.id) ? "checked" : ""}> ${esc(x.name)}</label>`).join("")}</div></div>` : ""}
      ${field("Arguments for this flow", input("args", (f.args || []).join(" "), "text", 'placeholder="e.g. pair --match colour,size" class="code"'))}
      ${f.machine === "environment" ? field("Program (for the environment)", `<select data-k="program">${options([["", "none (simulated only)"], ...S.programs.map((x) => [x, x])], f.program || "")}</select>`) : ""}
      <h2 style="margin-top:16px">Who does it</h2>
      <p><button class="btn pickbtn" data-act="pick"><i class="dot" style="background:${machineColor(f.machine)}"></i>${esc(machineName(f.machine))} <span class="kbd">M</span></button></p>
      ${f.machine && f.machine !== "environment" ? field(`Machine ${esc(tu())}s per ${esc(unitOf(f))}`, input("work", f.work ?? 0, "number", 'step="0.01" min="0"')) : ""}
      <div class="stat"><span>Rate now (${esc(tu())} ${fmt(cs.t[i])})</span><b>${fmt(rate)} / ${esc(tu())}</b></div>
      <div id="flow-runs">${flowRunsHtml(f)}</div>
      <p style="margin-top:14px"><button class="btn danger" data-act="delete">Delete flow</button></p>`;
  }
  function machineForm(m) {
    const mine = S.model.flows.filter((f) => f.machine === m.id);
    const stat = machineStat(m.id);
    const free = S.model.flows.filter((f) => !f.machine).length;
    return `<h2>Machine</h2><h3 style="color:${esc(m.color)}">${esc(m.name)}</h3>
      ${field("Name", input("name", m.name))}
      <div class="row">${field("Kind", `<select data-k="kind">${options([["person", "Person"], ["agent", "AI agent"], ["code", "Program"]], m.kind)}</select>`)}${field("Colour", input("color", m.color, "color"))}</div>
      <div class="row">${field(`Capacity (${esc(tu())}s of work per ${esc(tu())})`, input("capacity", m.capacity, "number", 'step="0.1" min="0"'))}${field("For each unit of", `<select data-k="capacity_stock">${options([["", "(a fixed amount)"], ...S.model.stocks.map((x) => [x.id, x.name])], m.capacity_stock || "")}</select>`)}</div>
      ${m.capacity_stock ? `<p class="note">Capacity is ${fmt(m.capacity)} \u00d7 ${esc(stockName(m.capacity_stock))}, so it grows and shrinks with that stock.</p>` : ""}
      ${field("Program", `<select data-k="program">${options([["", "none (simulated only)"], ...S.programs.map((x) => [x, x])], m.program || "")}</select>`)}
      ${m.kind === "agent" ? `${field("Prompt: what this agent does with what it is given", `<textarea data-k="prompt" class="prompt">${esc(m.prompt || "")}</textarea>`)}
        <p class="note">The agent is given the items it took, the stocks it may write to, and the level and a few recent items of every stock around it. It runs on the language model at SDLAB_LLM_URL (the local server by default).</p>
        ${field("Give up after (seconds)", input("timeout", m.timeout ?? 180, "number", 'min="5"'))}` : ""}
      ${field("Parameters", input("args", (m.args || []).join(" "), "text", 'placeholder="arguments added after each flow\'s own" class="code"'))}
      ${field("What it does", `<textarea data-k="description">${esc(m.description || "")}</textarea>`)}
      <div class="stat"><span>Flows</span><b>${esc(mine.map((f) => f.name).join(", ") || "none")}</b></div>
      <div class="stat"><span>${stat.measured ? "Busy (last 20 steps)" : "Busy (projected)"}</span><b>${Math.round(stat.busy * 100)}%</b></div>
      <p style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
        ${mine.length ? `<button class="btn" data-act="select-flows">Select its flows</button>` : ""}
        ${free ? `<button class="btn" data-act="fill">Apply to the ${free} flow${free === 1 ? "" : "s"} with no machine</button>` : ""}
        <button class="btn danger" data-act="delete-machine">Delete machine</button></p>`;
  }
  function applyField(inp, obj) {
    const k = inp.dataset.k;
    let v = inp.value;
    if (inp.type === "number") v = v === "" ? "" : +v;
    const path = k.split(".");
    if (path[0] === "target") {
      obj.target ||= {};
      obj.target[path[1]] = v;
      if ((obj.target.value === "" || obj.target.value === undefined) && (obj.target.by === "" || obj.target.by === undefined)) delete obj.target;
    } else if (path[0] === "rate") {
      obj.rate ||= {};
      obj.rate[path[1]] = v;
      if (path[1] === "form") normalizeRate(obj);
    } else if (k === "from" || k === "to") {
      obj[k] = v || null;
      if (!obj.from && !obj.to) obj[k] = inp.options[1] ? inp.options[1].value : null;
      if (obj.from && obj.to) delete obj.cloud;
    } else if (k === "sensor") {
      if (v) obj.sensor = v; else delete obj.sensor;
    } else if (k === "args") {
      const list = String(v).trim().split(/\s+/).filter(Boolean);
      if (list.length) obj.args = list; else delete obj.args;
    } else if (k === "program" || k === "capacity_stock") {
      if (v) obj[k] = v; else delete obj[k];
    } else if (k === "kind") {
      obj.kind = v;
      if (v === "agent" && !obj.program && S.programs.includes("agents/llm")) obj.program = "agents/llm";
    } else if (k === "take") {
      const txt = String(v).trim();
      if (!txt) { delete obj.take; inp.classList.remove("bad"); }
      else {
        try { const t = JSON.parse(txt); if (!Array.isArray(t)) throw new Error(); obj.take = t; inp.classList.remove("bad"); }
        catch { inp.classList.add("bad"); return; }       // keep typing; nothing changes until it parses
      }
    } else obj[k] = v;
    changed(true, { keepInspector: inp.tagName !== "SELECT" });
  }
  function normalizeRate(f) {
    const r = f.rate, first = (S.model.stocks[0] || {}).id;
    if (r.form === "constant") f.rate = { form: "constant", value: r.value ?? 1 };
    if (r.form === "proportional") f.rate = { form: "proportional", stock: r.stock || f.from || first, k: r.k ?? 0.1 };
    if (r.form === "gap") f.rate = { form: "gap", stock: r.stock || f.to || first, goal: r.goal ?? 10, time: r.time ?? 1 };
    if (r.form === "available") f.rate = { form: "available" };
  }

  // ---------- machine panel: a palette of machines ----------
  // With flows selected, clicking a machine applies it to them. With none selected, it opens the machine.
  function buildMachinePanel() {
    $("machines-panel").innerHTML = `<h2>Machines</h2>
      <input id="mfilter" class="mfilter" placeholder="Filter machines" aria-label="Filter machines">
      <ul class="mlist" id="mlist"></ul>
      <button class="btn" id="add-machine">+ Machine</button>`;
    $("mfilter").addEventListener("input", (e) => { S.filter = e.target.value; renderMachineList(); });
    $("mfilter").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { const first = $("mlist").querySelector("[data-m]"); if (first) first.click(); }
      if (e.key === "Escape") { e.target.value = ""; S.filter = ""; renderMachineList(); e.target.blur(); }
    });
    $("add-machine").addEventListener("click", () => {
      const m = newMachine();
      const fl = selFlows();
      if (fl.length) return applyMachine(fl, m.id);
      S.sel.clear(); S.editMachine = m.id; changed();
    });
  }
  function renderMachineList() {
    const list = $("mlist"); if (!list) return;
    // load: measured share of time busy in a live run, otherwise the simulation's work asked of it
    const loads = Object.fromEntries(S.model.machines.map((m) => [m.id, { avgLoad: machineStat(m.id).busy }]));
    const fl = selFlows(), inSel = {};
    fl.forEach((id) => { const m = (flow(id) || {}).machine || "none"; inSel[m] = (inSel[m] || 0) + 1; });
    const count = (id) => S.model.flows.filter((f) => (f.machine || "none") === id).length;
    const term = S.filter.trim().toLowerCase();
    const item = (id, name, color, meta, load, shape, editable) => `<li data-m="${id}" class="${S.editMachine === id && !S.sel.size ? "on" : ""} ${inSel[id] ? "used" : ""}" title="${fl.length ? `Apply ${esc(name)} to ${fl.length} selected flow${fl.length === 1 ? "" : "s"}` : editable ? "Edit this machine" : ""}">
        <div class="name"><i class="sw ${shape || ""}" style="background:${color}"></i><span>${esc(name)}</span>${inSel[id] ? `<span class="insel">${inSel[id]} selected</span>` : ""}${editable ? `<button class="edit" data-edit="${id}" title="Edit machine" aria-label="Edit ${esc(name)}">✎</button>` : ""}</div>
        <div class="meta">${meta}</div>${load === null ? "" : `<div class="load"><i style="width:${Math.min(100, load * 100)}%;background:${load > 1 ? "var(--bad)" : color}"></i></div>`}</li>`;
    let h = "";
    S.model.machines.filter((m) => m.name.toLowerCase().includes(term)).forEach((m) => {
      const l = loads[m.id] || {}, c = count(m.id);
      h += item(m.id, m.name, m.color, `<span><span class="chip">${esc(m.kind)}</span> ${c} flow${c === 1 ? "" : "s"}</span><span>busy ${Math.round((l.avgLoad || 0) * 100)}%</span>`, l.avgLoad || 0, "", true);
    });
    if (!S.model.machines.length) h += `<li class="empty">No machines yet.</li>`;
    if ("environment".includes(term)) h += item("environment", "Environment", "var(--env)", `<span>happens on its own</span><span>${count("environment")} flows</span>`, null, "sq", false);
    if ("no machine".includes(term)) h += item("none", "No machine", "var(--unassigned)", `<span>does not run</span><span>${count("none")} flows</span>`, null, "sq", false);
    list.innerHTML = h;
    list.querySelectorAll("[data-m]").forEach((li) => li.addEventListener("click", (e) => {
      const id = li.dataset.m, edit = e.target.closest("[data-edit]");
      if (!edit && selFlows().length) return applyMachine(selFlows(), id === "none" ? null : id);
      if (machine(id)) { S.sel.clear(); S.editMachine = id; renderAll(); }
    }));
  }

  // ---------- run panel ----------
  // Built once per model structure and tab; polling then only swaps the lines and numbers inside,
  // so scroll positions and clicks are never disturbed.
  function machineStat(id) {
    if (hasData()) {
      const a = (S.live.series.load[id] || []).slice(-20);
      return { busy: a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0, measured: true };
    }
    const m = S.proj && S.proj.summary.machines.find((x) => x.machine === id);
    return { busy: m ? m.avgBusy : 0, measured: false };
  }
  // ---------- eras ----------
  // An era is a stretch of the run with one configuration of the system. The server records
  // them; a run that began before eras were recorded gets one era covering its early part.
  function eras() {
    if (!hasData()) return [];
    const L = S.live.series, last = L.t[L.t.length - 1];
    let list = (S.live.eras || []).map((e) => ({ ...e }));
    if (!list.length || list[0].start > L.t[0]) {
      list.unshift({ n: 0, start: L.t[0], label: "Before eras were recorded", model: S.model, equations: [{ t: L.t[0], rates: Object.fromEntries(S.model.flows.map((f) => [f.id, f.rate])) }] });
    }
    list.forEach((e, k) => { e.end = k + 1 < list.length ? list[k + 1].start - 1 : last; });
    return list;
  }
  function currentEra() { const e = eras(); return e.length ? e[e.length - 1] : { n: 1, start: 1, end: 0, label: "Start" }; }
  function idxOf(t) { const L = S.live.series; return t - L.t[0]; }              // live t is consecutive
  function levelsBefore(t) {                                                     // levels at the end of step t-1
    const L = S.live.series, i = idxOf(t) - 1;
    return Object.fromEntries(S.model.stocks.map((s) => [s.id, i >= 0 ? (L.levels[s.id] || [])[i] || 0 : 0]));
  }
  function sliceRun(from, to) {
    const L = S.live.series, a = Math.max(0, idxOf(from)), b = Math.max(a, idxOf(to) + 1);
    const cut = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v.slice(a, b)]));
    return { t: L.t.slice(a, b), levels: cut(L.levels), rates: cut(L.rates), load: cut(L.load) };
  }
  function withRates(base, rates) {
    return { ...S.model, ...base, stocks: S.model.stocks, flows: (base.flows || S.model.flows).map((f) => (rates && rates[f.id] ? { ...f, rate: rates[f.id] } : f)) };
  }
  // the configuration and equations of an era, replayed from the levels at its start
  function replay(model, from, steps) {
    return simulate(model, { start: levelsBefore(from), t0: from - 1, horizon: Math.max(1, steps) }).series;
  }

  // ---------- fits for the current era (worked out every 10 steps, not every poll) ----------
  // On a large model, fitting covers only the selected flows (and flows touching selected stocks),
  // replayed together with their neighbours: every flow that shares a stock with them.
  const FIT_MAX = 30;
  function fitScope() {
    if (S.model.flows.length <= FIT_MAX) return { model: S.model, flows: null };
    const pickS = selStocks(), ids = new Set([...selFlows(), ...S.model.flows.filter((f) => pickS.includes(f.from) || pickS.includes(f.to)).map((f) => f.id)]);
    if (!ids.size) return null;
    const touched = new Set(S.model.flows.filter((f) => ids.has(f.id)).flatMap((f) => [f.from, f.to]).filter(Boolean));
    const flows = S.model.flows.filter((f) => ids.has(f.id) || touched.has(f.from) || touched.has(f.to));
    flows.forEach((f) => { if (f.from) touched.add(f.from); if (f.to) touched.add(f.to); });
    return { model: { ...S.model, flows, stocks: S.model.stocks.filter((x) => touched.has(x.id)) }, flows: ids };
  }
  function eraFit(now_) {
    const era = currentEra(), L = S.live.series, now = L.t[L.t.length - 1];
    const from = Math.max(era.start, now - 599), len = now - from + 1;
    if (len < 15) return null;
    const scope = fitScope();
    if (!scope) return null;
    const key = `${era.n}:${Math.floor(len / 10)}:${JSON.stringify(scope.model.flows.map((f) => [f.id, f.rate]))}`;
    if (S.fitCache && S.fitCache.key === key) return S.fitCache;
    if (!now_ && scope.model.flows.length > 8) {             // big: do it after drawing, not while the page waits
      if (S.fitPending !== key) {
        S.fitPending = key;
        setTimeout(() => { if (S.fitPending !== key) return; eraFit(true); S.fitPending = null; if (S.mode === "run") updateRunPanel(); }, 60);
      }
      return null;
    }
    S.fitPrev = S.fitPrev || {}; S.fitHist = S.fitHist || {};
    let rows = window.SDSim.fit(scope.model, sliceRun(from, now), { start: levelsBefore(from), prefer: S.fitPrev[era.n] || {}, history: S.fitHist[era.n] || {} });
    const hist = rows.history;
    // a measured model has no data for flows nothing measures (found ones, say), nor for stocks found
    // but never measured: there is nothing to fit them to
    const observed = !!(S.model.sensors || S.model.history);
    const fittable = (id) => {
      const f = flow(id); if (!f) return false;
      if ([f.from, f.to].some((x) => x && (stock(x) || {}).inferred)) return false;
      return !observed || (L.rates[id] || []).some((v) => v);
    };
    { const keep = rows.filter((r) => (!scope.flows || scope.flows.has(r.flow)) && fittable(r.flow)); keep.history = hist; rows = keep; }
    S.fitPrev[era.n] = { ...(S.fitPrev[era.n] || {}), ...Object.fromEntries(rows.map((r) => [r.flow, r.proposed.rate])) };
    S.fitHist[era.n] = { ...(S.fitHist[era.n] || {}), ...hist };
    S.fitCache = { key, rows, from };
    return S.fitCache;
  }
  // flows a chart is about: a flow chart is one flow; a stock chart is the flows that fill or drain it
  function chartFlows(kind, id) {
    if (kind === "f") return [id];
    return S.model.flows.filter((f) => f.from === id || f.to === id || (f.outputs || []).includes(id)).map((f) => f.id);
  }
  function betterFit(kind, id) {
    const F = hasData() && eraFit(); if (!F) return null;
    const rows = F.rows.filter((r) => r.change && chartFlows(kind, id).includes(r.flow));
    return rows.length ? rows : null;
  }

  // ---------- run panel ----------
  // Built once per model structure and tab; polling then only swaps the lines and numbers inside,
  // so scroll positions and clicks are never disturbed.
  function machineStat(id) {
    if (hasData()) {
      const a = (S.live.series.load[id] || []).slice(-20);
      return { busy: a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0, measured: true };
    }
    const m = S.proj && S.proj.summary.machines.find((x) => x.machine === id);
    return { busy: m ? m.avgBusy : 0, measured: false };
  }
  const WINDOWS = [[30], [60], [120], [240], [0]];
  // "last 60 minutes", or "last 240 5-minute steps (20 h)" when the unit is not a plain duration
  function windowLabel(v) {
    if (!v) return "everything";
    const sec = stepSeconds(), plain = UNIT_SECONDS[tu().toLowerCase()] && !S.model.step_seconds;
    if (!sec || plain) return `last ${v} ${tu()}s`;
    const d = v * sec, [u, a] = [[604800, "wk"], [86400, "d"], [3600, "h"], [60, "min"], [1, "s"]].find(([x]) => d >= 2 * x) || [1, "s"];
    return `last ${v} ${tu()}s (${fmt(d / u)} ${a})`;
  }
  function renderRunPanel() {
    const box = $("run-panel");
    if (S.mode !== "run") { box.innerHTML = ""; box.dataset.skel = ""; return; }
    const CHART_MAX = 24;
    const pickS = selStocks(), pickF = [...new Set([...selFlows(), ...S.model.flows.filter((f) => pickS.includes(f.from) || pickS.includes(f.to)).map((f) => f.id)])];
    const allItems = S.tab === "stocks"
      ? (pickS.length ? pickS.map(stock) : S.model.stocks).map((s) => ["s", s.id, s.name])
      : (pickF.length ? pickF.map(flow) : S.model.flows).map((f) => ["f", f.id, f.name]);
    const total = S.tab === "stocks" ? S.model.stocks.length : S.model.flows.length;
    const shown = allItems.slice(0, CHART_MAX);
    const skel = JSON.stringify([S.model.id, S.tab, shown.map((x) => x[1] + x[2]), total]);
    if (box.dataset.skel !== skel) {
      box.dataset.skel = skel;
      const items = shown;
      const more = allItems.length > shown.length || (!pickS.length && !pickF.length && total > shown.length)
        ? `<p class="note">Showing ${shown.length} of ${pickS.length || pickF.length ? allItems.length : total} ${S.tab}. Select ${S.tab} on the canvas (or find them with the search box) to chart those.</p>` : "";
      box.innerHTML = `<div class="run-side"><ul class="findings" id="rf"></ul><div id="rr"></div></div>
        <div class="live-main">
          <div class="runbar">
            <div class="seg"><button data-tab="stocks" class="${S.tab === "stocks" ? "on" : ""}">Stocks</button><button data-tab="flows" class="${S.tab === "flows" ? "on" : ""}">Flows</button></div>
            <label title="How much of the run the charts show. One step of this model is one ${esc(tu())}.">Show <select id="win">${WINDOWS.map(([v]) => `<option value="${v}" ${S.win === v ? "selected" : ""}>${esc(windowLabel(v))}</option>`).join("")}</select> <span id="win-unit"></span></label>
            <input id="scroll" type="range" min="0" max="0" value="0" aria-label="Scroll back in time">
            <span id="scroll-at" class="muted"></span>
          </div>
          <div class="runbar keys">
            <span class="key"><i style="background:var(--accent)"></i>What happened</span>
            <span class="key"><i class="dash" style="border-color:var(--accent)"></i>Today's equations</span>
            <span class="key"><i class="dot" style="border-color:var(--pred)"></i>The equations when this era began</span>
            <span class="key"><i style="background:var(--fit)"></i>A better fit (hover a chart)</span>
            <span class="muted">Each line runs from the start of the era to the end of the projection.</span>
          </div>
          ${more}<div class="charts">${items.map(([k, id, name]) => `<div class="chart" data-kind="${k}" data-id="${esc(id)}" id="ch-${k}-${esc(id)}">
            <div class="ct"><span>${esc(name)}</span><b></b></div>
            <div class="plot"><svg viewBox="0 0 260 86" preserveAspectRatio="none"></svg><div class="eralabs"></div>
              <button class="usefit" hidden>Use this fit</button><div class="fitcap" hidden></div></div>
            <div class="axis"></div></div>`).join("")}</div>
        </div>`;
      box.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => { S.tab = b.dataset.tab; renderRunPanel(); }));
      $("win").addEventListener("change", (e) => { S.win = +e.target.value; S.endAt = null; updateRunPanel(); });
      $("scroll").addEventListener("input", (e) => { const v = +e.target.value; S.endAt = v >= +e.target.max ? null : v; updateRunPanel(); });
      box.querySelectorAll(".chart").forEach((c) => {
        c.addEventListener("mouseenter", () => { S.hover = c.id; updateRunPanel(); });
        c.addEventListener("mouseleave", () => { if (S.hover === c.id) { S.hover = null; updateRunPanel(); } });
        c.querySelector(".usefit").addEventListener("click", () => {
          const rows = betterFit(c.dataset.kind, c.dataset.id);
          if (rows) useFits(rows);
        });
      });
    }
    updateRunPanel();
  }

  function updateRunPanel() {
    const box = $("run-panel"); if (!box || S.mode !== "run" || !$("rf")) return;
    const data = hasData(), L = data ? S.live.series : null, P = S.proj.series;
    const now = data ? L.t[L.t.length - 1] : 0, ahead = Math.max(1, +S.model.horizon || 100);
    const E = eras(), era = currentEra();

    // time window: the last N steps up to "end" (now, unless scrolled back), plus the projection when at now
    const first = data ? L.t[0] - 1 : 0;
    const end = S.endAt !== null && S.endAt !== undefined && S.endAt < now ? S.endAt : now;
    const lo = S.win && data ? Math.max(first, end - S.win) : first;
    const hi = end === now ? now + ahead : end;
    const sc = $("scroll");
    const canScroll = data && S.win && now - first > S.win;
    sc.hidden = !canScroll; $("scroll-at").textContent = canScroll && end !== now ? `ending at ${tu()} ${end}` : "";
    if (canScroll) { sc.min = String(first + S.win); sc.max = String(now); if (document.activeElement !== sc) sc.value = String(end); }
    $("win-unit").textContent = "";

    // left column
    const f = [];
    if (!runnable()) f.push(["", `This model's machines have no programs, so there is nothing to run; the charts show what its equations project from the starting values.`]);
    else if (!data) f.push(["", `No run yet: the charts show what the equations project from the starting values. Press Start to run the real programs.`]);
    else {
      const P = S.paceLog || [], pace = P.length > 1 && S.live.running ? (P[P.length - 1][1] - P[0][1]) / ((P[P.length - 1][0] - P[0][0]) / 1000) : null;
      const shown = pace !== null && pace > 0 ? (pace >= 10 ? Math.round(pace) : +pace.toFixed(1)) : null;
      const going = shown ? ` (about ${shown} ${esc(tu())}${shown === 1 ? "" : "s"} a second)` : "";
      f.push(["", `${S.live.running ? "Running" : "Paused"} at ${esc(tu())} ${now}${going}. Era ${era.n} began at ${esc(tu())} ${era.start}: ${esc(era.label)}.`]);
      const F = eraFit();
      if (F) {
        const ch = F.rows.filter((r) => r.change);
        if (!ch.length) f.push(["good", "The equations fit this era as well as any other would."]);
        else f.push(["warn", `Better fits for this era (hover a chart to see the line):<ul class="fits-list">${ch.map((r) => `<li><b>${esc(flow(r.flow).name)}</b>: ${esc(describeRate(r.current.rate, stockName, tu()))} <span class="muted">\u2192</span> <span class="fitc">${esc(describeRate(r.proposed.rate, stockName, tu()))}</span></li>`).join("")}</ul>`]);
      } else if (!fitScope()) f.push(["", `This model has ${S.model.flows.length} flows. Select flows or stocks to see better-fitting equations for them.`]);
      else if (S.fitPending) f.push(["", "Working out better-fitting equations for the selection\u2026"]);
      else f.push(["", `After 15 ${esc(tu())}s in this era, charts can offer a better-fitting equation.`]);
    }
    S.model.stocks.forEach((s) => {
      if (!s.target || s.target.value === undefined || s.target.value === "") return;
      const goal = +s.target.value, by = s.target.by === undefined || s.target.by === "" ? null : +s.target.by;
      const past = L ? (L.levels[s.id] || []).findIndex((v) => v >= goal) : -1;
      const pi = P.levels[s.id].findIndex((v) => v >= goal);
      const when = past >= 0 ? L.t[past] : pi >= 0 ? P.t[pi] : null, done = past >= 0;
      if (when !== null && (by === null || when <= by)) f.push(["good", `${esc(s.name)} ${done ? "reached" : "is projected to reach"} ${fmt(goal)} at ${esc(tu())} ${fmt(when)}${by !== null ? `, before the goal's ${esc(tu())} ${fmt(by)}` : ""}.`]);
      else if (when !== null) f.push(["warn", `${esc(s.name)} ${done ? "reached" : "is projected to reach"} ${fmt(goal)} only at ${esc(tu())} ${fmt(when)}, after the goal's ${esc(tu())} ${fmt(by)}.`]);
      else f.push(["bad", `${esc(s.name)} is not projected to reach ${fmt(goal)} by ${esc(tu())} ${fmt(P.t[P.t.length - 1])}.`]);
    });
    S.model.machines.forEach((m) => {
      const st = machineStat(m.id);
      f.push([st.busy > 0.95 ? "bad" : "good", `${esc(m.name)} ${st.measured ? "is" : "would be"} busy ${Math.round(st.busy * 100)}% of the time${st.busy > 0.95 ? ", so its flows wait for it" : ""}.`]);
    });
    const unassigned = S.model.flows.filter((x) => !x.machine);
    if (unassigned.length) f.push(["warn", `No machine, so these never run: ${esc(unassigned.map((x) => x.name).join(", "))}.`]);
    if (S.live && S.live.stopped) f.push(["bad", `<b>The run stopped at ${esc(tu())} ${S.live.stopped.t}</b>, because its source keeps failing: ${esc(S.live.stopped.reason)}. Nothing after that was recorded.`]);
    else if (data) (S.live.errors || []).slice(-3).forEach((e) => f.push(["bad", `${esc(e.flow ? (flow(e.flow) || {}).name || e.flow : "Run")} failed at ${esc(tu())} ${e.t}: ${esc(e.error)}`]));
    const fh = f.map(([c, t]) => `<li class="${c}">${t}</li>`).join("");
    if ($("rf").dataset.html !== fh) { $("rf").dataset.html = fh; $("rf").innerHTML = fh; }
    const recent = data ? (S.live.recent || []).slice(-12).reverse().map(firingRow).join("") : "";
    const rr = $("rr");
    const rh = recent ? `<h2 style="margin-top:12px">Last program runs <span class="muted">(click one to see its input and output)</span></h2><ul class="recent">${recent}</ul>` : "";
    if (rr.dataset.html !== rh) { rr.dataset.html = rh; rr.innerHTML = rh; wireFirings(rr); }

    // the model's lines, computed once for all charts
    const visibleEras = E.filter((e) => e.end >= lo && e.start <= end);
    // every model line runs from the start of its era to the end of the projection
    const lines = { now: null, predicted: {}, hoverFit: null };
    const toEnd = now + ahead - era.start + 1;
    // On a large model, replay only what the charts show: the charted stocks (and the stocks at
    // the ends of the charted flows) with the flows that touch them.
    const charted = [...box.querySelectorAll(".chart")].map((c) => [c.dataset.kind, c.dataset.id]);
    const scopeIds = new Set(charted.flatMap(([k, id]) => (k === "s" ? [id] : [(flow(id) || {}).from, (flow(id) || {}).to]).filter(Boolean)));
    const scoped = (m) => {
      if ((m.stocks || []).length <= 40) return m;
      const fl = (m.flows || []).filter((f) => scopeIds.has(f.from) || scopeIds.has(f.to));
      const ids = new Set([...scopeIds, ...fl.flatMap((f) => [f.from, f.to]).filter(Boolean)]);
      return { ...m, flows: fl, stocks: (m.stocks || []).filter((x) => ids.has(x.id)) };
    };
    const replayScoped = (m, from, steps) => replay(scoped(m), from, steps);
    if (data) {
      lines.now = replayScoped(S.model, era.start, toEnd);                                       // this era, with today's equations
      visibleEras.forEach((e) => {
        if (e.n <= 1 && e.label !== "Start" && e.n !== 1) return;                         // nothing was predicted before eras were recorded
        const at = e.equations && e.equations[0] ? e.equations[0].rates : null;
        const span = e === era ? toEnd : e.end - e.start + 1;
        lines.predicted[e.n] = { era: e, s: replayScoped(withRates(e.model || S.model, at), e.start, span) };
      });
      if (S.preview) lines.preview = replayScoped(S.preview, era.start, toEnd);
      const hk = S.hover && document.getElementById(S.hover);
      const rows = hk ? betterFit(hk.dataset.kind, hk.dataset.id) : null;
      if (rows) {
        const rates = Object.fromEntries(rows.map((r) => [r.flow, r.proposed.rate]));
        const fitted = withRates(S.model, rates);
        lines.hoverFit = { s: replayScoped(fitted, era.start, toEnd), rows };
      }
    }

    const W = 260, H = 86, pad = 4, span = Math.max(1e-9, hi - lo);
    const x = (t) => pad + (W - 2 * pad) * ((t - lo) / span);
    const pct = (t) => `${(100 * (t - lo) / span).toFixed(2)}%`;
    const ticks = timeTicks(lo, hi, 4);
    const draw = (node, key, kind) => {
      const series = (s) => (s ? (kind === "s" ? s.levels[key] : s.rates[key]) || [] : []);
      const smooth = (a) => (kind === "f" ? a.map((_, i) => { const sl = a.slice(Math.max(0, i - 4), i + 1); return sl.reduce((p, q) => p + q, 0) / sl.length; }) : a);
      const parts = [];
      const add = (ts, vs, style) => { const pts = []; ts.forEach((t, i) => { if (t >= lo && t <= hi) pts.push([t, vs[i]]); }); if (pts.length) parts.push({ pts, style }); };
      if (L) add(L.t, smooth(series(L)), "live");
      Object.values(lines.predicted).forEach(({ s: sp }) => add(sp.t, series(sp), "pred"));
      if (lines.now) add(lines.now.t, series(lines.now), "model");
      else if (!data) add(P.t, series(P), "model");
      if (lines.preview) add(lines.preview.t, series(lines.preview), "fit");
      const showFit = lines.hoverFit && S.hover === node.id;
      if (showFit) add(lines.hoverFit.s.t, series(lines.hoverFit.s), "fit");
      const target = kind === "s" ? (stock(key) || {}).target : null;
      const goal = target && target.value !== undefined && target.value !== "" ? +target.value : null;
      const max = Math.max(1e-9, ...parts.flatMap((p) => p.pts.map((q) => q[1])), goal && goal <= 3 * Math.max(1, ...parts.flatMap((p) => p.pts.map((q) => q[1]))) ? goal : 0) * 1.08;
      const y = (v) => H - pad - (H - 2 * pad) * (v / max);
      let g = `<rect x="0" y="0" width="${W}" height="${H}" fill="var(--canvas)"/>`;
      visibleEras.forEach((e, k) => {
        const a = Math.max(lo, e.start - 1), b = Math.min(hi, e.end);
        if ((E.indexOf(e) % 2) === 1) g += `<rect x="${x(a)}" y="0" width="${Math.max(0, x(b) - x(a))}" height="${H}" fill="var(--era)"/>`;
        if (e.start - 1 > lo) g += `<line x1="${x(e.start - 1)}" x2="${x(e.start - 1)}" y1="0" y2="${H}" stroke="var(--fg)" stroke-opacity=".35" stroke-dasharray="3 2"/>`;
      });
      if (end === now && data) g += `<rect x="${x(now)}" y="0" width="${Math.max(0, W - x(now))}" height="${H}" fill="var(--rule)" opacity=".35"/>`;
      if (goal !== null) g += `<line x1="${pad}" x2="${W - pad}" y1="${y(goal)}" y2="${y(goal)}" stroke="var(--fg)" stroke-opacity=".45" stroke-dasharray="1 3"/>`;
      const style = {
        live: `stroke="var(--accent)" stroke-width="2"`,
        model: `stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="5 3" stroke-opacity=".9"`,
        pred: `stroke="var(--pred)" stroke-width="1.5" stroke-dasharray="1.5 2.5"`,
        fit: `stroke="var(--fit)" stroke-width="2"`,
      };
      parts.forEach((p) => {
        const d = p.pts.map(([t, v], k) => `${k ? "L" : "M"}${x(t).toFixed(1)} ${y(v).toFixed(1)}`).join("");
        if (p.style === "live") g += `<path d="${d}L${x(p.pts[p.pts.length - 1][0])} ${H - pad}L${x(p.pts[0][0])} ${H - pad}Z" fill="var(--accent)" opacity=".08"/>`;
        g += `<path d="${d}" fill="none" ${style[p.style]} vector-effect="non-scaling-stroke"/>`;
      });
      if (data && end === now) g += `<line x1="${x(now)}" x2="${x(now)}" y1="${pad}" y2="${H - pad}" stroke="var(--fg)" stroke-opacity=".5"/>`;
      node.querySelector("svg").innerHTML = g;
      node.querySelector(".axis").innerHTML = ticks.map(({ t, label }) => { const r = (t - lo) / span; return `<span style="left:${pct(t)};transform:translateX(${r < 0.04 ? "0" : r > 0.96 ? "-100%" : "-50%"})">${esc(label)}</span>`; }).join("");
      node.querySelector(".eralabs").innerHTML = visibleEras.filter((e) => e.n > 0 && e.start - 1 >= lo && (e.start - 1 - lo) / span < 0.85)
        .map((e) => `<span style="left:${pct(e.start - 1)}" title="${esc(e.label)}">era ${e.n}</span>`).join("");
      const last = L && kind === "s" ? (series(L)[series(L).length - 1] || 0) : L ? smooth(series(L)).slice(-1)[0] || 0 : series(P)[0] || 0;
      node.querySelector("b").textContent = `${fmt(last)} ${kind === "s" ? (stock(key) || {}).unit || "" : `per ${tu()}`}`;
      const btn = node.querySelector(".usefit");
      const rows = data ? betterFit(kind, key) : null;
      btn.hidden = !(rows && S.hover === node.id);
      const cap = node.querySelector(".fitcap");
      cap.hidden = btn.hidden;
      if (rows) cap.innerHTML = rows.map((r) => `${esc(flow(r.flow).name)}: <s>${esc(describeRate(r.current.rate, stockName, tu()))}</s> ${esc(describeRate(r.proposed.rate, stockName, tu()))}`).join("<br>");
      if (rows) btn.title = rows.map((r) => `${flow(r.flow).name}: ${describeRate(r.current.rate, stockName, tu())} → ${describeRate(r.proposed.rate, stockName, tu())}`).join("\n");
      node.classList.toggle("hasfit", !!rows);
    };
    box.querySelectorAll(".chart").forEach((node) => draw(node, node.dataset.id, node.dataset.kind));
  }
  // How long one step of the model is, in seconds, when its time unit says so.
  const UNIT_SECONDS = { second: 1, minute: 60, "quarter hour": 900, "half hour": 1800, hour: 3600, day: 86400, week: 604800, month: 2629800, year: 31557600 };
  const stepSeconds = () => +S.model.step_seconds || UNIT_SECONDS[tu().toLowerCase()] || null;
  // Axis marks in real time since the run began: minutes, hours, days or weeks, whichever reads
  // best for the window shown. Models with an unknown time unit get step numbers and the unit.
  function timeTicks(lo, hi, n) {
    const sec = stepSeconds();
    if (!sec) return niceTicks(lo, hi, n).map((t, i, a) => ({ t, label: i === a.length - 1 ? `${fmt(t)} ${tu()}s` : fmt(t) }));
    const spanS = (hi - lo) * sec;
    const units = [[1, "s"], [60, "min"], [3600, "h"], [86400, "d"], [604800, "wk"]];
    const [us, abbr] = [...units].reverse().find(([u]) => spanS / u >= 2) || units[0];
    return niceTicks(lo * sec / us, hi * sec / us, n).map((v) => ({ t: v * us / sec, label: `${fmt(v)} ${abbr}` }));
  }
  function niceTicks(lo, hi, n) {
    const span = Math.max(1, hi - lo), raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 5, 10].map((k) => k * mag).find((k) => k >= raw) || raw;
    const out = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(+t.toFixed(6));
    return out;
  }

  // ---------- simplify ----------
  function runSimplify() {
    const pick = selStocks();
    if (!pick.length && S.model.stocks.length > 200) { setStatus(`This model has ${S.model.stocks.length} stocks. Select the ones to simplify (up to 200).`, true); return; }
    setStatus("Looking for flows and stocks that are not earning their place\u2026");
    setTimeout(() => {
      const t0 = performance.now();
      const L = hasData() ? S.live.series : { t: [], levels: {}, rates: {} };
      const list = window.SDSimplify.suggest(S.model, L, { stocks: pick.length ? pick : null, eras: hasData() ? eras() : [] });
      S.simplify = { list, scope: pick.length, ms: Math.round(performance.now() - t0), steps: L.t.length };
      S.leverage = null; S.discovery = null; S.preview = null; S.panelSel = [...S.sel].sort().join();
      renderInspector(); updateRunPanel();
      setStatus(`${list.length} suggestion${list.length === 1 ? "" : "s"} in ${S.simplify.ms} ms`);
    }, 30);
  }
  function simplifyView(r) {
    if (!r.list.length) return `<h2>Simplify</h2><h3>Nothing to suggest</h3><p class="note">Every flow moved something or explains something, and every stock changes and is connected${r.scope ? " (among the selected stocks)" : ""}.</p><p><button class="btn" data-sp-close>Close</button></p>`;
    const items = r.list.map((sg, i) => `<li class="sg ${S.previewIdx === i ? "on" : ""}"><b>${esc(sg.title)}</b><div class="small">${esc(sg.reason)}</div>
      <div class="sgbtns"><button class="btn small" data-sp-preview="${i}">${S.previewIdx === i ? "Stop preview" : "Preview"}</button><button class="btn small primary" data-sp-apply="${i}">Apply</button></div></li>`).join("");
    return `<h2>Simplify</h2><h3>${r.list.length} suggestion${r.list.length === 1 ? "" : "s"}</h3>
      <p class="note">Each one makes the model simpler without making it fit the data worse${r.scope ? `, among the ${r.scope} selected stocks` : ""}. Stocks are hidden, not removed: their data and equations stay. Preview draws the result in orange on the charts. Anything marked Keep, and every stock with a goal, is left alone.</p>
      <ul class="sglist">${items}</ul>
      <p style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" data-sp-all>Apply all</button>${S.undoSimplify ? `<button class="btn" data-sp-undo>Undo</button>` : ""}<button class="btn" data-sp-close>Close</button></p>`;
  }
  function wireSimplify(box) {
    const r = S.simplify;
    const applyIdx = (idxs) => {
      S.undoSimplify = { stocks: JSON.parse(JSON.stringify(S.model.stocks)), flows: JSON.parse(JSON.stringify(S.model.flows)) };
      let m = S.model;
      idxs.forEach((i) => { m = window.SDSimplify.apply(m, r.list[i]); });
      S.model.stocks = m.stocks; S.model.flows = m.flows;
      r.list = r.list.filter((_, i) => !idxs.includes(i));
      S.preview = null; S.previewIdx = null;
      changed();
      setStatus(`Applied ${idxs.length} suggestion${idxs.length === 1 ? "" : "s"}`);
    };
    box.querySelectorAll("[data-sp-apply]").forEach((b) => b.addEventListener("click", () => applyIdx([+b.dataset.spApply])));
    box.querySelectorAll("[data-sp-preview]").forEach((b) => b.addEventListener("click", () => {
      const i = +b.dataset.spPreview;
      if (S.previewIdx === i) { S.preview = null; S.previewIdx = null; }
      else { S.preview = window.SDSimplify.apply(S.model, r.list[i]); S.previewIdx = i; }
      renderInspector(); updateRunPanel();
    }));
    const all = box.querySelector("[data-sp-all]"); if (all) all.addEventListener("click", () => applyIdx(r.list.map((_, i) => i)));
    const und = box.querySelector("[data-sp-undo]"); if (und) und.addEventListener("click", () => {
      S.model.stocks = S.undoSimplify.stocks; S.model.flows = S.undoSimplify.flows; S.undoSimplify = null; S.simplify = null; changed(); setStatus("Put the model back as it was");
    });
    box.querySelectorAll("[data-sp-close]").forEach((b) => b.addEventListener("click", () => { S.simplify = null; S.preview = null; S.previewIdx = null; renderInspector(); updateRunPanel(); }));
  }

  // ---------- leverage ----------
  function runLeverage() {
    const now = nowState();
    const pickS = selStocks(), pickF = [...new Set([...selFlows(), ...S.model.flows.filter((f) => pickS.includes(f.from) || pickS.includes(f.to)).map((f) => f.id)])];
    if (!pickF.length && S.model.flows.length > 60) { setStatus(`This model has ${S.model.flows.length} flows. Select the flows (or stocks) to compare first.`, true); return; }
    const r = window.SDSim.leverage(S.model, { horizon: Math.max(1, +S.model.horizon || 100), start: now.levels, t0: now.t, flows: pickF.length ? pickF : undefined });
    S.leverage = r; S.editMachine = null; S.firing = null; S.panelSel = [...S.sel].sort().join();
    renderInspector();
  }
  function leverageView(r) {
    if (!r.goals.length) return `<h2>Where would more speed help?</h2><p class="note">Give a stock a goal first (click a stock and fill in Goal). Then this shows which flow, sped up by 10%, moves it most.</p><p><button class="btn" data-lev-close>Close</button></p>`;
    const top = Math.max(1e-9, ...r.rows.map((x) => Math.abs(x.score)));
    const rows = r.rows.map((x) => {
      const f = flow(x.flow), m = machine(f.machine);
      const parts = r.goals.map((g) => `${esc(stockName(g))} ${x.effect[g].change >= 0 ? "+" : ""}${fmt(x.effect[g].change)}`).join(", ");
      return `<li><div class="levrow"><b>${esc(f.name)}</b><span class="muted small">${m ? esc(m.name) : esc(f.machine)}</span></div>
        <div class="levbar"><i style="width:${Math.max(1, 100 * Math.abs(x.score) / top)}%;background:${x.score >= 0 ? "var(--good)" : "var(--bad)"}"></i></div>
        <div class="muted small">${parts} by ${esc(tu())} ${fmt(r.horizon)}</div></li>`;
    }).join("");
    return `<h2>Where would more speed help?</h2><h3>${esc(r.goals.map(stockName).join(", "))}</h3>
      <p class="note">Each flow made 10% faster in turn, projected ${fmt(r.horizon - nowState().t)} ${esc(tu())}s from now. The top of the list is where a faster machine, a second machine or an AI agent would help these goals most.</p>
      <ul class="levlist">${rows}</ul><p><button class="btn" data-lev-close>Close</button></p>`;
  }

  // ---------- which strategy discovers ----------
  // The picker lists every strategy, best on the ladder first (pass rate over the cells it has run,
  // and coverage), from /api/discovery/menu; the default is the ladder's best, and a choice is
  // remembered per browser. The page always sends the strategy by name.
  async function loadMenu() {
    let m = null;
    try { const r = await fetch("/api/discovery/menu"); if (r.ok) m = await r.json(); } catch { /* the server may be restarting */ }
    if (m && Array.isArray(m.strategies)) S.menu = m;
    if (!S.menu || !S.menu.ready) { S.menuTries = (S.menuTries || 0) + 1; if (S.menuTries < 60) setTimeout(loadMenu, 5000); }              // the ladder's numbers are still being worked out
    if (S.model && S.mode === "run") { renderToolbar(); if (S.discovery) { const box = $("inspector"), top = box.scrollTop; renderInspector(); box.scrollTop = top; } }
  }
  const menuRow = (name) => ((S.menu && Array.isArray(S.menu.strategies) && S.menu.strategies) || []).find((x) => x.name === name) || null;
  function currentStrategy() {
    let mine = null; try { mine = localStorage.getItem("sdlab.strategy"); } catch { /* fine */ }
    if (mine && menuRow(mine) && menuRow(mine).available !== false) return mine;
    return (S.menu && S.menu.default) || "matrix";
  }
  const pct = (x) => (x === null || x === undefined ? "–" : `${Math.round(100 * x)}%`);
  const STATUS_MARK = { parked: "parked", "work in progress": "work in progress", "retire-candidate": "retire candidate" };
  function strategyLabel(x, best) {
    const nums = x.pass_rate !== undefined ? ` — ${pct(x.pass_rate)} pass, ${pct(x.coverage)} run` : "";
    const mark = STATUS_MARK[x.status] ? ` [${STATUS_MARK[x.status]}]` : "";
    return `${x.name === best ? "★ " : ""}${x.name}${nums}${mark}${x.available === false ? " (unavailable)" : ""}`;
  }
  function strategyPicker() {
    const m = S.menu && Array.isArray(S.menu.strategies) ? S.menu : { strategies: [], best: null }, cur = currentStrategy();
    const opts = (m.strategies.length ? m.strategies : [{ name: cur }]).map((x) =>
      `<option value="${esc(x.name)}" ${x.name === cur ? "selected" : ""} ${x.available === false ? "disabled" : ""} title="${esc([x.idea, x.how, x.note].filter(Boolean).join("\n\n"))}">${esc(strategyLabel(x, m.best))}</option>`).join("");
    const tip = m.ready ? `Which strategy discovers. Ordered by the ladder's pass rate over the cells each has run (with its coverage). ★ best on the ladder: ${m.best}.` : "Which strategy discovers (the ladder's numbers are still loading)";
    return `<label class="stratpick" title="${esc(tip)}">🧪 <select id="strategy" aria-label="Discovery strategy">${opts}</select></label>`;
  }
  function setStrategy(name) {
    try { localStorage.setItem("sdlab.strategy", name); } catch { /* fine */ }
    const again = hasData() && S.live.series.t.length >= 40 && (S.discovery || S.discovering || S.autoDiscover);
    clearEstimate();                       // what is on screen is only ever the selected strategy's
    renderToolbar(); renderCanvas();
    const box = $("inspector"), top = box.scrollTop; renderInspector(); box.scrollTop = top;
    setStatus(`Discovery strategy: ${name}${S.menu && name === S.menu.best ? " (best on the ladder)" : ""}${again ? `: discovering with ${name}…` : ""}`);
    if (again) runDiscovery(S.autoDiscover);   // a newer job replaces a running one
  }
  // Drop the estimate on screen and any search still running (its result will be ignored): after a
  // change of strategy or variant nothing found before stays on the page.
  function clearEstimate() {
    S.discovery = null; S.discovering = null; S.discToken = (S.discToken || 0) + 1; S.foundPick = null; S.estHist = null; S.lastAutoN = 0; S.lastAutoAt = 0;
  }
  // Which strategy made an estimate, and which version of it: prominent, beside the estimate.
  function strategyBox(r) {
    const name = r.strategy || "matrix", x = menuRow(name) || {}, best = S.menu && S.menu.best;
    const ver = x.commit ? `commit ${esc(x.commit)}${x.date ? ` (${esc(x.date)})` : ""}${x.uncommitted ? ", with uncommitted changes" : ""}` : "";
    const hash = x.hash ? `version ${esc(x.hash)}` : "";
    const nums = x.pass_rate !== undefined && x.pass_rate !== null ? `${pct(x.pass_rate)} pass on the ladder over the ${x.ran} cells it has run (${pct(x.coverage)} of ${x.total})` : "";
    const mark = STATUS_MARK[x.status] ? ` <span class="stratmark">${esc(STATUS_MARK[x.status])}</span>` : "";
    return `<div class="stratbox"><div class="stratname">Estimated by <b>${esc(name)}</b>${name === best ? ' <span class="stratbest">★ best on the ladder</span>' : ""}${mark}</div>
      <div class="small">${[hash, ver].filter(Boolean).join(" · ")}${nums ? `<br>${nums}` : ""}${r.chosen ? `<br>chose ${esc(r.chosen)}` : ""}</div>
      ${x.idea ? `<details class="small"><summary>${esc(x.idea)}</summary>${esc(x.how || "")}${x.note ? `<p class="muted">${esc(x.note)}</p>` : ""}</details>` : ""}</div>`;
  }

  // ---------- discovering flows from stock levels alone ----------
  // Keep discovering: run discovery again once enough new steps have arrived, and never spend
  // more than about a third of the time on it (a large model takes a second or more).
  function maybeRediscover() {
    if (!S.autoDiscover || S.mode !== "run" || !hasData() || S.discovering) return;
    const n = S.live.series.t.length;
    if (n < 40 || (S.lastAutoN && n - S.lastAutoN < Math.max(5, Math.round(0.01 * n)))) return;
    if (performance.now() - (S.lastAutoAt || 0) < Math.max(2000, 3 * ((S.discovery && S.discovery.ms) || 0))) return;
    runDiscovery(true);
  }
  // What discovery is asked: the stocks in scope, their levels, the announced eras, and what is
  // already known about each step (measured flows, and what the model's own unmeasured flows'
  // equations predict), as the known change of each stock in each step.
  function discoveryRequest() {
    const pick = selStocks().filter((id) => !(stock(id) || {}).inferred && (stock(id) || {}).measured !== false);   // stocks found earlier, or nobody measures, have no data
    const L = S.live.series;
    const E = eras().map((e) => ({ start: e.start, label: e.label || null }));
    // measured models send no per-step accounting: it is each measured flow's amount, from and to its stocks
    if ((S.model.sensors || S.model.history) && S.model.flows.some((f) => f.query)) {
      const qf = S.model.flows.filter((f) => f.query && L.rates[f.id]);
      L.moved = L.t.map((_, i) => Object.fromEntries(qf.map((f) => {
        const a = L.rates[f.id][i] || 0, r = f.ratio === undefined || f.ratio === null || f.ratio === "" ? 1 : +f.ratio;
        return [f.id, { took: f.from ? { [f.from]: a * r } : {}, made: f.to ? { [f.to]: a } : {} }];
      })));
    }
    let measuredMoves = L.moved && L.moved.some((m) => m && Object.keys(m).length) ? L.moved : null;
    // a measured model with only levels, whose flows were all found earlier: their equations are what is known
    if (!measuredMoves && (S.model.sensors || S.model.history) && S.model.flows.some((f) => f.found)) measuredMoves = L.t.map(() => ({}));
    // The model's flows that nothing measures (no program) still say what the model expects:
    // add what their equations predict for each step, so a flow already added is not "missing".
    let moved = measuredMoves;
    if (measuredMoves) {
      const measured = new Set(measuredMoves.flatMap((m) => Object.keys(m || {})));
      const unmeasured = S.model.flows.filter((f) => f.machine && !measured.has(f.id) && !(f.program || (machine(f.machine) || {}).program));
      if (unmeasured.length) {
        // a stock found earlier but never measured has no data: its level is what its flows say
        const hold = Object.fromEntries(S.model.stocks.filter((st) => st.inferred).map((st) => [st.id, +st.initial || 0]));
        moved = measuredMoves.map((m, i) => {
          const prev = Object.fromEntries(S.model.stocks.map((st) => [st.id, st.id in hold ? hold[st.id] : i ? (L.levels[st.id] || [])[i - 1] || 0 : 0]));
          const extra = { ...(m || {}) };
          unmeasured.forEach((f) => {
            const q = window.SDSim.desiredRate(f.rate, prev, f, 1), r = f.ratio === undefined || f.ratio === null || f.ratio === "" ? 1 : +f.ratio;
            extra["model:" + f.id] = { took: f.from ? { [f.from]: q * r } : {}, made: f.to ? { [f.to]: q } : {} };
            if (f.from in hold) hold[f.from] = Math.max(0, hold[f.from] - q * r);
            if (f.to in hold) hold[f.to] += q;
          });
          return extra;
        });
      }
    }
    const useKnown = !S.discoverFromNothing && !!measuredMoves;
    const scopeStocks = pick.length ? S.model.stocks.filter((x) => pick.includes(x.id)) : S.model.stocks.filter((x) => !x.inferred && x.measured !== false);
    const ids = new Set(scopeStocks.map((x) => x.id)), n = L.t.length;
    const known = {};
    if (useKnown) moved.forEach((m, i) => Object.values(m || {}).forEach((x) => {
      const add = (s, v) => { if (ids.has(s) && Number.isFinite(+v)) (known[s] || (known[s] = new Array(n).fill(0)))[i] += +v; };
      Object.entries(x.made || {}).forEach(([s, v]) => add(s, v));
      Object.entries(x.took || {}).forEach(([s, v]) => add(s, -v));
    }));
    const body = {
      stocks: scopeStocks.map((x) => ({ id: x.id, unit: x.unit, final: x.final, group: x.group })),
      run: { t: L.t, levels: Object.fromEntries(scopeStocks.map((x) => [x.id, L.levels[x.id] || new Array(n).fill(0)])) },
      eras: E.length > 1 ? E : [], known, strategy: currentStrategy(),
    };
    return { body, pick, scopeStocks, eras: E.length, useKnown, canResidual: !!measuredMoves };
  }
  // Discovery runs on the server, as a background job (a newer request replaces an older one); the
  // last result stays on screen while a new one is worked out.
  async function runDiscovery(auto) {
    if (!hasData()) return;
    if (S.discoverFromNothing === undefined) S.discoverFromNothing = false;
    const q = discoveryRequest(), model = S.model.id, token = (S.discToken || 0) + 1, t0 = performance.now();
    S.discToken = token;
    S.discovering = { auto: !!auto, steps: q.body.run.t.length, since: Date.now(), strategy: q.body.strategy };
    if (!auto) setStatus(`Searching for the simplest flows that explain the stocks (${q.body.run.t.length} ${tu()}s)…`);
    showDiscovering();
    const stale = () => token !== S.discToken || !S.model || S.model.id !== model;
    let st;
    try {
      const post = await fetch(`/api/models/${model}/discovery`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(q.body) });
      if (!post.ok) throw new Error(((await post.json().catch(() => ({}))).detail) || post.statusText);
      const job = (await post.json()).job;
      do {
        st = await fetch(`/api/models/${model}/discovery?job=${job}&wait=20`).then((x) => x.json());
        if (stale()) return;                                  // replaced by a newer request, or another model
      } while (st.state === "running");
      if (st.state !== "done") throw new Error(st.error || `the search was ${st.state}`);
    } catch (e) {
      if (stale()) return;
      S.discovering = null; S.lastAutoAt = performance.now(); S.lastAutoN = q.body.run.t.length;
      showDiscovering();
      setStatus(`Discovery failed: ${e.message || e}`, true);
      return;
    }
    S.discovering = null;
    if (!hasData()) return;
    const r = st.result;
    r.strategy = r.strategy || st.strategy || q.body.strategy;
    if (r.strategy !== q.body.strategy || q.body.strategy !== currentStrategy()) {     // not the strategy selected now: never shown
      showDiscovering();
      if (!auto) setStatus(`Ignored a result from ${r.strategy}: ${currentStrategy()} is selected`);
      return;
    }
    r.scope = q.pick.length; r.total = q.scopeStocks.length;
    r.steps = q.body.run.t.length; r.eras = q.eras; r.ms = Math.round(performance.now() - t0);
    r.residual = q.useKnown; r.canResidual = q.canResidual;
    r.at = q.body.run.t[q.body.run.t.length - 1];
    r.flows.forEach((f) => { f.nearly ||= []; f.rates ||= [f.rate]; f.ratio ??= 1; });
    r.unexplained ||= {};
    S.lastAutoN = q.body.run.t.length; S.lastAutoAt = performance.now();
    // a proposed stock that was dragged keeps its place when the same one is found again
    const placed = new Map(((S.discovery && S.discovery.flows) || []).filter((f) => f.via && f.via.pos).map((f) => [`${f.from}>${f.to}<${f.via.echo || ""}`, f.via.pos]));
    r.flows.forEach((f) => { if (f.via && placed.has(`${f.from}>${f.to}<${f.via.echo || ""}`)) f.via.pos = placed.get(`${f.from}>${f.to}<${f.via.echo || ""}`); });
    const pickedKey = S.discovery && S.foundPick != null && S.discovery.flows[S.foundPick] ? `${S.discovery.flows[S.foundPick].from}>${S.discovery.flows[S.foundPick].to}` : null;
    S.foundPick = pickedKey ? (() => { const i = r.flows.findIndex((f) => f.via && `${f.from}>${f.to}` === pickedKey); return i >= 0 ? i : null; })() : null;
    if ((S.model.basic || S.truth) && S.discovery && S.discovery.compare && S.discovery.strategy === r.strategy) { r.compare = S.discovery.compare; r.compareStale = true; }
    S.discovery = r; S.leverage = null; S.panelSel = [...S.sel].sort().join();
    if (!auto) { S.editMachine = null; S.firing = null; }
    renderCanvas(); renderToolbar();
    // keep the panel where it was scrolled: it is redrawn every time new suggestions arrive
    const box = $("inspector"), top = box.scrollTop;
    renderInspector(); box.scrollTop = top;
    if (!auto) setStatus(`Found ${r.flows.length} flow${r.flows.length === 1 ? "" : "s"} in ${r.ms} ms`);
    if (S.model.basic || S.truth) compareWithTruth(r, model);
  }
  // A basic model's estimate against its truth (the ladder's scorer, on the steps it was found
  // from), and the estimate's history: each true number's estimate as the steps accumulate.
  async function compareWithTruth(r, model) {
    let c;
    try {
      const res = await fetch(`/api/models/${model}/truth-compare`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(S.model.basic ? { flows: r.flows, steps: r.steps, variant: S.basicVariant, live: !!S.basicLive }
          : { flows: r.flows, steps: r.steps, last: lastLevels(r.steps) }) });
      if (!res.ok) c = { error: String(((await res.json().catch(() => ({}))).detail) || res.statusText || res.status) };
      else c = await res.json();
    } catch { c = { error: "the server did not answer" }; }
    if (!c || c.error || !Array.isArray(c.parts)) {
      if (S.discovery === r) { r.compare = { error: (c && c.error) || "no comparison came back" }; r.compareStale = false; if (inspected().type === "discovery") { const box = $("inspector"), top = box.scrollTop; renderInspector(); box.scrollTop = top; } }
      return;
    }
    if (S.discovery !== r || !S.model || S.model.id !== model) return;
    r.compare = c; r.compareStale = false;
    const key = `${S.basicVariant}|${S.basicLive ? "live" : "rec"}|${r.strategy}`;
    if (!S.estHist || S.estHist.key !== key) S.estHist = { key, parts: {} };
    const num = (v) => (typeof v === "number" ? v : v && typeof v === "object" && typeof v.mean === "number" ? v.mean : null);
    c.parts.forEach((p) => {
      const tv = num(p.true); if (tv === null) return;
      const h = S.estHist.parts[p.key] || (S.estHist.parts[p.key] = { truth: tv, pts: [] });
      h.truth = tv; h.windows = !!(p.true && typeof p.true === "object");
      h.pts = h.pts.filter((q) => q[0] < r.steps);                 // a run started again: the old points go
      h.pts.push([r.steps, p.found ? num(p.found_value) : null]);
      if (h.pts.length > 400) h.pts.splice(0, h.pts.length - 400);
    });
    if (inspected().type === "discovery") { const box = $("inspector"), top = box.scrollTop; renderInspector(); box.scrollTop = top; }
  }
  // an example's levels at the last step an estimate was found from: the server checks its run is the case's data
  function lastLevels(n) {
    const L = S.live && S.live.series;
    if (!L || !n) return {};
    return Object.fromEntries(S.model.stocks.filter((x) => L.levels[x.id] && L.levels[x.id].length >= n).map((x) => [x.id, L.levels[x.id][n - 1]]));
  }
  // the stocks of the truth that the example's data does not show
  function truthHiddenHtml() {
    if (S.model.basic || !S.truth || !S.truth.ghostList.length) return "";
    const g = S.truth.ghostList, drawn = Object.keys(S.truth.ghosts).length;
    return `<details class="small" style="margin-top:8px"><summary>The truth has ${g.length} stock${g.length === 1 ? "" : "s"} hidden in the data${drawn ? " (drawn dashed on the canvas)" : " (not drawn: too many)"}</summary>
      <ul class="found-list">${g.map((s) => `<li><b>${esc(s.name)}</b> <span class="muted">${esc(s.id)}, ${esc(s.unit || "")}</span></li>`).join("")}</ul></details>`;
  }
  const signedNum = (x) => (x > 0 ? "+" : x < 0 ? "−" : "±") + String(+Math.abs(x).toPrecision(3));
  function truthCompareHtml(r) {
    if (!S.model.basic && !S.truth) return "";
    if (S.hideTruth) return `<p class="note">The truth is hidden: show it (\ud83d\udc41\ufe0f) to compare this estimate with the true equations.</p>`;
    const c = r.compare;
    if (!c) return `<p class="note">Comparing with the truth…</p>`;
    if (c.error) return `<h2 style="margin-top:14px">Against the truth</h2><p class="note">Not compared: ${esc(c.error)}</p>${truthHiddenHtml()}`;
    const L = window.SDLadder, pn = (k) => (L ? L.partName(k) : k), fv = (v) => (L ? L.fmt(v) : fmt(v));
    const num = (v) => (typeof v === "number" ? v : v && typeof v === "object" && typeof v.mean === "number" ? v.mean : null);
    // a number with what it multiplies: "0.5·A" for a part read from A, "20" for a constant
    const term = (key, v) => { const k = L && L.parseKey ? L.parseKey(key) : null; return k && k.kind === "flow" && k.reader && k.reader !== "const" ? `${fv(v)}·${k.reader}` : fv(v); };
    const rows = (c.parts || []).map((p) => {
      const a = num(p.found_value), b = num(p.true);
      const diff = p.found && a !== null && b !== null ? `${signedNum(a - b)}${b ? ` (${signedNum(100 * (a - b) / Math.abs(b))}%)` : ""}` : "";
      const cls = p.ok ? "ok" : p.found ? "wrong" : "missing";
      return `<tr class="cmp-${cls}"><td>${p.ok ? "✓" : p.found ? "~" : "−"}</td><td>${esc(pn(p.key))}</td><td>${esc(term(p.key, p.true))}</td><td>${p.found ? esc(term(p.key, p.found_value)) : "not found"}</td><td>${esc(diff)}</td></tr>`;
    }).join("") + (c.spurious || []).map((p) => `<tr class="cmp-spurious"><td>+</td><td>${esc(pn(p.key))}</td><td>–</td><td>${esc(term(p.key, p.value))}</td><td>remove</td></tr>`).join("");
    const b = S.model.basic || { case: S.truth.case }, strat = r.strategy || "matrix", bv = S.model.basic ? S.basicVariant : c.variant || S.truth.variant;
    const links = `<p class="note">On the ladder: <a href="/ladder/strategy?name=${encodeURIComponent(strat)}" target="_blank" rel="noopener">${esc(strat)}'s cases</a> (find ${esc(S.model.basic ? b.case.slice(0, 3) : b.case)}) · <a href="/ladder?view=now&case=${encodeURIComponent(b.case)}&variant=${encodeURIComponent(bv)}&strategy=${encodeURIComponent(strat)}" target="_blank" rel="noopener">this case's ladder result, every part</a> (on the recorded data, not this run)</p>`;
    const rep = c.repairs;
    const verdict = { pass: "right: every true number within tolerance, nothing extra", equivalent: "equivalent: the same behaviour, read another way", fail: "not right yet" }[c.status] || c.status;
    return `<h2 style="margin-top:14px">Against the truth</h2>
      <p class="note">On the ${c.steps} ${esc(tu())}s it was found from, by the ladder's scorer: <b class="cmp-verdict cmp-${esc(c.status)}">${esc(verdict)}</b>${rep && rep.headline ? ` · ${esc(rep.headline)}` : ""}.</p>
      ${r.compareStale ? `<p class="note">These are the previous estimate's; the newest is being compared.</p>` : ""}
      <table class="kv cmp"><tr><th></th><th>Part</th><th>True</th><th>Found</th><th>Found − true</th></tr>${rows}</table>
      ${rep && rep.items && rep.items.length ? `<ul class="found-list">${rep.items.map((it) => `<li>${esc(it.text)}</li>`).join("")}</ul>` : ""}
      ${convergenceHtml()}${truthHiddenHtml()}${links}`;
  }
  // Small multiples: each true number's estimate (line) against its true value (dashed) as the steps grew.
  function convergenceHtml() {
    const H = S.estHist && S.estHist.parts, keys = H ? Object.keys(H).filter((k) => H[k].pts.length) : [];
    if (!keys.length) return "";
    const L = window.SDLadder, pn = (k) => (L ? L.partName(k) : k);
    const W = 300, Hh = 64, P = { l: 44, r: 8, t: 6, b: 16 };
    const charts = keys.map((k) => {
      const h = H[k], pts = h.pts.filter((q) => q[1] !== null && Number.isFinite(q[1]));
      const xs = h.pts.map((q) => q[0]), x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1);
      const ys = [h.truth, ...pts.map((q) => q[1])], y0 = Math.min(...ys), y1 = Math.max(...ys), pad = (y1 - y0) * 0.1 || Math.abs(h.truth) * 0.1 || 1;
      const lo = y0 - pad, hi = y1 + pad;
      const X = (x) => P.l + (W - P.l - P.r) * (x - x0) / (x1 - x0), Y = (y) => P.t + (Hh - P.t - P.b) * (1 - (y - lo) / (hi - lo));
      const line = pts.map((q, i) => `${i ? "L" : "M"}${X(q[0]).toFixed(1)},${Y(q[1]).toFixed(1)}`).join("");
      const last = pts[pts.length - 1];
      const dots = pts.map((q) => `<circle cx="${X(q[0]).toFixed(1)}" cy="${Y(q[1]).toFixed(1)}" r="5" fill="transparent"><title>${esc(tu())} ${q[0]}: ${fmt(q[1])} (true ${fmt(h.truth)})</title></circle>`).join("");
      return `<figure class="conv"><figcaption>${esc(pn(k))}${h.windows ? " (its mean over the eras)" : ""}: true ${fmt(h.truth)}${last ? `, now ${fmt(last[1])}` : ", not found"}</figcaption>
        <svg viewBox="0 0 ${W} ${Hh}" width="100%" role="img" aria-label="${esc(`Estimate of ${pn(k)} as the steps grew, against its true value ${fmt(h.truth)}`)}">
          <line x1="${P.l}" x2="${W - P.r}" y1="${Y(h.truth).toFixed(1)}" y2="${Y(h.truth).toFixed(1)}" class="conv-truth"/>
          <text x="${P.l - 4}" y="${(Y(hi - pad) + 4).toFixed(1)}" class="conv-ax" text-anchor="end">${fmt(hi - pad)}</text>
          <text x="${P.l - 4}" y="${Y(lo + pad).toFixed(1)}" class="conv-ax" text-anchor="end">${fmt(lo + pad)}</text>
          <text x="${P.l}" y="${Hh - 3}" class="conv-ax">${x0}</text><text x="${W - P.r}" y="${Hh - 3}" class="conv-ax" text-anchor="end">${x1} ${esc(tu())}s</text>
          <path d="${line}" class="conv-est"/>${last ? `<circle cx="${X(last[0]).toFixed(1)}" cy="${Y(last[1]).toFixed(1)}" r="4" class="conv-dot"/>` : ""}${dots}
        </svg></figure>`;
    }).join("");
    return `<h3 style="margin-top:12px">How the estimate converges</h3><p class="note">Each true number's estimate after each re-discovery (line), against its true value (dashed).</p><div class="convs">${charts}</div>`;
  }
  // Discovery is running: the toolbar's button says so, and an open findings panel notes it.
  function showDiscovering() {
    renderToolbar();
    const note = document.querySelector("#inspector [data-disc-running]");
    if (note) note.hidden = !S.discovering;
    else if ((S.discovering && ["discovery", "discovering"].includes(inspected().type)) || (!S.discovering && document.querySelector("#inspector [data-disc-pending]"))) { const box = $("inspector"), top = box.scrollTop; renderInspector(); box.scrollTop = top; }
  }
  // The rate a found flow has now: the configuration in force at the end of the run, or the outside
  // inflow's latest level (a found inflow may change over time; the model's equation is one number).
  function currentRate(f) {
    if (f.byTime && f.byTime.length) return f.byTime.reduce((a, b) => (b.from > a.from ? b : a)).rate;
    if (f.inflow && f.inflow.length > 1) return { form: "constant", value: +Math.max(0, +f.inflow[f.inflow.length - 1].value).toFixed(4) };
    return f.rate;
  }
  const nodeName = (id) => (id ? stockName(id) : "outside");
  const SHAPES = { exp: "it lets things go in proportion to what it holds, like a lab or a vendor working through a pile",
    erlang: "things leave it bunched around that time, like a follow-up after a fixed-ish wait",
    pipe: "everything waits about the same time, like a pipeline or a fixed-length process" };
  function hiddenView(f) {
    const v = f.via, span = v.delayMin !== v.delayMax ? ` (anything from ${fmt(v.delayMin)} to ${fmt(v.delayMax)} fits about as well)` : "";
    const what = f.from
      ? `About ${fmt(f.perStep)} per ${esc(tu())} leave <b>${esc(stockName(f.from))}</b> and arrive in <b>${esc(stockName(f.to))}</b> about ${fmt(v.delay)} ${esc(tu())}s later${span}.`
      : `About ${fmt(f.perStep)} per ${esc(tu())} arrive in <b>${esc(stockName(f.to))}</b> about ${fmt(v.delay)} ${esc(tu())}s after arriving in <b>${esc(stockName(v.echo))}</b>${span}: ${fmt(v.share * 100)}% of them come back.`;
    return `<li>${what} In between they wait in a stock nobody measures, holding about <b>${fmt(v.holds)}</b> at a time; ${SHAPES[v.shape]}.</li>`;
  }
  // One stock discovery proposes, picked on the canvas: what it is, and adding just it.
  function foundStockView(f) {
    const v = f.via, live = S.autoDiscover && S.live && S.live.running;
    const into = f.from ? stockName(f.from) : `after arriving in ${stockName(v.echo)}`;
    return `<h2>Stock nobody measures</h2><h3>Between ${esc(into)} and ${esc(stockName(f.to))}</h3>
      <p class="note">Proposed by discovery, not part of the model yet. Drag it on the canvas to place it; adding it keeps that place.</p>
      <ul class="found-list">${hiddenView(f)}</ul>
      <table class="kv">
        <tr><th>Holds on average</th><td>${fmt(v.holds)}</td></tr>
        <tr><th>Delay</th><td>${fmt(v.delay)} ${esc(tu())}s${v.delayMin !== v.delayMax ? ` (${fmt(v.delayMin)} to ${fmt(v.delayMax)} fit about as well)` : ""}</td></tr>
        <tr><th>Shape</th><td>${esc(v.shape)}</td></tr>
        <tr><th>Flow in</th><td>${esc(describeRate(f.rate, stockName, tu()))}</td></tr>
      </table>
      <p style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn primary" data-found-one ${live ? 'disabled title="Pause the run to approve it"' : ""}>Add this stock and its two flows</button>
        <button class="btn" data-found-back>All findings</button></p>`;
  }
  function wireFoundStock(box, f) {
    box.querySelector("[data-found-back]").addEventListener("click", () => { S.foundPick = null; renderCanvas(); renderInspector(); });
    box.querySelector("[data-found-one]").addEventListener("click", () => {
      const parts = hiddenParts(f, uniqueId, uniqueId);
      parts.stocks.forEach((x) => S.model.stocks.push(x));
      parts.flows.forEach((x) => S.model.flows.push(x));
      S.discovery.flows = S.discovery.flows.filter((g) => g !== f);
      S.foundPick = null;
      S.sel = new Set([...parts.stocks.map((x) => "s:" + x.id), ...parts.flows.map((x) => "f:" + x.id)]);
      fillInferred(); changed();
      setStatus(`Added ${parts.stocks[0].name} and its two flows`);
    });
  }
  function discoveryView(r) {
    const latent = r.flows.filter((f) => f.via);
    const flows = r.flows.filter((f) => !f.via).map((f) => {
      // the rate per configuration (era label) when the engine found that they differ
      const names = r.labels || [];
      const short = (s) => (s.length > 28 ? `${s.slice(0, 27)}…` : s);
      const per = f.rates.length > 1 ? `<div class="muted small">by era: ${f.rates.map((x, i) => `<span title="${esc(names[i] || "")}">${esc(names[i] ? short(names[i]) : i + 1)}</span>: ${esc(describeRate(x, stockName, tu()))}`).join("; ")}</div>` : `<div class="muted small">${esc(describeRate(f.rate, stockName, tu()))}</div>`;
      const conv = f.ratio !== 1 ? ` <span class="muted">(${esc(fmtRatio(f.ratio))})</span>` : "";
      const alt = f.nearly.length ? `<div class="small warnc">Fits about as well: ${esc(f.nearly.slice(0, 4).join("; "))}${f.nearly.length > 4 ? `, and ${f.nearly.length - 4} more` : ""}</div>` : "";
      const drive = f.driver && f.from !== f.driver && f.to !== f.driver ? `<div class="muted small">follows the level of ${esc(stockName(f.driver))}</div>` : "";
      const note = f.note ? `<div class="muted small">${esc(f.note.replace(/\b[a-z0-9_]+\b/g, (w) => (stock(w) ? stockName(w) : w)))}</div>` : "";
      const vals = (f.inflow || []).map((g) => +g.value);
      const changes = vals.length > 1 ? `<div class="muted small">changes ${vals.length - 1} time${vals.length === 2 ? "" : "s"} (between ${fmt(Math.min(...vals))} and ${fmt(Math.max(...vals))} per ${esc(tu())}); now ${fmt(vals[vals.length - 1])}</div>` : "";
      return `<li><b>${esc(nodeName(f.from))} \u2192 ${esc(nodeName(f.to))}</b>${conv}, about ${fmt(f.perStep)} per ${esc(tu())}${f.bothWays ? " (both ways)" : ""}${per}${drive}${note}${changes}${alt}</li>`;
    }).join("");
    const left = Object.entries(r.unexplained).filter(([, u]) => u.persistent);
    const ambiguous = r.flows.filter((f) => f.nearly.length >= 3).length;
    const intro = r.residual
      ? `Your measured flows (and what your other flows' equations predict) explain part of how each stock changed. These are the simplest flows that explain <b>the rest</b>, over ${r.steps} ${esc(tu())}s${r.eras > 1 ? ` and ${r.eras} eras` : ""}: things happening in the real system that the model does not show.`
      : `The simplest set of flows that explains how every stock changed over ${r.steps} ${esc(tu())}s${r.eras > 1 ? ` and ${r.eras} eras` : ""}, from the stock levels alone, ignoring the flows you have. They are drawn in orange on the canvas. Other structures may explain the data too; what matters is that this one does.`;
    const scopeNote = (r.scope ? `<p class="note">Searched among the ${r.scope} selected stocks; flows to stocks outside the selection show as flows to or from outside.</p>` : "")
      + (r.searched !== undefined ? `<p class="note">${r.explained} of the ${r.total} stocks were already fully explained${r.residual ? " by the measured flows" : ""}; the other ${r.searched} were searched${r.together ? `, ${r.together} groups of related stocks together and the rest one by one` : " one by one"}.</p>` : "");
    const live = S.autoDiscover && S.live && S.live.running;
    const autoNote = S.autoDiscover ? `<p class="note autonote">\ud83d\udd04 Keeps updating as data arrives: last at ${esc(tu())} ${r.at} (${r.ms} ms). ${live ? "Pause the run to approve these flows." : "The run is paused: approve these flows, or start it again to keep watching."}</p>` : "";
    const running = `<p class="note discrunning" data-disc-running ${S.discovering ? "" : "hidden"}>⏳ Discovering again with the latest data; these are the last findings until it is done.</p>`;
    const engine = `<p class="note small">Found on the server by the <b>${esc(r.strategy || "matrix")}</b> strategy${r.chosen ? ` (${esc(r.chosen)})` : ""}, in ${fmt(r.computeMs || 0)} ms.</p>`;
    return `<h2>Flows found from stock levels</h2>${strategyBox(r)}${running}${autoNote}${scopeNote}<h3>${r.flows.length ? `${r.flows.length} flow${r.flows.length === 1 ? "" : "s"}${r.residual ? " the model is missing" : ""}` : r.residual ? "Nothing is missing" : "No flows"}</h3>
      <p class="note">${intro}</p>
      ${r.canResidual ? `<label class="note" style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-found-nothing ${S.discoverFromNothing ? "checked" : ""}> Ignore my flows and start from nothing</label>` : ""}
      ${r.residual && !r.flows.length ? `<p class="note">The measured flows explain every stock's change; what remains is step-to-step scatter.</p>` : ""}
      ${ambiguous ? `<p class="note warnc">For ${ambiguous} of these, other flows fit about as well. This run did not move enough to tell them apart: change something (a machine, a capacity) and run again, and the difference in how the stocks respond will separate them.</p>` : ""}
      <ul class="found-list">${flows}</ul>
      ${truthCompareHtml(r)}
      ${latent.length ? `<h2 style="margin-top:14px">${latent.length} stock${latent.length === 1 ? "" : "s"} nobody measures</h2><p class="note">These are inferred from the timing: what arrives is a delayed copy of what left. They are drawn dashed on the canvas. Adding them adds the hidden stock and its two flows, so projections include the wait; measuring it would confirm it.</p><ul class="found-list">${latent.map(hiddenView).join("")}</ul>` : ""}
      <h2 style="margin-top:14px">Not explained</h2>
      ${left.length ? `<ul class="found-list">${left.map(([id, u]) => `<li><b>${esc(stockName(id))}</b> drifts ${fmt(u.drift)} per ${esc(tu())} that no flow explains. A stock or flow is probably missing here.</li>`).join("")}</ul>` : `<p class="note">Every stock's change is explained; what remains is step-to-step scatter.</p>`}
      ${(r.hidden || []).length && !latent.length ? `<h2 style="margin-top:14px">Probably a stock nobody measures</h2><ul class="found-list">${r.hidden.slice(0, 3).map((h) => `<li>Things leave <b>${esc(stockName(h.from))}</b> and about as many arrive in <b>${esc(stockName(h.to))}</b>${h.delay !== null ? ` about ${fmt(h.delay)} ${esc(tu())}s later` : ""}. They are probably waiting somewhere in between${h.holds !== null ? `: a stock holding about ${fmt(h.holds)} at a time` : ""}. Measure it and add it to the model.</li>`).join("")}</ul>` : ""}
      ${r.flows.some((f) => (f.byTime && f.byTime.length) || (f.inflow && f.inflow.length > 1)) ? `<p class="note">A flow whose rate changed over the run joins the model with the rate it has now.</p>` : ""}
      ${engine}
      <p style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">${r.flows.length ? (r.residual ? `<button class="btn primary" data-found-add ${live ? 'disabled title="Pause the run to approve these flows"' : ""}>Add these flows to the model</button>` : `<button class="btn primary" data-found-model ${live ? 'disabled title="Pause the run to approve these flows"' : ""}>Make a new model from these flows</button>`) : ""}<button class="btn" data-found-close>Close</button></p>`;
  }
  function wireDiscovery(box) {
    const c = box.querySelector("[data-found-close]"); if (c) c.addEventListener("click", () => { S.discovery = null; renderCanvas(); renderInspector(); });
    const mk = box.querySelector("[data-found-model]"); if (mk) mk.addEventListener("click", makeFoundModel);
    const add = box.querySelector("[data-found-add]"); if (add) add.addEventListener("click", addFoundFlows);
    const nothing = box.querySelector("[data-found-nothing]"); if (nothing) nothing.addEventListener("change", () => { S.discoverFromNothing = nothing.checked; runDiscovery(); });
  }
  function foundFlow(f, k, idBase) {
    const fl = { id: idBase(k), name: `${nodeName(f.from)} to ${nodeName(f.to)}`, from: f.from, to: f.to, rate: currentRate(f), machine: "environment",
                 found: { when: new Date().toISOString().slice(0, 10), steps: S.discovery.steps } };
    if (f.ratio !== 1) fl.ratio = +f.ratio.toFixed(4);
    if (!f.from || !f.to) { const st = stock(f.from || f.to); fl.cloud = { x: st.x + (f.from ? BOX.w + 90 : -90), y: st.y + BOX.h / 2 + 40 }; }
    return fl;
  }
  // The missing flows join the model as environment flows: the model now expects them, and the
  // projection includes them. They have no program, so the live run is unchanged.
  // A flow through a stock nobody measures becomes that stock and two flows: in at the rate found,
  // out in proportion to what it holds (one over the delay; for a fixed delay this is the nearest
  // equation the model has).
  function hiddenParts(f, stockId, flowId) {
    const p = hiddenPos(f), found = { when: new Date().toISOString().slice(0, 10), steps: S.discovery.steps };
    const to = stock(f.to), name = f.from ? `Between ${stockName(f.from)} and ${stockName(f.to)}` : `Coming back to ${stockName(f.to)}`;
    const st = { id: stockId(name), name, unit: to.unit, initial: Math.round(f.via.holds), x: Math.round(p.x), y: Math.round(p.y),
                 inferred: { shape: f.via.shape, delay: f.via.delay, ...found } };
    const inFlow = { id: flowId(`into ${name}`), name: `into ${name.toLowerCase()}`, from: f.from, to: st.id, rate: currentRate(f), machine: "environment", found };
    if (!f.from) inFlow.cloud = { x: st.x - 90, y: st.y + BOX.h / 2 };
    const outFlow = { id: flowId(`out of ${name}`), name: `out of ${name.toLowerCase()}`, from: st.id, to: f.to,
                      rate: { form: "proportional", stock: st.id, k: +(1 / Math.max(1, f.via.delay)).toFixed(4) }, machine: "environment", found };
    return { stocks: [st], flows: [inFlow, outFlow] };
  }
  function addFoundFlows() {
    const r = S.discovery, added = [], stocks = [];
    const sid = (name) => { const id = uniqueId(name); return id; };
    r.flows.forEach((f, k) => {
      if (!f.via) { const fl = foundFlow(f, k, () => uniqueId(`found ${nodeName(f.from)} ${nodeName(f.to)}`)); S.model.flows.push(fl); added.push(fl); return; }
      const parts = hiddenParts(f, sid, sid);
      parts.stocks.forEach((x) => { S.model.stocks.push(x); stocks.push(x); });
      parts.flows.forEach((x) => { S.model.flows.push(x); added.push(x); });
    });
    S.discovery = null;
    S.sel = new Set([...added.map((fl) => "f:" + fl.id), ...stocks.map((x) => "s:" + x.id)]);
    fillInferred();
    changed();
    setStatus(`Added ${added.length} flow${added.length === 1 ? "" : "s"}${stocks.length ? ` and ${stocks.length} stock${stocks.length === 1 ? "" : "s"} nobody measures` : ""}, found in the data`);
    if (S.autoDiscover && S.mode === "run") runDiscovery(true);    // look again, now for what the new flows leave unexplained
  }
  // A new model with the same stocks and the discovered flows, so the original stays as it is.
  async function makeFoundModel() {
    const r = S.discovery, base = S.model;
    const id = `${base.id}-found`.slice(0, 60);
    const flows = [], stocks = base.stocks.map((x) => ({ ...x }));
    let n = 0;
    const next = (prefix) => () => `${prefix}_${++n}`;
    r.flows.forEach((f, k) => {
      if (!f.via) { flows.push(foundFlow(f, k, next("found"))); return; }
      const parts = hiddenParts(f, next("hidden"), next("found"));
      stocks.push(...parts.stocks); flows.push(...parts.flows);
    });
    const model = { id, name: `${base.name} (found)`, description: `Flows discovered from the stock levels of ${r.steps} ${tu()}s of ${base.name}.`,
      time_unit: base.time_unit, horizon: base.horizon, dt: base.dt, stocks, flows, machines: [] };
    const res = await fetch(`/api/models/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(model) });
    if (!res.ok) { setStatus("Could not save the new model", true); return; }
    S.discovery = null;
    await loadList(id);
    setStatus(`Made "${model.name}" from the discovered flows`);
  }

  // Saving a fit changes the model's equations, which are the current era's beliefs. Earlier
  // eras keep the equations they had (the server records them per era). Undo puts them back.
  function useFits(rows) {
    const n = S.live.series.t.length, era = currentEra();
    const when = `${new Date().toISOString().slice(0, 10)}, era ${era.n}`;
    const undo = {};
    rows.forEach((r) => {
      const fl = flow(r.flow);
      undo[fl.id] = { rate: fl.rate, fitted: fl.fitted };
      fl.fitted = { when, before: fl.rate, notes: r.notes };
      fl.rate = JSON.parse(JSON.stringify(r.proposed.rate));
    });
    S.undo = undo; S.fitCache = null;
    changed();
    setStatus(`Saved a better fit for ${rows.map((r) => flow(r.flow).name).join(", ")} in era ${era.n}`);
    void n;
  }
  function updateEquations() {
    const F = eraFit(true);
    if (!F) { setStatus(`Run at least 15 ${tu()}s in this era first`); return; }
    const rows = F.rows.filter((r) => r.change);
    if (!rows.length) { setStatus("Every equation already fits this era as well as any other would"); return; }
    useFits(rows);
  }
  function undoEquations() {
    Object.entries(S.undo || {}).forEach(([id, u]) => {
      const fl = flow(id); if (!fl) return;
      fl.rate = u.rate;
      if (u.fitted) fl.fitted = u.fitted; else delete fl.fitted;
    });
    S.undo = null; S.fitCache = null;
    changed();
    setStatus("Put back the earlier equations");
  }

  function firingRow(r) {
    const f = flow(r.flow) || { name: r.flow };
    return `<li class="fire ${r.ok ? "" : "failed"} ${S.firing && S.firing.n === r.n ? "on" : ""}" data-fire="${r.n}" tabindex="0">
      <span class="mark">${r.ok ? "\u2713" : "\u2717"}</span> ${esc(tu())} ${r.t} \u00b7 <b>${esc(f.name)}</b> took ${esc(r.in.join(" + ") || "nothing")}, wrote ${r.out} <span class="muted">${r.ms} ms</span></li>`;
  }
  function wireFirings(root) {
    root.querySelectorAll("[data-fire]").forEach((li) => {
      const open = async () => {
        const r = await fetch(`/api/models/${S.model.id}/live/firings/${li.dataset.fire}`);
        if (!r.ok) { setStatus("That run is no longer kept; only the most recent 60 are.", true); return; }
        S.firing = await r.json(); S.sel.clear(); S.editMachine = null;
        renderCanvas(); renderInspector(); renderRunPanel();
      };
      li.addEventListener("click", open);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    });
  }

  // ---------- modes ----------
  function setMode(mode) {
    S.mode = mode; S.pending = null;
    document.body.dataset.mode = mode;
    const u = new URL(location.href); u.hash = mode; history.replaceState(null, "", u);
    document.querySelectorAll(".modes button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === mode)));
    if (S.model) { syncPolling(); requestAnimationFrame(renderAll); }
  }
  document.querySelectorAll(".modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  window.addEventListener("resize", () => S.model && renderCanvas());

  function renderAll() { renderToolbar(); renderCanvas(); renderInspector(); renderMachineList(); renderRunPanel(); }
  function esc(s) { return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

  fetch("/api/programs").then((r) => r.json()).then((r) => { S.programs = r.programs || []; }).catch(() => {});
  loadMenu();
  buildMachinePanel();
  setMode(location.hash.slice(1) === "run" ? "run" : "edit");
  // ---------- models: open, copy, delete, and to and from disk ----------
  function renderFiles() {
    const d = $("files"), r = S.list, cur = S.model && S.model.id;
    const when = (m) => new Date(m.modified * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    const row = (m, mine) => `<li class="${m.id === cur ? "current" : ""}"><span class="nm" title="${esc(m.id)}">${esc(m.name)}</span>
      ${m.running ? `<span class="runtag" title="Its run is going on now">\u25b6 running \u00b7 step ${m.t}</span><button class="btn icon" data-f-pause="${m.id}" title="Pause its run">\u23f8\ufe0f</button>` : ""}
      ${mine ? `<span class="when">${esc(when(m))}</span>` : ""}
      <button class="btn" data-f-open="${m.id}" title="Open it">Open</button>
      <button class="btn icon" data-f-copy="${m.id}" title="Save a copy of it (and its run) in My models">&#128203;</button>
      <a class="btn icon" href="/api/models/${m.id}/download" download="${m.id}.json" title="Download it as a file">&#11015;&#65039;</a>
      ${mine ? `<button class="btn icon danger" data-f-del="${m.id}" title="Delete it and its run">&#128465;&#65039;</button>` : ""}</li>`;
    d.innerHTML = `<div class="fhead"><h2>Models</h2>
        <button class="btn" data-f-upload title="Open a model file (.json) from your disk; it becomes one of your models">&#11014;&#65039; Open a file…</button>
        <button class="btn icon" data-f-close title="Close" aria-label="Close">✕</button></div>
      <div class="fbody">
        <h3>Basic models (ladder)</h3><ul>${basicsOf(r).map((m) => row(m, false)).join("")}</ul>
        <p class="note">The ladder's tiny true models, simplest first; each opens with its recorded data, ready for Discover.</p>
        <label class="pickold"><input type="checkbox" data-f-old ${S.showOld ? "checked" : ""}> Show older models (${r.models.length + r.examples.length})</label>
        ${S.showOld ? `<h3>My models</h3>${r.models.length ? `<ul>${r.models.map((m) => row(m, true)).join("")}</ul>` : `<p class="note">None yet. Change an example and it is saved here as your own copy.</p>`}
        <h3>Examples</h3><ul>${r.examples.map((m) => row(m, false)).join("")}</ul>
        <p class="note">Examples always open as shipped. Their runs are kept; a copy takes the run with it.</p>` : ""}
      </div>`;
    d.querySelector("[data-f-close]").onclick = () => d.close();
    d.querySelector("[data-f-old]").onchange = (e) => { setShowOld(e.target.checked); renderFiles(); renderPick(); };
    d.querySelector("[data-f-upload]").onclick = () => $("file-in").click();
    d.querySelectorAll("[data-f-open]").forEach((b) => (b.onclick = async () => { d.close(); await loadModel(b.dataset.fOpen); }));
    d.querySelectorAll("[data-f-pause]").forEach((b) => (b.onclick = async () => {
      await fetch(`/api/models/${b.dataset.fPause}/live/stop`, { method: "POST" });
      await fetchList(); renderPick(S.model.id); renderFiles();
      if (b.dataset.fPause === S.model.id) await refetchLive();
    }));
    const n = [...r.models, ...r.examples].filter((m) => m.running).length;
    d.querySelector(".fhead h2").textContent = n ? `Models \u00b7 ${n} running` : "Models";
    d.querySelectorAll("[data-f-copy]").forEach((b) => (b.onclick = async () => {
      await flushSave();
      const src = allModels(r).find((m) => m.id === b.dataset.fCopy);
      const name = prompt("Name of the copy", `${src.name} (copy)`); if (!name) return;
      const res = await fetch(`/api/models/${src.id}/copy`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
      if (!res.ok) { setStatus("Could not copy", true); return; }
      await fetchList(); renderPick(S.model.id); renderFiles(); setStatus(`Saved a copy: “${name}”`);
    }));
    d.querySelectorAll("[data-f-del]").forEach((b) => (b.onclick = async () => {
      if (b.dataset.armed !== "1") { b.dataset.armed = "1"; b.textContent = "Delete?"; return; }   // a second click deletes
      const id = b.dataset.fDel;
      if (id === cur) { clearTimeout(S.saveTimer); S.saveTimer = null; }
      const res = await fetch(`/api/models/${id}`, { method: "DELETE" });
      if (!res.ok) { setStatus("Could not delete", true); return; }
      await fetchList();
      if (id === cur) await loadList(); else renderPick(cur);
      renderFiles(); setStatus("Deleted");
    }));
  }
  $("files-open").addEventListener("click", async () => { await flushSave(); await fetchList(); renderFiles(); $("files").showModal(); });
  $("save-as").addEventListener("click", async () => {
    await flushSave();
    const name = prompt("Save as", S.isExample ? `${S.model.name} (my copy)` : `${S.model.name} (copy)`); if (!name) return;
    const c = await saveCopy(name);
    if (c) setStatus(`Saved as “${c.name}”; that is what you are editing now`);
  });
  $("file-in").addEventListener("change", async (e) => {
    const file = e.target.files[0]; e.target.value = ""; if (!file) return;
    let model;
    try { model = JSON.parse(await file.text()); } catch { setStatus(`${file.name} is not a model file (not JSON)`, true); return; }
    if (!model || !Array.isArray(model.stocks)) { setStatus(`${file.name} is not a model file (no stocks)`, true); return; }
    if (!model.name) model.name = file.name.replace(/\.json$/i, "");
    const res = await fetch("/api/models", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(model) });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setStatus(`Could not open ${file.name}: ${((body.detail && body.detail.errors) || [res.statusText]).join("; ")}`, true); return;
    }
    const { id } = await res.json();
    if ($("files").open) $("files").close();
    await fetchList(); renderPick(id); await loadModel(id);
    setStatus(`Opened ${file.name} as one of your models`);
  });

  loadList().catch((e) => setStatus("Could not load models: " + e.message, true));
})();
