"""A master-equation model written as SD Lab flows (the mean-field model's own forms)."""

from __future__ import annotations

import math

from . import terms as T


def sig(v: float, n: int = 6) -> float:
    v = float(v)
    if v == 0 or not math.isfinite(v):
        return 0.0
    return round(v, n - 1 - int(math.floor(math.log10(abs(v)))))


def _rate(t: T.Term, k: float, ids: list[str], inputs: list[str], normal: dict[int, float]) -> dict:
    if t.kind in ("move", "drain", "link"):
        return {"form": "proportional", "stock": ids[t.src], "k": sig(k)}
    if t.kind == "input":
        return {"form": "proportional", "stock": inputs[t.other], "k": sig(k)}
    if t.kind in ("bind", "catal"):
        return {"form": "proportional", "stock": ids[t.src], "k": sig(k * normal[t.other])}
    return {"form": "constant", "value": sig(k)}


def _ends(t: T.Term, ids: list[str]) -> tuple:
    if t.kind in ("move", "drain", "bind", "catal"):
        return ids[t.src], None if t.dst is None else ids[t.dst]
    return None, ids[t.dst]


def to_flows(fitted: list[tuple[T.Term, float]], ids: list[str], inputs: list[str], normal: dict[int, float],
             eras: list[tuple[float, float, str]] | None = None) -> list[dict]:
    """Flows for (term, number) pairs; era-split terms (same term in several eras) as one flow with byTime
    segments over the announced eras (from, to, label)."""
    groups: dict[tuple, dict] = {}
    for t, k in fitted:
        base = T.Term(t.kind, t.src, t.dst, t.other)
        groups.setdefault(base.key(), {"term": base, "all": None, "by": {}})
        if t.era is None:
            groups[base.key()]["all"] = k
        else:
            for lab in t.era:
                groups[base.key()]["by"][lab] = groups[base.key()]["by"].get(lab, 0.0) + k
    flows = []
    for g in groups.values():
        t = g["term"]
        src, dst = _ends(t, ids)
        if g["by"] and eras:
            segs = [{"from": a, "to": b, "rate": _rate(t, g["by"].get(lab, 0.0) + (g["all"] or 0.0), ids, inputs, normal)} for a, b, lab in eras]
            f = {"from": src, "to": dst, "ratio": 1, "rate": segs[0]["rate"], "byTime": segs}
        else:
            f = {"from": src, "to": dst, "ratio": 1, "rate": _rate(t, g["all"] or 0.0, ids, inputs, normal)}
        if t.kind in ("bind", "catal"):
            f["effects"] = [{"stock": ids[t.other], "shape": "linear", "normal": sig(normal[t.other]), "min": 0, "max": 1e9}]
            if t.kind == "bind":
                f["uses"] = [{"stock": ids[t.other], "per": 1}]
        if t.kind == "link":
            f["note"] = f"reads {ids[t.src]} without drawing it down"
        flows.append(f)
    return flows
