"""The calls in progress (a source's occupancy view, Little's law) are a stock by construction: its
completions by status drain it, and its arrivals, the completions plus its change, fill it
(``sd.construction``)."""

import random

from orchestra.sd.discover import discover
from orchestra.sd.series import Declared, series_key

T0 = 1_800_000_000.0
STEP = 60.0
N = 120


def test_an_occupancy_is_a_stock_drained_by_its_completions_and_filled_by_its_arrivals():
    rng = random.Random(3)
    in_progress, passed, failed, lv, ps, fs = 2, 0, 0, [], [], []
    for i in range(N + 1):
        arrived = rng.randint(0, 6)
        done = min(in_progress + arrived, rng.randint(0, 6))
        bad = sum(rng.random() < 0.1 for _ in range(done))
        in_progress += arrived - done
        passed, failed = passed + done - bad, failed + bad
        t = T0 + STEP * i
        lv.append((t, float(in_progress)))
        ps.append((t, float(passed)))
        fs.append((t, float(failed)))
    level, cp, cf = {"method": "Get"}, {"method": "Get", "status": "passed"}, {"method": "Get", "status": "failed"}
    dump = [("work:grpc_m_in_progress", level, lv), ("work:grpc_m_count", cp, ps), ("work:grpc_m_count", cf, fs)]
    occ = {"law": "Little's law", "derived": "busy time over the interval (Little's law)", "completions": "grpc_m_count",
           "by": "status", "driver": "grpc_m_count"}
    lk, pk, fk = (series_key(n, lab) for n, lab, _ in dump)
    prov = {lk: {"view": "occupancy", "family": "grpc_m:count", "unit": "calls", "occupancy": occ,
                 "derived": occ["derived"]},
            pk: {"view": "increments", "family": "grpc_m:count", "unit": "calls"},
            fk: {"view": "increments", "family": "grpc_m:count", "unit": "calls"}}
    kinds = {lk: Declared("level"), pk: Declared("counter"), fk: Declared("counter")}
    m = discover(dump, start=T0, end=T0 + N * STEP, step=STEP, kinds=kinds, provenance=prov)
    [st] = [s for s in m.stocks if s.series and s.series.name == "work:grpc_m_in_progress"]
    ev = st.evidence
    assert ev["by_construction"] is True and ev["trust"]["kind"] == "by_construction"
    signs = {b["series"]: b["sign"] for b in ev["balance"]}
    arrivals = ev["occupancy"]["arrivals"]
    assert signs == {arrivals: 1, pk: -1, fk: -1} and arrivals.startswith("work:grpc_m_arrived_total")
    assert ev["occupancy"]["completions"] == [pk, fk] or sorted(ev["occupancy"]["completions"]) == sorted([pk, fk])
    assert ev["occupancy"]["derived"] == "busy time over the interval (Little's law)" and ev["occupancy"]["driver"] == "grpc_m_count"
    assert lk not in m.discovery["left_out"]
