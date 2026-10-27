"""The evidence a balance needs is counted for the balance, not for each counter (sd.balance): a
state work is sent back to, fed by three rejections from review and one from the merge and
emptied by four returns to work, changed eight times, each change explained exactly. Rare
counters that do not make the balance exact, or that between them counted too few events, are
still no balance."""

import random

from orchestra.sd.balance import MIN_EVENTS, balance
from orchestra.sd.series import Series

N = 400


def counter(name, at):
    out, total = [], 0
    for i in range(N):
        total += at.count(i)
        out.append(float(total))
    return Series(name, {"instrument": "board"}, [], out, True)


def level(ups, downs):
    out, v = [], 0
    for i in range(N):
        v += ups.count(i) - downs.count(i)
        out.append(float(v))
    return Series("rejected", {"instrument": "board"}, [], out, False)


FROM_REVIEW, FROM_MERGE, BACK_TO_WORK = [10, 40, 150], [90], [12, 45, 95, 152]


def busy(seed=1):
    rng = random.Random(seed)
    return counter("done_total", [i for i in range(N) if rng.random() < 0.1])        # a counter of its own, unrelated


def test_rare_counters_that_together_balance_a_level_exactly_carry_it():
    assert all(len(x) < MIN_EVENTS for x in (FROM_REVIEW, FROM_MERGE, BACK_TO_WORK))
    lv = level(FROM_REVIEW + FROM_MERGE, BACK_TO_WORK)
    cs = [counter("from_review", FROM_REVIEW), counter("from_merge", FROM_MERGE), counter("back_to_work", BACK_TO_WORK),
          counter("other_rare", [5, 70]), busy()]
    terms, r2, exact = balance(lv, cs)
    assert {(c.name, sign) for c, sign in terms} == {("from_review", 1), ("from_merge", 1), ("back_to_work", -1)}
    assert r2 == 1.0 and exact == 1.0


def test_rare_counters_short_of_exact_are_no_balance():
    late = [12, 45, 97, 152]                         # one return counted two steps after the level fell
    lv = level(FROM_REVIEW + FROM_MERGE, BACK_TO_WORK)
    terms, _, _ = balance(lv, [counter("from_review", FROM_REVIEW), counter("from_merge", FROM_MERGE), counter("back_to_work", late), busy()])
    assert terms == []


def test_rare_counters_with_too_few_events_between_them_are_no_balance():
    lv = level([10, 40], [12, 45])                   # four changes, each explained: still a coincidence as readily as a flow
    terms, _, _ = balance(lv, [counter("in", [10, 40]), counter("out", [12, 45]), busy()])
    assert terms == []
