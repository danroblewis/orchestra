// The Dashboard: a board of panels (Orchestra.panels in app.js), Orchestra's own and any a package
// registers. The viewer arranges them: drag a panel by its title bar to move it, widen it to two
// columns, hide it, and bring it back from "Panels". The arrangement is kept in this browser.
(function () {
  const KEY = "orchestra.dashboard";
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } };
  let L = Object.assign({ order: [], hidden: [], wide: [] }, load());
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(L)); } catch (e) {} };
  const board = document.getElementById("board"), mounted = new Map();
  let dragging = null;

  function ordered() {
    const all = Orchestra.panels.all(), pos = (id) => { const i = L.order.indexOf(id); return i < 0 ? 1e6 + all.findIndex((p) => p.id === id) : i; };
    return all.sort((a, b) => pos(a.id) - pos(b.id));
  }

  function section(p) {
    const el = document.createElement("section");
    el.className = "dpanel"; el.dataset.id = p.id;
    el.innerHTML = `<header draggable="true" title="drag to move"><span class="grip">⠿</span><h1>${esc(p.title)}</h1><span class="sub"></span>
        <span class="acts"><button title="wider or narrower" data-act="wide">⇔</button><button title="hide (bring it back from Panels)" data-act="hide">✕</button></span></header>
      <div class="dbody"></div>`;
    const head = el.querySelector("header");
    head.addEventListener("dragstart", (e) => { dragging = el; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", p.id); });
    head.addEventListener("dragend", () => { el.classList.remove("dragging"); dragging = null; L.order = [...board.querySelectorAll(".dpanel")].map((x) => x.dataset.id); save(); });
    el.querySelector('[data-act="wide"]').onclick = () => { L.wide = L.wide.includes(p.id) ? L.wide.filter((x) => x !== p.id) : [...L.wide, p.id]; save(); place(); };
    el.querySelector('[data-act="hide"]').onclick = () => { L.hidden = [...new Set([...L.hidden, p.id])]; save(); place(); };
    return el;
  }

  board.addEventListener("dragover", (e) => {
    if (!dragging) return;
    e.preventDefault();
    const over = e.target.closest(".dpanel");
    if (!over || over === dragging) return;
    const r = over.getBoundingClientRect(), before = e.clientY < r.top + r.height / 2 || (e.clientX < r.left + r.width / 2 && e.clientY < r.bottom);
    board.insertBefore(dragging, before ? over : over.nextSibling);
  });

  function place() {
    for (const p of ordered()) {
      if (!mounted.has(p.id)) mounted.set(p.id, section(p));
      const el = mounted.get(p.id);
      el.classList.toggle("wide", L.wide.includes(p.id));
      if (L.hidden.includes(p.id)) { el.remove(); continue; }
      board.appendChild(el);                        // in order: appending moves it
      if (!el._mounted) {                           // drawn once, when it is first on the page
        el._mounted = true;
        try { p.mount(el.querySelector(".dbody"), { setSub: (t) => { el.querySelector(".sub").textContent = t || ""; } }); }
        catch (e) { el.querySelector(".dbody").innerHTML = `<div class="empty">This panel failed: ${esc(String(e))}</div>`; }
      }
    }
    menu();
  }

  function menu() {
    const m = document.getElementById("panels-menu");
    const hidden = Orchestra.panels.all().filter((p) => L.hidden.includes(p.id));
    m.innerHTML = `<button class="ctl" onclick="this.nextElementSibling.hidden=!this.nextElementSibling.hidden">Panels${hidden.length ? ` · ${hidden.length} hidden` : ""} ▾</button>
      <div class="pmenu" hidden>${hidden.map((p) => `<button data-show="${esc(p.id)}">show ${esc(p.title)}</button>`).join("") || '<span class="muted">every panel is shown</span>'}
        <button data-reset="1">reset the layout</button></div>`;
    m.querySelectorAll("[data-show]").forEach((b) => (b.onclick = () => { L.hidden = L.hidden.filter((x) => x !== b.dataset.show); save(); place(); }));
    m.querySelector("[data-reset]").onclick = () => { L = { order: [], hidden: [], wide: [] }; save(); place(); };
  }

  document.addEventListener("orchestra:panels", place);
  place();
})();
