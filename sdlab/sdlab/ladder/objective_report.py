"""The objective test's tables (objective_test.py): per set, the share of achievable, non-C cells
labelled OK or TIE-known, the count per label, min delta, the truth's rank, |J(R) - J(T)| for right
candidates, the same labels under one-step BIC, and every objective failure (E) with its case, delta,
its D / P_num / P_struct parts and the winner's mechanism."""

from __future__ import annotations

import collections
import statistics

from . import cases as casemod

SET_TAGS = ("canonical", "distilled", "control")


def _set_of(cell: dict) -> str:
    tags = cell.get("tags") or []
    for t in SET_TAGS:
        if t in tags:
            return t
    return "tests"


def _q(xs: list[float]) -> str:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return "-"
    return f"min {xs[0]:.1f}, median {statistics.median(xs):.1f}, max {xs[-1]:.1f}"


def report(cells: list[dict]) -> tuple[str, dict]:
    lines, summary = [], {}
    by: dict[str, list] = collections.defaultdict(list)
    for c in cells:
        if not c.get("tags") and c.get("case"):
            try:
                c["tags"] = casemod.load(c["case"]).get("tags") or []
            except Exception:  # noqa: BLE001
                c["tags"] = []
        by[_set_of(c)].append(c)
    for name, cs in sorted(by.items()):
        labels = collections.Counter(_cell_label(c) for c in cs)
        judged = [c for c in cs if _cell_label(c) not in ("C", "not run", "error", "partial", "no wrong candidates")]
        ach = [c for c in judged if c.get("analysis") == "achievable"]
        good = [c for c in ach if _cell_label(c) in ("OK", "TIE-known")]
        bic = collections.Counter(c.get("label_bic", "-") for c in judged)
        s = {"cells": len(cs), "labels": dict(labels), "achievable_judged": len(ach), "achievable_ok": len(good),
             "share": (len(good) / len(ach)) if ach else None, "bic_labels": dict(bic),
             "min_delta": _q([c.get("min_delta") for c in judged]),
             "truth_rank": dict(collections.Counter(c.get("truth_rank") for c in judged)),
             "right_abs_delta": _q([x for c in judged for x in c.get("right_abs_delta") or []])}
        summary[name] = s
        lines.append(f"== set {name}: {len(cs)} cells")
        lines.append(f"   labels: {dict(sorted(labels.items()))}")
        share = f"{s['share']:.0%}" if s["share"] is not None else "-"
        lines.append(f"   achievable, non-C cells OK or TIE-known: {len(good)}/{len(ach)} ({share})")
        lines.append(f"   under one-step BIC (A-bic): {dict(sorted(bic.items()))}")
        lines.append(f"   min delta J(W*) - J(T*): {s['min_delta']};  truth's rank: {s['truth_rank']}")
        lines.append(f"   right candidates |J(R) - J(T)|: {s['right_abs_delta']}")
    lines.append("")
    lines.append("cell                                   variant          label            min delta  analysis       sanity")
    for c in sorted(cells, key=lambda c: (c.get("case", ""), c.get("variant", ""))):
        md = c.get("min_delta")
        san = c.get("sanity") or {}
        bad = [k for k, v in (san.get("checks") or {}).items() if not v]
        lines.append(f"{c.get('case', '?')[:38]:38s} {c.get('variant', '?'):16s} {_cell_label(c):16s} "
                     f"{(f'{md:9.1f}' if md is not None else '        -')}  {c.get('analysis', '-'):14s} "
                     f"{'ok' if san.get('ok') else ('fails ' + ','.join(bad)) if san else '-'}"
                     + (f"  [{c['why']}]" if c.get("why") else "") + (f"  ERROR {c['error'][:120]}" if c.get("error") else ""))
    fails = [(c, g) for c in cells for g in (c.get("groups") or {}).values() if str(g.get("label", "")).startswith("E")]
    if fails:
        lines.append("")
        lines.append("objective failures (E): case variant delta [D, P_num, P_struct] winner mechanism, strategies")
        for c, g in sorted(fails, key=lambda x: x[1]["delta"]):
            p = g["delta_parts"]
            lines.append(f"  {c['case']} {c['variant']} {g['label']} {g['delta']:.1f} [{p['D']:.1f}, {p['P_num']:.1f}, {p['P_struct']:.1f}]"
                         f" {', '.join(g.get('mechanism') or []) or '-'}; {', '.join(sorted(set(g.get('strategies') or [])))[:150] or g.get('why', '')[:150]}")
    return "\n".join(lines), summary


def _cell_label(c: dict) -> str:
    if c.get("error"):
        return "error"
    if c.get("label") == "not run":
        return "not run"
    if not c.get("done") and c.get("label") != "C":
        return "partial"
    return c.get("label") or "?"
