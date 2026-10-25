"""Rows read as links: every number in a stock's row is a flow of its own, into or out of that
stock, and nothing is taken from another stock, except through an unmeasured stage (below).

Requests that cause requests downstream, CPU that follows load, replicas that follow CPU: in a
system of services, most of what one stock's level does to another is a link (the downstream
stock gains, the upstream one loses nothing), and the main line's conservation would drain the
caller by what its callees receive. The candidates read this way stand beside the main line's.

A row's positive number k on a delayed copy of A (delay d; hidden.py: z(t) = (1 - d) z(t-1) +
d A(t-1)) is an unmeasured stage H in front of the row's stock B, fed k x A a step and drained into
B at d x H (one stage per receiving stock and delay, fed by every source the row chose): a load
balancer's queue in front of a service, pods restarting before they are ready. It takes from A
(a move A -> H) as far as A's own drain in its row allows and A is of B's unit, and is a link
beyond. H's level is sum k / d x z: its estimate, from the data alone.
"""

from __future__ import annotations

from ...flows import r4


def read_links(rows: list[dict], ids: list[str], means: dict, inputs: set, copies: dict | None = None,
               unit: dict | None = None) -> tuple[list[dict], dict]:
    """rows: {"id", "coef": {column: number}, "inflow": pieces}; columns are levels, copies
    ({name: (source, delay)}) or inputs. Returns (flows, {hidden stock: [(column, "copy" | "lag1",
    scale)]}): the stage's level is the sum of scale x the copy, or x the column a step before."""
    copies, unit = copies or {}, unit or {}
    flows: list[dict] = []
    stages: dict[str, list] = {}

    def add(src, dst, rate, per, **extra):
        flows.append({"from": src, "to": dst, "ratio": 1, "rate": rate, "rates": [rate], "perStep": per, "nearly": [], "bothWays": False, **extra})

    def lin(j, k):
        return {"form": "linear", "c": 0, "terms": [{"stock": j, "k": r4(k)}]}

    coef = {r["id"]: r["coef"] for r in rows}
    left = {s: max(0.0, -(coef.get(s, {}).get(s) or 0.0)) for s in ids}   # each stock's own drain, still to place
    fed: dict[tuple, list] = {}
    for r in rows:                                   # the stages: by receiving stock and delay
        for j, k in r["coef"].items():
            if j in copies and k > 0:
                fed.setdefault((r["id"], copies[j][1]), []).append((j, k))
    absorbed = set()
    for (b, d), srcs in sorted(fed.items(), key=lambda x: -x[0][1]):
        h = f"{b}~stage{d:g}"
        feed = {copies[j][0]: k for j, k in srcs}
        parts = [(j, "copy", k / d) for j, k in srcs]
        if d == 1.0 and b not in absorbed:
            # a one-step stage takes the row's other terms too (a step later: what a level does to
            # b this step, it does through the stage next step), so that a stock that turns over
            # every step never has to lose more than it holds: its inflows carry the signs
            absorbed.add(b)
            for j, k in coef[b].items():
                if k and j not in copies and j != b:
                    feed[j] = feed.get(j, 0.0) + k
                    parts.append((j, "lag1", k))
        room = sum(k * means.get(j, 0.0) for j, k in feed.items())   # the stage's mean feed
        for j, k in srcs:
            a = copies[j][0]
            if unit.get(a) != unit.get(b) or means.get(a, 0.0) <= 0:
                continue
            move = max(0.0, min(k, left.get(a, 0.0), room / means[a]))
            if move > 1e-9:
                add(a, h, {"form": "proportional", "stock": a, "k": r4(move)}, move * means[a], hidden=h)
                left[a] -= move
                feed[a] -= move
                room -= move * means[a]
        feed = {j: k for j, k in feed.items() if abs(k) > 1e-9}
        if feed:
            add(None, h, {"form": "linear", "c": 0, "terms": [{"stock": j, "k": r4(k)} for j, k in feed.items()]},
                sum(k * means.get(j, 0.0) for j, k in feed.items()), hidden=h, **({"driver": next(iter(feed))} if len(feed) == 1 else {"drivers": list(feed)}))
        stages[h] = parts
        add(h, b, {"form": "proportional", "stock": h, "k": r4(d)}, sum(k * means.get(copies[j][0], 0.0) for j, k in srcs), hidden=h)
    for r in rows:
        s = r["id"]
        if r.get("hinge"):                          # two floored rates of the row's columns: one in, one out
            for (c, ks), (src, dst) in zip(r["hinge"], ((None, s), (s, None))):
                rate = {"form": "linear", "c": r4(c), "terms": [{"stock": j, "k": r4(k)} for j, k in ks.items() if k]}
                add(src, dst, rate, 0.0, floored=True, **({"drivers": list(ks)} if len(ks) > 1 else {"driver": next(iter(ks))}))
            continue
        k_self = r["coef"].get(s) or 0.0
        if k_self < 0 and left[s] > 1e-9:
            add(s, None, {"form": "proportional", "stock": s, "k": r4(left[s])}, left[s] * means.get(s, 0.0))
        # what the other levels and the inputs do to s, as one flow (its terms' signs kept, the rate
        # floored at 0 as every rate is): into s if it adds on average, else out of s. Split into a
        # flow per term, a negative term would be an outflow on top of the stock's own drain, and a
        # stock that turns over every step cannot lose more than it holds in one step.
        terms = {j: k for j, k in r["coef"].items() if k and j not in copies and (j != s or k > 0) and not (s in absorbed and j != s)}
        if terms:
            net = sum(k * means.get(j, 0.0) for j, k in terms.items())
            sign = 1.0 if net >= 0 else -1.0
            rate = {"form": "linear", "c": 0, "terms": [{"stock": j, "k": r4(sign * k)} for j, k in terms.items()]}
            ins = [j for j in terms if j in inputs]
            extra = {"input": ins[0]} if len(terms) == 1 and ins else {"driver": next(iter(terms))} if len(terms) == 1 else {"drivers": list(terms)}
            if sign > 0:
                add(None, s, rate, abs(net), **extra)
            else:
                add(s, None, rate, abs(net), **extra)
        for a, m, k, pts in r.get("ratios") or []:          # k x a / m: a flow k x a with an effect 1 / m
            rate = {"form": "proportional", "stock": a, "k": r4(abs(k))} if a not in inputs else {"form": "linear", "c": 0, "terms": [{"stock": a, "k": r4(abs(k))}]}
            eff = [{"stock": m, "shape": "table", "points": pts}]
            if k > 0:
                add(None, s, rate, 0.0, effects=eff, driver=a)
            else:
                add(s, None, rate, 0.0, effects=eff, driver=a)
        pieces = r["inflow"]
        if pieces:
            W = sum(g["to"] - g["from"] + 1 for g in pieces)
            mean = sum(g["value"] * (g["to"] - g["from"] + 1) for g in pieces) / max(1, W)
            if abs(mean) > 1e-9:
                rate = {"form": "constant", "value": r4(abs(mean))}
                if mean > 0:
                    add(None, s, rate, abs(mean), inflow=pieces, changes=len(pieces) - 1)
                else:
                    add(s, None, rate, abs(mean), inflow=[{**g, "value": -g["value"]} for g in pieces], changes=len(pieces) - 1)
    return flows, stages
