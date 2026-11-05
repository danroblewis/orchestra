"""People relayed from another system, told apart by their ``source`` alone (SPEC §2, "Many
people"): a bridge relays each act on a system it reads as the person who did it,
``person.<system>.<account>`` (``person.jira.5b10ac``), and announces each one. At work that is
hundreds of machines from one system. Each is still a machine (AGENTS.md rule 2); what is grouped
here is how they are shown (the Machines page and the Event Map, ``web/people.py``) and how
discovery's attribution tests them (``sd/attribute.py``), never what they are.

An owner-mapped person (``person.<key>``, the identity map's: two parts) is never relayed-from-a-
system here: those are few and named on purpose. A system's people are grouped only when there are
at least ``GROUP_MIN`` of them; fewer stay one by one."""

from __future__ import annotations

GROUP_MIN = 8          # fewer people relayed from one system than this are shown and tested one by one


def relayed_from(machine: str | None) -> str | None:
    """The system a person was relayed from (``person.jira.5b10ac``: ``jira``), or None for any
    other machine, an owner-mapped ``person.<key>`` included."""
    if not isinstance(machine, str) or not machine.startswith("person."):
        return None
    system, dot, account = machine[len("person."):].partition(".")
    return system if system and dot and account else None
