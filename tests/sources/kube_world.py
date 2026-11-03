"""A faux Kubernetes namespace ``shop``, shaped like kube-state-metrics and an app's own metrics,
scraped from one exporter every 15 s (the scrape's time jitters by a few hundred ms, every series
of one scrape at the same time). Deterministic for a seed.

- ``kube_pod_status_phase{namespace, deployment, pod, phase}``: for every pod, every phase, 0 or 1
  (kube-state-metrics' one-hot gauge). A new pod is Pending for a few scrapes, then Running; a pod
  replaced is Succeeded (or, now and then, Failed) for a few scrapes, then gone.
- ``http_requests_in_flight{namespace, deployment, pod}``: a running pod's requests in flight, 0–9.
- ``queue_depth``, ``queue_enqueued_total``, ``queue_dequeued_total`` (``queue="jobs"``): depth is
  enqueued less dequeued at every scrape, exactly.

``kube(end, minutes)`` returns the dump and the truth: per scrape time, the pods in each phase."""

from __future__ import annotations

import random

PHASES = ("Pending", "Running", "Succeeded", "Failed", "Unknown")
DEPLOYMENTS = {"api": 3, "store": 2, "stream": 2, "worker": 3}
SCRAPE = 15.0


def kube(end: float, minutes: int, seed: int = 7) -> tuple[list, dict[float, dict[str, int]]]:
    rnd = random.Random(seed)
    start = end - minutes * 60
    n = int(minutes * 60 / SCRAPE)
    times = [start + k * SCRAPE + round(rnd.uniform(0.05, 0.6), 3) for k in range(n)]
    pods: dict[str, dict] = {}                     # name -> {deployment, phase, left (scrapes in this phase), born}
    serial = 0

    def new(dep: str, running: bool) -> None:
        nonlocal serial
        serial += 1
        pods[f"{dep}-{serial:04d}"] = {"deployment": dep, "phase": "Running" if running else "Pending",
                                       "left": rnd.randint(2, 4)}
    for dep, r in DEPLOYMENTS.items():
        for _ in range(r):
            new(dep, True)
    phase_pts: dict[tuple[str, str], list] = {}
    inflight: dict[str, list] = {}
    meta: dict[str, str] = {}
    depth, enq, deq = 40.0, 1000.0, 960.0
    q = {"depth": [], "enq": [], "deq": []}
    truth: dict[float, dict[str, int]] = {}
    for k, t in enumerate(times):
        for name, p in list(pods.items()):         # the lifecycle moves on
            if p["phase"] == "Pending":
                p["left"] -= 1
                if p["left"] <= 0:
                    p["phase"] = "Running"
            elif p["phase"] in ("Succeeded", "Failed"):
                p["left"] -= 1
                if p["left"] <= 0:
                    del pods[name]
        if k and k % 40 == 0:                      # every ten minutes, one deployment's pod is replaced
            dep = list(DEPLOYMENTS)[(k // 40) % len(DEPLOYMENTS)]
            old = next(nm for nm, p in pods.items() if p["deployment"] == dep and p["phase"] == "Running")
            pods[old].update(phase="Failed" if (k // 40) % 3 == 0 else "Succeeded", left=rnd.randint(3, 6))
            new(dep, False)
        truth[t] = {ph: sum(1 for p in pods.values() if p["phase"] == ph) for ph in PHASES}
        for name, p in pods.items():
            meta[name] = p["deployment"]
            for ph in PHASES:
                phase_pts.setdefault((name, ph), []).append((t, 1.0 if p["phase"] == ph else 0.0))
            if p["deployment"] != "worker" and p["phase"] == "Running":
                inflight.setdefault(name, []).append((t, float(rnd.randint(0, 9))))
        a, b = rnd.randint(0, 12), rnd.randint(0, 12)
        b = min(b, depth + a)
        depth += a - b
        if k == n // 2:                            # the exporter restarts: its counters start again from 0, the queue holds what it held
            enq, deq = float(a), float(b)
        else:
            enq, deq = enq + a, deq + b
        q["depth"].append((t, depth))
        q["enq"].append((t, enq))
        q["deq"].append((t, deq))
    ns = {"namespace": "shop", "instance": "127.0.0.1:8940", "job": "kubesim"}
    dump = [("kube_pod_status_phase", {**ns, "deployment": meta[name], "pod": name, "phase": ph}, pts)
            for (name, ph), pts in phase_pts.items()]
    dump += [("http_requests_in_flight", {**ns, "deployment": meta[name], "pod": name}, pts) for name, pts in inflight.items()]
    jobs = {**ns, "queue": "jobs"}
    dump += [("queue_depth", jobs, q["depth"]), ("queue_enqueued_total", jobs, q["enq"]), ("queue_dequeued_total", jobs, q["deq"])]
    return dump, truth
