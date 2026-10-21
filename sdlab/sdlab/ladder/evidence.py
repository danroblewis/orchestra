"""Evidence beside the pass: for each stored latest result, the reasons to believe (or doubt) its model,
gathered from the checks that already exist. It changes no status, no score and no score hash.

One report per result has three parts:

- **existing**: the stored status (unchanged), the long run (longrun_cache: computed when missing, as
  `sdlab-ladder longrun` does) and the strict verdict (strict.py, read from its cache: "pending" when
  `sdlab-ladder strict` has not computed the cell's reference).
- **truth** (scoring: these read the truth): the push test (pushes.py: impulse, step and sine responses of
  truth vs found model, tolerances widened by REFERENCE refits of the truth's own structure, strict's seeds),
  the Cramer-Rao bound per true number and the likelihood ratio against the truth's refit (consistency.py).
- **notruth** (NO-TRUTH: notruth.py reads only the discovery view and found flows): residuals,
  invariance, held-out, and agreement with the other stored models on the cell, including the *best other*:
  the other distinct model with the highest NO-TRUTH score of the first three checks (so choosing it never
  reads a status or the truth).

`label(report)` (evidence_confidence.py) says whether a model is "right" by the truth, and `features`
(same module) turns the NO-TRUTH part into the confidence model's inputs.

Computed by `sdlab-ladder evidence` into $SDLAB_LADDER_CACHE/evidence.sqlite, keyed by result id and code
hash (CODE). The per-model part (everything but agreement) depends only on the result's flows and its
cell; agreement also depends on the cell's other results, so it is keyed by them too (ctx: a hash of the
cell's result ids). Identical found models on a cell are computed once.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path

from . import sqlite_keep
from .data import cache_root

HERE = Path(__file__).resolve().parent
REFERENCE = 3              # the push test's refits of the truth (the run discovery saw + 2 more seeds)
MAX_OTHERS = 12            # agreement: at most this many other distinct models (the best ones by NO-TRUTH score)
OWN_CHECKS = ("residuals", "invariance", "heldout")
CODE = ("evidence.py", "pushes.py", "consistency.py", "noise_kf.py", "noise_oracle.py", "strict.py", "fisher.py", "noise.py",
        "notruth.py", "notruth_core.py", "notruth_kf.py", "notruth_run.py", "sim.py", "data.py", "parts.py")


def code_hash() -> str:
    h = hashlib.sha256()
    for name in CODE:
        h.update((HERE / name).read_bytes())
    for p in (HERE.parent / "skill.py", HERE.parent / "sdtruth.py", HERE.parent / "discovery" / "simulate.py"):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def path() -> Path:
    return cache_root() / "evidence.sqlite"


@contextmanager
def connect():
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite_keep.connect(p, timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE IF NOT EXISTS evidence (result_id INTEGER NOT NULL, code TEXT NOT NULL, part TEXT NOT NULL,"
                    " ctx TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (result_id, code, part, ctx))")
        yield con
        con.commit()
    finally:
        con.close()


def model_key(flows) -> str:
    return hashlib.sha256(json.dumps(flows, sort_keys=True, default=str).encode()).hexdigest()[:16]


def ctx_of(ids: list[int]) -> str:
    return hashlib.sha256(",".join(str(i) for i in sorted(ids)).encode()).hexdigest()[:16]


def _flows(found):
    return found if isinstance(found, list) else (found or {}).get("flows", found)


def _err(e: Exception) -> dict:
    return {"error": f"{type(e).__name__}: {e}"[:300]}


# ---- one cell (in any process) ----

class Bench:
    """What every result on one cell shares: the truth's push bench and its reference refits, the
    consistency cell, and the discovery view (the NO-TRUTH checks get only the view)."""

    def __init__(self, case_id: str, variant: str, reference: int = REFERENCE):
        from . import cases as casemod
        from . import data
        from .notruth_run import view
        self.case_id, self.variant = case_id, variant
        self.view = view(case_id, variant)
        self.case = casemod.load(case_id)
        self.why = None
        if self.case.get("real") or self.case.get("physics") or self.case.get("particles"):
            self.why = "no truth model (real-data, physics or particle case)"
            return
        self.tm = casemod.truth_model(self.case, variant)
        self.data = data.load(self.case, variant)
        self.push, self.ref, self.cell = None, None, None
        try:
            self.push = self._push_bench(reference)
        except Exception as e:  # noqa: BLE001 - reported as the push test's error on every result
            self.push = _err(e)
        try:
            from .consistency import Cell
            self.cell = Cell(self.case, variant, self.data)
        except Exception as e:  # noqa: BLE001
            self.cell = _err(e)

    def _push_bench(self, reference: int):
        from . import cases as casemod
        from .pushes import Bench as PushBench
        from .pushes import compare
        from .strict import SEED_BASE, _run, refit
        d = self.data
        bench = PushBench(self.tm, d.get("clean") or d)
        v = casemod.variant(self.case, self.variant)
        ref = []
        for i in range(reference):
            try:
                run = d if i == 0 else _run(self.case, v, self.tm, int(self.tm["seed"]) + SEED_BASE + i - 1)
                flows, how = refit(self.tm, run, v["noise"])
            except Exception:  # noqa: BLE001 - a refit that fails is left out (the reference says how many there are)
                continue
            if flows is not None:
                ref.append({**compare(bench, flows), "how": how})
            if v["noise"] == "none" and not v.get("observe"):
                break                                   # noise-free: the refit is the truth on every run
        self.ref = ref or None
        return bench

    # -- the per-model part --

    def pushes(self, flows) -> dict:
        from .pushes import compare
        if isinstance(self.push, dict):
            return self.push
        o = compare(self.push, flows, reference=self.ref)
        fp = o.get("footprint") or {}
        return {"verdict": o.get("verdict"), "agree": o.get("agree"), "agree_fixed": o.get("agree_fixed"), "n": o.get("n"),
                "data_limited": o.get("data_limited"), "footprint": fp,
                "footprint_ok": not any(fp.get(k) for k in ("missing", "spurious", "sign")),
                "tau_true": o.get("tau_true"), "tau_found": o.get("tau_found"), "diagnosis": (o.get("diagnosis") or [])[:6],
                "reference": (o.get("reference") or {}).get("refits", 0)}

    def consistency(self, flows) -> tuple[dict | None, dict | None]:
        from .consistency import bound_check, likelihood_check
        if isinstance(self.cell, dict):
            return self.cell, self.cell
        if not self.cell.covered:
            return {"covered": False, "why": self.cell.why}, {"covered": False, "why": self.cell.why}
        try:
            b = bound_check(self.cell, flows)
            b = b and {"ok": b["ok"], "worst_z": b.get("worst_z"), "joint_p": (b.get("joint") or {}).get("p"), "kinds": b.get("kinds"),
                       "entries_ok": (b.get("entries") or {}).get("ok"), "noise_free": b.get("noise_free"),
                       "parts": [{k: p.get(k) for k in ("key", "true", "found", "se", "z", "diagnosis")} for p in b.get("parts") or []]}
        except Exception as e:  # noqa: BLE001
            b = _err(e)
        try:
            lk = likelihood_check(self.cell, flows)
            if lk and lk.get("covered"):
                w = (lk.get("where") or [None])[0]
                lk = {"covered": True, "verdict": lk["verdict"], "rejected": lk["rejected"], "LR": lk["LR"], "df": lk["df"], "p": lk["p"],
                      "extra": lk["numbers"]["extra"], "where": w and {"stock": w["stock"], "kinds": w.get("kinds")}}
        except Exception as e:  # noqa: BLE001
            lk = _err(e)
        return b, lk

    def own(self, flows) -> dict:
        """Everything but agreement, for one found model."""
        from .notruth import evidence
        out: dict = {"notruth": {}, "truth": {}}
        try:
            ev = evidence(self.view, flows, checks=OWN_CHECKS)
            out["notruth"] = {k: _compact(k, v) for k, v in ev["checks"].items()}
            out["notruth_score3"] = ev["score"]
        except AssertionError:
            raise
        except Exception as e:  # noqa: BLE001
            out["notruth"] = {k: {"verdict": "error", **_err(e)} for k in OWN_CHECKS}
            out["notruth_score3"] = None
        if self.why:
            out["truth"] = {"error": self.why}
            return out
        try:
            out["truth"]["pushes"] = self.pushes(flows)
        except Exception as e:  # noqa: BLE001
            out["truth"]["pushes"] = _err(e)
        out["truth"]["bound"], out["truth"]["likelihood"] = self.consistency(flows)
        return out

    def agreement(self, flows, others: dict[str, list], best: str | None) -> dict:
        from .notruth import agreement
        try:
            a = agreement(self.view, flows, others)
        except Exception as e:  # noqa: BLE001
            return {"verdict": "error", **_err(e)}
        o = a.get("others") or {}
        b = o.get(best) if best else None
        return {"verdict": a["verdict"], "n_distinct_others": a.get("n_distinct_others"), "n_agree": a.get("n_agree"),
                "agree_with": a.get("agree_with"), "best_other": best,
                "agree_with_best": None if not b or "error" in b else bool(b.get("agree")),
                "best_push_diff": None if not b or "error" in b else b.get("push_diff"),
                "diagnosis": [f["diagnosis"] for f in a.get("findings") or [] if f.get("diagnosis")][:3]}


def _compact(name: str, r: dict) -> dict:
    """A NO-TRUTH check's verdict, the numbers the confidence model reads, and its diagnoses."""
    out = {"verdict": r.get("verdict")}
    if r.get("error"):
        out["error"] = r["error"]
    if name == "residuals":
        ps = [t.get("p_holm") for s in r.get("stocks") or [] for t in s.get("tests") or [] if t.get("p_holm") is not None]
        out["min_p"] = min(ps) if ps else None
    elif name == "invariance":
        ps = [n.get("p_holm") for part in (r.get("partitions") or {}).values() for n in part.get("numbers") or [] if n.get("p_holm") is not None]
        out["min_p"] = min(ps) if ps else None
    elif name == "heldout":
        h = str(r.get("main_horizon")) if r.get("main_horizon") is not None else None
        sk = [x.get("skill") for x in ((r.get("horizons") or {}).get(h) or {}).get("held_out") or [] if x.get("skill") is not None]
        out["min_skill"] = min(sk) if sk else None
    out["diagnosis"] = [f["diagnosis"] for f in r.get("findings") or [] if f.get("verdict") != "supports" and f.get("diagnosis")][:4]
    return out


