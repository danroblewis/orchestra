"""A forward run's inputs: each measured input up to now, then what the experiment's scenario
assumes of it (``edits``: hold, value, scale, step, ramp, series), as points the engine holds
between. A ramp is written as one point per step."""

from __future__ import annotations

from .history import at, inputs_until


def inputs(history: dict, now: float, scenario: dict | None, horizon_s: float, step_s: float) -> dict[str, list]:
    out = inputs_until(history, now)
    for name, sc in ((scenario or {}).get("inputs") or {}).items():
        last = at(out.get(name), now)
        last = 0.0 if last is None else float(last)
        pts = list(out.get(name) or [])
        kind = sc["kind"]
        if kind == "value":
            pts.append([now, sc["value"]])
        elif kind == "scale":
            pts.append([now, last * sc["factor"]])
        elif kind == "step":
            pts += [[now, last], [now + sc["at_s"], sc["value"]]]
        elif kind == "ramp":
            n = max(1, int(sc["to_s"] // step_s))
            pts += [[now + i * step_s, last + (sc["value"] - last) * min(1.0, i / n)] for i in range(n + 1)]
        elif kind == "series":
            pts += [[now + s, v] for s, v in sc["points"] if s <= horizon_s]
            if sc["points"][0][0] > 0:
                pts.append([now, last if name in out else sc["points"][0][1]])
        out[name] = sorted(pts)
    return out
