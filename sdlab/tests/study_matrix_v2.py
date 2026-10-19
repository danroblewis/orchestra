"""The ablation behind matrix_v2 (docs/research/matrix_v2.md): matrix_v2 run with one set of options
on every ladder cell, scored exactly as the ladder scores (sdlab.ladder.runner.run_item), and nothing
written to the result store (the store keys results by code, not by options).

    uv run python tests/study_matrix_v2.py run NAME 'OPTIONS_JSON' [CASES]   -> ABL_DIR/NAME.jsonl
    uv run python tests/study_matrix_v2.py run matrix - [CASES]              the shared matrix itself
    uv run python tests/study_matrix_v2.py table BASE NAME [NAME ...]         totals per set, cells
                                                                               better / worse than BASE
    uv run python tests/study_matrix_v2.py diff BASE NAME                     every cell that differs

OPTIONS_JSON is merged over matrix_v2's defaults (SDLAB_MATRIX_V2, read by the strategy in each
worker); "{}" is the defaults. CASES is a runner spec (default: every case the watcher runs).
Env: SET ("realistic" or "other": only those cases), RETRY (run cells that errored again), JOBS (2), ABL_DIR (~/.sdlab/matrix_v2_ablation), TIMEOUT (300). Run single-threaded:
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1.
"""

from __future__ import annotations

import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

DIR = Path(os.environ.get("ABL_DIR") or Path.home() / ".sdlab" / "matrix_v2_ablation")
RANK = {"pass": 3, "equivalent": 2, "fail": 1, "error": 0, "timeout": 0}


def _one(item: dict, timeout: float) -> dict:
    from sdlab.ladder import api, runner

    row = runner.run_item(item, timeout)
    return {"case": item["case"], "variant": item["variant"], **api.flatten(row), "found": row.get("found")}


def run(name: str, spec: str, cases: str | None) -> None:
    from sdlab.ladder import cases as casemod
    from sdlab.ladder import runner
    from sdlab.ladder.real import data as real_data

    if spec != "-":
        os.environ["SDLAB_MATRIX_V2"] = spec
    strategy = "matrix" if spec == "-" else "matrix_v2"
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / f"{name}.jsonl"
    done = set()
    if out.exists():
        rows = list(map(json.loads, out.read_text().splitlines()))
        if os.environ.get("RETRY"):            # errors (e.g. a harness file mid-edit by another agent) run again
            rows = [r for r in rows if r["status"] != "error"]
            out.write_text("".join(json.dumps(r) + "\n" for r in rows))
        done = {(r["case"], r["variant"]) for r in rows}
    only = os.environ.get("SET")               # "realistic", or "other" (every case but the realistic ones)
    items = []
    for cid in runner.select_cases(cases):
        c = casemod.load(cid)
        if only and (casemod.is_realistic(cid) != (only == "realistic")):
            continue
        for v in c["variants"]:
            if (cid, v["name"]) in done or (c.get("real") and real_data.available(c, v["name"])):
                continue
            items.append({"case": cid, "variant": v["name"], "strategy": strategy, "case_hash": "", "strategy_hash": "", "score_hash": "",
                          "mode": "run", "steps": v["steps"]})
    items.sort(key=lambda i: (casemod.is_realistic(i["case"]), i["steps"]), reverse=True)
    timeout = float(os.environ.get("TIMEOUT", 300))
    print(f"{name}: {len(items)} cells ({len(done)} done before)", flush=True)
    with ProcessPoolExecutor(max_workers=int(os.environ.get("JOBS", 2))) as pool, out.open("a") as fh:
        futs = [pool.submit(_one, {k: v for k, v in it.items() if k != "steps"}, runner.case_timeout(it["case"], timeout)) for it in items]
        for n, f in enumerate(as_completed(futs), 1):
            r = f.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            if n % 100 == 0:
                print(f"  {n}/{len(items)}", flush=True)


def load(name: str) -> dict:
    p = DIR / f"{name}.jsonl"
    return {(r["case"], r["variant"]): r for r in map(json.loads, p.read_text().splitlines())}


