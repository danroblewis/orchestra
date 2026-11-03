"""A role's capacity on its held pile survives an outflow's empty source (sd.driverchoice), and what
discovery finds now that the Workflows plugin's place is the step.

The Workflows plugin's model-structure cases, as their discovery read them (the plugin's recorded
series, written by its examples' scripts: task_loop seed 7, delivery_sail seed 5, team_review seed
8; three simulated hours on a 30 s grid; tests/fixtures/sd/workflows-*.json.gz, captured from the
plugin's model tests, tests/unit/test_example_*_model.py, at its be2edc9).

The rule: a form on another stock is an interaction the simulator steps with the source's own
limit, and is not held to the empty-source test; a measured input still is (the team review's case
below: scoring every form only on the time its source held items let a lagging copy of the source
win). The plugin's instrument no longer prints a step's halves as stocks (2026-11-02: the place is
the step, ``workflow_step_items``; ``workflow_pile_items`` with ``held`` is an aggregate), so the
rule's case is kept on the series the former instrument printed (``*-pre-step-piles``)."""

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


@pytest.mark.parametrize(("fixture", "workflow", "step"),
                         [("workflows-task-loop-pre-step-piles.json.gz", "task_loop", "write"),
                          ("workflows-delivery-sail-pre-step-piles.json.gz", "delivery_sail", "change")])
def test_the_claim_into_a_held_pile_is_fitted_on_that_pile_the_fuller_the_slower(fixture, workflow, step):
    """The series this reads is the plugin's former instrument (``workflow_pile_items`` per half,
    waiting and held, each a stock), kept as data for this rule: the claim into a held pile is
    fitted reading that pile, the fuller the slower (the role's capacity). T16's drain rule refused
    it for the claims it would make while the waiting pile was empty (3.5 and 15 minutes of the
    window) and kept the proportion of the waiting pile instead."""
    m = _model(fixture)
    pile = {s.series.labels.get("pile"): s.id for s in m.stocks if s.series and s.series.labels.get("workflow") == workflow}
    [claim] = [f for f in m.flows if f.counter and f.counter.labels.get("from") == f"{step}.waiting"
               and f.counter.labels.get("to") == f"{step}.held"]
    eq = claim.current()
    assert (claim.src, claim.dst) == (pile[f"{step}.waiting"], pile[f"{step}.held"])
    assert eq.form == "linear" and eq.inputs == [pile[f"{step}.held"]] and eq.params["k"] < 0, eq


@pytest.mark.parametrize(("fixture", "workflow", "steps", "step", "out_on"),
                         [("workflows-task-loop.json.gz", "task_loop", {"write", "review", "gate"}, "write",
                           "input:workflow_pile_oldest_seconds_true_write_held_write_task_loop"),
                          ("workflows-delivery-sail.json.gz", "delivery_sail",
                           {"change", "open_pr", "ci", "review", "nudge", "ping", "sail", "sail_check", "triage", "retry"},
                           "change", "workflow_step_items_change_delivery_sail")])
def test_on_the_step_series_each_step_is_one_stock_the_claim_is_hidden_inside_it_and_no_capacity_stock_is_found(
        fixture, workflow, steps, step, out_on):
    """The plugin's instrument now: one stock per step, recorded by construction; the claim (waiting
    to held) is a passage inside the step, never a move, so no flow and no held-pile stock carries
    it, and the role's capacity is not representable (a known loss: the move out of the claimed
    step is fitted on the oldest item's age in the task loop and proportional to the step in the
    delivery, never on a held pile, the fuller the slower)."""
    m = _model(fixture)
    found = {s.series.labels["step"]: s for s in m.stocks
             if s.series and s.series.name == "workflow_step_items" and s.series.labels.get("workflow") == workflow}
    assert set(found) == steps, sorted(found)
    assert all(s.evidence.get("by_construction") for s in found.values())
    assert not [s for s in m.stocks if s.series and s.series.name == "workflow_pile_items"]     # no half is a stock
    moves = [f for f in m.flows if f.counter and f.counter.name == "workflow_pile_moves_total"]
    assert moves and not [f for f in moves if "." in f.counter.labels["from"] + f.counter.labels["to"]]
    [out] = [f for f in moves if f.counter.labels["from"] == step and f.dst is not None]
    eq = out.current()
    assert out.src == found[step].id and eq.inputs == [out_on], eq
    assert not (eq.form == "linear" and eq.params.get("k", 0) < 0), eq                         # no capacity form


def test_a_step_read_away_from_by_its_own_level_is_not_taken_over_by_a_lagging_count_of_it():
    # the team review's re-read loop (seed 8 of the plugin's example): the read's end is fitted on
    # the read step itself; the floor's count of held offers (an input) is the same number a little
    # behind, nonzero while the step reads empty, and is still held to the empty-source test
    m = _model("workflows-team-review.json.gz")
    [done] = [f for f in m.flows if f.counter and f.counter.labels.get("workflow") == "team_review"
              and f.counter.labels.get("from") == "read" and f.counter.labels.get("to") == "comment"]
    assert done.current().inputs == [done.src], done.current()
