"""Extra seeds: how much of a bench number is run-to-run noise.

With --seeds K each example is also run with K other seeds (the same true model and schedule, other
random draws; the example's SEED + 2, + 3, ...: SEED + 1 is the fresh run). On each, discovery runs
again and is graded on that run ("skill"), and the main run's model is graded on it too ("fresh").
Reported per run as mean ± spread (sample standard deviation) over the main seed and the extra ones,
and in the headline as the mean skill@20 / @100 per seed: the spread of the headline itself, which
is the noise an adopt decision has to beat.
"""

from __future__ import annotations

import math
import statistics

import datasets
from grade import same_behaviour


def extra(example: str, k: int) -> list[int]:
    if k <= 0:
        return []
    base = datasets.load_sim(example).SEED
    return [base + 2 + i for i in range(k)]


def graded(seed: int, main: dict, again: dict, error: str | None, truth_model: dict, data: dict) -> dict:
    """On the run with this seed: the model discovered on it, and the main run's model."""
    return {"seed": seed, "error": error,
            "skill": {str(h): same_behaviour(again, truth_model, data, horizon=h)["skill"] for h in (20, 100)},
            "fresh": {str(h): same_behaviour(main, truth_model, data, horizon=h)["skill"] for h in (20, 100)}}


def _clip(v) -> float:
    return max(-1.0, v) if isinstance(v, (int, float)) and math.isfinite(v) else -1.0


def values(x: dict, h: int, key: str = "skill") -> list[float]:
    """skill@h on the main seed and every extra seed (key "fresh": the main model on the extra seeds)."""
    own = [_clip(x["skill"][str(h)])] if key == "skill" else []
    return own + [_clip(s[key][str(h)]) for s in x.get("seeds") or []]


def mean_sd(v: list[float]) -> tuple[float, float]:
    return (statistics.fmean(v), statistics.stdev(v) if len(v) > 1 else 0.0) if v else (math.nan, math.nan)


def spread(x: dict, h: int) -> str:
    m, s = mean_sd(values(x, h))
    return f"{100 * m:.1f}% ± {100 * s:.1f}"


def headline(results: list[dict]) -> list[str]:
    """Mean skill per seed (the headline's own spread), and the typical spread of one run."""
    k = min((len(x.get("seeds") or []) for x in results), default=0)
    if not k:
        return []
    out = []
    for h in (20, 100):
        per_seed = [statistics.fmean(values(x, h)[i] for x in results) for i in range(k + 1)]
        m, s = mean_sd(per_seed)
        runs = statistics.fmean(mean_sd(values(x, h))[1] for x in results)
        fm, fs = mean_sd([statistics.fmean(values(x, h, "fresh")[i] for x in results) for i in range(k)])
        out.append(f"Seeds ({k + 1} per run): mean skill@{h} {100 * m:.1f}% ± {100 * s:.1f} over seeds "
                   f"({', '.join(f'{100 * v:.1f}%' for v in per_seed)}); one run's spread {100 * runs:.1f} points on average; "
                   f"the main model on the other seeds {100 * fm:.1f}% ± {100 * fs:.1f}")
    return out
