"""Balances that hold by construction: a count of reporters and its own turnover.

A source that reads another store counts, for a family with an identity label, how many of them
report (``…_pods``: the pods reporting ``http_requests_total``), and that count's turnover (``…_pods_started_total``,
``…_pods_stopped_total``: reporters that appeared and disappeared, ``orchestra.sources.views``). The
turnover is the count's changes, taken apart: the balance is exact whatever the count means, so its
R² of 1.000 is no evidence of anything. Such a level is still a count of things (pods come and go),
and it is kept as a stock only when it counts reporters in a place pods are held (a deployment, a
node, a phase), recorded as ``by_construction`` with no R², its trust nil; split by what happened
to a request (an HTTP status code, a method, an outcome), it counts the pods that happened to
report one lately, which no system holds, and it is left out.

Which series are counts of reporters and their turnover is the source's to say: its definitions'
views (``count``, ``starts``, ``stops``), passed to discovery as the reading's provenance."""

from __future__ import annotations

COUNT_VIEW = "count"
TURNOVER_VIEWS = {"starts", "stops"}
# labels that say where reporters are held: a count of them split by these is a count of pods in a place
PLACES = {"deployment", "statefulset", "daemonset", "replicaset", "node", "namespace", "service", "job", "app", "phase",
          "condition", "cluster", "zone", "region", "container", "workload"}
WRITERS = {"instrument", "machine", "source", "project", "instance"}


def _view(provenance: dict, key: str) -> str | None:
    return (provenance.get(key) or {}).get("view")


def constructed(level, terms: list, provenance: dict) -> bool:
    """Whether a level's balance is a count of reporters and turnover counters only."""
    return bool(terms) and _view(provenance, level.key) == COUNT_VIEW and \
        all(_view(provenance, c.key) in TURNOVER_VIEWS for c, _ in terms)


def no_place(level) -> str:
    """The label a count of reporters is split by that is no place pods are held, or nothing."""
    return next((k for k in sorted(level.labels) if k not in WRITERS and k not in PLACES), "")
