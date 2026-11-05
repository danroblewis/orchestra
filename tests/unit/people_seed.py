"""A synthetic bus of many people relayed from other systems (the bridges' Jira reader at work:
hundreds of ``person.jira.<account>`` machines, each announced with a display name, kind
``person``, package ``bridges``) and a few programs that take the issues they touch. Used by the
tests of the grouped people (web/people.py), the Machines page and discovery's attribution."""

from __future__ import annotations

from orchestra.events import ANNOUNCEMENT, utc_time

T0 = 1_790_000_000.0
PROGRAMS = ("triage", "notifier", "builder")


def people_events(n: int = 600, *, step: float = 7.0, slack: int = 0, teams: dict[int, str] | None = None,
                  mapped: tuple[str, ...] = ("alice",)) -> list[dict]:
    """``n`` Jira people (``person.jira.u0000`` ...), ``slack`` Slack people, the owner-mapped
    ``person.<key>`` of ``mapped``, and three programs: each person updates or comments on issues;
    ``triage`` listens for ``jira.issue.*`` and acts next on each issue, ``notifier`` after it, and
    ``builder`` on a few. ``teams``: a person's index to the team its announcement names."""
    evs: list[dict] = []
    t = T0

    def add(src, type, subject=None, data=None):
        nonlocal t
        t += step
        evs.append({"type": type, "source": src, "time": utc_time(t), "id": f"e{len(evs)}",
                    **({"subject": subject} if subject else {}), "data": data or {}})

    for p in PROGRAMS:
        add(p, ANNOUNCEMENT, data={"mode": "continuous", "kind": "program", "package": "demo",
                                   "listens_for": {"triage": ["jira.issue.*"], "notifier": ["triage.done"], "builder": ["triage.done"]}[p]})
    for k in mapped:
        add(f"person.{k}", ANNOUNCEMENT, data={"mode": "ad hoc", "kind": "person", "package": "bridges", "listens_for": [],
                                               "name": k.title() + " Example", "team": "sre"})
    people = [(f"person.jira.u{i:04d}", f"Person {i}", (teams or {}).get(i)) for i in range(n)]
    people += [(f"person.slack.m{i:03d}", f"Slacker {i}", None) for i in range(slack)]
    for i, (src, name, team) in enumerate(people):
        add(src, ANNOUNCEMENT, data={"mode": "ad hoc", "kind": "person", "package": "bridges", "listens_for": [], "name": name,
                                     **({"team": team} if team else {})})
        for j in range(3):
            issue = f"ISS-{(i * 3 + j) % (n + 7)}"
            add(src, "jira.issue.updated" if j != 1 else "jira.comment.added", issue)
            if j == 0:
                add("triage", "triage.done", issue)
                add("notifier", "notify.sent", issue)
    for k in mapped:
        add(f"person.{k}", "jira.issue.updated", "ISS-1")
    for i in range(0, n, 50):
        add("builder", "build.done", f"ISS-{i}")
    return evs
