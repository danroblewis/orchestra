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


def _counter(name, labels, at, n):
    vals, c = [], 0.0
    for i in range(n):
        c += at.count(i)
        vals.append(c)
    from orchestra.sd.series import Series
    return Series(name, labels, [], vals, True)


def attribution_world(people=600, steps=2880, seed=3):
    """A day at 30 s steps: each person resolves a few issues (``jira.issue.resolved``) and comments
    on others; an instrument counts the issues resolved (the people's resolutions, all of them) and
    the builds done (the program ``builder``'s ``build.done``), and twenty unrelated flows."""
    import random
    rng = random.Random(seed)
    events, resolved = [], []
    for p in range(people):
        at = sorted(rng.sample(range(steps), rng.randint(1, 4)))
        resolved += at
        events.append(_counter("orchestra_events_total", {"type": "jira.issue.resolved", "source": f"person.jira.u{p:04d}"}, at, steps))
        events.append(_counter("orchestra_events_total", {"type": "jira.comment.added", "source": f"person.jira.u{p:04d}"},
                               sorted(rng.sample(range(steps), rng.randint(3, 12))), steps))
    builds = sorted(rng.sample(range(steps), 120))
    events.append(_counter("orchestra_events_total", {"type": "build.done", "source": "builder"}, builds, steps))
    events.append(_counter("orchestra_events_total", {"type": "jira.issue.resolved", "source": "person.alice"}, builds[:40], steps))
    flows = {"resolved": _counter("issues_resolved_total", {"instrument": "jira"}, sorted(resolved), steps),
             "builds": _counter("builds_done_total", {"instrument": "ci"}, builds, steps)}
    for f in range(20):
        flows[f"other{f}"] = _counter(f"other_{f}_total", {"instrument": "x"}, sorted(rng.sample(range(steps), rng.choice((6, 10, 20, 60)))), steps)
    return events, flows


def test_attribution_tests_the_people_of_one_system_together_quickly_and_names_machines():
    from orchestra.sd.attribute import associate, candidates
    events, flows = attribution_world()
    on_bus = candidates(events)
    # 1,202 candidates one by one; the 600 Jira people's two types are two (alice and builder stay)
    assert len(on_bus) == 4 and {s.labels["source"] for s in on_bus} == {"person.jira.*", "builder", "person.alice"}
    t = time.perf_counter()
    got = {k: associate(c, on_bus) for k, c in flows.items()}
    assert time.perf_counter() - t < 0.5, "was 3.6 s for these 22 flows, one candidate per person, and found no machine for the issues resolved (2026-11-04)"
    res = got["resolved"]
    hs = res["hypotheses"]
    assert hs and all(h["machine"].startswith("person.jira.u") for h in hs), "hypotheses name machines, never the group"
    assert all(h["together"]["system"] == "jira" and h["events"]["source"] == h["machine"] for h in hs)
    own = [h["together"]["own_events"] for h in hs]
    assert own == sorted(own, reverse=True) and own[0] == 4, "the busiest first"
    [g] = res["together"]
    assert g["system"] == "jira" and g["type"] == "jira.issue.resolved" and len(g["machines"]) == 600 and g["confidence"] > 0.5
    assert "600 people relayed from jira, tested together" in g["why"]
    assert len({h["confidence"] for h in hs}) == 1 and res["tied"][0]["machines"] == [h["machine"] for h in hs]
    assert got["builds"]["hypotheses"][0]["machine"] == "builder"
    assert all("together" not in h for h in got["builds"]["hypotheses"])


def test_a_few_people_of_one_system_and_an_owner_mapped_person_are_tested_one_by_one():
    from orchestra.people import GROUP_MIN, relayed_from
    from orchestra.sd.attribute import candidates
    assert relayed_from("person.jira.5b10ac") == "jira" and relayed_from("person.alice") is None
    assert relayed_from("bot.jira.x") is None and relayed_from("person.jira.") is None and relayed_from(None) is None
    events, _ = attribution_world(people=GROUP_MIN - 1, steps=200)
    on_bus = candidates(events)
    assert len(on_bus) == len(events) and not any("relayed" in s.__dict__ for s in on_bus)
