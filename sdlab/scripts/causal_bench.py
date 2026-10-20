"""Offline bench: time-series causal discovery (PCMCI+, LPCMCI, Granger) on the ladder, graded on the graph.

docs/research/causal-discovery.md. Each method gets exactly what a strategy gets (the measured levels and
the measured inputs of a case's variant, through the ladder's data loader; never the truth) and returns
directed edges "X affects Y's change" among the measured stocks and inputs. The truth's edges come from
its flows: every stock or input a flow's rate or effects read affects the stocks the flow drains, fills or
uses up. Hidden stocks are marginalised out (X -> hidden -> Y counts as X -> Y), the graph a method that
sees only the measured series can find. The stored models of the leading strategies (the result store,
read only) are turned into graphs the same way and compared on the same cells.

Tigramite (PCMCI+, LPCMCI) is GPL-3.0: it is never a dependency of sdlab. It is imported only inside the
functions that use it, so this file imports without it; run the bench from a scratch venv that has it:

    uv venv /path/cdvenv && VIRTUAL_ENV=/path/cdvenv uv pip install tigramite -e .
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMBA_NUM_THREADS=1 \
        /path/cdvenv/bin/python scripts/causal_bench.py run --out cells.jsonl --jobs 4
    uv run python scripts/causal_bench.py report cells.jsonl      # adds the stored strategies; no tigramite

Without tigramite, `run --methods granger_pair,granger_cond,row_reg` works in the project venv.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
from collections import defaultdict

import numpy as np
from scipy import stats

ALPHA = 0.01
TAU_MAX = 3
METHOD_TIMEOUT = 120       # seconds per method per cell; LPCMCI blows up on some 6-8 variable cases
METHODS = ("pcmci_plus", "pcmci_plus_c", "pcmci", "granger_pair", "granger_cond", "row_reg", "lpcmci")
STRATEGIES = ("matrix_v2", "structures", "kalman_lna", "blockwise")
SETS = ("tests", "kubernetes")


# ---- graphs from flows (the truth's and a found model's) ----

def _rate_reads(r: dict | None, flow: dict, model: dict | None) -> set:
    r = r or {}
    form = r.get("form")
    out = {r.get("stock")} | {x.get("stock") for x in r.get("terms") or []}
    if form == "available":
        out.add(r.get("stock") or flow.get("from"))
    if form == "expr" and model is not None:
        from sdlab.sdtruth import _expr_reads
        out |= set(_expr_reads({"rate": r}, model))
    return out


def flow_edges(flows: list[dict], model: dict | None = None) -> set:
    """Directed edges reader -> stock: a flow's readers (rate, its pieces and scheduled rates, effects,
    its input) affect the change of every stock it moves (from, to, uses)."""
    sched: dict = defaultdict(list)
    for ch in ((model or {}).get("schedule") or {}).get("changes") or []:
        for fid, r in (ch.get("set") or {}).items():
            sched[fid].append(r)
    edges = set()
    for f in flows or []:
        rates = [f.get("rate")] + list(f.get("rates") or []) + [g.get("rate") for g in f.get("byTime") or []]
        rates += sched.get(f.get("id"), [])
        reads = set()
        for r in rates:
            reads |= _rate_reads(r, f, model)
        reads |= {e.get("stock") for e in f.get("effects") or []}
        if f.get("input"):
            reads.add(f["input"])
        ends = {f.get("from"), f.get("to")} | {u.get("stock") for u in f.get("uses") or []}
        ends |= {o.get("stock") if isinstance(o, dict) else o for o in f.get("outputs") or []}
        for a in reads - {None}:
            for b in ends - {None}:
                if a != b:
                    edges.add((a, b))
    return edges


def marginal(edges: set, measured: set) -> set:
    """Edges among the measured nodes, with paths through unmeasured nodes collapsed (X -> h.. -> Y)."""
    out_of = defaultdict(set)
    for a, b in edges:
        out_of[a].add(b)
    res = set()
    for s in measured:
        seen, todo = set(), list(out_of[s])
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in measured:
                if n != s:
                    res.add((s, n))
            else:
                todo += list(out_of[n])
    return res


def confounded(edges: set, measured: set) -> set:
    """Unordered pairs of measured nodes that a hidden node reaches both of, through hidden nodes only."""
    out_of = defaultdict(set)
    for a, b in edges:
        out_of[a].add(b)
    hidden = {n for e in edges for n in e} - measured
    pairs = set()
    for h in hidden:
        seen, todo, hit = set(), [h], set()
        while todo:
            n = todo.pop()
            for m in out_of[n]:
                if m in measured:
                    hit.add(m)
                elif m not in seen:
                    seen.add(m)
                    todo.append(m)
        pairs |= {frozenset((x, y)) for x in hit for y in hit if x < y}
    return {tuple(sorted(p)) for p in pairs}


def truth_graph(case: dict, variant: str) -> dict:
    from sdlab.ladder import cases as C
    model = C.truth_model(case, variant)
    stocks = [s["id"] for s in model["stocks"]]
    measured = {s["id"] for s in model["stocks"] if s.get("measured", True) and not s.get("switch")}
    inputs = set((model.get("inputs") or {}).keys()) if isinstance(model.get("inputs"), dict) else \
        {i["id"] if isinstance(i, dict) else i for i in model.get("inputs") or []}
    e = flow_edges(model["flows"], model)
    nodes = measured | inputs
    return {"edges": sorted(marginal(e, nodes)), "direct": sorted(x for x in e if set(x) <= nodes),
            "confounded": sorted(confounded(e, nodes)), "hidden": sorted(set(stocks) - measured),
            "measured": sorted(measured), "inputs": sorted(inputs)}


# ---- the data a strategy sees ----

def page_data(case: dict, variant: str) -> tuple[list[str], list[str], np.ndarray]:
    """(stocks, inputs, X[T, n]) from the ladder's loader: measured levels and measured inputs only. An
    irregular sampling (gaps) is interpolated onto its median step, as a naive analyst would."""
    from sdlab.ladder import data
    d = data.load(case, variant)
    t = np.asarray(d["t"], float)
    stocks = list(d["levels"])
    inputs = list((d.get("inputs") or {}))
    cols = [np.asarray(d["levels"][s], float) for s in stocks]
    for k in inputs:
        v = np.asarray(d["inputs"][k], float)
        cols.append(v[: len(t)] if len(v) >= len(t) else np.pad(v, (0, len(t) - len(v)), mode="edge"))
    X = np.column_stack(cols)
    dt = np.diff(t)
    if len(dt) and dt.min() != dt.max():
        step = float(np.median(dt))
        grid = np.arange(t[0], t[-1] + 1e-9, step)
        X = np.column_stack([np.interp(grid, t, X[:, j]) for j in range(X.shape[1])])
    return stocks, inputs, X


def _usable(X: np.ndarray) -> np.ndarray:
    ok = np.all(np.isfinite(X), axis=0) & (np.nanstd(X, axis=0) > 1e-9)
    return ok


# ---- methods: each returns directed edges (src, dst) with dst a stock ----

def _lags(X: np.ndarray, p: int) -> np.ndarray:
    T = X.shape[0]
    return np.column_stack([X[p - k: T - k] for k in range(1, p + 1)])


def _f_test(y: np.ndarray, full: np.ndarray, restricted: np.ndarray) -> float:
    def rss(A):
        A = np.column_stack([np.ones(len(y)), A]) if A.size else np.ones((len(y), 1))
        beta, *_ = np.linalg.lstsq(A, y, rcond=None)
        return float(np.sum((y - A @ beta) ** 2)), A.shape[1]
    r1, k1 = rss(full)
    r0, k0 = rss(restricted)
    df1, df2 = k1 - k0, len(y) - k1
    if df1 <= 0 or df2 <= 0 or r1 <= 0:
        return 1.0 if r1 > 0 or r0 <= 0 else 0.0
    F = ((r0 - r1) / df1) / (r1 / df2)
    return float(stats.f.sf(F, df1, df2))


def granger(names: list[str], n_stocks: int, X: np.ndarray, p: int, conditional: bool, alpha: float = ALPHA) -> set:
    """Granger tests on levels at lags 1..p: pairwise (Y's own lags vs + X's) or conditional (every
    variable's lags vs all but X's)."""
    T = X.shape[0]
    L = [X[p - k: T - k] for k in range(1, p + 1)]
    lag = lambda js: np.column_stack([lx[:, j] for lx in L for j in js]) if js else np.empty((T - p, 0))  # noqa: E731
    out = set()
    n = X.shape[1]
    for i in range(n_stocks):
        y = X[p:, i]
        for j in range(n):
            if j == i:
                continue
            base = [k for k in range(n) if k != j] if conditional else [i]
            pval = _f_test(y, lag(base + [j]), lag(base))
            if pval < alpha:
                out.add((names[j], names[i]))
    return out


def row_reg(names: list[str], n_stocks: int, X: np.ndarray, alpha: float = ALPHA) -> set:
    """Our per-stock row regression as a test: each stock's change on every level and input one step
    earlier, a t test per coefficient (the same as conditional Granger at lag 1)."""
    return granger(names, n_stocks, X, 1, True, alpha)


def _tig(X: np.ndarray):
    from tigramite import data_processing as pp
    from tigramite.independence_tests.parcorr import ParCorr
    Z = (X - X.mean(0)) / X.std(0)
    return pp.DataFrame(Z), ParCorr(significance="analytic")


def _assumptions(n: int, n_stocks: int, tau_max: int, contemp: bool = True) -> dict:
    """No link into an input (exogenous); anything else allowed."""
    la = {}
    for j in range(n):
        if j >= n_stocks:
            la[j] = {}
            continue
        d = {}
        for i in range(n):
            for tau in range(0 if contemp else 1, tau_max + 1):
                if tau == 0 and i == j:
                    continue
                d[(i, -tau)] = "-?>" if tau > 0 else ("-?>" if i >= n_stocks else "o?o")
        la[j] = d
    return la


def pcmci_plus(names: list[str], n_stocks: int, X: np.ndarray, tau_max: int = TAU_MAX, alpha: float = ALPHA) -> dict:
    """PCMCI+ with partial correlation; a lagged link X(t-k) -> Y(t) for a stock Y is the edge X -> Y.
    Contemporaneous links (the shared draw within a step) are counted separately, not as edges."""
    from tigramite.pcmci import PCMCI
    df, ci = _tig(X)
    pc = PCMCI(dataframe=df, cond_ind_test=ci, verbosity=0)
    res = pc.run_pcmciplus(tau_min=0, tau_max=tau_max, pc_alpha=alpha,
                           link_assumptions=_assumptions(X.shape[1], n_stocks, tau_max))
    g = res["graph"]
    lagged, contemp = set(), set()
    for i in range(X.shape[1]):
        for j in range(n_stocks):
            if i != j and any(g[i, j, tau] == "-->" for tau in range(1, tau_max + 1)):
                lagged.add((names[i], names[j]))
            if i != j and g[i, j, 0] not in ("",):
                contemp.add((names[i], names[j], g[i, j, 0]))
    return {"edges": lagged, "contemp": sorted(contemp)}


def pcmci(names: list[str], n_stocks: int, X: np.ndarray, tau_max: int = TAU_MAX, alpha: float = ALPHA) -> dict:
    """PCMCI (lagged links only, Runge et al. 2019): PC1 condition selection, then the MCI test."""
    from tigramite.pcmci import PCMCI
    df, ci = _tig(X)
    pc = PCMCI(dataframe=df, cond_ind_test=ci, verbosity=0)
    res = pc.run_pcmci(tau_min=1, tau_max=tau_max, pc_alpha=None, alpha_level=alpha,
                       link_assumptions=_assumptions(X.shape[1], n_stocks, tau_max, contemp=False))
    g = res["graph"]
    return {"edges": {(names[i], names[j]) for i in range(X.shape[1]) for j in range(n_stocks)
                      if i != j and any(g[i, j, tau] == "-->" for tau in range(1, tau_max + 1))}}


def lpcmci(names: list[str], n_stocks: int, X: np.ndarray, tau_max: int = 2, alpha: float = ALPHA) -> dict:
    """LPCMCI (latent confounders allowed): lagged X -> Y edges, and pairs it marks as confounded
    (a bidirected '<->' at any lag), the hint of a hidden stock or a shared unmeasured driver."""
    from tigramite.lpcmci import LPCMCI
    df, ci = _tig(X)
    lp = LPCMCI(dataframe=df, cond_ind_test=ci, verbosity=0)
    res = lp.run_lpcmci(tau_max=tau_max, pc_alpha=alpha)
    g = res["graph"]
    edges, bidir = set(), set()
    n = X.shape[1]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            for tau in range(0, tau_max + 1):
                m = g[i, j, tau]
                if j < n_stocks and tau > 0 and m == "-->":
                    edges.add((names[i], names[j]))
                if m == "<->" and i < n_stocks and j < n_stocks:
                    bidir.add(tuple(sorted((names[i], names[j]))))
    return {"edges": edges, "bidirected": sorted(bidir)}


class MethodTimeout(Exception):
    pass


def _timeout(*_):
    raise MethodTimeout(f"took longer than {METHOD_TIMEOUT} s")


def run_cell(item: tuple) -> dict:
    case_id, variant, methods = item
    from sdlab.ladder import cases as C
    from sdlab.ladder import leaderboard as LB
    c = C.load(case_id)
    row = {"case": case_id, "variant": variant, "set": LB.kind_of(c), "tags": c.get("tags") or []}
    try:
        row["truth"] = truth_graph(c, variant)
        stocks, inputs, X = page_data(c, variant)
        ok = _usable(X)
        names = [n for n, k in zip(stocks + inputs, ok) if k]
        ns = int(sum(ok[: len(stocks)]))
        Xu = X[:, ok]
        row.update(T=int(X.shape[0]), dropped=[n for n, k in zip(stocks + inputs, ok) if not k])
        row["methods"] = {}
        for m in methods:
            t0 = time.perf_counter()
            signal.signal(signal.SIGALRM, _timeout)
            signal.alarm(METHOD_TIMEOUT)
            try:
                if ns == 0:
                    r = {"edges": set()}
                elif m == "pcmci_plus":
                    r = pcmci_plus(names, ns, Xu)
                elif m == "pcmci":
                    r = pcmci(names, ns, Xu)
                elif m == "lpcmci":
                    r = lpcmci(names, ns, Xu)
                elif m == "granger_pair":
                    r = {"edges": granger(names, ns, Xu, 2, False)}
                elif m == "granger_cond":
                    r = {"edges": granger(names, ns, Xu, 2, True)}
                elif m == "row_reg":
                    r = {"edges": row_reg(names, ns, Xu)}
                else:
                    raise ValueError(m)
                r["edges"] = sorted(r["edges"])
                r["seconds"] = round(time.perf_counter() - t0, 3)
            except Exception as e:  # noqa: BLE001
                r = {"error": f"{type(e).__name__}: {e}"[:300]}
            finally:
                signal.alarm(0)
            row["methods"][m] = r
    except Exception as e:  # noqa: BLE001
        row["error"] = f"{type(e).__name__}: {e}"[:300]
    return row


def cells(sets: tuple, cases_filter: str | None = None) -> list[tuple[str, str]]:
    from sdlab.ladder import cases as C
    from sdlab.ladder import leaderboard as LB
    out = []
    for cid in C.case_ids():
        if cases_filter and not any(cid.startswith(p) for p in cases_filter.split(",")):
            continue
        c = C.load(cid)
        if LB.kind_of(c) in sets:
            out += [(cid, v["name"]) for v in c["variants"]]
    return out


def cmd_run(a) -> None:
    from multiprocessing import Pool
    methods = tuple(a.methods.split(","))
    todo = cells(tuple(a.sets.split(",")), a.cases)
    if a.variants:
        todo = [x for x in todo if any(x[1].startswith(v) for v in a.variants.split(","))]
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            r = json.loads(line)
            done.add((r["case"], r["variant"]))
    items = [(c, v, methods) for c, v in todo if (c, v) not in done]
    print(f"{len(items)} cells to run ({len(done)} already in {a.out}), methods {methods}", file=sys.stderr)
    with open(a.out, "a") as fh, Pool(a.jobs, maxtasksperchild=50) as pool:
        for k, row in enumerate(pool.imap_unordered(run_cell, items, chunksize=1)):
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            if k % 50 == 0:
                print(f"  {k}/{len(items)}", file=sys.stderr)


# ---- grading ----

def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else float("nan")
    r = tp / (tp + fn) if tp + fn else float("nan")
    f = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else float("nan")
    return p, r, f


def grade(found: set, truth: set, stock_only: set | None = None) -> dict:
    if stock_only is not None:
        found = {e for e in found if e[0] in stock_only}
        truth = {e for e in truth if e[0] in stock_only}
    tp = len(found & truth)
    return {"tp": tp, "fp": len(found - truth), "fn": len(truth - found)}


def stored_graphs(strategies: tuple) -> dict:
    from sdlab.ladder import store
    out = {}
    for s in strategies:
        for r in store.latest(strategy=s, found=True):
            if r["status"] in ("error", "timeout") or r.get("found") is None:
                out[(s, r["case"], r["variant"])] = None
            else:
                out[(s, r["case"], r["variant"])] = flow_edges(r["found"])
    return out


def _cluster_ci(diffs: dict, n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean paired difference over cells, with a 95% bootstrap interval resampling cases (a case's
    variants are not independent)."""
    cases = list(diffs)
    allv = [x for v in diffs.values() for x in v]
    if not allv:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        pick = [x for _ in cases for x in diffs[rng.choice(cases)]]
        means.append(sum(pick) / len(pick))
    means.sort()
    return sum(allv) / len(allv), means[int(0.025 * n_boot)], means[int(0.975 * n_boot)]


