"""Which series drives a flow's rate, if any: the search priced, the winner refuted as the net-flow
layer refutes its drivers (``sd.netflow``), and the evidence kept on the flow.

``sd.discover.fit_flow`` scores every form a flow's rate may take: the flow's **own** forms (a
constant, or its own source's level: what waits is taken) and one or two forms on each other
series it may read (a stock, or a measured gauge: a **driver**). A hundred or more series are
offered, and the best of a hundred unrelated series beats a constant by chance; and the events of
real flows come in bursts, so the Poisson likelihood counts each burst many times over. So a
driver is kept only when it passes all of these, in this order:

- **the price**: its gain over the best own form, in quasi-likelihood (the log-likelihood divided
  by the events' dispersion around the driver's own rate, ``dispersion``: Pearson's χ² per degree
  of freedom over ``BINS`` stretches of the window, at least 1), must reach ``AIC_MARGIN`` plus
  ``2 ln m`` for the ``m`` driver forms tried (as ``sd.netflow`` charges its search);
- **a steady trend in time** (a rate ``c + a × t``) must not explain the events as well: the driver
  must beat it by the same price. Over an hour any two series that follow the day's curve fit each
  other, and a trend is the clock itself;
- **the other half of the window**: fitted on either half, it must predict the other half's events
  better than the own form and the trend fitted on that half, and its slope must keep its sign. A
  driver that wins a window by a coincidence of one stretch rarely carries to the other;
- **the driver read a quarter of the window away** (earlier and later) must explain clearly less:
  under ``SHIFTED`` of the gain it has in place. A cause explains the events it causes when they
  happen; a series that moves smoothly explains a smooth rate as well an hour off.

What survives is the driver; when several survive within ``AIC_MARGIN`` of the best, the one
nearest the flow by its name and labels (``adjacency``: the same unit, a shared service, queue or
topic, words of the name) is preferred, a tie-break and never a reason on its own. When none
survives, the flow keeps its own form: a rate the other series do not explain, said so on the flow
rather than explained by free disk. Every flow records what was tried and why the leaders fell
(``evidence["driver"]``)."""

from __future__ import annotations

import math

from .drivers import AIC_MARGIN, EVENTS_PER_PARAM
from .live import intersect, length
from .netflow import SHIFTED
from .path import Path, by_level, nelder_mead

BINS = 120             # the stretches the events' dispersion is measured over
TESTED = 12            # the leading drivers (by likelihood) put through the refutations
LISTED = 6             # the refuted drivers recorded on the flow
QUIET = {"instance", "instrument", "machine", "project", "source", "job", "le", "quantile", "__name__"}
GENERIC = {"total", "count", "sum", "bucket", "seconds", "bytes", "max", "min", "avg", "current", "value", "info"}


def adjacency(a_name: str, a_labels: dict, b_name: str, b_labels: dict, same_unit: bool) -> int:
    """How near two series are by what they say of themselves: one for the same unit, one per label
    value they share (a service, a queue, a topic; who wrote them is not counted), one per word of
    their names they share (beyond units and suffixes)."""
    shared = {(k, v) for k, v in (a_labels or {}).items() if k not in QUIET} & {(k, v) for k, v in (b_labels or {}).items() if k not in QUIET}
    words = lambda n: {w for w in n.split(":")[-1].lower().split("_") if len(w) >= 3 and w not in GENERIC}
    return int(same_unit) + len(shared) + len(words(a_name) & words(b_name))


def _fit(events: list, p: Path | None, form: str, t: float) -> dict | None:
    """The form's parameters fitted on ``events`` over ``p`` (``t``: the time, in the model's unit)."""
    n = sum(d for _, d in events)
    if n <= 0 or t <= 0:
        return None
    if form == "constant":
        return {"c": n / t}
    expo = p.integral(0.0, 1.0)
    if form == "proportional":
        return {"k": n / expo} if expo > 0 else None
    xs = list(p.time_at)
    span = (max(xs) - min(xs)) if xs else 0.0
    if span <= 0:
        return None
    c0 = n / t
    lv = by_level(events, [p.before(e) for e, _ in events])

    def nll(q):
        v = _ll_at(lv, p, q[0], q[1])
        return -v if math.isfinite(v) else 1e18
    c, k = nelder_mead(nll, [c0, 0.0], [max(c0, 1e-3) * 0.5, max(c0, 1e-3) / span])
    return {"c": c, "k": k}


