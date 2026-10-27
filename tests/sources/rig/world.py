"""The sources rig's world: three services in three regions, shaped like the owner's work metrics,
one sample per pod per minute. Deterministic for a seed, so tests and the rig agree.

- Each service is spelled its own way, as teams instrument differently in one production
  Prometheus: ``checkout`` with ``service``/``region``/``pod`` and a ``stat`` label; ``search``
  with ``app``/``zone``/``pod_name`` and statistic suffixes; ``authz`` with
  ``k8s_app``/``location``/``kubernetes_pod_name`` and a ``statistic`` label.
- Per pod per minute: max, min, avg, p50, p95 and p99 of request latency, and a requests counter.
- Load follows a daily curve; latency comes from a queue (load per pod against its capacity);
  pods are scaled on p95 after a delay (up after 3 minutes above target, down after 10 well
  below), which closes a real loop (load → latency → pods → latency); rolling deploys replace
  pods one a minute under new names; a region can be down for a stretch (nothing reports).
- A ``:sum`` recording-rule rollup, ``http_requests_inflight:sum`` (checkout's requests in flight
  per region, Little's law), stands beside the per-pod series.

``World.minute()`` advances one minute and returns the samples and the ground truth for it: per
service and region the pods reporting, the pods ``gone`` (reported the minute before, not this
one), requests per second and the mean of the pods' p95."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

SPELLINGS = {
    "checkout": {"service": "service", "region": "region", "pod": "pod", "latency": "http_request_duration_seconds",
                 "stat": "stat", "requests": "http_requests_total"},
    "search": {"service": "app", "region": "zone", "pod": "pod_name", "latency": "app_latency_seconds",
               "stat": None, "requests": "app_requests_total"},
    "authz": {"service": "k8s_app", "region": "location", "pod": "kubernetes_pod_name", "latency": "k8s_request_latency",
              "stat": "statistic", "requests": "k8s_requests_total"},
}
REGIONS = {"us-east": 1.0, "us-west": 0.7, "eu-west": 0.5}
BASE_RPS = {"checkout": 120.0, "search": 200.0, "authz": 400.0}      # per region at share 1, mid-day
SERVICE_S = {"checkout": 0.08, "search": 0.05, "authz": 0.01}        # seconds per request
CONCURRENCY = 4                                                         # concurrent requests a pod serves
STATS = ("max", "min", "avg", "p50", "p95", "p99")
UP_AFTER, DOWN_AFTER = 3, 10                                          # minutes above target / well below
MIN_PODS, MAX_PODS = 2, 12
DEPLOY_EVERY = 120                                                    # minutes between a service's rolling deploys
RULE = ("per service and region: one pod more after p95 is above 2.2 × service time / 0.3 (utilisation 0.7) for "
        f"{UP_AFTER} minutes in a row; one fewer after it is below half that for {DOWN_AFTER} (at least {MIN_PODS}, "
        f"at most {MAX_PODS}); a rolling deploy every {DEPLOY_EVERY} min replaces one pod a minute")


def target(service: str) -> float:
    return 2.2 * SERVICE_S[service] / 0.3


@dataclass
class Pod:
    name: str
    born: int
    requests: float = 0.0


@dataclass
class Cell:
    service: str
    region: str
    pods: list[Pod] = field(default_factory=list)
    above: int = 0
    below: int = 0
    replacing: int = 0          # pods still to replace in a rolling deploy
    reported: set = field(default_factory=set)   # the pods that reported last minute


class World:
    def __init__(self, start: float, *, seed: int = 7, regions: dict[str, float] | None = None,
                 down: tuple[str, float, float] | None = None, pods: int = 3, deploy_every: int = DEPLOY_EVERY):
        self.t = math.floor(start / 60) * 60
        self.rng = random.Random(seed)
        self.k = 0
        self.down = down                    # (region, from, to): nothing in that region reports
        self.deploy_every = deploy_every
        self.cells = [Cell(s, r) for s in SPELLINGS for r in (regions or REGIONS)]
        self.share = dict(regions or REGIONS)
        for c in self.cells:
            c.pods = [self._pod(c) for _ in range(pods)]

    def _pod(self, c: Cell) -> Pod:
        return Pod(f"{c.service}-{c.region[:2]}{c.region[-1]}-{self.rng.getrandbits(24):06x}", self.k)

    def load(self, c: Cell) -> float:
        hour = (self.t % 86400) / 3600
        daily = 1.0 + 0.5 * math.sin(2 * math.pi * (hour - 9) / 24)
        return BASE_RPS[c.service] * self.share[c.region] * daily * (1 + self.rng.uniform(-0.05, 0.05))

    def minute(self) -> tuple[list[tuple[str, dict, float, float]], dict]:
        """One minute on: the samples written at its end, and the truth about it."""
        self.t += 60
        self.k += 1
        samples: list[tuple[str, dict, float, float]] = []
        truth = {"t": self.t, "cells": {}, "down": []}
        for c in self.cells:
            sp = SPELLINGS[c.service]
            if c.replacing and c.pods:                       # a rolling deploy: the oldest pod is replaced
                c.pods.pop(0)
                c.pods.append(self._pod(c))
                c.replacing -= 1
            if self.k % self.deploy_every == list(SPELLINGS).index(c.service) * self.deploy_every // 3:
                c.replacing = len(c.pods)
            rps = self.load(c)
            n = len(c.pods)
            rho = min(0.95, rps * SERVICE_S[c.service] / (CONCURRENCY * n))
            mean = SERVICE_S[c.service] / (1 - rho)
            down = self.down is not None and c.region == self.down[0] and self.down[1] <= self.t < self.down[2]
            p95s = []
            for p in c.pods:
                jitter = self.rng.uniform(0.95, 1.05)
                m = mean * jitter
                stats = {"max": 4.5 * m, "min": 0.35 * SERVICE_S[c.service], "avg": m, "p50": 0.8 * m, "p95": 2.2 * m, "p99": 3.5 * m}
                p95s.append(stats["p95"])
                p.requests += round(rps / n * 60)
                if down:
                    continue
                base = {sp["service"]: c.service, sp["region"]: c.region, sp["pod"]: p.name}
                for st in STATS:
                    if sp["stat"]:
                        samples.append((sp["latency"], {**base, sp["stat"]: st}, self.t, round(stats[st], 6)))
                    else:
                        samples.append((f"{sp['latency']}_{st}", base, self.t, round(stats[st], 6)))
                samples.append((sp["requests"], base, self.t, p.requests))
            if c.service == "checkout" and not down:
                samples.append(("http_requests_inflight:sum", {"service": "checkout", "region": c.region}, self.t, round(rps * mean, 4)))
            p95 = sum(p95s) / len(p95s)
            now = set() if down else {p.name for p in c.pods}
            # gone: reported last minute, not this one; a count over one and a half reporting
            # intervals still holds them at this minute's samples
            truth["cells"][f"{c.service}/{c.region}"] = {"pods": len(now), "gone": len(c.reported - now), "rps": round(rps, 3),
                                                         "p95": round(p95, 6)}
            c.reported = now
            if down:
                truth["down"].append(f"{c.service}/{c.region}")
            c.above = c.above + 1 if p95 > target(c.service) else 0
            c.below = c.below + 1 if p95 < 0.5 * target(c.service) else 0
            if c.above >= UP_AFTER and n < MAX_PODS:
                c.pods.append(self._pod(c))
                c.above = 0
            elif c.below >= DOWN_AFTER and n > MIN_PODS:
                c.pods.pop(0)
                c.below = 0
        return samples, truth

    def run(self, minutes: int) -> tuple[list[tuple[str, dict, list[tuple[float, float]]]], list[dict]]:
        """``minutes`` on, as a dump (name, labels, points) and the truth per minute."""
        series: dict[tuple, tuple[str, dict, list]] = {}
        truths = []
        for _ in range(minutes):
            samples, truth = self.minute()
            truths.append(truth)
            for name, labels, t, v in samples:
                series.setdefault((name, tuple(sorted(labels.items()))), (name, labels, []))[2].append((t, v))
        return list(series.values()), truths
