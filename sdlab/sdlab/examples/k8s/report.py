"""What happens in a run of a Kubernetes example: the counts behind docs/research/k8s-model.md.

    uv run python sdlab/examples/k8s/report.py                       # both examples, the default week
    uv run python sdlab/examples/k8s/report.py sd-k8s-small --steps 20160

Prints the run time, the model's size, and each mechanism's activity: the traffic cycle, HPA scaling,
pods, OOM kills, CPU throttling, load-balancer timeouts and retries, node autoscaling, the databases.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from sdlab.sdtruth import Truth

EXAMPLES = Path(__file__).resolve().parent.parent
DAY = 1440


def report(example: str, steps: int | None = None) -> None:
    t = Truth(EXAMPLES / example / "truth.model.json")
    m = t.model
    a = time.perf_counter()
    r = t.run(steps=steps)
    secs = time.perf_counter() - a
    L, C = r["levels"], r["counters"]
    n = len(L["ingress"])
    flows = {f["id"]: f for f in m["flows"]}
    svcs = [f["id"][: -len("_done")] for f in m["flows"] if f["id"].endswith("_done")]
    measured = len(t.measured_ids)
    tot = lambda fid: sum(C.get(fid) or [0])  # noqa: E731
    print(f"== {example}: {len(svcs)} services, {len(m['stocks'])} stocks ({measured} measured, {len(m['stocks']) - measured} hidden), "
          f"{len(m['flows'])} flows; {n} steps (minutes) in {secs:.1f} s")

    edge = L["ingress"]
    days = [edge[d * DAY:(d + 1) * DAY] for d in range(n // DAY)]
    wk, we = [sum(d) / len(d) for d in days[:5]], [sum(d) / len(d) for d in days[5:7]]
    print(f"traffic at the edge (requests a minute): weekday peak {max(max(d) for d in days[:4])}, night trough {min(min(d) for d in days[:5])}, "
          f"weekday mean {sum(wk) / len(wk):.0f}, weekend mean {sum(we) / max(1, len(we)):.0f}; the Friday spike's peak {max(days[4]) if len(days) > 4 else '-'}")

    def episodes(v):
        """minutes in which the rounded level rose, and fell"""
        up = sum(1 for x, y in zip(v, v[1:]) if round(y) > round(x))
        return up, sum(1 for x, y in zip(v, v[1:]) if round(y) < round(x))

    hpa = [s for s in svcs if f"{s}_desired" in L]
    added = sum(tot(f"{s}_hpa_up") for s in hpa)
    removed = sum(tot(f"{s}_hpa_down") for s in hpa)
    ups = sum(episodes(L[f"{s}_desired"])[0] for s in hpa)
    downs = sum(episodes(L[f"{s}_desired"])[1] for s in hpa)
    rng = sorted(((max(L[f"{s}_desired"]) - min(L[f"{s}_desired"])), s) for s in hpa)[::-1][:5]
    print(f"HPA: {added:.0f} replicas added, {removed:.0f} removed over {len(hpa)} services; desired replicas rose in {ups} "
          f"service-minutes and fell in {downs}; widest ranges: " + ", ".join(f"{s} {min(L[s + '_desired'])}-{max(L[s + '_desired'])}" for _, s in rng))
    atmax = [s for s in hpa if max(L[f"{s}_desired"]) >= m["stocks"][[x["id"] for x in m["stocks"]].index(f"{s}_desired")]["max"]]
    print(f"  at maxReplicas at some point: {', '.join(atmax) or 'none'}")

    print(f"pods: {sum(tot(f'{s}_create') for s in svcs):.0f} created, {sum(tot(f'{s}_scheduled') for s in svcs):.0f} scheduled, "
          f"{sum(tot(f'{s}_gone') for s in svcs):.0f} terminated; rolling update replaced {sum(tot(f'{s}_rollout') for s in svcs):.0f}")
    pend = {s: sum(1 for x in L[f"{s}_pending"] if x >= 1) for s in svcs}
    print(f"  minutes with a pod pending (summed over services): {sum(pend.values())}; most: " +
          ", ".join(f"{s} {v}" for s, v in sorted(pend.items(), key=lambda kv: -kv[1])[:4]))
    kills = {s: tot(f"{s}_oom_kill") for s in svcs if tot(f"{s}_oom_kill")}
    by_day = {s: [sum(C[f"{s}_oom_kill"][d * DAY:(d + 1) * DAY]) for d in range(n // DAY)] for s in kills}
    print(f"OOM kills: {sum(kills.values()):.0f} (" + "; ".join(f"{s} {v:.0f}, by day {by_day[s]}" for s, v in sorted(kills.items(), key=lambda kv: -kv[1])) + ")")
    print(f"  requests lost in killed pods {sum(tot(f'{s}_oom_lost') for s in svcs):.0f}")

    thr = {}
    for s in svcs:
        lim = flows[f"{s}_done"]["effects"][0]["points"][1][0] / 0.85          # the throttle table's knee is 0.85 x limit
        thr[s] = sum(1 for x in L[f"{s}_cpu_pod"] if x >= 0.85 * lim)
    print("CPU throttling (minutes with CPU per pod above 85% of the limit): " + (", ".join(f"{s} {v}" for s, v in sorted(thr.items(), key=lambda kv: -kv[1]) if v) or "none")
          + f"; requests timed out while throttled {sum(tot(f'{s}_timeouts') for s in svcs):.0f}")
    done = sum(tot(f"{s}_done") for s in svcs)
    print(f"requests: {done:.0f} completed (all services), {sum(tot(f'{s}_errors') for s in svcs):.0f} 5xx, "
          f"{sum(tot(f'{s}_lb_timeout') for s in svcs if f'{s}_lb_timeout' in C):.0f} load-balancer timeouts, "
          f"{sum(tot(f'{s}_retried') for s in svcs):.0f} retried, {sum(tot(f'{s}_given_up') for s in svcs):.0f} given up "
          f"({100 * sum(tot(f'{s}_given_up') for s in svcs) / max(1, done):.2f}%)")

    for p in sorted(k[len("nodes_"):] for k in L if k.startswith("nodes_")):
        v = L[f"nodes_{p}"]
        occ = L[f"cpu_requested_{p}"]
        print(f"node pool {p}: {min(v)}-{max(v)} nodes; autoscaler added {tot(f'{p}_scale_up'):.1f} (booted {tot(f'{p}_provision_3'):.1f}), "
              f"removed {tot(f'{p}_scale_down'):.1f}; nodes rose in {episodes(v)[0]} minutes, fell in {episodes(v)[1]}; "
              f"CPU requested {min(occ)}-{max(occ)}% (minutes above 100%: {sum(1 for x in occ if x > 100)})")
    for j in r.get("injections") or []:
        if j["stock"].startswith("nodes_"):
            print(f"  node failure at minute {j['t']} (day {j['t'] // DAY}, {(j['t'] % DAY) // 60:02d}:{(j['t'] % DAY) % 60:02d}): {j['amount']} node")

    for d in sorted(k[: -len("_conn")] for k in L if k.endswith("_conn") and not k.endswith("_replica_conn")):
        lag = f" replication lag max {max(L[d + '_lag'])} s (median {sorted(L[d + '_lag'])[n // 2]} s); replica connections max {max(L[d + '_replica_conn'])}" if f"{d}_lag" in L else ""
        print(f"database {d}: connections max {max(L[d + '_conn'])}, query timeouts {tot(d + '_query_timeout'):.0f}{lag}")
    for q in sorted(k for k in L if k.startswith("mq_")):
        print(f"queue {q[3:]}: depth {min(L[q])}-{max(L[q])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("examples", nargs="*", default=["sd-k8s-small", "sd-k8s-platform"])
    ap.add_argument("--steps", type=int)
    a = ap.parse_args()
    for e in a.examples:
        report(e, a.steps)