def _ll_at(lv: list, p: Path, c: float, k: float) -> float:
    out = 0.0
    for x, d in lv:
        r = c + k * x
        if r <= 1e-12:
            return -math.inf
        out += d * math.log(r)
    return out - p.integral(c, k)


def loglik(events: list, p: Path | None, form: str, params: dict | None, t: float) -> float:
    """The events' Poisson point-process log-likelihood under the form (``t``: the live time)."""
    if params is None:
        return -math.inf
    if form == "constant":
        c, n = params["c"], sum(d for _, d in events)
        return (n * math.log(c) if n else 0.0) - c * t if c > 0 else -math.inf
    return _ll_at(by_level(events, [p.before(e) for e, _ in events]), p, params.get("c", 0.0), params["k"])


def dispersion(events: list, p: Path | None, form: str, params: dict, live: list, unit_s: float) -> float:
    """Pearson's χ² per degree of freedom of the events counted over ``BINS`` stretches of the live
    time, against the rate the form expects in each; at least 1."""
    total = length(live)
    if total <= 0:
        return 1.0
    width = total / BINS
    bins = []
    for a, b in live:
        x = a
        while x < b - 1e-9:
            bins.append((x, min(b, x + width)))
            x += width
    counts = [0.0] * len(bins)
    j = 0
    for t, d in sorted(events):
        while j < len(bins) and t > bins[j][1]:
            j += 1
        if j < len(bins) and t > bins[j][0] - 1e-9:
            counts[j] += d
    c, k = params.get("c", 0.0), params.get("k", 0.0)
    chi, used = 0.0, 0
    for (a, b), o in zip(bins, counts):
        e = p.expected(a, b, c, k) if p is not None and form != "constant" else max(0.0, c) * (b - a) / unit_s
        if e > 1e-9:
            chi += (o - e) ** 2 / e
            used += 1
    df = used - (1 if form != "linear" else 2)
    return max(1.0, chi / df) if df > 0 else 1.0


class Window:
    """A flow's events and live time, with the paths cut to halves and shifted as the tests need."""

    def __init__(self, events: list, live: list, unit_s: float):
        self.events, self.live, self.unit_s = events, live, unit_s
        self.t = length(live) / unit_s
        acc, mid = 0.0, live[-1][1] if live else 0.0
        for a, b in live:
            if acc + (b - a) >= length(live) / 2:
                mid = a + (length(live) / 2 - acc)
                break
            acc += b - a
        self.halves = [intersect(live, [(-math.inf, mid)]), intersect(live, [(mid, math.inf)])]
        self._cut: dict = {}
        first = live[0][0] if live else 0.0
        step = max(1.0, length(live) / BINS)
        ticks = [first + i * step for i in range(int(((live[-1][1] if live else first) - first) / step) + 2)]
        self.clock = Path.of([(x, (x - first) / unit_s) for x in ticks], live, unit_s)

    def on(self, live: list, p: Path | None) -> tuple[list, Path | None, float]:
        """The events, the path and the time over ``live`` (a part of the window)."""
        ev = [(t, d) for t, d in self.events if any(a < t <= b + 1e-9 for a, b in live)]
        if p is None:
            return ev, None, length(live) / self.unit_s
        key = (id(p), tuple(live))
        if key not in self._cut:
            self._cut[key] = Path.of(list(zip(p.times, p.values)), live, self.unit_s)
        return ev, self._cut[key], length(live) / self.unit_s


def _form(c: dict) -> str:
    return c["form"]


