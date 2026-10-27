"""Machines are associated with flows only as hypotheses with evidence, from their events on the bus
(``sd.attribute``): never from who wrote a counter, never by declaration, and never changing the
model's stocks, flows or equations."""

import random

from orchestra.sd.attribute import associate, match
from orchestra.sd.discover import discover
from orchestra.sd.series import Series

T0, MIN = 1_800_000_000.0, 60


def world(seed=1, minutes=90, with_events=True):
    """A queue an instrument measures: jobs arrive (no machine's events count them) and are done by
    two workers (worker/1, worker/2), each job done also acknowledged by a dispatcher.
    A third machine, a pager, publishes now and then, unrelated."""
    rng = random.Random(seed)
    inst = {"project": "p", "instrument": "queue_probe"}
    arrived = done = queue = 0
    by_worker = {"worker/1": 0, "worker/2": 0}
    acked = pages = 0
    pts = {"jobs_arrived_total": [], "jobs_done_total": [], "jobs_queued": []}
    ev = {k: [] for k in ("worker/1", "worker/2", "dispatcher", "pager")}
    for i in range(minutes * 6):                     # every 10 s
        t = T0 + 10 * i
        a = 1 if rng.random() < 0.5 else 0
        d = min(queue + a, 1 if rng.random() < 0.45 else 0)
        arrived, queue = arrived + a, queue + a - d
        if d:
            done += d
            w = rng.choice(sorted(by_worker))
            by_worker[w] += 1
            ev[w].append((t, by_worker[w]))
            acked += 1
            ev["dispatcher"].append((t, acked))
        if rng.random() < 0.05:
            pages += 1
            ev["pager"].append((t, pages))
        pts["jobs_arrived_total"].append((t, arrived))
        pts["jobs_done_total"].append((t, done))
        pts["jobs_queued"].append((t, queue))
    dump = [(n, dict(inst), p) for n, p in pts.items()]
    if with_events:
        types = {"worker/1": "job.done", "worker/2": "job.done", "dispatcher": "job.acked", "pager": "page.sent"}
        dump += [("orchestra_events_total", {"project": "p", "type": types[s], "source": s}, p) for s, p in ev.items() if p]
        dump.append(("orchestra_events_total", {"project": "p", "type": "orchestra.machine.started", "source": "worker/1"}, [(T0, 1.0)]))
    return dump, T0, T0 + minutes * MIN


def test_machines_whose_events_match_a_flow_are_hypotheses_with_evidence():
    dump, start, end = world()
    m = discover(dump, start=start, end=end, step=30)
    assert [s.id for s in m.stocks] == ["jobs_queued"]
    f = {x.id: x for x in m.flows}
    done = f["jobs_done_total"].evidence["machines"]
    hyps = {h["machine"]: h for h in done["hypotheses"]}
    worker = hyps["worker"]                                                         # its instances summed: one machine
    assert worker["origin"] == "inferred" and worker["by"] == "events on the bus" and worker["events"] == {"type": "job.done", "source": "worker"}
    assert worker["confidence"] >= 0.9 and worker["counts"]["flow"] == worker["counts"]["events"] and "equal in" in worker["why"]
    # the dispatcher acknowledges every job done too: a second hypothesis for one flow
    assert set(hyps) == {"worker", "dispatcher"} and hyps["dispatcher"]["events"]["type"] == "job.acked"
    mach = {mc.id: mc for mc in m.machines}
    assert mach["worker"].attributed == ["jobs_done_total"] and mach["dispatcher"].attributed == ["jobs_done_total"]
    assert {r.labels["type"] for r in mach["worker"].observed_by} == {"job.done"}
    assert "pager" not in mach and "queue_probe" not in mach                       # unrelated; and an instrument is no machine


def test_a_flow_no_machines_events_match_has_no_machine_associated_yet():
    dump, start, end = world()
    m = discover(dump, start=start, end=end, step=30)
    arrived = m.flow("jobs_arrived_total").evidence["machines"]
    assert arrived["hypotheses"] == [] and arrived["why"].startswith("no machine associated yet")


