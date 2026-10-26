// The Dashboard: the panels (Orchestra.panels in app.js), Orchestra's own and any a package
// registers, laid out as sections of one page on a 12-column grid (gridstack.js). The viewer
// arranges it: drag a panel by its title bar, resize it from its edges and corners; panels pack
// upward, so one goes under another with no gap. A panel can be hidden and brought back from
// Panels (in the navigation). Where each panel is, and how big, is kept in this browser.
// A panel may say how big it starts: spec.size = {w: columns of 12, h: rows of 40 px}.
(function () {
  const KEY = "orchestra.dashboard.grid";
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || null; } catch (e) { return null; } };
  let L = Object.assign({ items: {}, hidden: [] }, load() || {});
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(L)); } catch (e) {} };
  const board = document.getElementById("board"), holder = document.createElement("div");
  holder.hidden = true; document.body.appendChild(holder);
  const grid = GridStack.init({
    column: 12, cellHeight: 40, margin: 3, float: false, animate: true, handle: ".dhead",
    resizable: { handles: "e,se,s,sw,w" }, columnOpts: { breakpoints: [{ w: 820, c: 1 }] },
  }, board);
  const els = new Map();                                 // panel id -> its grid item (mounted once)

  function remember() {
    for (const n of grid.save(false)) if (n.id) L.items[n.id] = { x: n.x, y: n.y, w: n.w, h: n.h };
    save();
  }
  grid.on("change", remember);

  function build(p) {
    const el = document.createElement("div");
    el.className = "grid-stack-item"; el.setAttribute("gs-id", p.id);
    el.innerHTML = `<div class="grid-stack-item-content dpanel">
        <div class="dhead" title="drag to move; drag an edge or a corner to resize"><h1>${esc(p.title)}</h1><span class="sub"></span>
          <button class="dx" title="hide (bring it back from Panels)">✕</button></div>
        <div class="dbody"></div></div>`;
    el.querySelector(".dx").onclick = (e) => { e.stopPropagation(); hide(p.id); };
    return el;
  }

  function place(p) {
    if (L.hidden.includes(p.id)) return;
    let el = els.get(p.id);
    const fresh = !el;
    if (fresh) { el = build(p); els.set(p.id, el); }
    const at = L.items[p.id], size = p.size || { w: 6, h: 8 };
    board.appendChild(el);
    grid.makeWidget(el, at ? { id: p.id, x: at.x, y: at.y, w: at.w, h: at.h } : { id: p.id, w: size.w, h: size.h, autoPosition: true });
    if (fresh) {                                         // drawn once, when it is first on the page
      try { p.mount(el.querySelector(".dbody"), { setSub: (t) => { el.querySelector(".sub").textContent = t || ""; } }); }
      catch (e) { el.querySelector(".dbody").innerHTML = `<div class="empty">This panel failed: ${esc(String(e))}</div>`; }
    }
  }

  function hide(id) {
    const el = els.get(id); if (!el) return;
    remember();
    grid.removeWidget(el, false);
    holder.appendChild(el);                             // kept, still running, out of sight
    L.hidden = [...new Set([...L.hidden, id])]; save(); menu();
  }
  function show(id) {
    L.hidden = L.hidden.filter((x) => x !== id); save();
    const p = Orchestra.panels.all().find((x) => x.id === id); if (p) place(p);
    menu();
  }
  function reset() {
    L = { items: {}, hidden: [] }; save();
    grid.removeAll(false);
    for (const p of Orchestra.panels.all()) { const el = els.get(p.id); if (el) holder.appendChild(el); }
    for (const p of Orchestra.panels.all()) { const el = els.get(p.id), size = p.size || { w: 6, h: 8 }; if (el) { board.appendChild(el); grid.makeWidget(el, { id: p.id, w: size.w, h: size.h, autoPosition: true }); } }
    remember(); menu();
  }

  function menu() {
    let m = document.getElementById("panels-menu");
    if (!m) { m = document.createElement("span"); m.id = "panels-menu"; const nav = document.getElementById("nav"); nav.insertBefore(m, document.getElementById("conn")); }
    const hidden = Orchestra.panels.all().filter((p) => L.hidden.includes(p.id));
    m.innerHTML = `<button class="ctl" onclick="this.nextElementSibling.hidden=!this.nextElementSibling.hidden">Panels${hidden.length ? ` · ${hidden.length} hidden` : ""} ▾</button>
      <div class="pmenu" hidden>${hidden.map((p) => `<button data-show="${esc(p.id)}">show ${esc(p.title)}</button>`).join("") || '<span class="muted">every panel is shown</span>'}
        <button data-reset="1">reset the layout</button></div>`;
    m.querySelectorAll("[data-show]").forEach((b) => (b.onclick = () => show(b.dataset.show)));
    m.querySelector("[data-reset]").onclick = reset;
  }

  const placed = new Set();
  function sync() {
    for (const p of Orchestra.panels.all()) if (!placed.has(p.id)) { placed.add(p.id); place(p); }
    menu();
  }
  document.addEventListener("orchestra:panels", sync);
  sync();
})();
