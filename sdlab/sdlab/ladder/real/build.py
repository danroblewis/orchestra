"""Writing the real cases: python -m sdlab.ladder.real build [--check] [--only ids].

For every entry of the catalogue (CATALOGUE below): load its series from the cache (loaders.py),
refit the published structure on the training part (fit.py), estimate the twin's measurement error,
and write `cases/real/<id>.yaml`: the case's metadata, a `real:` block (source, selector, split,
the series' sha256, the twin's noise, the citation) and the refitted published model in the case
format. The case files are committed; the data they were built from are not (except BLS, public
domain), and the sha256 lets a later download be checked against them.

--check compares what would be written with the files (no writes). An entry whose data are not in
the cache is skipped with the command that fetches them.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import yaml

from . import fit, loaders, models, sources
from .loaders import series_sha

CASES = Path(__file__).resolve().parents[1] / "cases" / "real"
SPLIT = 0.75                     # the training part: the first 75% of the samples (at least 5, at most n - 2) ...
MIN_SEEN = 21                    # ... or 21 if that still leaves 3 held out: the strategies need 21 samples (matrix.py: 20 steps)
LEVEL = 30                       # after the tests (1-19) and the realistic examples (20)


def n_train(n: int, split: float = SPLIT) -> int:
    return max(5, min(n - 2, max(int(round(split * n)), min(MIN_SEEN, n - 3))))


# ---- the catalogue ----

def _gause(cid, title, table, stocks, kind, tests, time="Time", step=1, unit="day", units="individuals", injections=None, cite="Gause (1934) The Struggle for Existence"):
    return {"id": cid, "title": title, "source": "gauseR", "family": "glv", "units": units, "kind": kind, "tests": tests, "cite": cite,
            "select": {"table": table, "time": time, "step": step, "unit": unit, "stocks": stocks, **({"injections": injections} if injections else {})}}


def _st(value, **where):
    return {"value": value, "where": where}


PA, PC, SP = "Paramecium aurelia", "Paramecium caudatum", "Stylonychia pustulata"
MONO = "one species growing alone (logistic): its growth and its crowding read from its level"
MIX = "two species competing for one food (Lotka-Volterra competition): each one's crowding by the other"
PRED = "predator and prey (Lotka-Volterra): the prey eaten and the predator fed in proportion to both"


def catalogue() -> list[dict]:
    out = [{"id": "real-bls-labour-flows", "title": "US labour force: employed, unemployed, not in the labour force", "source": "bls", "family": "markov3",
            "select": {"first": "1990-01", "last": "2025-09"}, "units": "thousand people", "kind": "flows",
            "tests": "three measured stocks whose six gross flows are also measured: are the found moves the real ones (BLS gross flows), and does the model forecast the held-out years",
            "cite": sources.SOURCES["bls"]["cite"]},
           {"id": "real-bsflu-1978", "title": "Influenza in a boarding school, 1978", "source": "pomp", "family": "sir_bc", "select": {},
            "units": "boys", "kind": "epidemic",
            "tests": "an epidemic seen only through two later stages (in bed, convalescent): the susceptible and infected boys are hidden",
            "cite": sources.SOURCES["pomp"]["cite"]}]
    # gauseR (Gause 1934, appendix tables: daily counts of Paramecium; raw cultures of Stylonychia)
    for med, word in (("one loop", "one"), ("half loop", "half")):
        out.append(_gause(f"real-gause-a4-{word}-pa", f"P. aurelia alone, {med} medium (Gause 1934, table A4)", "gause_1934_book_app_t04",
                          {"Pa": _st("Individuals", Species=PA, Treatment=med)}, "mono", MONO))
        out.append(_gause(f"real-gause-a4-{word}-pc", f"P. caudatum alone, {med} medium (Gause 1934, table A4)", "gause_1934_book_app_t04",
                          {"Pc": _st("Individuals", Species=PC, Treatment=med)}, "mono", MONO))
        out.append(_gause(f"real-gause-a4-{word}-mixture", f"P. aurelia and P. caudatum together, {med} medium (Gause 1934, table A4)", "gause_1934_book_app_t04",
                          {"Pa": _st("Individuals_Mixture", Species=PA, Treatment=med), "Pc": _st("Individuals_Mixture", Species=PC, Treatment=med)}, "mixture", MIX))
    out += [_gause("real-gause-a3-pa", "P. aurelia alone, mean of three (Gause 1934, table A3)", "gause_1934_book_app_t03", {"Pa": _st("Individuals", Species=PA, Treatment="Monoculture")}, "mono", MONO),
            _gause("real-gause-a3-pc", "P. caudatum alone, mean of three (Gause 1934, table A3)", "gause_1934_book_app_t03", {"Pc": _st("Individuals", Species=PC, Treatment="Monoculture")}, "mono", MONO),
            _gause("real-gause-a3-mixture", "P. aurelia and P. caudatum together, mean of three (Gause 1934, table A3)", "gause_1934_book_app_t03",
                   {"Pa": _st("Individuals", Species=PA, Treatment="Mixture"), "Pc": _st("Individuals", Species=PC, Treatment="Mixture")}, "mixture", MIX)]
    for c in "12345":
        out.append(_gause(f"real-gause-a5-stylonychia-{c}", f"Stylonychia alone, culture {c} (Gause 1934, table A5)", "gause_1934_book_app_t05",
                          {"S": _st("Individuals", Experiment=1, Culture=c, Species=SP)}, "mono", MONO))
    for exp, other, oid, word in ((2, PA, "Pa", "aurelia"), (3, PC, "Pc", "caudatum")):
        for c in "123":
            out.append(_gause(f"real-gause-a5-stylonychia-{word}-{c}", f"Stylonychia with P. {word}, culture {c} (Gause 1934, table A5)", "gause_1934_book_app_t05",
                              {"S": _st("Individuals", Experiment=exp, Culture=c, Species=SP), oid: _st("Individuals", Experiment=exp, Culture=c, Species=other)}, "mixture", MIX))
    out += [_gause("real-gause-f22-pc", "P. caudatum alone, volume (Gause 1934, fig. 22)", "gause_1934_book_f22", {"Pc": _st("Volume_Species1", Treatment="Pc")}, "mono", MONO,
                   time="Day", units="volume units"),
            _gause("real-gause-f22-pa", "P. aurelia alone, volume (Gause 1934, fig. 22)", "gause_1934_book_f22", {"Pa": _st("Volume_Species2", Treatment="Pa")}, "mono", MONO,
                   time="Day", units="volume units"),
            _gause("real-gause-f22-mixture", "P. caudatum and P. aurelia together, volume (Gause 1934, fig. 22)", "gause_1934_book_f22",
                   {"Pc": _st("Volume_Species1", Treatment="Mixture"), "Pa": _st("Volume_Species2", Treatment="Mixture")}, "mixture", MIX, time="Day", units="volume units"),
            _gause("real-gause-f30-didinium", "Didinium eating Paramecium, Osterhout medium (Gause 1934, fig. 30)", "gause_1934_book_f30",
                   {"P": _st("Individuals", Species="Paramecium caudatum"), "D": _st("Individuals", Species="Didinium nasutum")}, "predation", PRED),
            _gause("real-gause-f32-immigration", "Didinium and Paramecium with immigration every third day (Gause 1934, fig. 32)", "gause_1934_book_f32",
                   {"P": {"value": "Individuals_Prey", "where": {}}, "D": {"value": "Individuals_Predator", "where": {}}}, "predation",
                   PRED + "; announced immigrations (one of each, Gause 1934 ch. 6) as injections", time="Day",
                   injections={"flag": "Immigration", "when": "y", "amounts": {"P": 1, "D": 1}}),
            _gause("real-gause-f39-bursaria", "Paramecium bursaria eating yeast (S. pombe) (Gause 1934, fig. 39)", "gause_1934_book_f39.1",
                   {"Y": _st("Individuals", Species="Schizosaccharomyces pombe"), "B": _st("Individuals", Species="Paramecium bursaria")}, "predation", PRED),
            _gause("real-huffaker-3b", "Huffaker's mites: predator and prey on oranges, 60 weeks (Huffaker 1958, fig. 3b)", "huffaker_1963",
                   {"Prey": _st("Individuals", Figure="3b", Species="Prey (Eotetranychus sexmaculatus)"), "Pred": _st("Individuals", Figure="3b", Species="Predator (Typhlodromus occidentalis)")},
                   "predation", PRED, time="Weeks", unit="week", cite="Huffaker (1958) Hilgardia 27:343, via gauseR"),
            _gause("real-huffaker-4b", "Huffaker's mites: predator and prey on oranges, 24 weeks (Huffaker 1958, fig. 4b)", "huffaker_1963",
                   {"Prey": _st("Individuals", Figure="4b", Species="Prey (Eotetranychus sexmaculatus)"), "Pred": _st("Individuals", Figure="4b", Species="Predator (Typhlodromus occidentalis)")},
                   "predation", PRED, time="Weeks", unit="week", cite="Huffaker (1958) Hilgardia 27:343, via gauseR"),
            _gause("real-isle-royale", "Isle Royale: moose and wolves, 1959-1994 (McLaren and Peterson 1994)", "mclaren_1994_f03",
                   {"Moose": _st("individuals", Species="Alces alces"), "Wolves": _st("individuals", Species="Canis lupus")}, "predation", PRED,
                   time="year", unit="year", cite="McLaren and Peterson (1994) Science 266:1555, via gauseR")]
    for tech in ADOPTION:
        slug = "".join(ch if ch.isalnum() else "-" for ch in tech.lower()).strip("-").replace("--", "-")
        out.append({"id": f"real-adoption-{slug}", "title": f"US households with: {tech}", "source": "owid", "family": "bass", "select": {"entity": tech},
                    "units": "% of households", "kind": "adoption",
                    "tests": "technology diffusion (Bass): adoption from innovation and from imitation of those who already have it",
                    "cite": sources.SOURCES["owid"]["cite"]})
    return out


# the OWID series with a long run of consecutive years that rise like a diffusion (checked again at build: at
# least MIN_ADOPTION consecutive years, rising by at least 30 points)
ADOPTION = ["Automatic transmission", "Automobile", "Cable TV", "Cellular phone", "Colour TV", "Disk brakes", "Electric power",
            "Home air conditioning", "Household refrigerator", "Internet", "Microcomputer", "Nox pollution controls (boilers)",
            "Power steering", "RTGS adoption", "Radio", "Refrigerator", "Shipping container port infrastructure", "Social media usage",
            "Stove", "Vacuum", "Washing machine"]
MIN_ADOPTION = 15
MIN_POINTS = 8


# ---- refitting the published structure ----

def published(entry: dict, s: dict, nt: int) -> tuple[dict, str]:
    """The family's model refitted on the first nt samples, and a sentence on how."""
    lv = s["levels"]
    first = {k: float(v[0]) for k, v in lv.items()}
    fam = entry["family"]
    if fam == "markov3":
        return _markov3(entry, s, nt), (f"transition rates = mean of (BLS gross flow / the stock it leaves) over the first {nt} months; "
                                        "outside flows = median of BLS's other flows; January population controls as injections")
    if fam == "glv":
        ids = list(lv)
        cap = {j: _nice(100 * max(lv[j])) for j in ids}
        scale = {j: max(1e-9, max(lv[j][:nt])) for j in ids}

        def make(x):
            r = dict(zip(ids, x[:len(ids)]))
            a = {(i, j): x[len(ids) + k] / scale[j] for k, (i, j) in enumerate((i, j) for i in ids for j in ids)}
            return models.glv(first, r, a, cap, entry["units"], s["injections"])
        n = len(ids)
        x0s = []
        med = {j: max(1e-9, float(np.median(lv[j][:nt]))) for j in ids}
        for r0 in (0.3, 0.7, 1.2):
            for off in (0.0, -0.3, 0.3):
                x0s.append([r0] * n + [(-r0 * scale[i] / med[i] if i == j else off) for i in ids for j in ids])
        if entry["kind"] == "predation":                       # prey grows, predator dies alone; prey eaten, predator fed
            prey, pred = ids
            x0s.append([0.5, -0.5, -0.2, -1.0, 1.0, 0.0])
        x, _ = fit.least_squares(make, x0s, ([-2.0] * n + [-20.0] * n * n, [2.0] * n + [20.0] * n * n), lv, nt)
        return make(x), f"least squares of the free run from the first sample on the first {nt} samples (gauseR's generalised Lotka-Volterra, every r_i and a_ij)"
    if fam == "sir_bc":
        b0, c0 = first["B"], first["C"]

        def make(x):
            beta, gamma, mu1, mu2, i0 = x
            return models.sir_bc(763, i0, b0, c0, beta, gamma, mu1, mu2)
        x, _ = fit.least_squares(make, [[1.5, 0.6, 0.5, 0.3, 2.0], [2.5, 0.9, 0.4, 0.2, 5.0], [1.0, 0.4, 0.7, 0.5, 1.0]],
                                 ([0.05, 0.01, 0.01, 0.01, 0.05], [10.0, 1.0, 1.0, 1.0, 50.0]), lv, nt)
        return make(x), f"least squares of the free run on the first {nt} days (N = 763 boys; S and I start from the fitted I0)"
    if fam == "bass":
        a = lv["A"]
        lo = min(100.0, max(a[:nt]))

        def make(x):
            p, q, m = x
            return models.bass(a[0], p, q, m)
        hi = max(100.0, lo + 1e-3)
        x, _ = fit.least_squares(make, [[0.01, 0.3, min(hi, lo + 20)], [0.001, 0.5, hi], [0.03, 0.1, min(hi, lo + 5)]],
                                 ([1e-5, 0.0, lo], [0.3, 2.0, hi]), lv, nt)
        return make(x), f"least squares of the free run on the first {nt} years (p, q and the market potential m, at most 100%)"
    raise ValueError(fam)


