"""A passage's measured state must read, at its own writes, what its counters imply (sd.between),
and its trust is judged against the items moved (sd.stocktrust.passage). The numbers are the owner
proxy's (R1, the modeller, 2026-11-01): on delivery_sail, the triage.waiting pile rose twice, both
at sail.waiting's in-events, while the ins moved 25 items, and was bound as sail.waiting ("matched
1.0", trust 0.71); on the core demo, REJECTED rose once in 31 moves of IN_REVIEW->APPROVED->DONE.
A true state sampled coarsely (UC-2's READY_FOR_REVIEW, 6 rises in 15 moves) still is one."""

from __future__ import annotations

from types import SimpleNamespace

from orchestra.sd import stocktrust
from orchestra.sd.between import at_events, state_level
from orchestra.sd.series import Series

T0, STEP = 1_800_000_000.0, 5.0
END = T0 + 3600


def _counter(name: str, at: list[float], **labels) -> Series:
    return Series(name, {"instrument": "workflows.piles", **labels}, [(T0 - STEP, 0.0)] + [(t, float(i + 1)) for i, t in enumerate(at)], [], True)


def _level(name: str, changes: list[tuple[float, float]], every: float = 10.0, at_changes: bool = True) -> Series:
    """A level written every ``every`` seconds, and at each change when ``at_changes``."""
    writes = sorted({T0 - STEP + k * every for k in range(int(3600 // every) + 2)} | ({t for t, _ in changes} if at_changes else set()))
    pts, v, i = [], 0.0, 0
    for t in writes:
        while i < len(changes) and changes[i][0] <= t:
            v = changes[i][1]
            i += 1
        pts.append((t, v))
    return Series(name, {"instrument": "workflows.piles", "pile": name}, pts, [], False)


IN = [T0 + 60.3 + 137.37 * k for k in range(25)]               # 25 items moved into sail.waiting
OUT = [t + 3.0 for t in IN]                                 # ... each out to sail_check within a step
WHERE = {"start": T0, "end": END, "step": STEP, "writer_of": lambda s: s.labels.get("instrument")}


def test_a_level_that_rose_at_two_of_25_moves_is_not_the_state_between_them():
    ins, outs = [_counter("moves_total", IN, to="sail.waiting")], [_counter("moves_total", OUT, to="sail_check.waiting")]
    triage = _level("triage.waiting", [(IN[3], 1.0), (OUT[3], 0.0), (IN[17], 1.0), (OUT[17], 0.0)])
    assert at_events(triage, ins, outs, T0, END, STEP) is None
    assert state_level([triage], ins, outs, **WHERE) is None
    sail = _level("sail.waiting", sorted([(t, 1.0) for t in IN] + [(t, 0.0) for t in OUT]))
    got = state_level([triage, sail], ins, outs, **WHERE)
    assert got is not None and got[0].labels["pile"] == "sail.waiting" and got[1] == [25, 25, 25, 25] and got[2] == [25, 25, 25, 25]


def test_rejected_rising_once_in_31_moves_is_not_the_state_between_approved_and_done():
    at = [T0 + 50 + 110 * k for k in range(31)]
    at = [t + 0.37 * k for k, t in enumerate(at)]                    # approved, then merged a few seconds later
    ins, outs = [_counter("approved_total", at)], [_counter("done_total", [t + 4.0 for t in at])]
    rejected = _level("REJECTED", [(at[9], 1.0), (at[9] + 4.0, 0.0)], every=12.0)
    assert at_events(rejected, ins, outs, T0, END, STEP) is None


def test_a_true_state_sampled_coarsely_is_still_the_state():
    # written every second and never at its changes: it sees each item for the three seconds it stays
    ins, outs = [_counter("moves_total", IN, to="sail.waiting")], [_counter("moves_total", OUT, to="sail_check.waiting")]
    sail = _level("sail.waiting", sorted([(t, 1.0) for t in IN] + [(t, 0.0) for t in OUT]), every=1.0, at_changes=False)
    assert at_events(sail, ins, outs, T0, END, STEP) is not None
    # items in for half a second, the level written every second: it misses most of them, and so
    # do the counters' totals at its writes; the ones it sees are still matched
    quick = [t + 0.5 for t in IN]
    sparse = _level("sail.waiting", sorted([(t, 1.0) for t in IN] + [(t, 0.0) for t in quick]), every=1.0, at_changes=False)
    got = at_events(sparse, ins, [_counter("moves_total", quick, to="sail_check.waiting")], T0, END, STEP)
    assert got is not None and got[0][1] < 25 and got[0][3] == 25


def test_passage_trust_is_matched_against_the_items_moved():
    p = SimpleNamespace(rises=[2, 2, 2, 25], falls=[2, 2, 2, 25], out_of_step=0, moved=25)
    t = stocktrust.passage(p)
    assert t["components"]["matched"] == 0.08 and t["matched_of_own"] == 1.0 and t["matched_of_moves"] == 0.08
    assert t["matched_counts"] == "4 of 50 moves matched" and t["level"] == "very low"
    # written every 30 s, two items at a write: every move accounted for
    pairs = stocktrust.passage(SimpleNamespace(rises=[39, 39, 78, 78], falls=[39, 39, 78, 78], out_of_step=0, moved=200))
    assert pairs["components"]["matched"] == 1.0 and pairs["matched_counts"] == "156 of 156 moves matched"
    old = stocktrust.passage(SimpleNamespace(rises=[2, 2], falls=[2, 2], out_of_step=0, moved=25))   # a record before the items were kept
    assert old["components"]["matched"] == 1.0 and old["matched_counts"] == "4 of 4 rises and falls matched"
