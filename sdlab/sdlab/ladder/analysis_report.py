"""`sdlab-ladder analyse`: a case's analysis (analysis.py) as text.

    sdlab-ladder analyse CASE [--variant V] [--json]     what the data can deliver, per variant
    sdlab-ladder analyse --all [--cases ...] [--jobs N]   fill the cache for every case; the labels' counts
    sdlab-ladder analyse --validate CASE --variant V [--seeds 20]
                                                          the bound against the spread of ML refits on fresh seeds
"""

from __future__ import annotations

import json
import sys

import numpy as np

from . import analysis
from . import cases as casemod

MARK = {"achievable": "ok", "data-limited": "DATA-LIMITED", "unidentifiable": "UNIDENTIFIABLE", "not analysed": "not analysed"}


def _g(x, fmt=".3g") -> str:
    return "-" if x is None else format(x, fmt)


def text(a: dict) -> str:
    out = [f"== {a['variant']} ({a['steps']} steps, noise {a['noise']}): {MARK.get(a['label'], a['label'])}"
           + ("" if a.get("p") is None else f", p = {a['p']:.3f} (numbers {_g(a.get('numbers_p'))} x structure {_g(a.get('structure_p'))})")]
    for w in a.get("why") or []:
        out.append(f"   why: {w}")
    out.append("   Structure (each stock's change on every level and a constant, weighted by its noise):")
    for row in a.get("design") or []:
        out.append(f"     {row['stock']}: rank {row['rank']} of {row['of']}, condition {row['cond']:.3g}; detect a term at z > {row['threshold']:.2f}")
        for t in row["terms"]:
            out.append(f"        {row['stock']} <- {t['column']:14s} true {t['true']:<10.4g} SE (all columns) {_g(t['se_full']):>9s}"
                       f"  z {_g(t['z'], '.1f'):>7s}  P(detected) {t['p_detect']:.2f}")
        for g in row["collinear"]:
            out.append(f"        {'exactly' if g['exact'] else 'nearly'} collinear: " + ", ".join(f"{w:+.2f} {c}" for c, w in zip(g["columns"], g["weights"]))
                       + f" (relative size {g['relative_size']:.1e})")
    if a.get("parameters"):
        out.append("   Numbers (Cramér-Rao bound: the best SE any unbiased method can reach; mean only = least squares;"
                   " noisy variants: the Kalman filter's SE on the reported data):")
        for p in a["parameters"]:
            se = p.get("crb_se", p.get("se_kalman"))                  # noise_analysis.py gives se_kalman and no mean-only SE
            out.append(f"     {p['name']:36s} true {p['true']:<10.4g} bound SE {_g(se):>9s}"
                       + (f"  (mean only {_g(p['crb_se_mean_only'])})" if "crb_se_mean_only" in p else "  (Kalman)" if "se_kalman" in p else "")
                       + ("  NOT IDENTIFIED" if p.get("unidentified") else ""))
    if a.get("parts"):
        out.append("   Scored parts: P(an estimate at the bound is within the scorer's tolerance):")
        for r in a["parts"]:
            rel = (r["crb_se"] / abs(r["true"])) if r.get("crb_se") is not None and r.get("true") else None
            out.append(f"     {r['part'] + (' w' + str(r['window']) if r.get('window') else ''):40s} "
                       + (f"true {r['true']:<10.4g} " if r.get("true") is not None else "")
                       + f"bound SE {_g(r.get('crb_se')):>9s}" + (f" ({100 * rel:.1f}%)" if rel is not None else "")
                       + f"  allowed {_g(r['allowed']):>9s}  p {r['p']:.3f}"
                       + ("  (variance only)" if r.get("variance_only") else "") + ("  NOT IDENTIFIED" if r.get("unidentified") else ""))
    for e in a.get("effects") or []:
        out.append(f"     flow {e['ends'][0]} -> {e['ends'][1]} (effects, as a whole): rms SE {100 * e['rel_rms_se']:.1f}% of its amount,"
                   f" allowed {100 * e['allowed']:.0f}%, p {_g(e.get('p'))}")
    for x in a.get("equivalences") or []:
        out.append(f"   equivalent: {x}")
    for n in a.get("notes") or []:
        out.append(f"   note: {n}")
    return "\n".join(out)


def run(cases: list[str], variant: str | None, as_json: bool) -> int:
    for cid in cases:
        c = casemod.load(cid)
        got = [analysis.get(cid, v["name"]) for v in c["variants"] if not variant or variant in (v["name"], v["noise"], v["length"])]
        if as_json:
            print(json.dumps(got, indent=1))
            continue
        print(f"{cid}: {c['title']}\n  tests: {c['tests']}\n")
        for a in got:
            print(text(a) + "\n")
    return 0


def run_all(cases: list[str], jobs: int | None) -> int:
    counts: dict[str, int] = {}
    errors = []

    def done(r):
        counts[r[2]] = counts.get(r[2], 0) + 1
        if r[4]:
            errors.append(r)

    analysis.analyse_all(cases, jobs, done)
    print("Cells by label: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])))
    for cid, v, _, _, err in errors:
        print(f"  error: {cid} {v}: {err}", file=sys.stderr)
    return 1 if errors else 0


def validate(case_id: str, variant: str, seeds: int) -> int:
    """The bound against the spread of the true structure refitted by ML on fresh seeds."""
    from .data import simulate
    from .fisher import TruthParams, bound

    c = casemod.load(case_id)
    v = casemod.variant(c, variant)
    tm = casemod.truth_model(c, variant)
    est, ses = [], []
    for s in range(seeds):
        d = simulate(tm, 10_000 + s, v["steps"])
        tp = TruthParams(tm, d, v["noise"])
        est.append(tp.ml_fit())
        C, _ = bound(tp.fisher()["full"])
        ses.append(np.sqrt(np.maximum(np.diag(C), 0)))
    est, ses = np.array(est), np.array(ses)
    print(f"{case_id} {variant}: ML refit of the true structure on {seeds} fresh seeds vs the Cramér-Rao bound")
    for i, name in enumerate(tp.labels):
        sd, crb = est[:, i].std(ddof=1), ses[:, i].mean()
        print(f"  {name:36s} true {tp.theta0[i]:<9.4g} mean {est[:, i].mean():<9.4g} sd {sd:<9.3g} bound {crb:<9.3g} sd/bound {sd / crb if crb else float('nan'):.2f}")
    return 0
