"""Z3 solve times of z3robust's encodings on ladder cells (docs/research/z3robust.md, "Encodings"):

    uv run python -m sdlab.discovery.strategies.z3robust.compare 007-link/counts-short 044-random-three-stocks#2/none-short

For each cell (the class "ends, kinds", what a page gets): the equations ("compressed", every step rotated;
or "blocks", sums of consecutive steps), each encoding's status, seconds, terms and objective (L1 + price on
the equations it read). A development tool: it reads the case through the harness, as runner.discover does.
"""

from __future__ import annotations

import sys

from . import core, robust

RUNS = (("compressed", "band"), ("compressed", "weighted"), ("compressed", "ladder"), ("blocks", "maxsmt"), ("blocks", "weighted"))
TIMEOUT = 20.0


def _problem(cell: str) -> core.Problem:
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import data
    cid, var = cell.rsplit("/", 1)
    c = casemod.load(cid)
    model = casemod.truth_model(c, var)
    d = {**data.load(c, var), **casemod.announced(c)}
    run = {"t": d["t"], "levels": d["levels"]}
    if d.get("boundary_declared"):
        run.update(boundary=d["boundary"], boundary_declared=True)
    opts = {"eras": d["eras"] if len(d.get("eras") or []) > 1 else None, "inputs": d.get("inputs"), "injections": d.get("injections")}
    return core.prepare(casemod.page_stocks(model), run, opts, pooled=True)


def main(cells: list[str]) -> None:
    for cell in cells:
        p = _problem(cell)
        for eq, enc in RUNS:
            B = robust.Compressed(p) if eq == "compressed" else robust.Blocks(p)
            sigma = robust.noise_scales(p, B)
            cand = robust.screen(p, B, sigma)
            g = robust.solve_guarded(p, B, cand, sigma, {}, TIMEOUT, encoding=enc)
            obj = robust.objective(p, B, g["support"], g["numbers"], sigma, g["price"])
            print(f"{cell}\t{eq}\t{enc}\t{len(cand)} candidates\t{g['status']}\t{g['seconds']:.2f} s\t{len(g['support'])} terms"
                  f"\tobjective {obj:.4g}\t{g.get('from', 'z3')}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