_meta: dict = {}


def meta(cid: str) -> dict:
    if cid not in _meta:
        from sdlab.ladder import cases as casemod
        from sdlab.ladder import leaderboard

        c = casemod.load(cid)
        _meta[cid] = {"kind": leaderboard.kind_of(c), "tags": set(c.get("tags") or []), "real": bool(c.get("real"))}
    return _meta[cid]


def totals(rows: dict) -> dict:
    from sdlab.ladder import realistic

    out = {}
    sets = {"tests": lambda m: m["kind"] == "tests", "noisy": lambda m: m["kind"] == "tests" and "noisy" in m["tags"],
            "canonical": lambda m: m["kind"] == "tests" and "canonical" in m["tags"],
            "distilled": lambda m: m["kind"] == "tests" and "distilled" in m["tags"], "physics": lambda m: m["kind"] == "physics"}
    for name, ok in sets.items():
        cs = [r for k, r in rows.items() if ok(meta(k[0]))]
        out[name] = (sum(r["status"] == "pass" for r in cs), sum(r["status"] == "equivalent" for r in cs), len(cs))
    rc = [r for k, r in rows.items() if meta(k[0])["kind"] == "realistic"]
    sk = [max(-1.0, r["skill20"]) for r in rc if r["status"] not in ("error", "timeout") and r.get("skill20") is not None and math.isfinite(r["skill20"])]
    out["realistic"] = (sum(sk) / len(sk) if sk else float("nan"), sum(realistic.meets_goal(r["status"], r.get("skill20"), r.get("skill100")) for r in rc),
                        len(rc), sum(r["status"] in ("error", "timeout") for r in rc))
    return out


def compare(base: dict, rows: dict) -> tuple[list, list]:
    better, worse = [], []
    for k, r in rows.items():
        b = base.get(k)
        if b is None or meta(k[0])["real"] or meta(k[0])["kind"] == "realistic":
            continue
        d = RANK.get(r["status"], 0) - RANK.get(b["status"], 0)
        (better if d > 0 else worse if d < 0 else []).append((k, b["status"], r["status"]))
    return better, worse


def table(base_name: str, names: list[str]) -> None:
    base = load(base_name)
    print("| run | tests P+E (of) | noisy | canonical | distilled | physics P | realistic skill@20 / goals (err) | better / worse vs " + base_name + " |")
    print("|---|---|---|---|---|---|---|---|")
    for n in [base_name] + names:
        rows = load(n)
        t = totals(rows)
        b, w = compare(base, rows)
        f = lambda x: f"{x[0]}+{x[1]} ({x[2]})"  # noqa: E731
        r = t["realistic"]
        print(f"| {n} | {f(t['tests'])} | {f(t['noisy'])} | {f(t['canonical'])} | {f(t['distilled'])} | {t['physics'][0]} ({t['physics'][2]}) "
              f"| {100 * r[0]:.1f}% / {r[1]} of {r[2]} ({r[3]}) | {len(b)} / {len(w)} |")


def diff(base_name: str, name: str) -> None:
    base, rows = load(base_name), load(name)
    b, w = compare(base, rows)
    for title, xs in (("better", b), ("worse", w)):
        print(f"{title}: {len(xs)}")
        for (c, v), s0, s1 in sorted(xs):
            print(f"  {c} {v}: {s0} -> {s1}")
    print("realistic skill@20 (base -> this):")
    for k in sorted(k for k in rows if meta(k[0])["kind"] == "realistic"):
        s0, s1 = (base.get(k) or {}).get("skill20"), rows[k].get("skill20")
        if s0 is not None and s1 is not None and abs(s0 - s1) > 0.02:
            print(f"  {k[0]} {k[1]}: {100 * max(-1, s0):.1f}% -> {100 * max(-1, s1):.1f}%")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "run":
        run(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == "table":
        table(sys.argv[2], sys.argv[3:])
    elif cmd == "diff":
        diff(sys.argv[2], sys.argv[3])