def best_others(own: dict[str, dict], key_of: dict[str, str], strategy: str, k: int = MAX_OTHERS) -> list[str]:
    """The other strategies on the cell whose models differ from this one's, best NO-TRUTH score of the
    three own checks first (ties: name), at most one per distinct model."""
    mine = key_of[strategy]
    seen, out = set(), []
    for s in sorted(key_of, key=lambda s: (-(own.get(key_of[s], {}).get("notruth_score3") or 0.0), s)):
        if s == strategy or key_of[s] == mine or key_of[s] in seen:
            continue
        seen.add(key_of[s])
        out.append(s)
    return out[:k]


def compute_cell(case_id: str, variant: str, items: list[tuple[int, str, str]], own_known: dict[str, dict], need_own: set,
                 need_agree: set, ctx: str, reference: int = REFERENCE) -> list[tuple[int, str, str, dict]]:
    """Rows to store [(result id, part, ctx, value)] for one cell: `items` are its results (id, strategy, found
    JSON); own_known {model key: own part} the per-model parts already cached."""
    began = time.time()
    try:
        bench = Bench(case_id, variant, reference)
    except Exception as e:  # noqa: BLE001 - a cell that cannot be built: recorded on each result
        v = {"error": f"cell: {type(e).__name__}: {e}"[:300]}
        return ([(i, "own", "", v) for i, _, _ in items if i in need_own]
                + [(i, "agreement", ctx, {"verdict": "error", **v}) for i, _, _ in items if i in need_agree])
    flows = {s: _flows(json.loads(raw)) for _, s, raw in items}
    key_of = {s: model_key(f) for s, f in flows.items()}
    own = dict(own_known)
    out = []
    for i, s, _ in items:
        k = key_of[s]
        if k not in own:
            own[k] = bench.own(flows[s])
        if i in need_own:
            out.append((i, "own", "", {**own[k], "model": k}))
    agr: dict = {}
    for i, s, _ in items:
        if i not in need_agree:
            continue
        names = best_others(own, key_of, s)
        memo = (key_of[s], tuple(key_of[n] for n in names))
        if memo not in agr:
            agr[memo] = bench.agreement(flows[s], {n: flows[n] for n in names}, names[0] if names else None)
        a = dict(agr[memo])
        out.append((i, "agreement", ctx, a))
    if out:
        out[0][3]["cell_seconds"] = round(time.time() - began, 2)
    return out


