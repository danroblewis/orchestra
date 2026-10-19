"""Latest results whose case or variant no longer exists (a case file removed or renamed, a draw count
lowered, a variant dropped: e.g. 052-sweep-run-length#5's old counts-run): pages that read
store.latest() would count them. `sdlab-ladder prune --dry-run` lists them; `sdlab-ladder prune`
archives them (store.archive: latest = 0 and a row in `archived`; nothing is deleted).

A case that exists but does not load now (a file being edited) is reported as unreadable and left
alone. A strategy that is no longer in the catalogue is reported, not archived.
"""

from __future__ import annotations

from collections import Counter

from . import cases as casemod
from . import catalog, store


def orphans() -> dict:
    """{"gone": [(id, case, variant, strategy, why)], "unreadable": [case ids], "strategy_gone": Counter}."""
    variants: dict[str, set | None] = {}
    unreadable = []
    gone = []
    strategies = set(catalog.names())
    strategy_gone: Counter = Counter()
    for rid, cid, var, strat in store.latest_keys():
        if cid not in variants:
            if not casemod.known(cid):
                variants[cid] = None
            else:
                try:
                    variants[cid] = {v["name"] for v in casemod.load(cid)["variants"]}
                except Exception:                                       # noqa: BLE001
                    variants[cid] = set()
                    unreadable.append(cid)
        have = variants[cid]
        if have is None:
            gone.append((rid, cid, var, strat, "case gone"))
        elif cid not in unreadable and var not in have:
            gone.append((rid, cid, var, strat, "variant gone"))
        elif strat not in strategies:
            strategy_gone[strat] += 1
    return {"gone": gone, "unreadable": unreadable, "strategy_gone": strategy_gone}


def main(a) -> int:
    o = orphans()
    gone = o["gone"]
    by = Counter((cid, var, why) for _, cid, var, _, why in gone)
    for (cid, var, why), n in sorted(by.items()):
        print(f"{cid} {var}: {why}, {n} result{'s' * (n != 1)}")
    kinds = Counter(why for *_, why in gone)
    print(f"{len(gone)} latest results to archive ({', '.join(f'{k}: {n}' for k, n in sorted(kinds.items())) or 'none'}), "
          f"over {len({c for c, _, _ in by})} cases and {len(by)} case-variants")
    if o["unreadable"]:
        print(f"left alone, case does not load now: {', '.join(o['unreadable'])}")
    if o["strategy_gone"]:
        print("not archived, strategy no longer in the catalogue: " + ", ".join(f"{s} ({n})" for s, n in sorted(o["strategy_gone"].items())))
    if a.dry_run:
        print("dry run: nothing archived")
        return 0
    n = store.archive([g[0] for g in gone], {g[0]: g[4] for g in gone})
    print(f"archived {n} results (latest = 0; listed in the archived table)")
    return 0
