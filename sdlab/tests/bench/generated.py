"""The bench on generated models (tests/bench/generator.py): evaluate.py --generated N.

    uv run python tests/bench/evaluate.py --generated 300                        dev models 0-299, both lengths
    uv run python tests/bench/evaluate.py --generated 100 --features coflow      dev models built with a co-flow
    uv run python tests/bench/evaluate.py --generated 300 --pool sealed --i-am-adopting --label "adopt X"

Each model is run at its default length and its long length (five times longer), graded as the
examples are (grade.py: parts against the answer key Truth.truth() derives, skill@5/@20/@100, and
skill on a fresh run with other random draws), and reported by motif family: for each family, the
runs of every model that has it. The headline (mean skill@20 and @100, each run clipped at -100%,
and runs meeting the goal) is computed as for the examples, so the two can be compared.

The sealed pool is scored only when a change is adopted (--i-am-adopting, with a --label naming
it); every sealed scoring is appended to sealed-log.jsonl next to the runs, so peeking shows.
Runs are saved under <bench cache>/runs/generated (not where the research view lists example runs);
without --baseline a run is compared with the latest earlier run of this branch on the same models.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import generator
from grade import grade, key_of, same_behaviour

from sdlab.discovery.strategies import load

HORIZONS = (5, 20, 100)
LENGTHS = ("default", "long")


def refuse_sealed(a) -> str | None:
    """Why this run may not score the sealed pool (None: it may)."""
    if a.pool != "sealed":
        return None
    if not a.i_am_adopting:
        return ("the sealed pool is scored only when a change is adopted: add --i-am-adopting (and --label "
                "naming the change). Develop on --pool dev.")
    if not a.label:
        return "a sealed scoring needs --label naming the change being adopted"
    return None


def specs(pool: str, n: int, features: tuple) -> list[tuple]:
    return [(pool, i, features) for i in range(n)]


def steps_of(model: dict, length: str) -> int:
    return int(model["long_steps"] if length == "long" else model["steps"])


def prepare(spec: tuple) -> dict:
    """Build (or load) the model and its datasets."""
    began = time.time()
    cached = generator.model_path(*spec).exists()
    try:
        model = generator.get(*spec)
    except RuntimeError as e:
        return {"spec": spec, "error": str(e), "seconds": time.time() - began, "cached": False}
    for length in LENGTHS:
        for seed in (model["seed"], model["seed"] + 1):
            generator.dataset(model, steps_of(model, length), seed)
    return {"spec": spec, "id": model["id"], "seconds": time.time() - began, "cached": cached}


def evaluate_generated(spec: tuple, length: str, strategy: str) -> dict:
    model = generator.get(*spec)
    steps = steps_of(model, length)
    data = generator.dataset(model, steps, model["seed"])
    stocks = [{"id": s["id"], "name": s["name"], "unit": s["unit"]} for s in model["stocks"] if s.get("measured", True)]
    eras = [{"start": e["start"], "label": e.get("label")} for e in data.get("eras") or []]
    began, error = time.time(), None
    try:
        r = load(strategy)(stocks, {"t": data["t"], "levels": data["levels"]}, {"eras": eras if len(eras) > 1 else None})
    except Exception:
        error = " ".join(traceback.format_exc().strip().splitlines()[-3:])
        r = {"flows": []}
    ms = round(1000 * (time.time() - began))
    g = grade(r, key_of(generator.truth(model).truth()))
    behaviour = {h: same_behaviour(r, model, data, horizon=h) for h in HORIZONS}
    other = generator.dataset(model, steps, model["seed"] + 1)
    fresh = {str(h): same_behaviour(r, model, other, horizon=h)["skill"] for h in (20, 100)}
    # the ceiling: the true flows themselves, without the schedule's unannounced changes to rates
    # inside the system (a demand, a season); 100% when every unannounced change is an outside inflow
    ceiling = same_behaviour({"flows": model["flows"]}, model, data, horizon=20)["skill"]
    return {"example": model["id"], "length": length, "steps": steps, "motifs": model["generated"]["motifs"],
            "measured": len(stocks), "hidden": len(model["stocks"]) - len(stocks), "parts": g["right"], "of": g["parts"],
            "skill": {str(h): b["skill"] for h, b in behaviour.items()}, "moved": {str(h): b["moved"] for h, b in behaviour.items()},
            "fresh": fresh, "ceiling": ceiling, "ms": ms, "flows": len(r["flows"]), "error": error}


def clip(x: float) -> float:
    return max(-1.0, x)


def pct(v) -> str:
    return "-" if v is None else f"{100 * v:.1f}%"


def delta(now, then) -> str:
    if then is None:
        return ""
    d = now - then
    return "" if abs(d) < 0.0005 else f" ({'+' if d > 0 else ''}{100 * d:.1f})"


def summary(rs: list[dict], meets) -> dict:
    n = max(1, len(rs))
    return {"runs": len(rs), "models": len({x["example"] for x in rs}),
            "s20": sum(clip(x["skill"]["20"]) for x in rs) / n, "s100": sum(clip(x["skill"]["100"]) for x in rs) / n,
            "f20": sum(clip(x["fresh"]["20"]) for x in rs) / n, "f100": sum(clip(x["fresh"]["100"]) for x in rs) / n,
            "parts": sum(x["parts"] for x in rs) / max(1, sum(x["of"] for x in rs)), "goal": sum(1 for x in rs if meets(x)),
            "ceiling": sum(clip(x.get("ceiling", 1.0)) for x in rs) / n,
            "median20": statistics.median(x["skill"]["20"] for x in rs) if rs else 0.0, "above0": sum(1 for x in rs if x["skill"]["20"] > 0)}


def groups(results: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for f in generator.FAMILIES:
        rs = [x for x in results if f in x["motifs"]]
        if rs:
            out[f] = rs
    return out


def sizes(results: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for name, lo, hi in (("3-5 measured", 3, 5), ("6-9 measured", 6, 9), ("10-15 measured", 10, 15)):
        rs = [x for x in results if lo <= x["measured"] <= hi]
        if rs:
            out[name] = rs
    return out


def table(title: str, rows: dict[str, list[dict]], base: dict[str, list[dict]] | None, meets) -> list[str]:
    lines = [f"| {title} | models | runs | skill@20 | skill@100 | median skill@20 | better than no change @20 | fresh @20 / @100 | parts | meeting the goal |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, rs in sorted(rows.items(), key=lambda kv: -summary(kv[1], meets)["s20"]):
        s, b = summary(rs, meets), (summary(base[name], meets) if base and base.get(name) else None)
        lines.append(f"| {name} | {s['models']} | {s['runs']} | {pct(s['s20'])}{delta(s['s20'], b and b['s20'])} | "
                     f"{pct(s['s100'])}{delta(s['s100'], b and b['s100'])} | {pct(s['median20'])} | {pct(s['above0'] / max(1, s['runs']))} | {pct(s['f20'])} / {pct(s['f100'])} | {pct(s['parts'])} | "
                     f"{s['goal']} of {s['runs']} ({pct(s['goal'] / max(1, s['runs']))}) |")
    return lines


def main(a, runs: Path, git, meets) -> None:
    why = refuse_sealed(a)
    if why:
        print(f"Refused: {why}", file=sys.stderr)
        sys.exit(2)
    features = tuple(f for f in (a.features or "").split(",") if f)
    unknown = [f for f in features if f not in generator.FAMILIES]
    if unknown:
        sys.exit(f"unknown motif families: {', '.join(unknown)} (known: {', '.join(generator.FAMILIES)})")
    if a.pool == "dev" and generator.held_out(features):
        sys.exit(f"held out of the development pool: {', '.join(generator.held_out(features))}")
    n = min(a.generated, generator.SEALED_SIZE) if a.pool == "sealed" else a.generated
    lengths = [x for x in a.lengths.split(",") if x in LENGTHS] or list(LENGTHS)
    out_dir = runs / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    began = time.time()
    built, failed = [], []
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        for fut in as_completed([pool.submit(prepare, s) for s in specs(a.pool, n, features)]):
            x = fut.result()
            (failed if x.get("error") else built).append(x)
    build_s = time.time() - began
    fresh_built = [x for x in built if not x["cached"]]
    print(f"  {len(built)} models ready in {build_s:.0f} s ({len(fresh_built)} built now, {len(built) - len(fresh_built)} from the cache)"
          + (f"; {len(failed)} could not be built" if failed else ""), file=sys.stderr)

    began = time.time()
    jobs = sorted(((x["spec"], length) for x in built for length in lengths), key=lambda j: j[1] != "long")
    results = []
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        futures = {pool.submit(evaluate_generated, spec, length, a.strategy): (spec, length) for spec, length in jobs}
        for i, fut in enumerate(as_completed(futures)):
            x = fut.result()
            results.append(x)
            if (i + 1) % 25 == 0 or x["error"]:
                print(f"  {i + 1}/{len(jobs)} runs" + (f"; {x['example']} {x['length']} ERROR {x['error']}" if x["error"] else ""), file=sys.stderr)
    bench_s = time.time() - began
    results.sort(key=lambda x: (x["example"], x["length"]))

    at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    run = {"at": at, "label": a.label, "engine": a.strategy, "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
           "commit": git("rev-parse", "--short", "HEAD") + ("+changes" if git("status", "--porcelain", "--", "sdlab", "tests") else ""),
           "pool": a.pool, "features": list(features), "n": n, "generator": generator.VERSION, "source": generator.source_key(),
           "timing": {"models": len(built), "built_now": len(fresh_built), "build_seconds": round(build_s, 1),
                      "runs": len(results), "bench_seconds": round(bench_s, 1), "jobs": a.jobs},
           "failed": [x["spec"][1] for x in failed], "results": results}
    slug = ("-" + re.sub(r"[^a-z0-9]+", "-", a.label, flags=re.I)[:40]) if a.label else ""
    file = out_dir / f"{re.sub(r'[:.]', '-', at)}-{a.pool}-n{n}{slug}.json"
    file.write_text(json.dumps(run, indent=1))

    keys = {(x["example"], x["length"]) for x in results}

    def same_models(p: Path) -> bool:
        try:
            r = json.loads(p.read_text())
            return r.get("branch") == run["branch"] and r.get("pool") == a.pool and {(x["example"], x["length"]) for x in r["results"]} >= keys
        except Exception:
            return False

    if a.baseline:
        base_file = out_dir / f"baseline-{a.baseline}.json"
        base_file = base_file if base_file.exists() else None
    else:
        saved = sorted(p for p in out_dir.glob("*.json") if p != file and not p.name.startswith("baseline-"))
        base_file = next((p for p in reversed(saved) if same_models(p)), None)
    base = json.loads(base_file.read_text()) if base_file else None
    base_results = [x for x in base["results"] if (x["example"], x["length"]) in keys] if base else None

    per_min = lambda k, s: f"{60 * k / s:.0f}" if s > 0 else "-"  # noqa: E731
    lines = [f"Discovery on generated models: {at}" + (f' "{a.label}"' if a.label else "") + f" ({a.strategy}) on {run['branch']} {run['commit']}"
             + (f", compared with {base['at']}" + (f' "{base["label"]}"' if base.get("label") else "") if base else ""),
             f"Pool {a.pool}: {len(built)} models (generator v{generator.VERSION}, indices 0-{n - 1}"
             + (f", built with {', '.join(features)}" if features else "") + f"), lengths {', '.join(lengths)}; "
             + (f"built {len(fresh_built)} models in {build_s:.0f} s ({per_min(len(fresh_built), build_s)} a minute), " if fresh_built else "models from the cache, ")
             + f"benched {len(results)} runs in {bench_s:.0f} s ({per_min(len(built), bench_s)} models a minute) with {a.jobs} workers", ""]
    lines += table("motif", groups(results), groups(base_results) if base_results else None, meets) + [""]
    lines += table("size", sizes(results), sizes(base_results) if base_results else None, meets) + [""]
    for length in lengths:
        rs = [x for x in results if x["length"] == length]
        s = summary(rs, meets)
        lines.append(f"{length}: mean skill@20 {pct(s['s20'])}, skill@100 {pct(s['s100'])}, meeting the goal {s['goal']} of {s['runs']}")
    worst = sorted(results, key=lambda x: x["skill"]["20"])[:8]
    lines += ["", "Worst runs at skill@20: " + "; ".join(f"{x['example']} {x['length']} {pct(x['skill']['20'])} ({', '.join(m for m in x['motifs'] if m != 'chain')})" for x in worst)]
    s, b = summary(results, meets), (summary(base_results, meets) if base_results else None)
    lines += ["", f"Overall: parts {pct(s['parts'])}{delta(s['parts'], b and b['parts'])}, mean skill@20 {pct(s['s20'])}{delta(s['s20'], b and b['s20'])}, "
              f"mean skill@100 {pct(s['s100'])}{delta(s['s100'], b and b['s100'])}, runs meeting the goal {s['goal']} of {s['runs']}; "
              f"on fresh runs: mean skill@20 {pct(s['f20'])}, skill@100 {pct(s['f100'])}; the true model's own skill@20 {pct(s['ceiling'])}"
              + (f"; errors in {sum(1 for x in results if x['error'])} runs" if any(x["error"] for x in results) else "")]
    print("\n".join(lines))
    print(f"\nSaved {file}")
    if a.save:
        (out_dir / f"baseline-{a.save}.json").write_text(file.read_text())
        print(f'Saved as baseline "{a.save}"')
    if a.pool == "sealed":
        with (out_dir / "sealed-log.jsonl").open("a") as log:
            log.write(json.dumps({"at": at, "label": a.label, "strategy": a.strategy, "branch": run["branch"], "commit": run["commit"],
                                  "n": n, "skill20": s["s20"], "skill100": s["s100"], "goal": s["goal"], "runs": s["runs"], "file": file.name}) + "\n")
        print(f"Logged in {out_dir / 'sealed-log.jsonl'}")