# ---- filling and reading the cache ----

def _read(ids: list[int], code: str) -> dict[tuple[int, str, str], dict]:
    if not path().exists() or not ids:
        return {}
    out = {}
    with connect() as con:
        for j in range(0, len(ids), 500):
            chunk = ids[j:j + 500]
            q = f"SELECT result_id, part, ctx, value FROM evidence WHERE code = ? AND result_id IN ({','.join('?' * len(chunk))})"
            for i, part, ctx, v in con.execute(q, [code, *chunk]):
                out[(i, part, ctx)] = json.loads(v)
    return out


def _save(rows: list[tuple[int, str, str, dict]], code: str) -> None:
    with connect() as con:
        con.executemany("INSERT OR REPLACE INTO evidence (result_id, code, part, ctx, value) VALUES (?, ?, ?, ?, ?)",
                        [(i, code, p, c, json.dumps(v, default=float)) for i, p, c, v in rows])


def usable(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("status") not in ("error", "timeout")]


def _cells(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    out: dict = {}
    for r in usable(rows):
        out.setdefault((r["case"], r["variant"]), []).append(r)
    return out


def _worker_init() -> None:
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMBA_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[k] = "1"
    try:
        os.nice(10)
    except OSError:
        pass


def plan(rows: list[dict], code: str | None = None) -> list[tuple]:
    """compute_cell's arguments for every cell with a result whose evidence is not cached. A cell's
    agreement needs every result of the cell (the whole cell in the store, not only the rows picked)."""
    from . import store
    code = code or code_hash()
    tasks = []
    for (c, v), picked in _cells(rows).items():
        cell_rows = usable(store.latest(c, v))
        ctx = ctx_of([r["id"] for r in cell_rows])
        ids = [r["id"] for r in cell_rows]
        known = _read(ids, code)
        need_own = {r["id"] for r in cell_rows if (r["id"], "own", "") not in known}
        need_agree = {r["id"] for r in picked if (r["id"], "agreement", ctx) not in known}
        if not need_own and not need_agree:
            continue
        found = store.found_flows(ids)
        items = [(r["id"], r["strategy"], found[r["id"]]) for r in cell_rows if found.get(r["id"])]
        own_known = {k["model"]: k for (i, p, _), k in known.items() if p == "own" and "model" in k}
        tasks.append((c, v, items, own_known, need_own & {i for i, _, _ in items}, need_agree & {i for i, _, _ in items}, ctx))
    return tasks


def fill(rows: list[dict], jobs: int = 1, reference: int = REFERENCE, progress=None) -> int:
    """Compute and keep the evidence of every row not yet cached; how many cells were computed."""
    code = code_hash()
    tasks = plan(rows, code)
    if not tasks:
        return 0
    done = 0
    if jobs <= 1:
        for t in tasks:
            _save(compute_cell(*t, reference=reference), code)
            done += 1
            if progress:
                progress(done, len(tasks), t[0], t[1])
        return done
    with ProcessPoolExecutor(max_workers=jobs, initializer=_worker_init) as ex:
        futs = {ex.submit(compute_cell, *t, reference=reference): t for t in tasks}
        for f in as_completed(futs):
            t = futs[f]
            try:
                _save(f.result(), code)
            except Exception as e:  # noqa: BLE001 - a worker that died: the cell is recorded as an error, not retried until the code changes
                _save([(i, "own", "", {"error": f"worker: {type(e).__name__}: {e}"[:300]}) for i in t[4]], code)
            done += 1
            if progress:
                progress(done, len(tasks), t[0], t[1])
    return done


def reports(rows: list[dict]) -> list[dict]:
    """The evidence report of each row (stored latest results) from the caches; missing parts are None."""
    from . import complexity, longrun_cache, store, strict
    code = code_hash()
    cells = _cells(rows)
    refs = strict.references()
    out = []
    for (c, v), picked in cells.items():
        cell_ids = [r["id"] for r in usable(store.latest(c, v))]
        ctx = ctx_of(cell_ids)
        known = _read([r["id"] for r in picked], code)
        try:
            from . import cases as casemod
            chash = casemod.load(c)["hash"]
        except Exception:  # noqa: BLE001
            chash = None
        for r in picked:
            full = store.get(r["id"], found=True) or r
            own = known.get((r["id"], "own", ""))
            agr = known.get((r["id"], "agreement", ctx))
            cx = complexity.of_result(full)
            lr = longrun_cache.of_result(full)
            fresh100 = (((full.get("scores") or {}).get("behaviour") or {}).get("fresh") or {}).get("100", {}).get("skill")
            sv = strict.verdict(full["status"], fresh100, cx, lr, refs.get((c, chash, v)))
            rep = {"id": r["id"], "case": c, "variant": v, "strategy": r["strategy"], "model": (own or {}).get("model"),
                   "existing": {"status": full["status"], "strict": sv, "complexity_extra": None if cx is None else cx.get("extra"),
                                "longrun": None if not lr else {k: lr.get(k) for k in ("flag", "hard_fail", "err", "error") if k in lr}},
                   "truth": (own or {}).get("truth"), "notruth": None if own is None else {**own.get("notruth", {}),
                                                                                         "agreement": agr},
                   "scores": {k: (full.get("scores") or {}).get(k) for k in ("recall", "precision", "spurious", "equivalent")},
                   "error": (own or {}).get("error")}
            if own is None:
                rep["pending"] = True
            out.append(rep)
    return out


def summary(reps: list[dict]) -> str:
    """One line per result: status, strict, push test, bound, likelihood, the NO-TRUTH verdicts, the label."""
    from .evidence_confidence import label
    lines = []
    for r in sorted(reps, key=lambda r: (r["case"], r["variant"], r["strategy"])):
        if r.get("pending"):
            lines.append(f"{r['case'][:26]:26} {r['variant']:13} {r['strategy'][:16]:16} pending")
            continue
        if r.get("error"):
            lines.append(f"{r['case'][:26]:26} {r['variant']:13} {r['strategy'][:16]:16} error {r['error'][:60]}")
            continue
        t, n, ex = r["truth"] or {}, r["notruth"] or {}, r["existing"]
        p, b, lk = t.get("pushes") or {}, t.get("bound") or {}, t.get("likelihood") or {}
        st = ex["strict"]["strict"]
        lab = label(r)
        push = "-" if p.get("agree") is None else f"{p['agree']:.0%}"
        bnd = "-" if "ok" not in b else ("ok" if b["ok"] else "out")
        lik = "-" if not lk.get("covered") else ("rej" if lk["rejected"] else "ok")
        nt = " ".join(f"{k[:3]}={(n.get(k) or {}).get('verdict', '-')[:4]}" for k in ("residuals", "invariance", "heldout", "agreement"))
        right = {True: "right", False: "wrong", None: "?"}[lab["right"]]
        lines.append(f"{r['case'][:26]:26} {r['variant']:13} {r['strategy'][:16]:16} {ex['status'][:5]:5} strict={'-' if st is None else int(st)}"
                     f" push={push:4} bound={bnd:3} lik={lik:3} {nt} label={right}")
    return "\n".join(lines)


def main(a) -> int:
    """sdlab-ladder evidence: fill the cache for the picked latest results, print a line per result and
    the confidence model's report (evidence_confidence.py)."""
    import sys

    from . import catalog, longrun_cache, runner, store
    from . import evidence_confidence as ec
    names = set(catalog.names()) if a.strategies in (None, "all") else set(a.strategies.split(","))
    cids = set(runner.select_cases(a.cases)) if a.cases else None
    rows = [r for r in store.latest() if r["strategy"] in names and (cids is None or r["case"] in cids)
            and (not a.variants or r["variant"] in a.variants.split(","))]
    jobs = max(1, min(3, a.jobs or 1))
    t0 = time.time()
    if not a.no_fill:
        longrun_cache.fill(usable(rows), jobs)
        n = fill(rows, jobs, a.reference, None if a.quiet else
                 lambda d, n, c, v: print(f"\r{d}/{n} cells ({c[:24]} {v})        ", end="", file=sys.stderr, flush=True))
        print(f"\n{n} cells computed in {time.time() - t0:.1f} s", file=sys.stderr)
    reps = reports(rows)
    if not a.quiet:
        print(summary(reps))
    conf = ec.report(reps)
    print(ec.text(conf))
    if a.out:
        Path(a.out).write_text(json.dumps({"reports": reps, "confidence": conf}, indent=1, default=float))
    return 0
