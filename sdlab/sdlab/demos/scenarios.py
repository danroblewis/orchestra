"""The demos' scenarios (docs/DEMOS.md): a kubernetes ladder case, the variant and strategy whose stored, passing
result is the found model, and the changes a demo can apply to an in-memory copy of the true model."""

from __future__ import annotations

SCENARIOS = {
    "memory-oom": {
        "title": "An API service with a memory leak and OOM kills (ladder case 310)",
        "case": "310-k8s-memory-oom", "variant": "none-long", "strategy": "milp",
        "about": ("Requests queue, are dispatched to ready pods, time out into retries; an autoscaler sets desired "
                  "pods from CPU; pods start from pending; each pod's memory grows with load and a slow leak, and "
                  "pods near the memory limit are OOM-killed back to pending."),
        # residual watch: what changes on "day 2" (a schedule change from step t on a copy of the true model)
        "changes": {
            "faster-retries": {"label": "a client release retries timed-out requests faster",
                               "flow": "retried", "rate": {"form": "proportional", "stock": "retries", "k": 0.9}, "t": 1200},
            "slower-starts": {"label": "a new base image makes pods start more slowly",
                              "flow": "started", "rate": {"form": "proportional", "stock": "pending", "k": 0.2}, "t": 1200},
            "worse-leak": {"label": "a library upgrade doubles the memory leak",
                           "flow": "leaking", "rate": {"form": "constant", "value": 2.0}, "t": 1200},
            "more-errors": {"label": "a bad deploy fails 3x as many requests",
                            "flow": "errors", "rate": {"form": "proportional", "stock": "inflight", "k": 0.09}, "t": 1200},
        },
        # leverage: goals a person might care about
        "goals": {
            "oom_kills_total": {"label": "pods OOM-killed by the end", "stock": "oom_kills_total", "how": "final", "better": "lower"},
            "errors_total": {"label": "failed requests by the end", "stock": "errors_total", "how": "final", "better": "lower"},
            "queue": {"label": "mean requests waiting", "stock": "queue", "how": "mean", "better": "lower"},
            "retries": {"label": "mean requests waiting to retry", "stock": "retries", "how": "mean", "better": "lower"},
            "pending": {"label": "mean pods pending", "stock": "pending", "how": "mean", "better": "lower"},
        },
        # the hidden-stock demo: the scenario author's reading of what the inferred stock probably is in production
        "hidden_hint": ("Memory a pod holds and never frees, growing about 1 MiB a step and released only when the pod "
                        "is OOM-killed: a leak. Measure it directly (a heap or RSS metric per pod beside the working "
                        "set), and alert on its growth rather than waiting for the OOM kills."),
    },
}


def get(name: str) -> dict:
    if name not in SCENARIOS:
        raise KeyError(name)
    return SCENARIOS[name]


def add(name: str, scenario: dict) -> None:
    """A demo module's own scenario (same keys as above; "changes", "goals" and "hidden_hint" may be empty)."""
    SCENARIOS.setdefault(name, {"changes": {}, "goals": {}, **scenario})