def _halves(w: Window, cand: dict, p: Path, own: dict, p_own: Path | None) -> str:
    """Why the driver fails the other half of the window, or nothing."""
    got = {"driver": 0.0, "own": 0.0, "trend": 0.0}
    signs = []
    for i in (0, 1):
        train, test = w.halves[i], w.halves[1 - i]
        for name, form, path in (("driver", _form(cand), p), ("own", _form(own), p_own), ("trend", "linear", w.clock)):
            ev, pp, t = w.on(train, path)
            params = _fit(ev, pp, form, t)
            if name == "driver" and params is not None and form == "linear":
                signs.append(params["k"])
            ev2, pp2, t2 = w.on(test, path)
            got[name] += loglik(ev2, pp2, form, params, t2)
    if not math.isfinite(got["driver"]):
        return "fitted on either half of the window, it could not explain the other half's events"
    if got["driver"] <= got["own"]:
        return (f"fitted on either half of the window, it predicted the other half no better than the flow's own form "
                f"(log-likelihood {got['driver']:.1f} against {got['own']:.1f})")
    if got["driver"] <= got["trend"]:
        return (f"fitted on either half of the window, it predicted the other half no better than a steady trend in time "
                f"(log-likelihood {got['driver']:.1f} against {got['trend']:.1f})")
    k = cand["params"].get("k", 0.0)
    if signs and any(s * k <= 0 for s in signs):
        return f"its slope turns around between the halves of the window ({', '.join(f'{s:.3g}' for s in signs)})"
    return ""


