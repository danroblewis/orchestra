"""A machine's cadence (orchestra/cadence.py): a rhythm of its own needs three beats, and a hang
is never learnt as its usual gap."""

from orchestra.cadence import MIN_BEATS, active_within, gaps


def test_two_times_are_one_interval_not_a_cadence():
    assert MIN_BEATS == 3
    assert gaps([100.0, 160.0]) is None
    assert gaps([100.0]) is None and gaps([]) is None


def test_three_times_are_a_cadence():
    assert gaps([100.0, 160.0, 220.0]) == 60.0


def test_a_hang_does_not_stretch_the_cadence():
    beats = [0.0, 60.0, 120.0, 180.0]
    hung = [*beats, 180.0 + 900.0]                   # silent 15 minutes, then heard again
    assert gaps(hung) == 60.0
    assert 900.0 > active_within(gaps(hung))         # the hang is past what counts as active by it
    # the open gap since the last beat is never part of it: only beats are given
    assert gaps(beats) == 60.0
