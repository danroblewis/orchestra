"""Parametric cases: a case whose numbers are drawn from ranges, run once per draw.

A hand-written case has one set of numbers, so a strategy can pass it by the luck of those numbers
(three chains whose inflows happen to be far apart, rates that happen to differ). In a parametric
case any number may be a range instead, and the case is run on several draws of its numbers:

    draws: 8                                   # how many draws (default 8)
    stocks: {A: draw(0, 200, int), B: 0}       # an initial level
    flows:
      outside -> A: draw(5, 40)                # uniform on [5, 40]
      A -> B: draw(0.05, 0.5, log) * A         # log-uniform
      B -> outside: {draw: [0.05, 0.5]}        # the same as draw(0.05, 0.5)

`draw(lo, hi)` takes two numbers (0 <= lo < hi) and optionally `log` (log-uniform, lo > 0) and `int`
(rounded to a whole number); other draws are rounded to three significant figures, so a drawn value
reads as written. A draw may stand for any number in the file (a rate's numbers, an initial level, a
schedule's values, an injection's amount), and is replaced in the text before the YAML is read, so
the YAML traps about commas do not apply to it. A draw inside a comment is left alone.

Draw i (1..N) of a case is the id `NNN-slug#i`. Its numbers come from a generator seeded by the case's
seed, i and an attempt number, so draws are reproducible, and raising N keeps the first draws. Each
draw must pass the case checks (checks.py: bounded, moving, every flow moves); a draw that does not
is drawn again with the next attempt (up to ATTEMPTS), and the rejected attempts are reported.

    sites(text) -> [Site]                     every draw(...) in the text, in order
    count(text) -> N                          how many draws (0: not a parametric case)
    seed(text), values(sites, seed, i, attempt), resolve(text, sites, values) -> the case's text
    describe(text, sites, values) -> [{label, value, lo, hi, log, int, line}]

A **sweep** varies one quantity along a grid instead of at random: `grid(v1, v2, ..., vN)` stands
for v_i in draw i, so the case has N draws (every grid in a case has the same length; a `draws:`
line, if any, must say N). Two grids in one case move together (draw i takes the i-th value of
each), which is how one mathematical quantity that appears in two places is varied. A sweep holds
everything else fixed: it has no draw(...). analysis.py and sweep.py read a sweep's draws in order
as the points of its axis.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass

from .caseformat import CaseError

DEFAULT_DRAWS = 8
ATTEMPTS = 12
DRAW_RE = re.compile(r"\bdraw\(([^()]*)\)|\{\s*draw\s*:\s*\[([^\[\]]*)\]\s*\}|\bgrid\(([^()]*)\)")
DRAWS_RE = re.compile(r"^draws[ \t]*:[ \t]*([^#\n]*?)[ \t]*(?:#.*)?$\n?", re.M)
SEED_RE = re.compile(r"^seed[ \t]*:[ \t]*(\d+)", re.M)
SECTION_RE = re.compile(r"^([A-Za-z_]+)[ \t]*:", re.M)


@dataclass(frozen=True)
class Site:
    start: int
    end: int
    lo: float
    hi: float
    log: bool
    integer: bool
    label: str
    line: int
    grid: tuple = ()                # a sweep's values (grid(...)): draw i takes grid[i - 1]


def _in_comment(text: str, pos: int) -> bool:
    line = text[text.rfind("\n", 0, pos) + 1: pos]
    return bool(re.search(r"(^|\s)#", line))


def _arg(word: str, where: str) -> float:
    try:
        return float(word)
    except ValueError:
        raise CaseError(f"{where}: draw takes (lo, hi[, log][, int]), not {word!r}") from None


def sites(text: str, name: str = "<case>") -> list[Site]:
    out: list[Site] = []
    seen: dict[str, int] = {}
    for m in DRAW_RE.finditer(text):
        if _in_comment(text, m.start()):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        where = f"{name}:{line_no}"
        if m.group(3) is not None:
            g = tuple(_arg(w.strip(), where) for w in m.group(3).split(",") if w.strip())
            if len(g) < 2:
                raise CaseError(f"{where}: grid takes two values or more: grid(v1, v2, ...)")
            label = _label(text, m.start())
            seen[label] = seen.get(label, 0) + 1
            out.append(Site(m.start(), m.end(), min(g), max(g), False, False, label, line_no, g))
            continue
        words = [w.strip() for w in (m.group(1) if m.group(1) is not None else m.group(2)).split(",") if w.strip()]
        if len(words) < 2:
            raise CaseError(f"{where}: draw takes (lo, hi[, log][, int])")
        lo, hi = _arg(words[0], where), _arg(words[1], where)
        flags = set(words[2:])
        if flags - {"log", "int"}:
            raise CaseError(f"{where}: draw's options are log and int, not {', '.join(sorted(flags - {'log', 'int'}))}")
        if not 0 <= lo < hi:
            raise CaseError(f"{where}: draw needs 0 <= lo < hi (write a negative number as '- draw(...)')")
        if "log" in flags and lo <= 0:
            raise CaseError(f"{where}: a log draw needs lo > 0")
        label = _label(text, m.start())
        seen[label] = seen.get(label, 0) + 1
        out.append(Site(m.start(), m.end(), lo, hi, "log" in flags, "int" in flags, label, line_no))
    # a label used twice (two draws in one rate) is numbered
    dup = {lb for lb, n in seen.items() if n > 1}
    k: dict[str, int] = {}
    fixed = []
    for s in out:
        if s.label in dup:
            k[s.label] = k.get(s.label, 0) + 1
            s = Site(s.start, s.end, s.lo, s.hi, s.log, s.integer, f"{s.label} [{k[s.label]}]", s.line, s.grid)
        fixed.append(s)
    return fixed


def _label(text: str, pos: int) -> str:
    """Where a draw is, in words: its section and the key it is the value of ("flows: A -> B")."""
    sec = [m.group(1) for m in SECTION_RE.finditer(text, 0, pos + 1)]
    section = sec[-1] if sec else ""
    line_start = text.rfind("\n", 0, pos) + 1
    line = text[line_start: text.find("\n", pos) if "\n" in text[pos:] else len(text)]
    prefix = text[line_start: pos]
    m = re.match(r"\s*(?:-\s*)?([^:{}\[\]]+?)\s*:", line)
    line_key = m.group(1).strip() if m else ""
    m = re.search(r"([^{},:\[\]]+?)\s*:[^:{},]*$", prefix)
    local = m.group(1).strip() if m else line_key
    if line_key in ("", section):
        key = local
    elif local and local != line_key:
        key = f"{line_key} / {local}"
    else:
        key = line_key
    return f"{section}: {key}" if section and key and key != section else (key or section)


def count(text: str, name: str = "<case>") -> int:
    """How many draws a case has: 0 when it has no draw(...) (an ordinary case)."""
    ss = sites(text, name)
    m = DRAWS_RE.search(text)
    if m and not ss:
        raise CaseError(f"{name}: draws is for a case with draw(lo, hi) numbers, and this one has none")
    if not ss:
        return 0
    grids = {len(s.grid) for s in ss if s.grid}
    if len(grids) > 1:
        raise CaseError(f"{name}: every grid(...) in a sweep has the same number of values ({', '.join(map(str, sorted(grids)))} here)")
    if not m:
        return grids.pop() if grids else DEFAULT_DRAWS
    try:
        n = int(m.group(1))
    except ValueError:
        n = 0
    if n < 1:
        raise CaseError(f"{name}: draws is how many draws to run, a whole number >= 1")
    if grids and n != next(iter(grids)):
        raise CaseError(f"{name}: draws: {n}, but its grid(...) has {next(iter(grids))} values")
    return n


def seed(text: str) -> int:
    m = SEED_RE.search(text)
    return int(m.group(1)) if m else 1


def round3(v: float) -> float:
    return float(f"{v:.3g}")


def fmt(v: float) -> str:
    """A drawn number as it is written into the case."""
    v = float(v)
    return str(int(v)) if v.is_integer() else repr(v)


def values(ss: list[Site], case_seed: int, i: int, attempt: int = 0) -> list[float]:
    """Draw i's numbers on an attempt: one generator per (seed, i, attempt), the sites in order."""
    rng = random.Random(int.from_bytes(hashlib.sha256(f"{case_seed}/{i}/{attempt}".encode()).digest()[:8], "big"))
    out = []
    for s in ss:
        if s.grid:                                                 # a sweep: the i-th point of its grid
            out.append(s.grid[(i - 1) % len(s.grid)])
            continue
        u = rng.random()
        v = s.lo * (s.hi / s.lo) ** u if s.log else s.lo + (s.hi - s.lo) * u
        v = float(round(v)) if s.integer else round3(v)
        out.append(min(max(v, s.lo), s.hi) if not s.integer else v)
    return out