def _shifted(w: Window, cand: dict, p: Path, own: dict, p_own: Path | None) -> tuple[str, dict]:
    """Why the driver read away from the events explains as much as in place, or nothing; and the
    gains. It is read an eighth, a quarter and three eighths of the window earlier and later, and
    refuted when, at the median of those, it keeps ``SHIFTED`` of its gain in place: a series that
    only moves smoothly explains a smooth rate at any of them, while a cause (even one that
    repeats, read half its period off) explains clearly less at most."""
    if not w.live:
        return "", {}
    span = w.live[-1][1] - w.live[0][0]
    out, ratios = {}, []
    for s in [f * span for f in (1 / 8, 1 / 4, 3 / 8, -1 / 8, -1 / 4, -3 / 8)]:
        sub = intersect(w.live, [(p.times[0] - s, p.times[-1] - s)])
        ev, pp, t = w.on(sub, p)
        if sum(d for _, d in ev) < max(EVENTS_PER_PARAM * cand["k"], 0.5 * sum(d for _, d in w.events)):
            continue
        evo, po, _ = w.on(sub, p_own)
        base = loglik(evo, po, _form(own), _fit(evo, po, _form(own), t), t)
        here = loglik(ev, pp, _form(cand), _fit(ev, pp, _form(cand), t), t) - base
        moved_path = Path.of([(x - s, v) for x, v in zip(p.times, p.values)], sub, w.unit_s)
        moved = loglik(ev, moved_path, _form(cand), _fit(ev, moved_path, _form(cand), t), t) - base
        out[f"{s / 60:+.3g} min"] = {"in_place": round(here, 2), "moved": round(moved, 2)}
        if here > 0:
            ratios.append(moved / here)
    if ratios:
        mid = sorted(ratios)[len(ratios) // 2]
        if mid >= SHIFTED:
            return (f"read an eighth to three eighths of the window earlier or later it keeps {mid:.0%} of the gain it has in "
                    "place, at the median: a series that moves smoothly, not a cause"), out
    return "", out


def _judge(w: Window, cand: dict, p: Path, ref: dict, p_ref: Path | None, price: float, ll_trend: float) -> tuple[float, str | None, dict]:
    """A form that reads ``p`` against the form it must beat (``ref``): its gain in quasi-likelihood
    over it, and why it is refuted (None when it does not pay the price; "" when it survives)."""
    phi = dispersion(w.events, p, cand["form"], cand["params"], w.live, w.unit_s)
    gain = 2 * (cand["loglik"] - ref["loglik"]) / phi - 2 * (cand["k"] - ref["k"])
    if gain < price:
        return gain, None, {}
    over_trend = 2 * (cand["loglik"] - ll_trend) / phi - 2 * (cand["k"] - 2)
    how = {"dispersion": round(phi, 3), "gain": round(gain, 2), "over_trend": round(over_trend, 2)}
    if over_trend < price:
        return gain, (f"a steady trend in time explains the events as well (its gain over the trend, {over_trend:.1f}, is under "
                      f"the price of {price:.1f}): it stands in for time"), how
    if why := _halves(w, cand, p, ref, p_ref):
        return gain, why, how
    why, shift = _shifted(w, cand, p, ref, p_ref)
    return gain, why, {**how, **({"shifted": shift} if shift else {})}


def choose(cands: list[dict], plain: dict, src: str | None, paths: dict[str, Path], events: list, unit_s: float,
           near: dict[str, int] | None = None) -> tuple[dict, dict]:
    """The flow's chosen form and the evidence for its driver (or for having none). ``cands``: every
    form scored on the whole window, with ``aic``; ``plain``: the constant or the proportion of its
    source, whichever scored better. A line in the flow's own source (``c + k × source``) is its own
    history, not a search, so it pays only ``AIC_MARGIN`` over the plain form; when it falls as its
    source grows it must also survive the same refutations: an outflow fitted as falling while its
    stock grew is usually the stock growing because the outflow fell, and run forward it runs
    away. One that rises with its source (a first-order drain) needs only the margin, as before."""
    drivers = [c for c in cands if c["inputs"] and c["inputs"] != [src]]
    m = len(drivers)
    price = AIC_MARGIN + 2 * math.log(max(1, m))
    ev = {"tried": m, "price": round(price, 2), "chosen": None}
    lines = [c for c in cands if c["inputs"] == [src] and c["form"] == "linear" and "rejected" not in c and math.isfinite(c["loglik"])]
    open_ = sorted((c for c in drivers if "rejected" not in c and math.isfinite(c["loglik"])), key=lambda c: c["aic"])
    if not paths or not (open_ or lines):
        return plain, ev
    live = next(iter(paths.values())).live
    w = Window(events, live, unit_s)
    trend = _fit(events, w.clock, "linear", w.t)
    ll_trend = loglik(events, w.clock, "linear", trend, w.t)
    p_plain = paths.get(plain["inputs"][0]) if plain["inputs"] else None
    own = plain
    for line in lines:
        if line["params"]["k"] >= 0:            # a drain that grows with what waits: the usual first-order outflow
            if line["aic"] <= plain["aic"] - AIC_MARGIN:
                own = line
            continue
        gain, why, how = _judge(w, line, paths[src], plain, p_plain, AIC_MARGIN, ll_trend)
        if why is None:
            continue
        if why:
            line["refuted"] = why
            ev["own_line"] = {"refuted": why, **how}
        else:
            own = line
            ev["own_line"] = {"chosen": True, **how}
    p_own = paths.get(own["inputs"][0]) if own["inputs"] else None
    survivors, refuted, priced = [], [], 0
    for cand in open_[:TESTED]:
        gain, why, how = _judge(w, cand, paths[cand["inputs"][0]], own, p_own, price, ll_trend)
        if why is None:
            continue
        priced += 1
        if why:
            refuted.append({"driver": cand["inputs"][0], "form": cand["form"], "why": why})
            cand["refuted"] = why
            continue
        survivors.append((gain, cand, how))
    ev["beat_price"] = priced
    if refuted:
        ev["refuted"] = refuted[:LISTED]
    if not survivors:
        if refuted:
            ev["why"] = ("rate not explained: no series it may read survived the refutations; it keeps its own form "
                         f"({own['form']})")
        return own, ev
    top = max(g for g, _, _ in survivors)
    close = [s for s in survivors if s[0] >= top - AIC_MARGIN]
    gain, best, how = max(close, key=lambda s: ((near or {}).get(s[1]["inputs"][0], 0), s[0]))
    ev.update({"chosen": best["inputs"][0], "form": best["form"], **how})
    if len(close) > 1:
        ev["tie_break"] = {"among": [s[1]["inputs"][0] for s in close],
                           "adjacency": {s[1]["inputs"][0]: (near or {}).get(s[1]["inputs"][0], 0) for s in close}}
    return best, ev