def _nice(x: float) -> float:
    e = 10 ** math.floor(math.log10(max(x, 1e-9)))
    return math.ceil(x / e) * e


def _markov3(entry: dict, s: dict, nt: int) -> dict:
    lv, fl = s["levels"], s["flows"]
    ids = list(lv)
    k = {(a, b): float(np.mean([fl[f"{a}->{b}"][i] / lv[a][i - 1] for i in range(1, nt)])) for a in ids for b in ids if a != b}
    jan = {j["t"] for j in s["injections"]}
    rest = [i for i in range(1, nt) if i not in jan]
    inflow = {x: float(np.median([fl[f"outside->{x}"][i] for i in rest])) for x in ids}
    outflow = {x: float(np.median([fl[f"{x}->outside"][i] / lv[x][i - 1] for i in rest])) for x in ids}
    return models.markov3({x: lv[x][0] for x in ids}, k, inflow, outflow, s["injections"], entry["units"])


# ---- writing ----

def case_text(entry: dict, s: dict, nt: int, model: dict, how: str, twin: dict) -> str:
    src = sources.SOURCES[entry["source"]]
    real = {"source": entry["source"], "select": entry["select"], "points": len(s["t"]), "train": nt,
            "time": {"unit": s["time_unit"], "first": s["time"][0], "last": s["time"][-1], "train_last": s["time"][nt - 1]},
            "sha256": series_sha(s), "measured_flows": sorted(k for k in (s.get("flows") or {}) if "outside" not in k),
            "published": {"family": entry["family"], "refit": how}, "twin": twin,
            "cite": entry.get("cite") or src["cite"], "licence": src["licence"], "url": src["url"].split("?")[0]}
    head = {"title": entry["title"], "level": LEVEL, "tags": ["real", entry["source"].lower(), entry["kind"]], "tests": entry["tests"]}
    return ("# A real-data case (sdlab/ladder/real): written by `python -m sdlab.ladder.real build`; do not edit by hand.\n"
            + yaml.safe_dump(head, sort_keys=False, width=200, allow_unicode=True)
            + yaml.safe_dump({"real": real}, sort_keys=False, width=200, allow_unicode=True) + models.text(model))


