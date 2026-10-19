"""The real cases' results per strategy: python -m sdlab.ladder.real report [--strategies a,b] [--by source] [--case ID].

Read from the result store (api.summary), never recomputed: per strategy and variant (real, twin),
the runs done, the mean held-out skill against persistence (each run clipped at -100%) beside the
published model's on the same runs, the runs at least as good as the published model, agreement with
the published structure (mean recall and precision; runs agreeing exactly), BLS's measured flows
matched, and on the twin the ladder's own verdicts. --by source splits it by data source; --case
prints one case's runs in full (held-out skill per stock, the parts matched, missed and extra).
"""

from __future__ import annotations

import argparse

from .. import api
from .. import cases as casemod


def pct(v) -> str:
    return "–" if v is None else f"{100 * v:.1f}%"


def _rows(sm: dict, strategies: list[str] | None, source: str | None = None) -> list[dict]:
    src = {c["id"]: (c.get("real") or {}).get("source") for c in sm["cases"] if c.get("real")}
    return [c for c in sm["cells"] if c["case"] in src and (not strategies or c["strategy"] in strategies) and (source is None or src[c["case"]] == source)]


def table(cells: list[dict], names: list[str]) -> list[str]:
    out = ["| strategy | variant | run | held-out skill | published (same runs) | ≥ published | agreement recall / precision | agree | flows matched (BLS) | twin pass / equiv / fail |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for n in names:
        for v in ("real", "twin"):
            cs = [c for c in cells if c["strategy"] == n and c["variant"] == v]
            ran = [c for c in cs if c.get("status")]
            g = [c for c in ran if c.get("heldout") is not None and c.get("heldout_published") is not None]
            mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
            hs, hp = mean([max(-1.0, c["heldout"]) for c in g]), mean([max(-1.0, c["heldout_published"]) for c in g])
            rec, pre = mean([c["agree_recall"] for c in ran if c.get("agree_recall") is not None]), mean([c["agree_precision"] for c in ran if c.get("agree_precision") is not None])
            fl = [c for c in ran if c.get("flows_of")]
            flows = f"{sum(c['flows_matched'] for c in fl)}/{sum(c['flows_of'] for c in fl)} (found {sum(c['flows_found'] for c in fl)})" if fl else "–"
            twin = "/".join(str(sum(c["status"] == k for c in ran)) for k in ("pass", "equivalent", "fail")) if v == "twin" else "–"
            bad = sum(c["status"] in ("error", "timeout") for c in ran)
            out.append(f"| {n} | {v} | {len(ran)}/{len(cs)}{f' ({bad} error/timeout)' if bad else ''} | {pct(hs)} ({len(g)} graded) | {pct(hp)} | "
                       f"{sum(bool(c.get('beats_published')) for c in g)}/{len(g)} | {pct(rec)} / {pct(pre)} | {sum(bool(c.get('agrees')) for c in ran)} | {flows} | {twin} |")
    return out


def one_case(case_id: str, names: list[str]) -> list[str]:
    c = casemod.load(case_id)
    out = [f"{case_id}: {c['title']} ({c['real']['points']} samples, discovery sees {c['real']['train']}; published: {c['real']['published']['family']})"]
    for n in names:
        for v in ("real", "twin"):
            r = api.result(case_id, v, n)
            if not r:
                out.append(f"  {n} {v}: not run")
                continue
            s = r.get("scores") or {}
            h, ag = s.get("heldout") or {}, s.get("agreement") or {}
            out.append(f"  {n} {v}: {r['status']}{' ' + r['error'][:120] if r.get('error') else ''}; held-out skill {pct(h.get('skill'))} (published {pct(h.get('published'))}) over {h.get('points')} samples;"
                       f" agreement {pct(ag.get('recall'))} / {pct(ag.get('precision'))}")
            if ag:
                out.append(f"      matched {ag.get('matched')}; missed {ag.get('missing')}; extra {ag.get('extra')}")
            for k, x in ((s.get("flows") or {}).get("rows") or {}).items():
                out.append(f"      {k}: measured {x['measured_mean']:.0f}/month, found {x['found_mean']:.0f} ({'matched' if x['matched'] else 'error ' + pct(x['error'])});"
                           f" net measured {x['net_measured']:.0f}, found {x['net_found']:.0f}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sdlab.ladder.real report")
    ap.add_argument("--strategies", default="combined,lna,effect_hats,censored,earned_pieces,matrix")
    ap.add_argument("--by", choices=("all", "source"), default="all")
    ap.add_argument("--case")
    a = ap.parse_args(argv)
    names = [x.strip() for x in a.strategies.split(",") if x.strip()]
    if a.case:
        print("\n".join(one_case(a.case, names)))
        return 0
    sm = api.summary()
    if a.by == "all":
        print("\n".join(table(_rows(sm, names), names)))
    else:
        for src in ("bls", "gauseR", "pomp", "owid"):
            print(f"\n{src}\n")
            print("\n".join(table(_rows(sm, names, src), names)))
    return 0
