// The intended model's keys and SVG marks on the Dynamics page (intended-dynamics.js draws with
// them; the drawers and the panel read the keys through it): what a mark matches a discovered part
// by, and the pill tags, rings, pins and hatching drawn on the diagram's nodes.
const IntendedMarks = (() => {
  const it = () => (MODEL && MODEL.intended && !MODEL.intended.error ? MODEL.intended : null);
  // what marks match by, since discovered ids are not stable: the server's keys (sd/intended/keys.py),
  // sent as ``intended.keys`` ({stocks: {id: key}, flows: {id: key}}), never made here
  const keys = () => { const x = it(); return (x && x.keys) || { stocks: {}, flows: {} }; };
  const stockKey = (s) => (s ? keys().stocks[s.id] || null : null);
  const flowKey = (f) => (f ? keys().flows[f.id] || null : null);
  const stockOfKey = (key) => (key ? MODEL.stocks.find((s) => keys().stocks[s.id] === key || s.id === key) : null);
  const marksOf = (part, id) => { const x = it(); return (x && ((x.marks || {})[part === "stock" ? "stocks" : "flows"] || {})[id]) || []; };
  const hasEarlier = () => { const x = it(), vs = (MODEL && MODEL.versions) || []; return !!x && vs.findIndex((v) => v.version === x.shown) > 0; };

  // a pill tag; ``max``: the widest it may be (a ghost's tags stay within its box); longer text is cut, in full on hover
  function svgTag(g, x, y, text, cls = "", max = Infinity) {
    const fit = Math.max(4, Math.floor((max - 14) / 5.6)), shown = text.length > fit ? text.slice(0, fit - 1) + "…" : text;
    const t = g.append("g").attr("class", "im-svgtag " + cls).attr("transform", `translate(${x},${y})`);
    if (shown !== text) t.append("title").text(text);
    t.append("rect").attr("x", 0).attr("y", -9).attr("width", shown.length * 5.6 + 14).attr("height", 16).attr("rx", 8);
    t.append("text").attr("x", 7).attr("y", 3).text(shown);
  }
  function svgRing(g, s) {
    g.insert("rect", ":first-child").attr("class", "im-ring").attr("x", -s.w / 2 - 6).attr("y", -s.h / 2 - 6).attr("width", s.w + 12).attr("height", s.h + 12).attr("rx", 10);
  }
  function svgPin(g, x, y, label) {
    const p = g.append("g").attr("class", "im-pin").attr("transform", `translate(${x},${y})`);
    p.append("circle").attr("cy", -6).attr("r", 4);
    p.append("line").attr("x1", 0).attr("y1", -2).attr("x2", 0).attr("y2", 5);
    if (label) p.append("text").attr("x", 7).attr("y", -2).text(label);
  }
  function hatch(g, s) {
    const svg = g.node().ownerSVGElement;
    if (svg && !svg.querySelector("#im-hatch")) d3.select(svg).insert("defs", ":first-child").html('<pattern id="im-hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" class="im-hatchline"/></pattern>');
    g.append("rect").attr("class", "im-hatch").attr("x", -s.w / 2 + 1.5).attr("y", -s.h / 2 + 1.5).attr("width", s.w - 3).attr("height", s.h - 3).attr("rx", 4).attr("fill", "url(#im-hatch)");
  }

  return { keys, stockKey, flowKey, stockOfKey, marksOf, hasEarlier, svgTag, svgRing, svgPin, hatch };
})();