def resolve(text: str, ss: list[Site], vals: list[float]) -> str:
    """The case's text with each draw replaced by its number and the draws line dropped."""
    out = text
    for s, v in sorted(zip(ss, vals), key=lambda x: -x[0].start):
        out = out[: s.start] + fmt(v) + out[s.end:]
    return DRAWS_RE.sub("", out, count=1)


def describe(text: str, ss: list[Site], vals: list[float]) -> list[dict]:
    """Each drawn number: where it is, its value, its range, and its line with the numbers in."""
    lines = resolve_lines(text, ss, vals)
    return [{"label": s.label, "value": v, "lo": s.lo, "hi": s.hi, "log": s.log, "int": s.integer, "line": lines[s.line],
             **({"grid": list(s.grid)} if s.grid else {})}
            for s, v in zip(ss, vals)]


def resolve_lines(text: str, ss: list[Site], vals: list[float]) -> dict[int, str]:
    """{line number: the line with its draws replaced}, for the lines that have draws."""
    by_line: dict[int, list] = {}
    for s, v in zip(ss, vals):
        by_line.setdefault(s.line, []).append((s, v))
    out = {}
    for n, items in by_line.items():
        start = text.rfind("\n", 0, items[0][0].start) + 1
        end = text.find("\n", start)
        end = len(text) if end < 0 else end
        line = text[start:end]
        for s, v in sorted(items, key=lambda x: -x[0].start):
            line = line[: s.start - start] + fmt(v) + line[s.end - start:]
        out[n] = line.split(" #")[0].strip().lstrip("- ").strip()
    return out


def frozen(text: str, name: str, i: int, attempt: int, case_id: str, title: str, tests: str) -> str:
    """Draw i (on its accepted attempt) written as an ordinary case: the drawn numbers in place of
    the ranges, no draws line, the title and test sentence saying where it came from, and the
    parametric tag replaced by frozen-draw. The comments are kept."""
    import json

    ss = sites(text, name)
    vals = values(ss, seed(text), i, attempt)
    out = resolve(text, ss, vals)
    drawn = "; ".join(dict.fromkeys(d["line"] for d in describe(text, ss, vals)))
    out = re.sub(r"^title[ \t]*:.*$", lambda _: "title: " + json.dumps(f"{title} (draw {i} of {case_id[:3]})"), out, count=1, flags=re.M)
    out = re.sub(r"^tests[ \t]*:.*$", lambda _: "tests: " + json.dumps(f"{case_id}#{i} as a fixed case ({drawn}); {tests}"), out, count=1, flags=re.M)
    out = re.sub(r"^(tags[ \t]*:.*)\bparametric\b", r"\1frozen-draw", out, count=1, flags=re.M)
    return f"# Frozen from {case_id}#{i} (attempt {attempt}) by sdlab-ladder freeze.\n" + out
