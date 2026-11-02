"""Every envelope's time is written in one format, UTC to the millisecond ending in Z, whatever the
caller passed (core row 5: the bus held +00:00, Z and -08:00 side by side)."""

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from orchestra.events import envelope, event_time, now, utc_time

FORMAT = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
WHEN = "2026-10-27T18:58:31.043Z"


@pytest.mark.parametrize("given", [
    "2026-10-27T18:58:31.043Z",
    "2026-10-27T18:58:31.043+00:00",
    "2026-10-27T10:58:31.043-08:00",
    "2026-10-27T10:58:31.043-0800",
    "2026-10-28T00:28:31.043456+05:30",
    "2026-10-27T18:58:31.043",                                   # no zone: taken as UTC
    "2026-10-27 18:58:31.043",
    datetime(2026, 10, 27, 18, 58, 31, 43000, tzinfo=UTC),
    datetime(2026, 10, 27, 10, 58, 31, 43000, tzinfo=timezone(timedelta(hours=-8))),
    datetime(2026, 10, 27, 18, 58, 31, 43000),                   # naive: taken as UTC
    datetime(2026, 10, 27, 18, 58, 31, 43000, tzinfo=UTC).timestamp(),
])
def test_every_form_is_written_as_utc_with_z(given):
    ev = envelope("x.happened", "m", time=given)
    assert ev["time"] == WHEN and FORMAT.match(ev["time"])
    assert event_time(ev) == pytest.approx(datetime(2026, 10, 27, 18, 58, 31, 43000, tzinfo=UTC).timestamp())


def test_now_and_a_seconds_only_time_are_in_the_format():
    assert FORMAT.match(envelope("x.happened", "m")["time"]) and FORMAT.match(now())
    assert utc_time("2026-10-27T18:58:31Z") == "2026-10-27T18:58:31.000Z"


def test_a_time_that_is_not_one_is_refused():
    with pytest.raises(ValueError, match="not ISO 8601"):
        envelope("x.happened", "m", time="last tuesday")
    with pytest.raises(TypeError):
        envelope("x.happened", "m", time=True)
