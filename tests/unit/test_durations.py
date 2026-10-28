"""Durations in orchestra.toml (orchestra.config.parse_duration), as every section reads them."""

import pytest

from orchestra.collect.spec import from_toml
from orchestra.config import ConfigError, parse_duration


@pytest.mark.parametrize(("text", "seconds"), [
    ("500ms", 0.5), ("30", 30), ("30s", 30), ("5m", 300), ("1h", 3600),
    ("7d", 7 * 86400), ("1.5d", 1.5 * 86400), ("2w", 14 * 86400), (" 3 d ", 3 * 86400),
])
def test_units(text, seconds):
    assert parse_duration(text, 0.0) == seconds


def test_numbers_and_the_default():
    assert parse_duration(90, 1.0) == 90.0 and parse_duration(None, 7.0) == 7.0


@pytest.mark.parametrize("text", ["7 days", "1y", "d", "-1h", "1h30m"])
def test_a_bad_duration_names_the_units(text):
    with pytest.raises(ConfigError, match=r"bad duration .*ms, s, m, h, d or w"):
        parse_duration(text, 0.0)


def test_a_section_takes_days():
    [c], errors = from_toml({"collect": [{"name": "slow", "command": "./x.sh", "every": "1d", "timeout": "1h"}]})
    assert errors == [] and (c.every_s, c.timeout_s) == (86400.0, 3600.0)
