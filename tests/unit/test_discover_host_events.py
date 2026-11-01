"""Two ways a repository's commits became a stock of five counters in the UC-3 re-score (core
1f01a878): 24 commits in ten changes, as 9 landings + 12 review turns + 5 supervisor turns − 3 of
the host's ``orchestra.machine.quiet`` + 1 ``orchestra.model.changed``. Orchestra's own events are
never a flow, nor is the host a machine (AGENTS.md rules 2 and 7). And a level with few changes
cannot test many counters by their squared error: beyond what it can test, a counter that makes no
unit exact and that no unit pins on its own goes; but an exact balance is never reduced."""

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.balance import allowed, balance
from orchestra.sd.discover import discover
from orchestra.sd.series import Series

T0 = 1_800_000_000.0
UNITS = 60


def _balance(rows, signs, at, extra=None):
    """The balance of a level that changes by ``rows`` (each counter's events, signed by ``signs``)
    and by ``extra`` (what no counter counted) in the units ``at``, and nothing else."""
    cols, lv = [[0.0] for _ in signs], [20.0]
    by, more = dict(zip(at, rows)), dict(zip(at, extra or ()))
    for u in range(UNITS):
        row = by.get(u, (0,) * len(signs))
        lv.append(lv[-1] + sum(s * x for s, x in zip(signs, row)) + more.get(u, 0))
        for c, x in zip(cols, row):
            c.append(c[-1] + x)
    level = Series("level", {"instrument": "y"}, [], lv, False)
    terms, r2, exact = balance(level, [Series(f"c{i}_total", {"instrument": "x"}, [], c, True) for i, c in enumerate(cols)])
    return level, {(c.name, sign) for c, sign in terms}, r2, exact


def test_beyond_what_a_few_changes_can_test_a_counter_that_makes_nothing_exact_goes():
    # the repository gains a commit with each landing (c0) and loses them in reverts (c1), six
    # changes in all; supervisor turns (c2, 5) come only with landings, and the level gained two
    # more in three of those units: with them the squared error falls by more than a counter costs,
    # but every unit they move in is then one off, where without them two were exact
    level, terms, r2, exact = _balance([(2, 0, 1), (1, 0, 1), (3, 2, 1), (1, 0, 1), (2, 0, 1), (0, 4, 0)], (1, -1, 0),
                                       [5, 13, 21, 30, 40, 50], extra=[2, 2, 2, 0, 0, 0])
    assert allowed(level.deltas) == 2
    assert terms == {("c0_total", 1), ("c1_total", -1)}, (terms, r2, exact)


def test_an_exact_balance_of_counters_that_always_move_together_is_never_reduced():
    # a quiet shelf baked, sold, discarded and eaten from in the same units (eight changes,
    # allowed three): no counter moves alone, and all four are needed for it to be exact
    _, terms, r2, exact = _balance([(6, 2, 1, 1), (4, 1, 1, 0), (5, 2, 0, 1), (3, 1, 1, 0), (6, 3, 1, 1), (4, 2, 1, 0),
                                    (5, 1, 1, 1), (6, 2, 2, 1)], (1, -1, -1, -1), [3, 10, 17, 24, 31, 38, 45, 52])
    assert terms == {("c0_total", 1), ("c1_total", -1), ("c2_total", -1), ("c3_total", -1)} and exact == 1.0, (terms, r2)


def test_an_outflow_that_only_comes_with_another_stays_in_an_exact_balance():
    # six changes, allowed two: the second outflow never fires without the first, yet with
    # coefficients of one it is identified exactly
    _, terms, r2, exact = _balance([(3, 1, 1), (2, 1, 0), (2, 0, 0), (0, 1, 1), (0, 2, 1), (1, 1, 0)], (1, -1, -1),
                                   [5, 13, 21, 30, 40, 50])
    assert terms == {("c0_total", 1), ("c1_total", -1), ("c2_total", -1)} and exact == 1.0, (terms, r2)


def test_orchestras_own_events_are_never_a_balance_and_the_host_is_never_a_machine(tmp_path):
    # the repository gains a commit with each landing (a ticket counter) and, as it happens, loses
    # one in the steps the host said a machine was quiet, gains one when it said the model changed;
    # and a worker announces itself (orchestra.machine.started) six times over the hour
    lab = {"project": "p"}
    landed = [T0 + 60 + 240 * i for i in range(12)]
    quiet = [T0 + 150 + 600 * i for i in range(6)]
    changed = [T0 + 1000, T0 + 2900]
    started = [T0 + 400 + 500 * i for i in range(6)]
    pts, level = [], 13
    for t in range(int(T0), int(T0) + 3600, 5):
        level += sum(1 for x in landed if t - 5 < x <= t) - sum(1 for x in quiet if t - 5 < x <= t) \
            + sum(1 for x in changed if t - 5 < x <= t)
        pts.append(Point("repo_commits", level, t, {**lab, "instrument": "repo_stats"}))
    for i, x in enumerate(landed, 1):
        pts.append(Point("tasks_gate_runs_total", i, x, {**lab, "instrument": "tasks.tickets", "status": "landed"}))
    for typ, src, times in (("orchestra.machine.quiet", "orchestra-host", quiet), ("orchestra.model.changed", "orchestra-host", changed),
                            ("orchestra.machine.started", "worker/1", started)):
        pts += [Point("orchestra_events_total", i, x, {**lab, "type": typ, "source": src}) for i, x in enumerate(times, 1)]
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(sorted(pts, key=lambda p: p.ts))
    m = discover(store.dump("", lab), start=T0, end=T0 + 3600, step=30)
    why = m.discovery["left_out"]
    for key in ('orchestra_events_total{source="orchestra-host",type="orchestra.machine.quiet"}',
                'orchestra_events_total{source="orchestra-host",type="orchestra.model.changed"}',
                'orchestra_events_total{source="worker",type="orchestra.machine.started"}'):
        assert why.get(key, "").startswith("Orchestra's own events"), (key, why)
    used = {b["series"] for s in m.stocks for b in s.evidence.get("balance", [])}
    assert not any("orchestra_events_total" in k for k in used), used
    assert all(f.series is None or f.series.name != "orchestra_events_total" for f in m.flows)
    assert "orchestra-host" not in {mc.id for mc in m.machines}