def test_the_hypotheses_change_no_stock_flow_or_equation():
    with_ev, start, end = world()
    without, _, _ = world(with_events=False)
    a = discover(with_ev, start=start, end=end, step=30)
    b = discover(without, start=start, end=end, step=30)
    shape = lambda m: sorted((f.id, f.src, f.dst, f.current().form, tuple(f.current().inputs), tuple(sorted(f.current().params.items())))
                             for f in m.flows if f.counter and f.counter.name != "orchestra_events_total")
    assert [s.id for s in a.stocks] == [s.id for s in b.stocks] and shape(a) == shape(b)
    assert b.machines == []


def test_a_counter_label_naming_a_machine_associates_nothing():
    dump, start, end = world(with_events=False)
    dump = [(n, {**lab, "machine": "worker"} if n == "jobs_done_total" else lab, p) for n, lab, p in dump]
    m = discover(dump, start=start, end=end, step=30)
    assert m.machines == [] and m.flow("jobs_done_total").evidence["machines"]["hypotheses"] == []


def counter(values, live=None):
    return Series("c", {}, [], [float(v) for v in values], True, live=live)


def test_match_needs_increments_that_agree_and_allows_a_step_of_lag():
    steps = [0, 1, 1, 3, 3, 4, 6, 6, 7, 9, 9, 10]
    assert match(counter(steps), counter(steps))["confidence"] == 1.0
    late = counter([0, *steps[:-1]])                                                   # a step behind
    assert match(counter(steps), late)["lag_steps"] == 1
    assert match(counter(steps), counter([0, 0, 0, 0, 0, 0, 0, 0, 5, 5, 5, 10])) is None
    assert associate(None, [])["why"].startswith("no machine associated yet")


def cumulative(n, at):
    """A counter over ``n`` steps that moves once at each step in ``at``."""
    out, total = [], 0
    for i in range(n):
        total += at.count(i)
        out.append(total)
    return counter(out)


MOVES = [12, 31, 32, 58, 77, 103, 140, 141, 166, 190]       # the live sample's shape: 10 transitions in a burst or two


def test_events_that_straddle_a_step_boundary_still_match_event_by_event():
    # 2 of the 10 events land a step before the counter moves, the rest on time: no single lag
    # makes the increments equal in 90% of the steps, but every event pairs within a step
    early = [m - 1 if k in (2, 6) else m for k, m in enumerate(MOVES)]
    found = match(cumulative(200, MOVES), cumulative(200, early))
    assert found is not None and found["test"] == "event by event" and found["confidence"] >= 0.9
    assert found["paired"] == {"flow": 1.0, "events": 1.0} and found["counts"] == {"flow": 10.0, "events": 10.0}
    assoc = associate(cumulative(200, MOVES), [Series("orchestra_events_total", {"type": "task.reported", "source": "worker/1"}, [],
                                                     cumulative(200, early).values, True)])
    assert [h["machine"] for h in assoc["hypotheses"]] == ["worker"] and "within a step" in assoc["hypotheses"][0]["why"]


def test_events_that_cover_every_increment_and_more_match_one_sided():
    # the worker accepts 10 tasks: 6 from OPEN, 4 back from REJECTED; the OPEN counter's every
    # increment has an accept beside it, and the other 4 feed another flow
    accepted = sorted(MOVES[:6] + [45, 120, 150, 180])
    found = match(cumulative(200, MOVES[:6]), cumulative(200, accepted))
    assert found["test"] == "covers every increment" and 0.5 < found["confidence"] <= 0.6     # 6 of 10, less chance


def test_an_unrelated_machine_does_not_match_event_by_event():
    rng = random.Random(3)
    for _ in range(20):
        other = sorted(rng.sample(range(200), 10))               # as many events, at other times
        assert match(cumulative(200, MOVES), cumulative(200, other)) is None
    near = [m + 2 for m in MOVES]                                # always two steps late: not within a step
    assert match(cumulative(200, MOVES), cumulative(200, near)) is None
    # a busy machine publishing in most steps would cover any counter by chance: never matched this way
    busy_counter = [i for i in range(200) if rng.random() < 0.4]
    busy = [i for i in range(200) if rng.random() < 0.6]
    assert match(cumulative(200, busy_counter), cumulative(200, busy)) is None
