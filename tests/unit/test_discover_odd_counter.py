"""One counter never empties the model: a level's balance needs the liveness of the counters it
may be balanced with, not of every counter in the store (bootstrap run 6, finding 5)."""

import random

from orchestra.metrics import Point
from orchestra.metrics.file import FileMetrics
from orchestra.sd.discover import discover

T0 = 1_800_000_000.0
QUEUES = ["emails", "exports", "imports", "reports", "thumbnails"]


def _queues(rng: random.Random, until: float, every: float = 15.0, *, only: set[str] | None = None) -> list[Point]:
    """Five queues, each with its own enqueued and processed counters, scraped on a schedule."""
    lab = lambda q: {"project": "p", "queue": q}
    state = {q: [0, 0, 0] for q in QUEUES}            # depth, enqueued, processed
    pts = []
    t = T0
    while t < until:
        for q in QUEUES:
            if only is not None and q not in only:
                continue
            d, e, p = state[q]
            add = rng.choice([0, 0, 1, 1, 2, 3])
            take = min(d + add, rng.choice([0, 1, 1, 2, 3]))
            state[q] = [d + add - take, e + add, p + take]
            pts += [Point("queue_depth", state[q][0], t, lab(q)),
                    Point("queue_jobs_enqueued_total", state[q][1], t, lab(q)),
                    Point("queue_jobs_processed_total", state[q][2], t, lab(q))]
        t += every
    return pts


def test_a_counter_counted_long_before_the_window_does_not_empty_every_level(tmp_path):
    # Run 6: the repository's commit count (12,765 at its first write, moving rarely) had no live
    # step in the grid, and every level was "live in only 0 of the steps while every counter was".
    rng = random.Random(6)
    end = T0 + 2 * 3600
    pts = _queues(rng, end)
    commits = {"project": "p", "instrument": "main_history"}
    pts += [Point("main_commits_total", 12765 + (i >= 3), end - 90 + 15 * i, commits) for i in range(6)]
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=T0, end=end, step=60)
    left = m.discovery["left_out"]
    assert len(m.stocks) == 5, left
    assert len(m.flows) == 10, [f.id for f in m.flows]
    odd = next(v for k, v in left.items() if k.startswith("main_commits_total"))
    assert "main_commits_total" in odd and "live" in odd, odd
    assert not any("while every counter was" in v for v in left.values()), left


def test_a_counter_live_for_half_the_window_still_yields_its_stock_over_that_half(tmp_path):
    rng = random.Random(7)
    end = T0 + 2 * 3600
    pts = [p for p in _queues(rng, end) if p.labels["queue"] != "thumbnails"]
    # the thumbnails' worker was started halfway: its queue and counters are written from then on,
    # the enqueued count carried over from before (not counted from nothing)
    half = _queues(random.Random(8), end, only={"thumbnails"})
    pts += [Point(p.series, p.value + (5000 if p.series == "queue_jobs_enqueued_total" else 0)
                  + (4990 if p.series == "queue_jobs_processed_total" else 0)
                  + (10 if p.series == "queue_depth" else 0), p.ts, p.labels)
            for p in half if p.ts >= T0 + 3600]
    store = FileMetrics(tmp_path / "m.jsonl")
    store.write(pts)
    m = discover(store.dump("", {"project": "p"}), start=T0, end=end, step=60)
    left = m.discovery["left_out"]
    assert len(m.stocks) == 5, left
    thumbs = next(s for s in m.stocks if "thumbnails" in str(s.series))
    assert 50 <= thumbs.evidence["balance_steps"] <= 60, thumbs.evidence["balance_steps"]
