"""Orchestra's own series are never a system flow's input (sd.inputs): a series Orchestra's own
machinery wrote of itself (a plugin's instrument, ``orchestra_*``) is offered only to flows of
stocks of the same provenance. Bootstrap run 7: a team's queue, read from its Prometheus, drained
"0.00 × workflow record bytes", the workflows plugin's record instrument."""

import random

from orchestra.sd.discover import discover
from orchestra.sd.series import series_key

T0 = 1_800_000_000.0
STEP = 15.0
N = 480                                    # two hours
RECORD = ("workflow_record_bytes", {"instrument": "workflows.record"})


def _world(seed: int = 7):
    """A queue in another store (``rig:``) whose processing follows a demand that comes and goes,
    and the workflows plugin's record size, which moves with that demand step for step."""
    rng = random.Random(seed)
    demand, t, v = [], 0, 1.0
    while t < N * STEP:
        demand.append((t, v))
        t += rng.randint(120, 600)
        v = 4.0 if v == 1.0 else 1.0
    at = lambda s: next(val for start, val in reversed(demand) if start <= s)
    level, ins, outs, rec, n_in, n_out = [], [], [], [], 0, 0
    for i in range(N + 1):
        t = T0 + i * STEP
        if i:
            n_in += sum(rng.random() < 5.0 / 60 for _ in range(int(STEP)))
            n_out += sum(rng.random() < 2.0 * at(i * STEP) / 60 for _ in range(int(STEP)))
        level.append((t, 500.0 + n_in - n_out))
        ins.append((t, float(n_in)))
        outs.append((t, float(n_out)))
        rec.append((t, 1000.0 * at(i * STEP)))
    return [("rig:queue_depth", {}, level), ("rig:queue_enqueued_total", {}, ins), ("rig:queue_processed_total", {}, outs),
            (RECORD[0], dict(RECORD[1]), rec)]


def _provenance(owner: str | None) -> dict:
    rig = {n: {"source": "rig", "kind": k, "origin": ["declared in orchestra.toml"]}
           for n, k in (("rig:queue_depth", "level"), ("rig:queue_enqueued_total", "counter"), ("rig:queue_processed_total", "counter"))}
    own = {"source": "own", "instrument": "workflows.record", "view": "aggregate", **({"owner": owner} if owner else {})}
    return {**{series_key(n, {}): p for n, p in rig.items()}, series_key(*RECORD): own}


def _reads(model) -> set[str]:
    return {x for f in model.flows for eq in f.equations for x in eq.inputs}


def test_an_own_record_series_is_no_input_to_a_source_fed_queue():
    m = discover(_world(), start=T0, end=T0 + N * STEP, step=STEP, provenance=_provenance("workflows"))
    assert [s.series.name for s in m.stocks] == ["rig:queue_depth"]
    assert not any("workflow_record" in x for x in _reads(m)), _reads(m)
    assert not any("workflow_record" in k for k in m.discovery["inputs"])
    why = m.discovery["left_out"][series_key(*RECORD)]
    assert why.startswith("Orchestra's own (its instrument workflows.record is the workflows plugin's)") and "never a stock" in why


def test_the_same_series_written_by_a_projects_instrument_is_offered():
    # the control: the rule is the provenance, not the name or the numbers
    m = discover(_world(), start=T0, end=T0 + N * STEP, step=STEP, provenance=_provenance(None))
    assert any("workflow_record_bytes" in k for k in m.discovery["inputs"])
    assert any("workflow_record_bytes" in x for x in _reads(m)), _reads(m)


def test_a_plugins_instrument_gives_its_series_an_owner():
    from orchestra.collect.views import provenance

    dump = [("workflow_record_bytes", {"instrument": "workflows.record"}, []), ("jira_issues", {"instrument": "jira_poller"}, []),
            ("queue_depth", {}, [])]
    got = provenance(dump, {}, series_key, {"workflows.record": "workflows"})
    assert got == {series_key(*RECORD): {"source": "own", "instrument": "workflows.record", "owner": "workflows"}}
