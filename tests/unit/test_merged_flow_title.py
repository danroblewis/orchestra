"""A flow SD Lab merged from several counters is titled by its members' plain names, never by one
counter's raw labels ("workflow pile moves · <start> → write.waiting")."""

from orchestra.sd.strategies import merged_title


def test_moves_into_one_thing_are_said_as_one_inflow_with_how_many_sources():
    assert merged_title(["start → write", "ci → write (sent back)", "review → write (sent back)", "triage → write (sent back)"]) == "into write (4 sources)"


def test_moves_out_of_one_thing_and_unrelated_moves():
    assert merged_title(["review → sail", "review → nudge"]) == "out of review (2 destinations)"
    assert merged_title(["a → b", "c → d"]) == "a → b + c → d"
    assert merged_title(["orders made", "a → b"]) == "orders made + a → b"
