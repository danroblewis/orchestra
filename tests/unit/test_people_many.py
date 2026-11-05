"""Hundreds of people as machines (the owner, 2026-11-04: "way too many people names sometimes, and
it's breaking various things"): the bridges relay each act as the person who did it
(``person.jira.<account>``) and announce each one. Every page's reading of the bus stays quick
with 600 of them; each person is still a machine (AGENTS.md rule 2)."""

import time

from people_seed import T0, people_events

from orchestra.web.hubs import Hubs
from orchestra.web.machines import machines_view


def best_of(f, n=3):
    out = []
    for _ in range(n):
        t = time.perf_counter()
        f()
        out.append(time.perf_counter() - t)
    return min(out)


def test_the_machines_view_with_600_people_is_quick_and_lists_every_one():
    evs = people_events(600)
    now = T0 + 7 * len(evs) + 60
    view = machines_view(evs, now=now)
    ids = {m["id"] for m in view["machines"]}
    assert len([i for i in ids if i.startswith("person.jira.")]) == 600 and {"triage", "notifier", "builder", "person.alice"} <= ids
    # was 0.32 s, most of it the hubs' pairs of machines and the listeners of each type (2026-11-04)
    assert best_of(lambda: machines_view(evs, now=now)) < 0.15


def test_a_machine_that_listens_for_nothing_is_never_a_hubs_member():
    pub = {"hub": {"a.go", "b.go"}, "a": {"a.done"}, "b": {"b.done"}, **{f"p{i}": {"x.y"} for i in range(800)}}
    sub = {"hub": {"a.done", "b.done", "x.y"}, "a": {"a.go"}, "b": {"b.go"}}
    t = time.perf_counter()
    h = Hubs(pub, sub)
    assert time.perf_counter() - t < 0.05
    assert h.record() == [{"hub": "hub", "members": ["a", "b"]}]
