"""A buffer between two counters fills and drains (sd.between.fills_and_drains): a level that only
rises is a tally, never the state items pass through, in sd.between (a passage's measured state)
and in sd.restate.measured_between (a buffer that stops a join) alike. The numbers are UC-3's
re-score (2026-11-01): the gate's nine landings, the test reports read (5 to 10, never less) and
MERGING, above zero at one raw point."""

from orchestra.sd.between import fills_and_drains, state_level
from orchestra.sd.restate import measured_between
from orchestra.sd.series import Series

START, END, STEP = 1793533402.714873, 1793535175.0, 5.0
TO_MERGING = [1793533495.358235, 1793533681.848618, 1793533782.590768, 1793533898.439497, 1793534079.798326,
              1793534185.605612, 1793534281.376765, 1793534382.140428, 1793534487.900915]
LANDED = [*TO_MERGING[:2], 1793533787.6433039, *TO_MERGING[3:]]
READ_RISES = [1793533495.3585742, 1793533681.848894, 1793533787.643656, 1793533898.439709, 1793534079.798545]


def _grid(points: list[tuple[float, float]], first: float) -> list[float]:
    out, i, cur = [], 0, first
    for k in range(int((END - START) // STEP) + 1):
        t = START + k * STEP
        while i < len(points) and points[i][0] <= t:
            cur = points[i][1]
            i += 1
        out.append(cur)
    return out


def _counter(name: str, at: list[float]) -> Series:
    pts = [(START - STEP, 0.0)] + [(t, float(i + 1)) for i, t in enumerate(at)]
    return Series(name, {"instrument": "tasks.tickets"}, pts, _grid(pts, 0.0), True)


def _level(name: str, changes: list[tuple[float, float]], first: float, every: float = 5.0) -> Series:
    """A level written every ``every`` seconds and at each change."""
    writes = sorted({START - STEP + k * every for k in range(int((END - START) // every) + 2)} | {t for t, _ in changes})
    pts, v, i = [], first, 0
    for t in writes:
        while i < len(changes) and changes[i][0] <= t:
            v = changes[i][1]
            i += 1
        pts.append((t, v))
    return Series(name, {"instrument": "tasks.tests"}, pts, _grid(pts, first), False)


def _read_tally() -> Series:
    return _level("test_report_files", [(t, 6.0 + i) for i, t in enumerate(READ_RISES)], 5.0)


def _merging() -> Series:
    return _level("tasks_tickets", [(TO_MERGING[2], 1.0), (LANDED[2] + 0.001, 0.0)], 0.0)


def test_a_level_fills_and_drains_only_when_it_rises_and_falls_by_a_whole_item():
    assert fills_and_drains([0, 1, 0, -1])
    assert not fills_and_drains([1, 1, 0, 1, 1])           # a tally: 5 to 10, never less
    assert not fills_and_drains([0, -1, -2])
    assert not fills_and_drains([0.1, -0.1, 0.1])          # a duration's moves: no items


def test_a_tally_that_never_falls_is_never_the_state_between_two_counters():
    # UC-3: the reports read rose at five of the nine landings and never fell; it was taken for the
    # buffer between APPROVED->MERGING and landed, outranking MERGING (one rise), and the path from
    # IN_REVIEW to DONE broke through outside
    ins, outs = [_counter("to_merging_total", TO_MERGING)], [_counter("gate_runs_total", LANDED)]
    where = {"start": START, "end": END, "step": STEP, "writer_of": lambda s: s.labels.get("instrument")}
    assert state_level([_read_tally()], ins, outs, **where) is None
    got = state_level([_read_tally(), _merging()], ins, outs, **where)
    assert got is not None and got[0].name == "tasks_tickets"


def test_measured_between_takes_no_level_that_never_falls_for_a_buffer():
    # the same predicate stops a join: a level that rose where one counter counted and the other
    # had not yet, and never fell, would read as exactly a - b in every step
    a = _counter("in_total", TO_MERGING)
    b = _counter("out_total", TO_MERGING[:-1])
    tally = _level("tally", [(TO_MERGING[-1], 1.0)], 0.0)
    assert not measured_between([tally], a, b)
    buffer = _level("buffer", [(TO_MERGING[-1], 1.0), (END - 20, 0.0)], 0.0)
    b2 = _counter("out_total", [*TO_MERGING[:-1], END - 20])
    assert measured_between([buffer], a, b2)


def test_with_the_tally_the_only_level_the_passage_state_is_the_hidden_one_its_counters_imply():
    from orchestra.sd.passing import passages
    ins, outs = _counter("to_merging_total", TO_MERGING), _counter("gate_runs_total", LANDED)
    review = Series("tasks_tickets", {"instrument": "tasks.tickets", "state": "IN_REVIEW"}, [], [0.0] * len(ins.values), False)
    done = Series("tasks_tickets", {"instrument": "tasks.tickets", "state": "DONE"}, [], [0.0] * len(ins.values), False)
    found = [(review, [(ins, -1)], 1.0, 1.0), (done, [(outs, 1)], 1.0, 1.0)]
    where = {"start": START, "end": END, "step": STEP, "writer_of": lambda s: s.labels.get("instrument")}
    (p,) = passages(found, [ins, outs], [_read_tally()], **where)
    assert not p.measured and p.level.name == "after_to_merging_total" and p.evidence().get("hidden")
    (p,) = passages(found, [ins, outs], [_read_tally(), _merging()], **where)
    assert p.measured and p.level.name == "tasks_tickets"
