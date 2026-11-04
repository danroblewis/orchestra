"""Which labels the whole store is split by: each label's rank across every family under the
source's ``match``, so the store's common groupings win over one family's oddity.

A label that **groups most families with few stable values** (the owner's ``container_name``,
``service_name``, ``method``, ``status``) ranks near 1; one that **appears on few families or has
many values** (``edge_service``, ``error``) near 0. The rank is

    share × few × steady

``share`` the families it is a grouping label of, of every family read as a level or a flow;
``few`` 1 up to ``rank.APART_VALUES`` values (its most, over those families), less beyond, as
``APART_VALUES / values``; ``steady`` 1 when it never churns (``checks.CHURN``), else a half. A
label the collection adds (``job``, ``instance``: ``rank.TARGET_LABELS``) says who reported a
series, not what it is of: it has no rank. Each rank says why ("groups 41 of 44 families, 7 stable
values").

A candidate split by grouping labels scores ``COMMON`` × the least of their ranks (``rank.score``:
the part ``common``); a total, none. Ranking is all it changes: what is generated and probed is
``views.py``'s and ``explore.py``'s."""

from __future__ import annotations

from .checks import CHURN
from .family import UNREAD, Family

COMMON = 1.0                 # what a split by the store's commonest grouping adds to a candidate's score, at most


def label_ranks(families: list[Family], few: int, target: set[str] | frozenset[str]) -> dict[str, dict]:
    """Each canonical label's rank across ``families`` (``few``: values a split may have at full
    rank; ``target``: the labels the collection adds, which are not ranked)."""
    read = [f for f in families if f.kind not in UNREAD]
    seen: dict[str, dict] = {}
    for f in read:
        for c, i in f.labels.items():
            if i.real in target or c in target:
                continue
            s = seen.setdefault(c, {"carried": 0, "groups": 0, "values": 0, "churn": 0.0})
            s["carried"] += 1
            if i.role == "grouping":
                s["groups"] += 1
                s["values"] = max(s["values"], int(i.cardinality))
                s["churn"] = max(s["churn"], float(i.churn))
    n = max(1, len(read))
    out: dict[str, dict] = {}
    for c, s in sorted(seen.items()):
        if not s["groups"]:
            continue
        share = s["groups"] / n
        many = min(1.0, few / s["values"]) if s["values"] else 0.0
        steady = 1.0 if s["churn"] < CHURN else 0.5
        stable = "stable" if steady == 1.0 else "churning"
        why = (f"groups {s['groups']} of {n} famil{'y' if n == 1 else 'ies'}, {s['values']} {stable} value{'s' if s['values'] != 1 else ''}"
               + (f" (on {s['carried']}, a grouping on {s['groups']})" if s["carried"] != s["groups"] else ""))
        out[c] = {"rank": round(share * many * steady, 3), "groups": s["groups"], "families": n, "values": s["values"],
                  "stable": steady == 1.0, "why": why}
    return out


def common(group: list[str], labels_info: dict, ranks: dict[str, dict] | None) -> tuple[float, str]:
    """What a candidate grouped by ``group`` takes from the store's ranks: the least rank of its
    grouping labels (a split is as common as its oddest label), and why; a total takes none."""
    split = [c for c in group if (labels_info.get(c) or {}).get("role") == "grouping"]
    if not split or not ranks:
        return 0.0, ""
    worst = min(split, key=lambda c: (ranks.get(c) or {}).get("rank", 0.0))
    r = (ranks.get(worst) or {}).get("rank", 0.0)
    why = (ranks.get(worst) or {}).get("why", "not ranked across the store")
    return COMMON * r, f"{worst}: {why}"
