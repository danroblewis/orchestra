"""Sweeps: parametric cases that vary one quantity along a grid (draws.py: grid(...)), read as phase
diagrams. For each point of the axis and each strategy: did it pass, and how far off is each true
number (relative error), against what the data allow at that point (analysis.py: the Cramér-Rao
bound's relative SE, the scorer's tolerance, the cell's label). Where a method's error leaves the
tolerance while the bound is still well inside it, the method breaks before the data does.

    sweeps() -> [{base, title, tests, axis, values, draws, variants}]
    phase(base, variant, strategies) -> {axis, values, points: [{case, value, label, p, parts: {part: {bound, allowed}},
                                         strategies: {name: {status, parts: {part: error}}}}]}
    svg(base, variant, strategies) -> a small-multiples chart (one panel per part), self-contained
    findings(base, strategies) -> lines of text: per variant, where each method breaks vs where the data does

A sweep's axis is named by a `# axis: ...` comment in its file, and its values by `# axis values:
...` (default: the first grid's values).
"""

from __future__ import annotations

import html
import math
import re

from . import analysis, store
from . import cases as casemod
from . import draws as drawmod

LEADERS = ("lna", "earned_pieces", "held_out", "common_cause", "hidden_transit", "matrix")
AXIS_RE = re.compile(r"^#\s*axis\s*:\s*(.+)$", re.M)
VALUES_RE = re.compile(r"^#\s*axis values\s*:\s*(.+)$", re.M)


def sweeps() -> list[dict]:
    out = []
    files = casemod.case_files()
    groups: dict[str, list[str]] = {}
    for cid in casemod.case_ids():
        base, i = casemod.split(cid)
        if i:
            groups.setdefault(base, []).append(cid)
    for base, ids in groups.items():
        text = files[base].read_text()
        ss = drawmod.sites(text, files[base].name)
        grids = [s for s in ss if s.grid]
        if not grids:
            continue
        ids = sorted(ids, key=lambda c: casemod.split(c)[1])
        m, mv = AXIS_RE.search(text), VALUES_RE.search(text)
        values = [float(x) for x in mv.group(1).split(",")] if mv else list(grids[0].grid)
        c = casemod.load(ids[0])
        out.append({"base": base, "title": c["title"], "tests": c["tests"], "axis": m.group(1).strip() if m else grids[0].label,
                    "values": values[: len(ids)], "draws": ids, "variants": [v["name"] for v in c["variants"]]})
    return out


def _sweep(base: str) -> dict:
    for s in sweeps():
        if s["base"] == base or s["base"].startswith(base):
            return s
    raise KeyError(base)


def phase(base: str, variant: str, strategies: list[str] | None = None, compute: bool = True) -> dict:
    sw = _sweep(base)
    names = list(strategies or LEADERS)
    points = []
    for cid, val in zip(sw["draws"], sw["values"]):
        a = analysis.get(cid, variant, compute=compute) or {}
        bounds: dict[str, dict] = {}
        for r in a.get("parts") or []:
            t = r.get("true")
            if not t:
                continue
            b = bounds.setdefault(r["part"], {"bound": 0.0, "allowed": math.inf, "true": t})
            se = r.get("crb_se")
            b["bound"] = math.inf if se is None else max(b["bound"], se / abs(t))
            b["allowed"] = min(b["allowed"], r["allowed"] / abs(t))
        strat = {}
        for n in names:
            rows = store.latest(cid, variant, n)
            if not rows:
                strat[n] = {"status": None, "parts": {}}
                continue
            r = rows[0]
            parts = {}
            for p in (r.get("scores") or {}).get("parts") or []:
                if isinstance(p.get("error"), (int, float)) and isinstance(p.get("true"), (int, float)) and p["true"]:
                    parts[p["key"]] = p["error"] if p.get("found") else None
            strat[n] = {"status": r["status"], "parts": parts, "spurious": len((r.get("scores") or {}).get("spurious") or [])}
        points.append({"case": cid, "value": val, "label": a.get("label"), "p": a.get("p"), "why": a.get("why") or [],
                       "parts": {k: {"bound": _f(v["bound"]), "allowed": _f(v["allowed"]), "true": v["true"]} for k, v in bounds.items()},
                       "strategies": strat})
    return {"base": sw["base"], "title": sw["title"], "tests": sw["tests"], "axis": sw["axis"], "variant": variant,
            "strategies": names, "points": points}


