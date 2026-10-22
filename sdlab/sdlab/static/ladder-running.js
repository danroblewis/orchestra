// The Now tab's default (the user, 2026-10-21): one card per item the pool is running now, all on one screen.
// Each card: the strategy, the case and variant, how long it has run against its time limit, and the
// differences of that cell's last stored result (a running item has no new result yet). With nothing running,
// the newest results. A click opens the full run (ladder.js: pick). ladder.js calls render() on every poll;
// a card is drawn once and only its clock changes after that.
(function () {
  "use strict";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const STATUS = { pass: "pass", equivalent: "equivalent", fits: "fits", fail: "fail", error: "error", timeout: "timeout" };
  const GAP = 8, MIN_W = 90, MIN_H = 130;
  const ASPECT = 0.62;                     // card width / height: the models are drawn two columns wide, taller than wide
  const keyOf = (i) => `${i.case}|${i.variant}|${i.strategy}`;
  const last = new Map();                  // cell -> {at, r}: its latest stored result (a minute's cache)
  const drawn = new Map();                 // cell -> the card element
  let H = null;                            // ladder.js's helpers

  const ago = (iso) => {
    const s = (Date.now() - new Date(iso)) / 1000;
    if (!isFinite(s)) return "";
    return s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : s < 172800 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s / 86400)} d`;
  };
  const clock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  async function latest(i) {
    if (i.state === "done" && i.id) {                    // a finished item: its own result (the store's id)
      try { const res = await fetch(`/api/ladder/result/${encodeURIComponent(i.id)}`); if (res.ok) return await res.json(); } catch { /* the cell's latest */ }
    }
    const k = keyOf(i), got = last.get(k);
    if (got && Date.now() - got.at < 60000) return got.r;
    let r = null;
    try {
      const res = await fetch(`/api/ladder/results/${encodeURIComponent(i.case)}/${encodeURIComponent(i.variant)}/${encodeURIComponent(i.strategy)}`);
      if (res.ok) r = await res.json();
    } catch { /* drawn without one */ }
    last.set(k, { at: Date.now(), r });
    return r;
  }

  // tall, narrow cards (the user, 2026-10-21): the columns and rows that make n cards of shape ASPECT largest inside w x h
  // (no smaller than MIN_W x MIN_H: past that the page scrolls)
  function grid(n, w, h) {
    let best = null;
    for (let cols = 1; cols <= n; cols++) {
      const rows = Math.ceil(n / cols), ch = Math.max(MIN_H, (h - GAP * (rows - 1)) / rows);
      const room = (w - GAP * (cols - 1)) / cols, cw = Math.min(room, ch * ASPECT);
      if (room < MIN_W && cols > 1) break;
      const fits = rows * ch + GAP * (rows - 1) <= h + 1;
      const score = cw * Math.min(ch, cw / ASPECT) - (fits ? 0 : 1e9);
      if (!best || score > best.score) best = { cols, room, cw, ch: Math.min(ch, cw / ASPECT * 1.25), score };
    }
    return best;
  }

  function card(i, done) {
    const el = document.createElement("button");
    el.className = "rcard";
    el.type = "button";
    const c = H.cases()[i.case] || {};
    el.title = `${i.case} ${c.title || ""}\n${i.variant} · ${i.strategy}${i.reason ? `\n${i.reason}${i.by ? ` (${i.by})` : ""}` : ""}${i.worker ? ` on ${i.worker}` : ""}\nClick for the full run`;
    el.innerHTML = `<b class="rcstrat">${esc(i.strategy)}</b>
      <div class="rchead"><span class="rcvar">${esc(i.variant)}</span>
        <span class="rcstate">${done ? `<span class="stbadge st-${esc(i.status)}">${esc(STATUS[i.status] || i.status)}</span>` : `<span class="rcclock"></span>`}</span></div>
      <div class="rccase">${esc(i.case)}</div>
      ${done ? "" : `<div class="rcbar"><span></span></div>`}
      <svg class="rcdiag" role="img" aria-label="${esc(`differences of ${i.strategy}'s last result on ${i.case} ${i.variant}`)}"></svg>
      <div class="rccap small muted">loading the last result…</div>`;
    if (done) last.delete(keyOf(i));                        // a finished cell: its new result, not the cached one
    el.addEventListener("click", () => H.open({ case: i.case, variant: i.variant, strategy: i.strategy, ...(done && i.id ? { id: i.id } : {}) }));
    fill(el, i, done);
    return el;
  }

  async function fill(el, i, done) {
    const c = H.cases()[i.case];
    if (!c) return;
    const r = await latest(i);
    const cmp = r ? await H.compareOf(c, r) : null;
    if (![...drawn.values()].includes(el)) return;          // gone while its result loaded
    const { caption } = H.drawDiff(c, r, el.querySelector(".rcdiag"), cmp, 2);
    const st = r && r.status;
    el.style.setProperty("--st", st ? `var(--${{ pass: "good", equivalent: "eq", fits: "fits", timeout: "warn" }[st] || "bad"})` : "var(--rule)");
    el.querySelector(".rccap").innerHTML = r
      ? `${done ? "" : `last: <span class="stbadge st-${esc(st)}">${esc(STATUS[st] || st)}</span> ${esc(ago(r.at))} ago · `}${esc((caption || "").replace(/^Differences: /, ""))}`
      : "no earlier result";
  }

  function tick(el, i) {
    const s = Math.max(0, (Date.now() - new Date(i.started)) / 1000), lim = i.timeout || 300;
    const c = el.querySelector(".rcclock"), b = el.querySelector(".rcbar span");
    if (c) c.textContent = `${clock(s)}/${clock(lim)}`;
    if (b) { b.style.width = `${Math.min(100, (100 * s) / lim).toFixed(1)}%`; b.classList.toggle("over", s > lim); }
  }

  // box: the cards' container; p: /api/ladder/progress. follow (the "follow the run" box): the running items, then
  // the newest finished results, newest first, each with its own result
  function render(box, p, opts = {}) {
    const items = ((p && p.items) || []).filter((i) => H.cases()[i.case]);
    const running = items.filter((i) => i.state === "running").sort((a, b) => (a.started < b.started ? -1 : a.started > b.started ? 1 : keyOf(a) < keyOf(b) ? -1 : 1));
    const finished = items.filter((i) => i.state === "done" && i.finished).sort((a, b) => (a.finished < b.finished ? 1 : -1));
    const shown = opts.follow ? [...running, ...finished.slice(0, Math.max(6, 30 - running.length))] : running.length ? running : finished.slice(0, 12);
    const nDone = shown.filter((i) => i.state === "done").length;
    const head = box.querySelector(".rchdr") || Object.assign(box.appendChild(document.createElement("div")), { className: "rchdr small muted" });
    const legend = `(<b class="d-missed">−</b> removed, <b class="d-spurious">+</b> added, <b class="d-wrong">~</b> values wrong). Click a card for the full run.`;
    head.innerHTML = opts.follow
      ? `Following the run: <b>${running.length}</b> running (their cell's last result), then the <b>${nDone}</b> newest results, newest first, each a diff of the truth ${legend}`
      : running.length ? `Running now: <b>${running.length}</b> item${running.length === 1 ? "" : "s"}. Each card: the cell's last stored result as a diff of the truth ${legend}`
        : shown.length ? `Nothing running. The ${shown.length} newest results ${legend}` : "Nothing running, and no results yet.";
    head.insertAdjacentHTML("beforeend", ` <button class="btn small" type="button" data-act="board" title="Every case on one page, one strategy at a time">All cases</button>`);
    head.querySelector("[data-act=board]").onclick = () => H.toBoard();
    const wrap = box.querySelector(".rcgrid") || Object.assign(box.appendChild(document.createElement("div")), { className: "rcgrid" });
    const want = new Map(shown.map((i) => [keyOf(i) + (i.state === "done" ? `|done|${i.finished}` : ""), i]));
    for (const [k, el] of drawn) if (!want.has(k)) { el.remove(); drawn.delete(k); }
    let prev = null;
    for (const [k, i] of want) {
      let el = drawn.get(k);
      const done = i.state === "done";
      if (!el) { el = card(i, done); drawn.set(k, el); }
      if (prev ? prev.nextSibling !== el : wrap.firstChild !== el) wrap.insertBefore(el, prev ? prev.nextSibling : wrap.firstChild);
      if (!done) tick(el, i);
      prev = el;
    }
    size(wrap, want.size);
  }

  function size(wrap, n) {
    if (!n) return;
    const top = wrap.getBoundingClientRect().top;               // below the status strip; the cards take the rest of the window
    const h = Math.max(MIN_H, innerHeight - Math.max(0, top) - 12), w = wrap.clientWidth || innerWidth - 32;
    const g = grid(n, w, h);
    // the chosen shape sets how many fit; spare width widens them a little (up to square), so the row is not half empty
    wrap.style.gridTemplateColumns = `repeat(${g.cols}, ${Math.floor(Math.min(g.room, g.ch * 0.9))}px)`;
    wrap.style.setProperty("--rch", `${Math.floor(g.ch)}px`);
  }

  window.SDLadderRunning = {
    init(helpers) { H = helpers; },
    render,
    resize(box) { const w = box.querySelector(".rcgrid"); if (w) size(w, w.children.length); },
  };
})();
