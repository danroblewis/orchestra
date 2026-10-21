"""`sdlab-ladder diff`: the found model as a git diff of the truth (diff.py), for agents diagnosing
failures. Read only: it reads stored results and never runs anything.

    sdlab-ladder diff CASE --strategy S [--variant V] [--json]       one block per stored result (every variant when V is omitted)
    sdlab-ladder diff CASES --summary [--strategies roster:kubernetes] [--variants ...] [--top N] [--json]
                                    the most common diff lines across strategies and variants, normalised (sign, ends,
                                    the flow's form with its numbers as #, a wrong number's direction), with counts and
                                    examples: the review step's broad-cause finder
    sdlab-ladder diff CASE --strategy S --variant V --between REF_A REF_B | --ids A,B [--json]
                                    two stored results of one cell (the newest at or before each commit, or by id):
                                    what changed in the found model between them, and the status
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from ..discovery.api import jsonable
from . import cases as casemod
from . import merge, store
from .diff import diff
from .diff_text import fmt, parse_key, part_name

ROOT = Path(__file__).resolve().parents[2]                  # inside the git checkout


def case_view(case_id: str) -> dict:
    """The case as the page reads it (api.case): its model and its declared boundary."""
    c = casemod.load(case_id)
    return jsonable({**c, "variants": [dict(v) for v in c["variants"]]})


def found_of(row: dict) -> list:
    """The found flows as the scorer and the page read them: same-pair flows merged (merge.py)."""
    return merge.flows(row["found"]) if row.get("found") else (row.get("found") or [])


def of_row(case: dict, row: dict) -> dict:
    """diff.diff for one stored result, with where it came from."""
    row = jsonable(row)
    out = diff(case, found_of(row), row.get("scores"))
    meta = {k: row.get(k) for k in ("id", "case", "variant", "strategy", "at", "code_commit")}
    return {**{("result" if k == "id" else k): v for k, v in meta.items()}, "result_status": row.get("status"), "error": row.get("error"), **out}


def _short(key: str) -> str:
    k = parse_key(key) or {}
    if k.get("kind") == "flow":
        return k["reader"]
    return part_name(key).removeprefix("the ")


def line_text(x: dict) -> str:
    """One diff line, as git would print it: '- ends   true equation', '+ ends   found equation',
    '~ ends   id: part true -> found', '= ends   how it was read'."""
    s = x["sign"]
    if s == "-":
        body = x["true_eq"]
    elif s == "+" and x["note"].startswith("invented "):
        body = x["found_eq"]
    elif s == "~":
        bits = [f"{_short(n['part'])} {fmt(n['true'])} -> {fmt(n['found'])}" + (f" ({100 * n['rel_error']:.0f}% off)" if isinstance(n["rel_error"], (int, float)) and n["found_it"] else "")
                for n in x["numbers"] if n["found_it"] and not n["ok"]]
        bits += [f"missed {_short(n['part'])}" for n in x["numbers"] if not n["found_it"]]
        body = f"{x['true_id']}: {'; '.join(bits)}" if bits else x["note"]
    else:
        body = x["note"]
    return f"{s} {x['ends']:<30} {body}"


def _stock(s: str) -> str:
    return f"(hidden #{s[4:]})" if s.startswith("via:") else s


def block(d: dict, context: bool = False) -> str:
    head = f"{d['case']} {d['strategy']} {d['variant']} ({d['result_status']}): {d['caption'].removeprefix('Differences: ')}"
    out = [head + (f"  [result #{d['result']}{', ' + d['code_commit'][:9] if d.get('code_commit') else ''}]" if d.get("result") else "")]
    if d.get("error") and not d["lines"]:
        out.append(f"  error: {str(d['error']).splitlines()[-1][:200] if str(d['error']).strip() else ''}")
    out += [line_text(x) for x in d["lines"]]
    if context:
        out += [line_text(x) for x in d["unchanged"]]
    elif d["unchanged"]:
        out.append(f"  ({len(d['unchanged'])} unchanged)")
    if d["hunk"]["stocks"]:
        out.append(f"hunk: {', '.join(_stock(s) for s in d['hunk']['stocks'])}")
    return "\n".join(out)


_NUM = re.compile(r"(?<![\w.#])-?\d[\d,]*(?:\.\d+)?(?:e[+-]?\d+)?(?![\w])")


def shape(eq: str) -> str:
    """An equation with its numbers as #: '0.03·inflight' -> '#·inflight'."""
    return _NUM.sub("#", eq)


def norm(x: dict) -> str:
    """A diff line with what varies between strategies taken out: its sign, ends and form, and for a wrong
    number which number and which way."""
    s = x["sign"]
    if s == "~":
        bits = [f"{_short(n['part'])} {'high' if _hi(n) else 'low' if _hi(n) is False else 'off'}" for n in x["numbers"] if n["found_it"] and not n["ok"]]
        bits += [f"missed {_short(n['part'])}" for n in x["numbers"] if not n["found_it"]]
        return f"~ {x['ends']}  {shape(x['true_eq'])}  [{', '.join(bits)}]"
    if x["side"] == "truth":
        return f"{s} {x['ends']}  {shape(x['true_eq'])}"
    kind = "extra term" if x["note"].startswith("extra term") else "read as" if s == "=" else "invented" if s == "+" else "small"
    terms = ", ".join(_short(n["part"]) for n in x["numbers"])
    return f"{s} {x['ends']}  {kind} {shape(x['found_eq'])}" + (f"  [{terms}]" if kind == "extra term" else "")