def _f(x):
    return x if x is not None and math.isfinite(x) else None


# ---- the chart ----

COLORS = {"light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
          "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]}
LABEL_TINT = {"unidentifiable": "u", "data-limited": "d"}


def _style() -> str:
    lt, dk = COLORS["light"], COLORS["dark"]
    rules = [f".s{i} {{ stroke: {c}; fill: {c}; }} .s{i}.open {{ fill: var(--surface); }}" for i, c in enumerate(lt)]
    drules = [f".s{i} {{ stroke: {c}; fill: {c}; }}" for i, c in enumerate(dk)]
    return ("svg { --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --grid: #e4e2dc; --u: #fde2e1; --d: #fdf0d5; }"
            " @media (prefers-color-scheme: dark) { svg { --surface: #1a1a19; --ink: #f0efec; --ink2: #c3c2b7; --grid: #34332f;"
            " --u: #4a2321; --d: #45371a; } " + " ".join(drules) + " }"
            " .bg { fill: var(--surface); } text { fill: var(--ink2); font: 11px system-ui, sans-serif; } .title { fill: var(--ink); font-weight: 600; font-size: 12px; }"
            " .grid { stroke: var(--grid); stroke-width: 1; } .u { fill: var(--u); } .d { fill: var(--d); }"
            " .bound { stroke: var(--ink); stroke-width: 2; stroke-dasharray: 5 3; fill: none; }"
            " .tol { stroke: var(--ink2); stroke-width: 1.5; stroke-dasharray: 1 3; fill: none; }"
            " .line { fill: none; stroke-width: 2; } .dot { stroke-width: 2; } " + " ".join(rules))


def svg(base: str, variant: str, strategies: list[str] | None = None, width: int = 760) -> str:
    ph = phase(base, variant, strategies)
    pts = ph["points"]
    names = ph["strategies"]
    part_names = list(dict.fromkeys(k for p in pts for k in p["parts"]))
    for p in pts:
        for s in p["strategies"].values():
            part_names += [k for k in s["parts"] if k not in part_names]
    vals = [p["value"] for p in pts]
    logx = min(vals) > 0 and max(vals) / min(vals) > 8
    cols = 2 if len(part_names) > 1 else 1
    pw, ph_ = (width - 20) // cols, 190
    rows = max(1, math.ceil(len(part_names) / cols))
    top = 64
    H = top + rows * (ph_ + 14) + 10
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {H}" width="{width}" height="{H}" role="img"'
           f' aria-label="{html.escape(ph["title"])}, {variant}">', f"<style>{_style()}</style>",
           f'<rect class="bg" width="{width}" height="{H}"/>',
           f'<text class="title" x="10" y="18">{html.escape(ph["title"])} — {variant}</text>',
           f'<text x="10" y="34">relative error |found − true| / |true| (log) vs {html.escape(ph["axis"])};'
           ' dashed: the Cramér–Rao bound (1 SE), dotted: the scorer\'s tolerance; filled: pass, open: fail</text>']
    lx = 10
    for i, n in enumerate(names):
        out.append(f'<line class="line s{i}" x1="{lx}" y1="50" x2="{lx + 16}" y2="50"/><text x="{lx + 20}" y="54">{html.escape(n)}</text>')
        lx += 30 + 7 * len(n)
    out.append(f'<rect class="u" x="{lx}" y="44" width="12" height="12"/><text x="{lx + 16}" y="54">unidentifiable</text>')
    out.append(f'<rect class="d" x="{lx + 110}" y="44" width="12" height="12"/><text x="{lx + 126}" y="54">data-limited</text>')
    ylo, yhi = -4.0, 1.0
    for k, part in enumerate(part_names):
        ox, oy = 10 + (k % cols) * pw, top + (k // cols) * (ph_ + 14)
        L, R, T, B = ox + 44, ox + pw - 12, oy + 16, oy + ph_ - 26

        def X(v):
            if len(vals) == 1:
                return (L + R) / 2
            a, b = (math.log10(min(vals)), math.log10(max(vals))) if logx else (min(vals), max(vals))
            x = math.log10(v) if logx else v
            return L + (R - L) * (x - a) / ((b - a) or 1)

        def Y(e):
            e = min(max(e, 10 ** ylo), 10 ** yhi)
            return B - (B - T) * (math.log10(e) - ylo) / (yhi - ylo)

        out.append(f'<text class="title" x="{ox + 4}" y="{oy + 10}">{html.escape(part)}</text>')
        # the cells' labels as background bands
        for i, p in enumerate(pts):
            cls = LABEL_TINT.get(p["label"] or "")
            if cls:
                x0 = (X(pts[i - 1]["value"]) + X(p["value"])) / 2 if i else L
                x1 = (X(pts[i + 1]["value"]) + X(p["value"])) / 2 if i + 1 < len(pts) else R
                out.append(f'<rect class="{cls}" x="{x0:.1f}" y="{T}" width="{max(1, x1 - x0):.1f}" height="{B - T}"><title>{html.escape(p["label"])}'
                           f' at {p["value"]:g}: {html.escape("; ".join(p["why"])[:300])}</title></rect>')
        for e in range(int(ylo), int(yhi) + 1):
            out.append(f'<line class="grid" x1="{L}" x2="{R}" y1="{Y(10 ** e):.1f}" y2="{Y(10 ** e):.1f}"/>'
                       f'<text x="{L - 6}" y="{Y(10 ** e) + 4:.1f}" text-anchor="end">{_pow(e)}</text>')
        for p in pts:
            out.append(f'<text x="{X(p["value"]):.1f}" y="{B + 14}" text-anchor="middle">{p["value"]:g}</text>')
        for key, cls in (("bound", "bound"), ("allowed", "tol")):
            seg = [(X(p["value"]), Y(p["parts"][part][key])) for p in pts if part in p["parts"] and p["parts"][part].get(key)]
            if len(seg) > 1:
                out.append(f'<polyline class="{cls}" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in seg)}"/>')
        for si, n in enumerate(names):
            seg = []
            for p in pts:
                s = p["strategies"].get(n) or {}
                e = (s.get("parts") or {}).get(part)
                if s.get("status") is None or part not in (s.get("parts") or {}):
                    continue
                y = Y(e) if e is not None else Y(10 ** yhi)
                seg.append((X(p["value"]), y, s["status"], e, p["value"]))
            if len(seg) > 1:
                out.append(f'<polyline class="line s{si}" opacity="0.8" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, *_ in seg)}"/>')
            for x, y, st, e, v in seg:
                out.append(f'<circle class="dot s{si}{"" if st == "pass" else " open"}" cx="{x:.1f}" cy="{y:.1f}" r="4">'
                           f'<title>{html.escape(n)} at {v:g}: {st}, error {"missing" if e is None else f"{100 * e:.2f}%"}</title></circle>')
    out.append("</svg>")
    return "\n".join(out)


def _pow(e: int) -> str:
    return {-4: "0.01%", -3: "0.1%", -2: "1%", -1: "10%", 0: "100%", 1: "1000%"}.get(e, f"1e{e}")


# ---- in words ----

def findings(base: str, strategies: list[str] | None = None) -> list[str]:
    sw = _sweep(base)
    names = list(strategies or LEADERS)
    lines = [f"{sw['base']}: {sw['title']} (axis: {sw['axis']}: " + ", ".join(f"{v:g}" for v in sw["values"]) + ")"]
    for variant in sw["variants"]:
        ph = phase(base, variant, names)
        lab = "".join({"achievable": "a", "data-limited": "d", "unidentifiable": "u"}.get(p["label"] or "", "?") for p in ph["points"])
        lines.append(f"  {variant:13s} data      {lab}   (a achievable, d data-limited, u unidentifiable; p: "
                     + " ".join("-" if p["p"] is None else f"{p['p']:.2f}" for p in ph["points"]) + ")")
        for n in names:
            st = [(p["strategies"][n]["status"] or ".") for p in ph["points"]]
            letters = "".join({"pass": "P", "equivalent": "E", "fail": "F", "error": "X", "timeout": "T"}.get(s, ".") for s in st)
            broken = [p["value"] for p, s in zip(ph["points"], st) if s not in ("pass", ".") and p["label"] == "achievable"]
            lines.append(f"  {'':13s} {n:16s} {letters}" + (f"   fails where the data allow it at: {', '.join(f'{v:g}' for v in broken)}" if broken else ""))
    return lines
