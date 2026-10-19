"""combined2 against combined and against each specialist, per set, from the ladder's summary (the
store's latest results; docs/research/combined2.md). Also: every cell some specialist in combined2
passes and combined2 does not (its losses to explain), and time per cell.

    uv run python tests/study_combined2_compare.py [OUT.json]

Sets: tests (every non-realistic, non-physics, non-real case), and within it noisy, canonical,
distilled; physics; particles; realistic (skill@20, goals met, recall); real twins (pass or
equivalent). A cell a strategy has not run is "not run", never a fail.
"""

from __future__ import annotations

import collections
import json
import sys

SPECIALISTS = ["kalman_lna", "structures", "archetypes", "odefit", "own_tables", "drifting_drain", "censored", "coflow_hats", "realistic_hats",
               "effect_hats", "hidden_transit", "common_cause", "lna", "lna_stack", "lna_pulses", "gap_prior", "periodic_inflows"]
NAMES = ["combined2", "combined"] + SPECIALISTS


def sets_of(c: dict, meta: dict, tags: list) -> list[str]:
    if meta["rd"]:
        return ["twins"] if c["variant"] == "twin" else []
    if meta["real"]:
        return ["realistic"]
    if meta["part"]:
        return ["particles"]
    if meta["phys"]:
        return ["physics"]
    return ["tests"] + [t for t in ("noisy", "canonical", "distilled") if t in tags]


def main(argv: list[str]) -> None:
    from sdlab.ladder import leaderboard as L

    sm, _ = L.summary_now()
    ix = L.index(sm)
    tags = {c["id"]: c.get("tags") or [] for c in sm["cases"]}
    by: dict = collections.defaultdict(dict)
    for c in sm["cells"]:
        if c["strategy"] in NAMES and c.get("status"):
            by[(c["case"], c["variant"])][c["strategy"]] = c
    mine = {k: v for k, v in by.items() if "combined2" in v}
    out: dict = {"sets": {}, "losses": [], "time": {}}
    for S in ("tests", "noisy", "canonical", "distilled", "physics", "particles", "realistic", "twins"):
        rows = {}
        cells = [(k, v) for k, v in mine.items() if S in sets_of(v["combined2"], ix["meta"][k[0]], tags[k[0]])]
        for n in NAMES:
            got = [v[n] for _, v in cells if n in v]
            if not got:
                continue
            r = {"run": len(got), "of": len(cells), "pass": sum(1 for c in got if c["status"] == "pass"),
                 "equivalent": sum(1 for c in got if c["status"] == "equivalent"),
                 "strict": sum(1 for c in got if c.get("strict") == 1), "strict_known": sum(1 for c in got if c.get("strict") is not None),
                 "seconds": round(sum(c.get("seconds") or 0 for c in got) / len(got), 1)}
            sk = [max(-1.0, c["skill20"]) for c in got if c.get("skill20") is not None]
            r["skill20"] = round(100 * sum(sk) / len(sk), 1) if sk else None
            rc = [c["recall"] for c in got if c.get("recall") is not None]
            r["recall"] = round(100 * sum(rc) / len(rc), 1) if rc else None
            r["goals"] = sum(1 for c in got if c.get("goal"))
            rows[n] = r
        out["sets"][S] = rows
    for k, v in sorted(mine.items()):
        if v["combined2"]["status"] == "pass":
            continue
        who = [n for n in SPECIALISTS + ["combined"] if (v.get(n) or {}).get("status") == "pass"]
        if who:
            out["losses"].append({"case": k[0], "variant": k[1], "combined2": v["combined2"]["status"], "passed_by": who})
    json.dump(out, open(argv[0], "w") if argv else sys.stdout, indent=1)
    if argv:
        for S, rows in out["sets"].items():
            print(f"== {S}")
            for n, r in rows.items():
                print(f"   {n:16s} {r['pass']:4d} pass + {r['equivalent']:3d} eq of {r['run']:4d} (of {r['of']}); strict {r['strict']}/{r['strict_known']};"
                      f" skill@20 {r['skill20']}; recall {r['recall']}; goals {r['goals']}; {r['seconds']} s/cell")
        print(f"losses: {len(out['losses'])}")


if __name__ == "__main__":
    main(sys.argv[1:])
