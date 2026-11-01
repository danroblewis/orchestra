// The order of the Dashboard's panels (dashboard.js). Wide: as the viewer arranged them, (y, x);
// a panel never placed goes after them, in the order it registered. On a phone's one column the
// same order, except that a panel which says so (spec.phone = "last": the Host, plumbing one opens
// when something breaks) goes below the others, so the work is seen first.
const PanelOrder = (() => {
  const wide = (ps, items) => ps.map((p, i) => ({ p, i, at: (items || {})[p.id] }))
    .sort((a, b) => (a.at ? 0 : 1) - (b.at ? 0 : 1) || (a.at && b.at ? a.at.y - b.at.y || a.at.x - b.at.x : 0) || a.i - b.i).map((x) => x.p);
  const phone = (ps, items) => { const w = wide(ps, items); return [...w.filter((p) => p.phone !== "last"), ...w.filter((p) => p.phone === "last")]; };
  return { wide, phone };
})();
if (typeof module !== "undefined") module.exports = PanelOrder;
