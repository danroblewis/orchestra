"""A role's capacity on its held pile survives an outflow's empty source (sd.driverchoice).

The Workflows plugin's two model-structure cases, as their discovery read them (the plugin's
recorded series, written by its examples' scripts: task_loop seed 7, delivery_sail seed 5; three
simulated hours on a 30 s grid; tests/fixtures/sd/workflows-*.json.gz). The claim into a held pile
is fitted reading that pile, the fuller the slower: the capacity limit the owner's use cases are
about. T16's drain rule refused it for the claims it would make while the waiting pile was empty
(3.5 and 15 minutes of the window) and kept the proportion of the waiting pile instead. A form on
another stock is an interaction the simulator steps with the source's own limit, and is not held
to the empty-source test; a measured input still is (the team review's case below: scoring every
form only on the time its source held items let a lagging copy of the source win)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from orchestra.sd.discover import discover

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sd"


def _model(name: str):
    r = json.loads(gzip.decompress((FIXTURES / name).read_bytes()))
    dump = [(n, labels, [tuple(p) for p in pts]) for n, labels, pts in r["dump"]]
    return discover(dump, **r["kwargs"], provenance=r["provenance"])


@pytest.mark.parametrize(("fixture", "workflow", "step"), [("workflows-task-loop.json.gz", "task_loop", "write"),
                                                          ("workflows-delivery-sail.json.gz", "delivery_sail", "change")])
def test_the_claim_into_a_held_pile_is_fitted_on_that_pile_the_fuller_the_slower(fixture, workflow, step):
    m = _model(fixture)
    pile = {s.series.labels.get("pile"): s.id for s in m.stocks if s.series and s.series.labels.get("workflow") == workflow}
    [claim] = [f for f in m.flows if f.counter and f.counter.labels.get("from") == f"{step}.waiting"
               and f.counter.labels.get("to") == f"{step}.held"]
    eq = claim.current()
    assert (claim.src, claim.dst) == (pile[f"{step}.waiting"], pile[f"{step}.held"])
    assert eq.form == "linear" and eq.inputs == [pile[f"{step}.held"]] and eq.params["k"] < 0, eq


def test_a_held_pile_read_away_from_by_its_own_level_is_not_taken_over_by_a_lagging_count_of_it():
    # the team review's re-read loop (seed of the plugin's example): the read's end is fitted on
    # read.held itself; the floor's count of held offers (an input) is the same number a little
    # behind, nonzero while the pile reads empty, and is still held to the empty-source test
    m = _model("workflows-team-review.json.gz")
    [done] = [f for f in m.flows if f.counter and f.counter.labels.get("from") == "read.held"
              and f.counter.labels.get("to") == "comment.waiting"]
    assert done.current().inputs == [done.src], done.current()
