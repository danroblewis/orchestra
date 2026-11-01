"""Two ways a repository's commits became a stock of five counters in the UC-3 re-score (core
1f01a878): 24 commits in ten changes, as 9 landings + 12 review turns + 5 supervisor turns − 3 of
the host's ``orchestra.machine.quiet`` + 1 ``orchestra.model.changed``. Orchestra's own events are
never a flow, nor is the host a machine (AGENTS.md rules 2 and 7); and a level with few changes
cannot test many counters, so beyond what it can test each counter needs a unit of its own."""

from itertools import pairwise

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.balance import balance
from orchestra.sd.discover import discover
from orchestra.sd.series import Series

T0 = 1_800_000_000.0

# the run's ten changes of repo_commits, one row per unit it changed in:
# (landed, reviewer turns, supervisor turns, host quiet, host model changed)
CHANGES = [(1, 1, 0, 0, 0), (1, 2, 0, 0, 0), (1, 1, 1, 0, 0), (1, 1, 0, 1, 0), (1, 1, 1, 0, 0),
           (1, 1, 0, 0, 0), (1, 1, 1, 1, 0), (1, 1, 1, 0, 1), (1, 1, 1, 1, 0), (0, 2, 0, 0, 0)]
SIGNS = (1, 1, 1, -1, 1)
NAMES = ("landed", "reviewer_turns", "supervisor_turns", "host_quiet", "host_model_changed")
UNITS = 58          # the run's two-minute stretches of the half hour


def test_a_level_with_ten_changes_is_not_balanced_by_five_counters_that_only_add_up_together():
    at = {u: row for u, row in zip(range(3, UNITS, 5), CHANGES)}
    cols = {k: [] for k in NAMES}
    lv, v = [], 13.0
    for u in range(UNITS):
        row = at.get(u, (0,) * 5)
        v += sum(s * x for s, x in zip(SIGNS, row))
        lv.append(v)
        for k, x in zip(NAMES, row):
            cols[k].append((cols[k][-1] if cols[k] else 0.0) + x)
    assert lv[-1] - lv[0] == 24 and sum(1 for a, b in pairwise(lv) if a != b) == 10
    counters = [Series(f"{k}_total", {"instrument": "x"}, [], cols[k], True) for k in NAMES]
    terms, r2, exact = balance(Series("repo_commits", {"instrument": "repo_stats"}, [], lv, False), counters)
    chosen = {c.name for c, _ in terms}
    # the five add up exactly, but supervisor turns, landings and the model change never moved but
    # with another inflow: nothing tells them apart from a coincidence of sums
    assert len(terms) <= 4 and exact < 1.0, (chosen, r2, exact)
    assert not chosen & {"supervisor_turns_total", "host_model_changed_total"}, chosen


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
