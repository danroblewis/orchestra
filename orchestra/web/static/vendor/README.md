# Vendored libraries

The core pages load these from here, never from a CDN, so they work behind a proxy that blocks
`cdnjs.cloudflare.com` and `cdn.jsdelivr.net`. Each file is the exact pinned release, unchanged.

| File | Library | Version | From | Licence |
|---|---|---|---|---|
| `d3.min.js` | d3 (Machines, Dynamics) | 7.9.0 | `cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js` (the same bytes as npm `d3@7.9.0/dist/d3.min.js`) | ISC, `d3.LICENSE` |
| `elk.bundled.js` | elkjs (Dynamics layout) | 0.9.3 | npm `elkjs@0.9.3/lib/elk.bundled.js` | EPL-2.0, `elkjs.LICENSE.md` |
| `gridstack-all.js`, `gridstack.min.css` | GridStack (Dashboard) | 10.3.1 | npm `gridstack@10.3.1/dist/` | MIT, `gridstack.LICENSE`, `gridstack-all.js.LICENSE.txt` |

To upgrade one, replace its file with the new release's, unchanged, and update its row here.
