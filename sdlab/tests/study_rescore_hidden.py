"""Credit a strategy's own hidden stock, and a fitted schedule standing in for hidden state is "fits" (2026-10-21,
the user; sdlab/ladder/hidden_match.py, score._schedule_stand_ins): re-score offline (nothing written to the store)
the stored results of the numbered cases whose truth has a stock the data do not show, with whichever scorer is
importable, then compare two outputs as study_rescore_algebra.py does (flips by set and strategy, with examples).

Only those cases can change: matching needs a true hidden stock, the schedule rule a true flow reading one, and
the boundary exemption a matched one; every other case is scored by exactly the old code path.

    git archive HEAD sdlab | tar -x -C <old>                                  # the scorer before the change
    PYTHONPATH=<old>:tests uv run python tests/study_rescore_hidden.py score old.json --jobs 8
    PYTHONPATH=tests uv run python tests/study_rescore_hidden.py score new.json --jobs 8
    PYTHONPATH=tests uv run python tests/study_rescore_hidden.py compare old.json new.json
"""

from __future__ import annotations

import sys

import study_rescore_algebra as base


def hidden_cases() -> set[str]:
    from sdlab.ladder import cases as casemod, data
    out = set()
    for cid in casemod.case_ids():
        if not cid[:1].isdigit():
            continue
        try:
            c = casemod.load(cid)
        except Exception:                                      # noqa: BLE001
            continue
        if c.get("real"):
            continue
        if any(s.get("measured") is False or s.get("hidden") for s in (c.get("model") or {}).get("stocks") or []):
            out.add(cid)
            continue
        try:                                                   # a delay or smoothing function compiles to hidden stocks
            d = data.load(c, (c.get("variants") or [{}])[0].get("name") or "none-short")
        except Exception:                                      # noqa: BLE001
            continue
        if set(d.get("all_levels") or {}) - set(d["levels"]) - set(d.get("inputs") or {}):
            out.add(cid)
    return out


_rows = base._rows


def _hidden_rows(only):
    keep = hidden_cases()
    return [r for r in _rows(only) if r[1] in keep]


if __name__ == "__main__":
    base._rows = _hidden_rows
    if sys.argv[1] == "cases":
        print(sorted(hidden_cases()))
    elif sys.argv[1] == "score":
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 1
        base.score_all(sys.argv[2], jobs)
    elif sys.argv[1] == "compare":
        base.compare(sys.argv[2], sys.argv[3], int(sys.argv[sys.argv.index("--examples") + 1]) if "--examples" in sys.argv else 3)