def _hi(n: dict):
    from .diff_text import num
    a, b = num(n["found"]), num(n["true"])
    return None if a is None or b is None else a > b


def summary(case_ids: list[str], strategies: list[str] | None, variants: list[str] | None) -> dict:
    counts: Counter = Counter()
    examples: dict[str, list] = {}
    who: dict[str, set] = {}
    cells = 0
    by_status: Counter = Counter()
    for cid in case_ids:
        try:
            c = case_view(cid)
        except Exception as e:                               # a case file mid-edit: say so, read the rest
            print(f"{cid}: skipped, the case does not load ({e})", file=sys.stderr)
            continue
        for row in store.latest(case=cid, found=True):
            if (strategies and row["strategy"] not in strategies) or (variants and row["variant"] not in variants):
                continue
            d = of_row(c, row)
            cells += 1
            by_status[row["status"]] += 1
            for x in d["lines"]:
                k = norm(x)
                counts[k] += 1
                ex = examples.setdefault(k, [])
                who.setdefault(k, set()).add(row["strategy"])
                if len(ex) < 4 and not any(e.startswith(row["strategy"] + " ") for e in ex):     # one example per strategy
                    ex.append(f"{row['strategy']} {cid[:3] if cid[:3].isdigit() else cid} {row['variant']}")
    statuses = dict(by_status)
    return {"cells": cells, "statuses": statuses,
            "lines": [{"line": k, "count": n, "strategies": len(who[k]), "examples": examples[k]} for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]}


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def at_ref(history: list[dict], ref: str) -> dict | None:
    """The newest result whose code is the commit ref or one before it (an ancestor)."""
    sha = _git("rev-parse", "--verify", f"{ref}^{{commit}}")
    seen: dict[str, bool] = {}
    for row in history:                                       # newest first
        c = row.get("code_commit")
        if not c:
            continue
        if c not in seen:
            seen[c] = c == sha or subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", c, sha], capture_output=True).returncode == 0
        if seen[c]:
            return row
    return None


def _key(x: dict) -> tuple:
    return ("truth", x["index"]) if x["side"] == "truth" else ("found", x["ends"], x["sign"], x["note"].split(" ")[0])


