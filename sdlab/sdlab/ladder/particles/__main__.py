"""python -m sdlab.ladder.particles [report] [--cases ID,...]: each particle case's regions, particles, tier,
mean-field check and noise against the ladder's counting noise.

Noise: on the case's counts-long run, the one-step residual of each region (its count minus the mean-field
model's one step from the counts before) has variance `observed`; the ladder's counting noise (each flow
Poisson around its rate) would give `poisson` = the sum of the region's flow amounts; the particles'
own (binomial moves) give `binomial` = sum of n k (1 - k) over the moves in and out and the inflows'
Poisson. The ratios observed / poisson are printed per case (median over regions)."""

from __future__ import annotations

import argparse

import numpy as np

from .. import cases as casemod
from .. import data as datamod
from . import meanfield


def noise(c: dict) -> dict:
    d = datamod.load(c, "counts-long")
    ids = list(d["levels"])
    X = np.array([d["levels"][s] for s in ids], dtype=float)
    t = d["t"]
    flows = meanfield.timed(c["model"], len(t) + 1)
    from ...discovery.simulate import Model
    m = Model(flows, ids, inputs={"t": t, "values": d["inputs"]} if d.get("inputs") else None)
    inj: dict[int, float] = {}
    for j in d.get("injections") or []:
        inj[(int(j["t"]), ids.index(j["stock"]))] = inj.get((int(j["t"]), ids.index(j["stock"])), 0.0) + float(j["amount"])
    L = X[:, :-1].copy()
    for (tk, i), a in inj.items():
        if 2 <= tk <= len(t):
            L[i, tk - 2] += a
    tt = np.asarray(t[1:], dtype=float)
    amounts = m._amounts(L, tt)
    pred = L + m.change(L, tt)
    res = X[:, 1:] - pred
    pois, binom = np.zeros_like(L), np.zeros_like(L)
    for f, a in zip(flows, amounts):
        n_from = L[ids.index(f["from"])] if f.get("from") in ids else None
        q = np.where(n_from > 0, a / np.maximum(n_from, 1e-9), 0.0) if n_from is not None else None
        v = a * (1 - q) if q is not None and not f.get("effects") else a
        for end in (f.get("from"), f.get("to")):
            if end in ids:
                pois[ids.index(end)] += a
                binom[ids.index(end)] += v
    ok = pois > 1e-9
    obs = np.array([np.var(res[i][ok[i]]) for i in range(len(ids))])
    return {"observed_over_poisson": float(np.median(obs / np.array([np.mean(pois[i][ok[i]]) for i in range(len(ids))]))),
            "binomial_over_poisson": float(np.median([np.mean(binom[i][ok[i]]) / np.mean(pois[i][ok[i]]) for i in range(len(ids))]))}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m sdlab.ladder.particles")
    ap.add_argument("what", nargs="?", default="report", choices=["report"])
    ap.add_argument("--cases")
    a = ap.parse_args(argv)
    ids = [i for i in casemod.case_ids() if casemod.is_particles(i)]
    if a.cases:
        ids = [i for i in ids if i in a.cases.split(",")]
    print("| case | system | tier | regions | particles (mean) | flows | check z rms | check gap | noise observed / Poisson | binomial / Poisson |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for cid in ids:
        c = casemod.load(cid)
        pt = c["particles"]
        nz = noise(c) if pt["equations"] else {}
        f = lambda x: "–" if x is None else f"{x:.2f}"     # noqa: E731
        print(f"| {cid} | {pt['system']} | {pt['tier']} | {pt['regions']} | {pt['particles']:,} | {len(c['model']['flows'])} | "
              f"{pt['check']['z_rms']:.2f} | {100 * pt['check']['rel']:.1f}% | {f(nz.get('observed_over_poisson'))} | {f(nz.get('binomial_over_poisson'))} |")


if __name__ == "__main__":
    main()
