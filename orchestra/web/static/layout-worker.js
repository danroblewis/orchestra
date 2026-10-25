// The Dynamics layout's last step, off the page's thread: untangle a placed graph (sd-layout.js)
// so as few lines as possible run behind boxes or cross, and every label can be read. Takes
// {nodes, edges, at}; answers {at}.
importScripts("netgraph.js", "layout-score.js", "sd-layout.js");
onmessage = ({ data }) => {
  const { nodes, edges, at, fixed } = data, size = NetGraph.size;
  const labels = (placed) => {
    const m = LayoutScore.mids(placed, edges, size), o = NetGraph.placeLabels(placed, edges, m);
    return Object.fromEntries(Object.entries(o).map(([id, [dx, dy]]) => [id, [m[id].x + dx, m[id].y + dy]]));
  };
  const out = SDLayout.untangle(nodes, edges, at, { size, frameOf: NetGraph.frameOf, tetherPlaces: NetGraph.tetherPlaces,
    score: LayoutScore.score, labelSize: NetGraph.labelSize, labels, fixed: fixed || [] });
  postMessage({ at: out });
};
