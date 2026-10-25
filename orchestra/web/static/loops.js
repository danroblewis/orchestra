// Feedback loops, found the same way for the Dynamics graph and the Machines page's event map.
//
// A graph has many more elementary cycles than loops worth reading (the bakery's event map: 649).
// They are grouped and reduced by what can be shown, not by what looks alike:
//
// 1. feedback structures: the strongly connected parts of the graph (every node in one reaches
//    every other). Every cycle lies inside exactly one, and they are unique;
// 2. in each, an independent loop set: the shortest cycle through each link, taken shortest first
//    and kept only when it uses a link no loop kept before it uses (Oliva, "Model structure analysis
//    through graph theory", System Dynamics Review, 2004). Every other cycle is made of these
//    loops' links; there are at most links − nodes + 1 of them per structure;
// 3. cycles through exactly the same nodes are one loop with several routes;
// 4. two nodes that link both ways directly are an exchange (a request and its reply), listed
//    apart and not counted as loops; a loop is at least three nodes long.
//
// Edges are {source, target, sign?, kind?, via?}; ``sign`` (+1/−1) gives a loop's polarity
// (balancing when the product is negative), ``kind`` lets the caller say what each link is.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Loops = factory();
})(typeof self !== "undefined" ? self : this, function () {
  // strongly connected parts (Tarjan), as arrays of node ids
  function structures(nodeIds, edges) {
    const adj = new Map(nodeIds.map((id) => [id, []]));
    for (const e of edges) if (adj.has(e.source) && adj.has(e.target)) adj.get(e.source).push(e.target);
    let i = 0;
    const index = new Map(), low = new Map(), on = new Set(), stack = [], out = [];
    const visit = (v) => {                      // iterative, so deep graphs cannot overflow the stack
      const work = [[v, 0]];
      index.set(v, i); low.set(v, i); i++; stack.push(v); on.add(v);
      while (work.length) {
        const top = work[work.length - 1], [u, k] = top, next = adj.get(u);
        if (k < next.length) {
          top[1]++;
          const w = next[k];
          if (!index.has(w)) { index.set(w, i); low.set(w, i); i++; stack.push(w); on.add(w); work.push([w, 0]); }
          else if (on.has(w)) low.set(u, Math.min(low.get(u), index.get(w)));
        } else {
          work.pop();
          if (work.length) { const p = work[work.length - 1][0]; low.set(p, Math.min(low.get(p), low.get(u))); }
          if (low.get(u) === index.get(u)) {
            const part = [];
            let w;
            do { w = stack.pop(); on.delete(w); part.push(w); } while (w !== u);
            out.push(part);
          }
        }
      }
    };
    for (const v of nodeIds) if (!index.has(v)) visit(v);
    return out;
  }

  // the shortest path from a to b inside ``members`` (BFS), not using the link ``skip`` ("x>y")
  function shortestPath(adj, members, a, b, skip) {
    const prev = new Map([[a, null]]), queue = [a];
    while (queue.length) {
      const u = queue.shift();
      if (u === b) break;
      for (const w of adj.get(u) || []) {
        if (!members.has(w) || prev.has(w) || `${u}>${w}` === skip) continue;
        prev.set(w, u); queue.push(w);
      }
    }
    if (!prev.has(b)) return null;
    const path = [];
    for (let v = b; v !== null; v = prev.get(v)) path.unshift(v);
    return path;
  }

  // how many elementary cycles a part has, counted up to ``cap`` (for "and N more")
  function countCycles(members, adj, cap = 2000) {
    const ids = [...members], order = new Map(ids.map((id, k) => [id, k]));
    let n = 0;
    for (const start of ids) {
      const s = order.get(start), onPath = new Set([start]);
      const go = (v, depth) => {
        for (const w of adj.get(v) || []) {
          if (n >= cap) return;
          if (!members.has(w)) continue;
          if (w === start) { n++; continue; }
          if (order.get(w) < s || onPath.has(w) || depth > 24) continue;
          onPath.add(w); go(w, depth + 1); onPath.delete(w);
        }
      };
      go(start, 0);
      if (n >= cap) break;
    }
    return n;
  }

  // ``minLength``: the fewest nodes a loop may have (3 when two-way pairs are exchanges)
  function analyse(nodeIds, edges, { exchanges = false, minLength = exchanges ? 3 : 1 } = {}) {
    const adj = new Map(nodeIds.map((id) => [id, []])), link = new Map();
    for (const e of edges) {
      if (!adj.has(e.source) || !adj.has(e.target)) continue;
      const k = `${e.source}>${e.target}`;
      if (!link.has(k)) { adj.get(e.source).push(e.target); link.set(k, []); }
      link.get(k).push(e);
    }
    const pairs = [];
    if (exchanges) {
      for (const k of link.keys()) {
        const [a, b] = k.split(">");
        if (a < b && link.has(`${b}>${a}`)) pairs.push({ nodes: [a, b], there: link.get(k), back: link.get(`${b}>${a}`) });
      }
    }
    const out = { structures: [], exchanges: pairs };
    for (const part of structures(nodeIds, edges)) {
      const members = new Set(part);
      const inner = [...link.keys()].filter((k) => { const [a, b] = k.split(">"); return members.has(a) && members.has(b); });
      if (!inner.length) continue;
      // the shortest cycle through each link (of at least minLength nodes)
      const candidates = [];
      for (const k of inner) {
        const [u, v] = k.split(">");
        if (u === v) { if (minLength <= 1) candidates.push([u]); continue; }
        let path = shortestPath(adj, members, v, u, minLength > 2 ? `${v}>${u}` : null);
        if (!path) continue;
        if (path.length < minLength) {                           // too short: look for the shortest long enough
          path = null;
          for (const w of adj.get(v)) {
            if (w === u || !members.has(w)) continue;
            const p = shortestPath(adj, members, w, u, `${v}>${u}`);
            if (p && !p.includes(v) && p.length + 1 >= minLength && (!path || p.length + 1 < path.length)) path = [v, ...p];
          }
          if (!path) continue;
        }
        candidates.push([u, ...path.slice(0, -1)]);               // u → v → … → (back to u)
      }
      candidates.sort((a, b) => a.length - b.length);
      // keep a cycle when it uses a link no kept cycle uses; merge cycles through the same nodes
      const covered = new Set(), kept = [], bySet = new Map();
      for (const c0 of candidates) {
        const r0 = c0.indexOf([...c0].sort()[0]), c = [...c0.slice(r0), ...c0.slice(0, r0)];   // one rotation per cycle
        const ks = c.map((id, j) => `${id}>${c[(j + 1) % c.length]}`);
        const key = [...c].sort().join("|");
        if (bySet.has(key)) { const l = bySet.get(key); if (!l.routes.some((r) => r.join() === c.join())) l.routes.push(c); ks.forEach((x) => covered.add(x)); continue; }
        if (ks.every((x) => covered.has(x))) continue;
        ks.forEach((x) => covered.add(x));
        const loop = { nodes: c, links: ks.map((x) => link.get(x)), routes: [c] };
        const signs = loop.links.map((ls) => (ls[0].sign == null ? 1 : ls[0].sign));
        loop.negatives = signs.filter((s) => s < 0).length;
        loop.polarity = signs.some((s) => s === 0) ? "?" : loop.negatives % 2 ? "B" : "R";
        kept.push(loop); bySet.set(key, loop);
      }
      if (!kept.length) continue;
      const nodesIn = part.length, linksIn = inner.length;
      out.structures.push({ nodes: part, loops: kept, links: linksIn, independent: linksIn - nodesIn + 1, cycles: countCycles(members, adj) });
    }
    out.structures.sort((a, b) => b.nodes.length - a.nodes.length);
    return out;
  }

  return { analyse, structures };
});
