"""``orchestra sources check|infer|preview``: what the sources are, what they offer, and what a
query returns, as text. Reads only (AGENTS.md rule 9); never a credential's value."""

from __future__ import annotations

import time

from ..sd.rediscover import aligned
from . import SourceError
from .catalogue import Catalogue
from .transform import TransformError

BARS = "▁▂▃▄▅▆▇█"


def spark(values: list[float], width: int = 40) -> str:
    if not values:
        return ""
    if len(values) > width:
        k = len(values) / width
        values = [values[int(i * k)] for i in range(width)]
    lo, hi = min(values), max(values)
    return "".join(BARS[0 if hi == lo else int((v - lo) / (hi - lo) * (len(BARS) - 1))] for v in values)


def _label(canonical: str, i: dict) -> str:
    churn = f", churn {i['churn']:.2f}" if i["churn"] else ""
    return f"{canonical}={i['real']} ({i['role']}, {i['cardinality']} values{churn})"


def check(cat: Catalogue) -> list[str]:
    out = []
    for name, why in cat.specs.refused.items():
        out.append(f"{name}: REFUSED: {why}")
    for spec in cat.specs.sources:
        src = cat.remotes[spec.name]
        a = src.auth.describe()
        out.append(f"{spec.name}: {spec.type} at {spec.where()}, prefix {spec.prefix}:, auth {'+'.join(a['kinds'])}"
                   + ("  INSECURE (TLS not verified)" if a["insecure"] else ""))
        for c in a["credentials"]:
            out.append(f"  {c['what']} from {c['from']}: {'present' if c['present'] else 'MISSING'}")
        h = src.health()
        out.append(f"  {'answers' if h.ok else 'DOES NOT ANSWER'}"
                   + (f" ({h.build.get('version')})" if h.build.get("version") else "") + f", {h.latency_ms} ms a request")
        out.append("  endpoints: " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in h.endpoints.items()))
        if h.error:
            out.append(f"  error: {h.error}")
    return out or ["no [[sources]] in orchestra.toml"]


def infer(cat: Catalogue, project, only: str | None = None) -> list[str]:
    now = time.time()
    start, end = aligned(now - project.config.discovery_window, now, project.config.discovery_step)
    out = []
    for spec in cat.specs.sources:
        if only and spec.name != only:
            continue
        try:
            inf = cat.inference(spec.name, start, end, refresh=True)
        except (SourceError, TransformError) as e:
            out.append(f"{spec.name}: inference failed: {e}")
            continue
        out.append(f"{spec.name}: {len(inf.families)} families, {len(inf.kept)} definitions kept, {len(inf.left_out)} left out"
                   + (f"; query script {inf.script}" if inf.script else ""))
        for f in inf.families:
            labels = ", ".join(_label(c, i) for c, i in f["labels"].items())
            out.append(f"  family {f['name']} [{f['kind']}{', ' + '/'.join(f['stats']) if f['stats'] else ''}] every "
                       f"{f['resolution_s'] or '?'} s: {labels}")
        for n in inf.notes:
            out.append(f"  note: {n}")
        out.append("  kept:")
        for d in inf.kept:
            out.append(f"    {spec.prefix}:{d.name} by ({', '.join(d.group_by)}) [{d.view}, {d.kind}] score {d.score}: {d.query}"
                       + (f"  ({'; '.join(d.flags)})" if d.flags else ""))
            if d.traffic:
                t = d.traffic
                out.append(f"      counted traffic: {t['direction']}, channel {t['channel']}, machine {t.get('machine') or 'unattributed'}"
                           + (f" (or [sources.producers]: {', '.join(f'{k} = {v}' for k, v in spec.producers.items())})"
                              if t["direction"] == "out" and spec.producers else ""))
        out.append("  left out:")
        for d in inf.left_out:
            out.append(f"    {d.name} by ({', '.join(d.group_by)}) [{d.view}]: {d.why}")
    return out or [f"no source named {only}" if only else "no [[sources]] in orchestra.toml"]


def preview(cat: Catalogue, query: str, source: str | None, minutes: float, step_s: float) -> list[str]:
    now = time.time()
    start, end = aligned(now - minutes * 60, now, step_s)
    src = cat.remotes.get(source) if source else cat.own
    if src is None:
        return [f"no source named {source}"]
    try:
        got = src.query_range(query, start, end, step_s)
    except SourceError as e:
        return [f"failed: {e}"]
    out = [f"{len(got)} series from {src.name} over the last {minutes:g} min in {step_s:g} s steps"]
    for labels, pts in got[:50]:
        vals = [v for _, v in pts]
        lab = "{" + ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
        out.append(f"  {lab}  {len(pts)} points, min {min(vals):.4g} max {max(vals):.4g} last {vals[-1]:.4g}  {spark(vals)}")
    if len(got) > 50:
        out.append(f"  … and {len(got) - 50} more")
    return out