def cmd_report(a) -> None:
    merged: dict = {}
    for path in a.cells:
        for line in open(path):
            r = json.loads(line)
            if "truth" not in r:
                continue
            k = (r["case"], r["variant"])
            if k in merged:
                merged[k]["methods"].update(r.get("methods") or {})
            else:
                merged[k] = r
    rows = list(merged.values())
    for r in rows:        # PCMCI+ with its contemporaneous links counted too: oriented ones one way, unoriented both ways
        p = r["methods"].get("pcmci_plus")
        if p and "edges" in p:
            extra = [[a_, b_] for a_, b_, mark in p.get("contemp") or [] if mark in ("-->", "o-o", "x-x")]
            r["methods"]["pcmci_plus_c"] = {"edges": sorted({tuple(e) for e in p["edges"]} | {tuple(e) for e in extra}),
                                            "seconds": p.get("seconds")}
    stored = stored_graphs(STRATEGIES) if not a.no_store else {}
    methods = [m for m in METHODS if any(m in r.get("methods", {}) for r in rows)]
    graphs = {}       # (who, case, variant) -> edges | None (error) ; absent: not run
    for r in rows:
        for m in methods:
            x = r["methods"].get(m)
            if x is not None:
                late = (x.get("seconds") or 0) > METHOD_TIMEOUT        # a cell run before the timeout existed
                graphs[(m, r["case"], r["variant"])] = None if "error" in x or late else {tuple(e) for e in x["edges"]}
    nodes = {}
    for r in rows:
        meas = set(r["truth"]["measured"]) | set(r["truth"]["inputs"])
        nodes[(r["case"], r["variant"])] = meas
    for (s, c, v), e in stored.items():
        if (c, v) in nodes:
            graphs[(s, c, v)] = None if e is None else marginal(e, nodes[(c, v)])
    who = methods + [s for s in STRATEGIES if any(k[0] == s for k in graphs)]

    def tally(sel, stock_only=False):
        out = {}
        for w in who:
            tp = fp = fn = run = err = 0
            f1s = []
            for r in sel:
                key = (w, r["case"], r["variant"])
                if key not in graphs:
                    continue
                run += 1
                g = graphs[key]
                if g is None:
                    err += 1
                    continue
                truth = {tuple(e) for e in r["truth"]["edges"]}
                so = set(r["truth"]["measured"]) if stock_only else None
                x = grade(g, truth, so)
                tp, fp, fn = tp + x["tp"], fp + x["fp"], fn + x["fn"]
                if x["tp"] + x["fn"]:
                    f1s.append(prf(x["tp"], x["fp"], x["fn"])[2])
            p, rr, f = prf(tp, fp, fn)
            out[w] = {"cells": run, "errors": err, "P": p, "R": rr, "F1": f, "cellF1": (sum(f1s) / len(f1s)) if f1s else float("nan"),
                      "tp": tp, "fp": fp, "fn": fn}
        return out

    def show(title, sel, stock_only=False):
        print(f"\n### {title} ({len(sel)} cells{', stock -> stock edges only' if stock_only else ''})\n")
        print("| method | cells run | errors | precision | recall | F1 (pooled) | mean cell F1 | TP | FP | FN |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for w, x in tally(sel, stock_only).items():
            if x["cells"]:
                print(f"| {w} | {x['cells']} | {x['errors']} | {x['P']:.3f} | {x['R']:.3f} | {x['F1']:.3f} | {x['cellF1']:.3f} | {x['tp']} | {x['fp']} | {x['fn']} |")

    def cell_f1(w, r):
        g = graphs.get((w, r["case"], r["variant"]))
        if g is None:
            return None
        truth = {tuple(e) for e in r["truth"]["edges"]}
        x = grade(g, truth)
        if not x["tp"] + x["fn"] + x["fp"]:
            return 1.0
        return prf(x["tp"], x["fp"], x["fn"])[2]

    def paired(title, sel, base):
        print(f"\n### Paired cell F1, {title}: method minus {base} (95% CI, bootstrap over cases)\n")
        print("| method | vs | paired cells | mean F1 method | mean F1 strategy | difference | 95% CI | method better / worse / tie |")
        print("|---|---|---|---|---|---|---|---|")
        for m in methods:
            for s in [x for x in who if x not in methods] if base == "strategies" else [base]:
                diffs, a_, b_, wins = defaultdict(list), [], [], [0, 0, 0]
                for r in sel:
                    fa, fb = cell_f1(m, r), cell_f1(s, r)
                    if fa is None or fb is None:
                        continue
                    diffs[r["case"]].append(fa - fb)
                    a_.append(fa)
                    b_.append(fb)
                    wins[0 if fa > fb + 1e-9 else 1 if fb > fa + 1e-9 else 2] += 1
                if not a_:
                    print(f"| {m} | {s} | 0 (not run) | | | | | |")
                    continue
                d, lo, hi = _cluster_ci(diffs)
                print(f"| {m} | {s} | {len(a_)} | {sum(a_)/len(a_):.3f} | {sum(b_)/len(b_):.3f} | {d:+.3f} | [{lo:+.3f}, {hi:+.3f}] | {wins[0]} / {wins[1]} / {wins[2]} |")

    print(f"Cells files: {' '.join(a.cells)} ({len(rows)} cells graded). Alpha {ALPHA}, PCMCI+ tau_max {TAU_MAX}, Granger lags 2, LPCMCI tau_max 2.")
    for st in SETS:
        sel = [r for r in rows if r["set"] == st]
        if not sel:
            continue
        show(f"{st}: all cells", sel)
        show(f"{st}: all cells", sel, stock_only=True)
        for noise in ("none", "counts"):
            show(f"{st}: {noise} noise", [r for r in sel if r["variant"].startswith(noise + "-")])
        show(f"{st}: other noises (meas, gaps, weekly, lag, outliers, bias)", [r for r in sel if r["variant"].split("-")[0] not in ("none", "counts")])
        paired(st, sel, "strategies")
    sel = [r for r in rows if r["set"] == "tests"]
    groups = {
        "hidden stocks in the truth": lambda r: bool(r["truth"]["hidden"]),
        "no hidden stocks": lambda r: not r["truth"]["hidden"],
        "measured inputs": lambda r: bool(r["truth"]["inputs"]),
        "tag loop or balancing": lambda r: any(t in ("loop", "balancing", "goal") for t in r["tags"]),
        "tag schedule / era / pieces": lambda r: any(t in ("schedule", "era", "eras", "pieces", "step", "unannounced") for t in r["tags"]),
        "tag injection": lambda r: any("inject" in t for t in r["tags"]),
        "no cross-stock edge in the truth": lambda r: not r["truth"]["edges"],
    }
    for name, f in groups.items():
        show(f"tests, {name}", [r for r in sel if f(r)])
    paired("tests, hidden stocks in the truth", [r for r in sel if r["truth"]["hidden"]], "strategies")
    # as a prior: does a method's edge set separate a strategy's true edges from its false ones?
    for st in SETS:
        sel = [r for r in rows if r["set"] == st]
        print(f"\n### {st}: a method as a check on each strategy's edges (share of the strategy's true / false edges the method also finds; and the strategy's F1 if its edges were cut to those the method also finds, or joined with the method's)\n")
        print("| strategy | method | strategy TP also found | strategy FP also found | truth edges the strategy misses that the method finds | F1 strategy | F1 strategy AND method | F1 strategy OR method |")
        print("|---|---|---|---|---|---|---|---|")
        for s in [x for x in who if x not in methods]:
            for m in methods:
                a_tp = a_fp = n_tp = n_fp = miss = miss_f = 0
                c0, c1, c2 = [0, 0, 0], [0, 0, 0], [0, 0, 0]
                for r in sel:
                    gs, gm = graphs.get((s, r["case"], r["variant"])), graphs.get((m, r["case"], r["variant"]))
                    if gs is None or gm is None:
                        continue
                    truth = {tuple(e) for e in r["truth"]["edges"]}
                    for e in gs:
                        if e in truth:
                            n_tp += 1
                            a_tp += e in gm
                        else:
                            n_fp += 1
                            a_fp += e in gm
                    lost = truth - gs
                    miss += len(lost)
                    miss_f += len(lost & gm)
                    for acc, g in ((c0, gs), (c1, gs & gm), (c2, gs | gm)):
                        x = grade(g, truth)
                        acc[0] += x["tp"]; acc[1] += x["fp"]; acc[2] += x["fn"]  # noqa: E702
                if not n_tp + n_fp:
                    continue
                f = lambda c: prf(*c)[2]  # noqa: E731
                print(f"| {s} | {m} | {a_tp}/{n_tp} ({a_tp / max(1, n_tp):.0%}) | {a_fp}/{n_fp} ({a_fp / max(1, n_fp):.0%}) | {miss_f}/{miss} | {f(c0):.3f} | {f(c1):.3f} | {f(c2):.3f} |")
    # LPCMCI's confounded pairs against the truth's hidden common causes
    lp = [r for r in rows if graphs.get(("lpcmci", r["case"], r["variant"])) is not None]
    if lp:
        print("\n### LPCMCI bidirected edges as hidden-stock hints\n")
        print("| cells | with a hidden stock | true confounded pairs | flagged pairs | flagged and true | cells with hidden stock and >=1 flag | cells without hidden stock and >=1 flag |")
        print("|---|---|---|---|---|---|---|")
        hid = [r for r in lp if r["truth"]["hidden"]]
        tc = sum(len(r["truth"]["confounded"]) for r in lp)
        fl = sum(len(r["methods"]["lpcmci"]["bidirected"]) for r in lp)
        both = sum(len({tuple(p) for p in r["truth"]["confounded"]} & {tuple(p) for p in r["methods"]["lpcmci"]["bidirected"]}) for r in lp)
        a1 = sum(1 for r in hid if r["methods"]["lpcmci"]["bidirected"])
        a0 = sum(1 for r in lp if not r["truth"]["hidden"] and r["methods"]["lpcmci"]["bidirected"])
        print(f"| {len(lp)} | {len(hid)} | {tc} | {fl} | {both} | {a1} of {len(hid)} | {a0} of {len(lp) - len(hid)} |")
    if a.worst:
        print("\n### Per-case mean F1 (all variants), PCMCI+ vs structures\n")
        per = defaultdict(lambda: defaultdict(list))
        for r in rows:
            for w in ("pcmci_plus", "row_reg", "structures"):
                f = cell_f1(w, r)
                if f is not None:
                    per[r["case"]][w].append(f)
        for c, d in sorted(per.items()):
            print(c, {w: round(sum(v) / len(v), 2) for w, v in d.items()})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True)
    r.add_argument("--methods", default="pcmci_plus,granger_pair,granger_cond,row_reg")
    r.add_argument("--sets", default="tests,kubernetes")
    r.add_argument("--cases", default=None, help="comma-separated id prefixes")
    r.add_argument("--variants", default=None, help="comma-separated variant-name prefixes")
    r.add_argument("--jobs", type=int, default=4)
    g = sub.add_parser("report")
    g.add_argument("cells", nargs="+")
    g.add_argument("--no-store", action="store_true")
    g.add_argument("--worst", action="store_true", help="also list per-case F1")
    a = ap.parse_args()
    {"run": cmd_run, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