def _flows(d: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for x in d["lines"] + d["unchanged"]:
        if x["side"] == "found" or x["found_eq"]:
            for eq in ([x["found_eq"]] if x["side"] == "found" else x["found_eq"].split("; ")):
                if eq and eq not in out.setdefault(x["ends"], []):
                    out[x["ends"]].append(eq)
    return out


def between(a: dict, b: dict) -> dict:
    """What changed from result a to result b of one cell: lines that went away (fixed), appeared (new)
    or changed, each wrong number closer to or further from the truth, and the found flows by ends."""
    la, lb = {_key(x): x for x in a["lines"]}, {_key(x): x for x in b["lines"]}
    changed = []
    for k in la.keys() & lb.keys():
        x, y = la[k], lb[k]
        moves = []
        nb = {n["part"]: n for n in y["numbers"]}
        for n in x["numbers"]:
            m = nb.get(n["part"])
            if m and isinstance(n["rel_error"], (int, float)) and isinstance(m["rel_error"], (int, float)) and n["rel_error"] != m["rel_error"]:
                moves.append({"part": n["part"], "before": n["rel_error"], "after": m["rel_error"], "closer": m["rel_error"] < n["rel_error"],
                              "found_before": n["found"], "found_after": m["found"], "true": n["true"]})
        if line_text(x) != line_text(y) or moves:
            changed.append({"before": x, "after": y, "numbers": moves})
    fa, fb = _flows(a), _flows(b)
    flows = []
    for ends in dict.fromkeys([*fa, *fb]):
        ea, eb = fa.get(ends, []), fb.get(ends, [])
        if ea != eb:
            flows.append({"ends": ends, "before": ea, "after": eb})
    return {"before": {k: a.get(k) for k in ("result", "at", "code_commit", "result_status", "caption")},
            "after": {k: b.get(k) for k in ("result", "at", "code_commit", "result_status", "caption")},
            "fixed": [la[k] for k in la if k not in lb], "new": [lb[k] for k in lb if k not in la], "changed": changed, "flows": flows}


def between_text(d: dict, cell: str) -> str:
    a, b = d["before"], d["after"]
    side = lambda s: f"#{s['result']} ({(s['code_commit'] or '?')[:9]}, {s['at'][:16]})"  # noqa: E731
    out = [f"{cell}: {side(a)} -> {side(b)}",
           f"status: {a['result_status']} -> {b['result_status']}",
           f"diff:   {a['caption'].removeprefix('Differences: ')} -> {b['caption'].removeprefix('Differences: ')}"]
    out += [f"fixed   {line_text(x)}" for x in d["fixed"]]
    out += [f"new     {line_text(x)}" for x in d["new"]]
    for c in d["changed"]:
        out.append(f"changed {line_text(c['before'])}")
        out.append(f"     to {line_text(c['after'])}")
        out += [f"          {_short(n['part'])}: {fmt(n['found_before'])} -> {fmt(n['found_after'])} (true {fmt(n['true'])}; "
                f"{100 * n['before']:.0f}% -> {100 * n['after']:.0f}% off, {'closer' if n['closer'] else 'further'})" for n in c["numbers"]]
    for f in d["flows"]:
        if not f["before"]:
            out.append(f"found + {f['ends']:<28} {'; '.join(f['after'])}")
        elif not f["after"]:
            out.append(f"found - {f['ends']:<28} {'; '.join(f['before'])}")
        else:
            out.append(f"found ~ {f['ends']:<28} {'; '.join(f['before'])}  ->  {'; '.join(f['after'])}")
    if len(out) == 3:
        out.append("(the found model is the same)")
    return "\n".join(out)


def add_parser(sub) -> None:
    p = sub.add_parser("diff", help="the found model as a git diff of the truth (diff.py): per result, a rung summary, or before/after")
    p.add_argument("case", help="a case (or, with --summary, cases in the --cases syntax: ids, prefixes, tag:x, level:n)")
    p.add_argument("--strategy")
    p.add_argument("--variant")
    p.add_argument("--json", action="store_true")
    p.add_argument("--context", action="store_true", help="also print the unchanged lines")
    p.add_argument("--summary", action="store_true", help="the most common diff lines across strategies and variants")
    p.add_argument("--strategies", help="with --summary: a comma list, all, everything or roster:NAME (default: every stored strategy)")
    p.add_argument("--variants", help="with --summary: a comma list (default: every variant)")
    p.add_argument("--top", type=int, default=30, help="with --summary: how many lines")
    p.add_argument("--between", nargs=2, metavar=("REF_A", "REF_B"), help="two commits: the newest result at or before each")
    p.add_argument("--ids", help="two result ids, A,B")


def main(a) -> int:
    from . import runner
    if a.summary:
        names = [s["name"] for part in runner.select_strategies(a.strategies) for s in part] if a.strategies else None
        got = summary(runner.select_cases(a.case), names, [v.strip() for v in a.variants.split(",")] if a.variants else None)
        if a.json:
            print(json.dumps({**got, "lines": got["lines"][: a.top]}, indent=1, ensure_ascii=False))
            return 0
        print(f"{got['cells']} results ({', '.join(f'{n} {k}' for k, n in sorted(got['statuses'].items()))}); the {min(a.top, len(got['lines']))} most common diff lines of {len(got['lines'])}:")
        for x in got["lines"][: a.top]:
            print(f"{x['count']:5d}  {x['line']}\n       {x['strategies']} strategies, e.g. {'; '.join(x['examples'])}")
        return 0
    if not casemod.known(a.case):
        ids = runner.select_cases(a.case)
        if len(ids) != 1:
            print(f"diff takes one case (got {len(ids)} for {a.case!r}); --summary reads many", file=sys.stderr)
            return 2
        a.case = ids[0]
    c = case_view(a.case)
    if a.between or a.ids:
        if a.ids:
            rows = [store.get(int(i)) for i in a.ids.split(",")[:2]]
            if len(rows) != 2 or None in rows:
                print("--ids takes two stored result ids, A,B", file=sys.stderr)
                return 2
        else:
            if not (a.strategy and a.variant):
                print("--between needs --strategy and --variant", file=sys.stderr)
                return 2
            hist = store.history(a.case, a.variant, a.strategy, found=True)
            rows = [at_ref(hist, r) for r in a.between]
            for ref, r in zip(a.between, rows):
                if r is None:
                    print(f"no result of {a.case} {a.strategy} {a.variant} at or before {ref}", file=sys.stderr)
                    return 1
        got = between(of_row(c, rows[0]), of_row(c, rows[1]))
        cell = f"{a.case} {rows[0]['strategy']} {rows[0]['variant']}"
        print(json.dumps(got, indent=1, ensure_ascii=False) if a.json else between_text(got, cell))
        return 0
    if not a.strategy:
        print("diff takes --strategy S (or --summary)", file=sys.stderr)
        return 2
    rows = [r for r in store.latest(case=a.case, strategy=a.strategy, found=True) if not a.variant or r["variant"] == a.variant]
    if not rows:
        print(f"no stored result for {a.case} {a.strategy}{' ' + a.variant if a.variant else ''}", file=sys.stderr)
        return 1
    ds = [of_row(c, r) for r in rows]
    print(json.dumps(ds if len(ds) > 1 else ds[0], indent=1, ensure_ascii=False) if a.json else "\n\n".join(block(d, a.context) for d in ds))
    return 0
