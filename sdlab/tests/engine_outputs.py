"""What the ground-truth engine makes, fingerprinted: every number of every existing simulation.

The engine (sdlab/sdtruth.py) may gain features only additively (CLAUDE.md rule 2, approved
2026-10-18): every existing ladder case, example and bench model must give exactly the same data.
tests/simulations.sha256 fingerprints the engine's *source*; this fingerprints its *output*, so a
change to the source can be proven harmless:

    ladder/<case>/<variant>/s<seed>   data.simulate() of every case (draws and realistic ones too) in
                                      every variant, on its seed and on the fresh run's (seed + 1)
    ladder/<case>/truth               the answer key Truth.truth() derives
    example/<id>/...                  every sd-* example: Truth.run() at its steps and long steps,
                                      Truth.measured() and the answer key
    bench/<id>/...                    generated bench models (tests/bench/generator.py, dev 0-39):
                                      the model the generator builds (it runs the engine to choose its
                                      numbers), its answer key and its datasets at both lengths, both seeds

Each line is "sha256  name" of the canonical JSON (sorted keys; floats as Python writes them, so
equal hashes mean bit-identical numbers).

    uv run python tests/engine_outputs.py --record    # only before an engine change, or for new items
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "tests" / "engine_outputs.sha256"
BENCH_MODELS = 40


def digest(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ladder_items() -> list[str]:
    from sdlab.ladder import cases
    return [f"ladder|{cid}" for cid in cases.case_ids()]


def example_items() -> list[str]:
    return [f"example|{p.parent.name}" for p in sorted((ROOT / "sdlab" / "examples").glob("sd-*/truth.model.json"))]


def bench_items() -> list[str]:
    return [f"bench|{i}" for i in range(BENCH_MODELS)]


def compute(item: str) -> dict[str, str]:
    """name -> hash for one case, example or bench model."""
    kind, key = item.split("|", 1)
    out: dict[str, str] = {}
    if kind == "ladder":
        from sdlab.ladder import cases, data
        from sdlab.ladder.cases import truth_model
        c = cases.load(key)
        for v in c["variants"]:
            tm = truth_model(c, v["name"])
            for seed in (int(tm["seed"]), int(tm["seed"]) + 1):
                out[f"ladder/{key}/{v['name']}/s{seed}"] = digest(data.simulate(tm, seed, v["steps"]))
        tm = truth_model(c, c["variants"][0]["name"])
        out[f"ladder/{key}/truth"] = digest(_truth(tm).truth())
    elif kind == "example":
        from sdlab.sdtruth import Truth
        t = Truth(ROOT / "sdlab" / "examples" / key / "truth.model.json")
        for seed in (t.seed, t.seed + 1):
            out[f"example/{key}/run/s{seed}"] = digest(t.run(seed))
            out[f"example/{key}/measured/s{seed}"] = digest(t.measured(seed))
        out[f"example/{key}/long/s{t.seed}"] = digest(t.run(t.seed, t.long_steps))
        out[f"example/{key}/truth"] = digest(t.truth())
    elif kind == "bench":
        sys.path.insert(0, str(ROOT / "tests" / "bench"))
        import generator
        try:
            model = generator.generate("dev", int(key))
        except RuntimeError as e:
            return {f"bench/{key}/model": digest({"error": str(e)})}
        out[f"bench/{key}/model"] = digest({**model, "generated": {k: v for k, v in (model.get("generated") or {}).items() if k != "seconds"}})
        t = generator.truth(model)
        out[f"bench/{key}/truth"] = digest(t.truth())
        for steps in (int(model["steps"]), int(model["long_steps"])):
            for seed in (model["seed"], model["seed"] + 1):
                out[f"bench/{key}/n{steps}/s{seed}"] = digest({"measured": t.measured(seed, steps), "run": t.run(seed, steps)})
    return out


def _truth(model: dict):
    import tempfile

    from sdlab.sdtruth import Truth
    d = tempfile.mkdtemp()
    p = Path(d) / "truth.model.json"
    p.write_text(json.dumps(model))
    return Truth(p)


def fingerprints(items: list[str] | None = None, jobs: int | None = None) -> dict[str, str]:
    items = items if items is not None else ladder_items() + example_items() + bench_items()
    out: dict[str, str] = {}
    with ProcessPoolExecutor(max_workers=jobs or min(8, os.cpu_count() or 2)) as ex:
        for got in ex.map(compute, items, chunksize=1):
            out.update(got)
    return out


def recorded() -> dict[str, str]:
    return dict(line.split("  ", 1)[::-1] for line in RECORD.read_text().splitlines() if line.strip())


if __name__ == "__main__" and "--record" in sys.argv:
    fp = fingerprints()
    old = recorded() if RECORD.exists() else {}
    changed = sorted(k for k in fp if k in old and old[k] != fp[k])
    if changed and "--force" not in sys.argv:
        raise SystemExit(f"refusing to record: {len(changed)} existing outputs changed, e.g. {changed[:5]}")
    RECORD.write_text("".join(f"{h}  {k}\n" for k, h in sorted({**old, **fp}.items())))
    print(f"recorded {len(fp)} output fingerprints in {RECORD.relative_to(ROOT)}")
