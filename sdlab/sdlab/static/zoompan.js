// Zoom and pan for model diagrams (the user, 2026-10-22). Click a diagram to enter: a trackpad's two-finger scroll
// pans, command + scroll (or a pinch, which browsers send as ctrl + scroll) zooms about the pointer, and a drag pans
// too. Click it again, click anywhere outside it, or press Escape to leave; the diagram goes back to how it was drawn.
// Works on any svg matching SELECTOR (diagrams drawn by diagram.js), across the pages that load this script.
(function () {
  "use strict";
  const SELECTOR = ".mdiag svg, .dpanel svg, .bdiag svg, svg.zp";
  // a model diagram: one of SELECTOR, or any svg diagram.js drew (it has stock boxes, g.dstock)
  const diagramOf = (t) => { const svg = t && t.closest && t.closest("svg"); return svg && (svg.matches(SELECTOR) || svg.querySelector("g.dstock")) ? svg : null; };
  let on = null;                                     // {svg, vb0, hint}

  const vbOf = (svg) => { const v = (svg.getAttribute("viewBox") || "").split(/[\s,]+/).map(Number); return v.length === 4 && v.every(isFinite) ? v : null; };
  const setVb = (svg, v) => svg.setAttribute("viewBox", v.map((x) => +x.toFixed(2)).join(" "));

  function enter(svg) {
    const vb0 = vbOf(svg);
    if (!vb0) return;
    leave();
    const hint = document.createElement("div");
    hint.className = "zp-hint";
    hint.textContent = "Zoom: ⌘ + scroll (or pinch) · pan: scroll or drag · click again, click outside or Esc to leave";
    document.body.appendChild(hint);
    const r = svg.getBoundingClientRect();
    hint.style.left = `${Math.max(8, r.left + window.scrollX)}px`;
    hint.style.top = `${Math.max(8, r.top + window.scrollY - 26)}px`;
    svg.classList.add("zp-on");
    svg.dataset.zpMax = svg.style.maxWidth || "";
    svg.style.maxWidth = "none";                    // a small model may grow while zoomed
    on = { svg, vb0, vb0s: svg.getAttribute("viewBox"), hint, moved: false };
  }
  function leave() {
    if (!on) return;
    on.svg.setAttribute("viewBox", on.vb0s);              // exactly as it was drawn
    on.svg.style.maxWidth = on.svg.dataset.zpMax || "";
    on.svg.classList.remove("zp-on");
    on.hint.remove();
    on = null;
  }

  // a click that ends a drag does not count as "click it again"
  let down = null;
  document.addEventListener("pointerdown", (e) => {
    if (on && on.svg.contains(e.target)) { down = { x: e.clientX, y: e.clientY, vb: vbOf(on.svg) }; on.svg.setPointerCapture?.(e.pointerId); }
  });
  document.addEventListener("pointermove", (e) => {
    if (!on || !down) return;
    const r = on.svg.getBoundingClientRect(), v = down.vb, k = v[2] / r.width;
    const dx = e.clientX - down.x, dy = e.clientY - down.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) on.moved = true;
    setVb(on.svg, [v[0] - dx * k, v[1] - dy * (v[3] / r.height), v[2], v[3]]);
  });
  document.addEventListener("pointerup", () => { down = null; });

  document.addEventListener("click", (e) => {
    const svg = diagramOf(e.target);
    if (on) {
      const inside = svg === on.svg;
      if (inside && on.moved) { on.moved = false; e.stopPropagation(); e.preventDefault(); return; }   // the end of a drag
      leave();                                       // clicked again, or outside
      if (inside) { e.stopPropagation(); e.preventDefault(); }   // an outside click still does what it does
      return;
    }
    if (svg && !svg.closest(".rcard")) {             // a Now-page card opens its run instead
      enter(svg);
      e.stopPropagation();
      e.preventDefault();
    }
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") leave(); });

  document.addEventListener("wheel", (e) => {
    if (!on || !on.svg.contains(e.target)) return;
    e.preventDefault();
    const svg = on.svg, v = vbOf(svg), r = svg.getBoundingClientRect();
    if (e.metaKey || e.ctrlKey) {                    // zoom about the pointer
      const f = Math.exp(Math.max(-1, Math.min(1, e.deltaY * (e.ctrlKey && !e.metaKey ? 0.01 : 0.002))));
      const px = v[0] + ((e.clientX - r.left) / r.width) * v[2], py = v[1] + ((e.clientY - r.top) / r.height) * v[3];
      const w = Math.max(on.vb0[2] / 40, Math.min(on.vb0[2] * 6, v[2] * f)), h = (w / v[2]) * v[3];
      setVb(svg, [px - ((px - v[0]) * w) / v[2], py - ((py - v[1]) * h) / v[3], w, h]);
    } else {                                         // pan
      setVb(svg, [v[0] + e.deltaX * (v[2] / r.width), v[1] + e.deltaY * (v[3] / r.height), v[2], v[3]]);
    }
  }, { passive: false });

  const css = document.createElement("style");
  css.textContent = `svg.zp-on { outline: 2px solid var(--accent, #2a78d6); outline-offset: 2px; cursor: grab; touch-action: none; }
    svg.zp-on:active { cursor: grabbing; }
    .zp-hint { position: absolute; z-index: 50; font: 12px system-ui, sans-serif; background: var(--fg, #1d1d1b); color: var(--bg, #fff); padding: 3px 8px; border-radius: 4px; pointer-events: none; }
    ${SELECTOR.split(",").map((s) => `${s.trim()}:not(.zp-on)`).join(", ")} { cursor: zoom-in; }`;
  document.head.appendChild(css);
})();
