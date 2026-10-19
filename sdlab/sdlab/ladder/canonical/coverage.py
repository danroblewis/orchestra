"""How much of SDXorg/test-models SD Lab's case format can hold exactly: every sample model and every
one-function test through the PySD importer (sdlab/ladder/pysd_import.py), each checked by simulating
it in PySD and in SD Lab's engine.

    git clone --depth 1 https://github.com/SDXorg/test-models /tmp/test-models     # MIT
    uv run --with pysd --with sympy python -m sdlab.ladder.canonical.coverage /tmp/test-models \\
        --json coverage.json --markdown tables.md

Each model gets one status:

- exact: converted, and PySD's run and SD Lab's (noise none) agree at every recorded step;
- exact with inputs: the same, with some part of a rate that reads only TIME given as a measured
  input (STEP, PULSE, a lookup of time, MAX(TIME, 5), ...): SD Lab holds it as data, not as an equation;
- differs: converted, but the runs differ (the reason: a stock or a rate that goes negative, which SD
  Lab floors at 0, or an outflow that empties a stock within a step);
- blocked: some part has no SD Lab form; the features are listed (a model can lack several);
- no model: the folder has no .mdl, .xmile or .stmx file.

A test is one folder of tests/ (153) or samples/ (12; samples/arrays holds two models, the first is
used). A folder's .mdl is used when there is one, else its .xmile, else its .stmx.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from collections import Counter
from pathlib import Path

TIMEOUT = 120


def model_file(folder: Path) -> Path | None:
    for ext in (".mdl", ".MDL", ".xmile", ".stmx"):
        found = sorted(p for p in folder.rglob(f"*{ext}") if p.is_file())
        if found:
            return found[0]
    return None


def entries(root: Path) -> list[tuple[str, str, Path | None]]:
    out = []
    for kind in ("samples", "tests"):
        for d in sorted(p for p in (root / kind).iterdir() if p.is_dir()):
            out.append((kind, d.name, model_file(d)))
    return out


def classify(path: str) -> dict:
    """One model's status (runs in a worker)."""
    import warnings

    warnings.filterwarnings("ignore")
    from ..pysd_import import convert, convert_checked

    try:
        conv = convert(path)
    except Exception as e:                                                      # noqa: BLE001
        return {"status": "blocked", "features": ["the importer fails"], "where": [f"{type(e).__name__}: {str(e)[:160]}"]}
    if conv.text is None:
        out = {"wrapped": conv.wrapped, "scale": conv.scale, "dt": conv.dt, "steps": conv.steps, "drivers": conv.drivers,
               "values": conv.uses_values, "notes": conv.notes}
        return out | {"status": "blocked", "features": conv.features, "where": [f"{f}: {w}" for f, w in conv.blocked][:12]}
    try:
        conv, eq = convert_checked(path)                                        # (2d: signed where only the floor differs)
    except Exception as e:                                                      # noqa: BLE001
        return {"wrapped": conv.wrapped, "status": "differs", "reason": f"SD Lab cannot run it: {type(e).__name__}: {str(e)[:160]}", "text": conv.text}
    out = {"wrapped": conv.wrapped, "scale": conv.scale, "dt": conv.dt, "steps": conv.steps, "drivers": conv.drivers,
           "values": conv.uses_values, "notes": conv.notes}
    if not eq.ok:
        return out | {"status": "differs", "reason": eq.reason, "error": eq.error, "text": conv.text}
    return out | {"status": "exact with inputs" if conv.drivers else "exact", "error": eq.error, "text": conv.text}


def run(root: Path, jobs: int = 4) -> list[dict]:
    rows = []
    items = entries(root)
    with mp.get_context("spawn").Pool(jobs, maxtasksperchild=4) as pool:
        futs = [(k, n, p, pool.apply_async(classify, (str(p),)) if p else None) for k, n, p in items]
        for kind, name, path, fut in futs:
            row = {"kind": kind, "name": name, "file": str(path.relative_to(root)) if path else None}
            if fut is None:
                row |= {"status": "no model", "features": []}
            else:
                try:
                    row |= fut.get(TIMEOUT)
                except mp.TimeoutError:
                    row |= {"status": "blocked", "features": ["the importer times out"]}
                except Exception as e:                                          # noqa: BLE001
                    row |= {"status": "blocked", "features": ["the importer fails"], "where": [str(e)[:160]]}
            rows.append(row)
    return rows


STATUSES = ("exact", "exact with inputs", "differs", "blocked", "no model")


def tables(rows: list[dict]) -> str:
    """The coverage tables in Markdown."""
    out = []
    for kind, label in (("samples", "Sample models (12)"), ("tests", "One-function tests (153)")):
        rs = [r for r in rows if r["kind"] == kind]
        c = Counter(r["status"] for r in rs)
        out.append(f"### {label}\n")
        out.append("| status | models |\n|---|---|")
        for s in STATUSES:
            out.append(f"| {s} | {c.get(s, 0)} |")
        out.append(f"| total | {len(rs)} |\n")
    feats = Counter()
    only = Counter()
    for r in rows:
        if r["status"] == "blocked":
            fs = r.get("features") or []
            feats.update(fs)
            if len(fs) == 1:
                only.update(fs)
        elif r["status"] == "differs":
            feats.update([r.get("reason") or "the runs differ"])
            only.update([r.get("reason") or "the runs differ"])
    out.append("### Missing features (all 165 models)\n")
    out.append("A blocked model can lack several features; \"only blocker\" counts the models that lack this one and nothing else "
               "(adding it would convert them, unless the runs then differ).\n")
    out.append("| feature | models | only blocker |\n|---|---|---|")
    for f, n in feats.most_common():
        out.append(f"| {f} | {n} | {only.get(f, 0)} |")
    drivers = Counter(d for r in rows if r["status"] == "exact with inputs" for d in r.get("drivers") or [])
    if drivers:
        out.append("\n### Functions of time held as measured inputs (in the \"exact with inputs\" models)\n")
        out.append("| function | models |\n|---|---|")
        for d, n in drivers.most_common():
            out.append(f"| {d} | {n} |")
    out.append("\n### Every model\n")
    out.append("| folder | file | status | features or reason |\n|---|---|---|---|")
    for r in rows:
        why = ", ".join(r.get("features") or []) if r["status"] == "blocked" else (r.get("reason") or "")
        if r["status"].startswith("exact"):
            why = ("inputs: " + ", ".join(r.get("drivers") or [])) if r.get("drivers") else ""
            if r.get("wrapped"):
                why = ("accumulated; " + why).strip("; ")
        out.append(f"| {r['kind']}/{r['name']} | {r.get('file') or ''} | {r['status']} | {why} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", type=Path, help="a checkout of SDXorg/test-models")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--markdown", type=Path)
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    rows = run(a.root, a.jobs)
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1, default=str))
    md = tables(rows)
    if a.markdown:
        a.markdown.write_text(md)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
