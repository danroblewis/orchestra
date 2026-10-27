"""Counted rates: every series of a source is measured up to that source's last point, so a
producer whose series ended (it disconnected) shows no rate, while the others keep theirs."""

from orchestra.web.traffic import summarise

T0 = 1_800_000_000.0


def _counter(machine: str, minutes: int) -> dict:
    """A producer publishing 6 a minute, read every 15 s for ``minutes`` minutes from T0."""
    pts = [(T0 + 15 * k, 1.5 * k) for k in range(minutes * 4 + 1)]
    return {"source": "rabbit", "name": "rabbit:published_total", "labels": {}, "direction": "out", "channel": "rabbit:orders",
            "machine": machine, "points": pts}


def test_a_producer_whose_series_ended_has_no_rate_and_the_others_keep_theirs():
    alone = summarise([_counter("rabbit.b", 60)], T0 + 3600 + 30)
    both = summarise([_counter("rabbit.a", 20), _counter("rabbit.b", 60)], T0 + 3600 + 30)   # a ended 40 minutes before b
    rate = lambda s, m: next(e["per_min"] for e in s["edges"] if e["machine"] == m)
    assert rate(both, "rabbit.a") == 0.0
    assert rate(both, "rabbit.b") == rate(alone, "rabbit.b") == 6.0


def test_a_counted_machine_the_model_also_knows_is_known_by_counts_like_any_other():
    # one counted machine is also on the page from the model's series (never seen on the bus),
    # the other only by its counts: both are known by counts only, not "no events yet"
    from orchestra.web.traffic import merge

    view = {"machines": [{"id": "rabbit.a", "publishes": [], "first_seen": None, "last_seen": None, "active": False,
                          "from_source": "rabbit"}]}
    merge(view, summarise([_counter("rabbit.a", 60), _counter("rabbit.b", 60)], T0 + 3600 + 30), T0 + 3600 + 30)
    assert {m["id"]: m.get("counted_only") for m in view["machines"]} == {"rabbit.a": True, "rabbit.b": True}