def build_one(entry: dict) -> tuple[str, str] | None:
    """(file text, note) for one entry, or None (with the reason printed) when it cannot be built."""
    try:
        s = loaders.series(entry["source"], entry["select"])
    except sources.Missing as e:
        print(f"skip {entry['id']}: {e}", file=sys.stderr)
        return None
    n = len(s["t"])
    if n < (MIN_ADOPTION if entry["family"] == "bass" else MIN_POINTS):
        print(f"skip {entry['id']}: only {n} consecutive samples", file=sys.stderr)
        return None
    if entry["family"] == "bass" and max(s["levels"]["A"]) - min(s["levels"]["A"]) < 30:
        print(f"skip {entry['id']}: rises by less than 30 points", file=sys.stderr)
        return None
    nt = n_train(n)
    model, how = published(entry, s, nt)
    twin = fit.twin_noise(model, s["levels"], nt)
    if entry["family"] == "bass":                  # N is 100 - A in the data: the twin keeps it so (the error is A's)
        twin = {"rel": {"A": twin["rel"]["A"]}, "floor": {"A": twin["floor"]["A"]}, "complement": {"N": {"of": "A", "total": 100}}}
    text = case_text(entry, s, nt, model, how, twin)
    _check_compiles(entry["id"], text, model, n)
    r = fit.scaled_residuals(model, s["levels"], nt)
    return text, f"{entry['id']}: {n} samples, train {nt}; refit rms error {float(np.sqrt(np.mean(r ** 2))):.2f} stock spreads"


def _check_compiles(cid: str, text: str, model: dict, n: int) -> None:
    """The written case compiles to a model that runs exactly as the fitted one."""
    from .case import compile_text

    got = compile_text(text, cid)["model"]
    a, b = fit.run(model, n), fit.run(got, n)
    for s in a:
        if not np.allclose(a[s], b[s], rtol=1e-9, atol=1e-9):
            raise RuntimeError(f"{cid}: the case file does not reproduce the fitted model (stock {s})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sdlab.ladder.real build")
    ap.add_argument("--check", action="store_true", help="compare with the case files, write nothing")
    ap.add_argument("--only", help="comma list of case ids")
    a = ap.parse_args(argv)
    only = set(a.only.split(",")) if a.only else None
    CASES.mkdir(parents=True, exist_ok=True)
    differ = 0
    for entry in catalogue():
        if only and entry["id"] not in only:
            continue
        got = build_one(entry)
        if not got:
            continue
        text, note = got
        p = CASES / f"{entry['id']}.yaml"
        if a.check:
            same = p.exists() and p.read_text() == text
            differ += not same
            print(f"{'same' if same else 'DIFFERS'} {note}")
        else:
            p.write_text(text)
            print(f"wrote {note}")
    return 1 if differ else 0
