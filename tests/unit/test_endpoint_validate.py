"""What POST /events accepts and refuses, before anything is written."""

import json

import pytest

from orchestra.config import ConfigError
from orchestra.endpoint import listen_address
from orchestra.endpoint.validate import MAX_BODY, Invalid, check, number, parse, types_filter


def refused(obj, status=400, says=""):
    with pytest.raises(Invalid) as e:
        check(obj)
    assert e.value.status == status
    assert says in str(e.value)


def test_the_least_an_event_needs_is_a_type_and_a_source():
    assert check({"type": "bread.baked", "source": "baker/2"}) == {"type": "bread.baked", "source": "baker/2", "data": None}


def test_every_field_is_passed_on_and_time_is_normalised_to_utc_milliseconds():
    out = check({"type": "invoice.sent", "source": "billing", "data": {"order": 42, "x": [1, None]},
                 "subject": "order-42", "correlationid": "checkout-7", "causationid": "abc",
                 "time": "2026-10-27T20:58:31.5+02:00", "id": "inv-42"})
    assert out == {"type": "invoice.sent", "source": "billing", "data": {"order": 42, "x": [1, None]},
                   "subject": "order-42", "correlationid": "checkout-7", "causationid": "abc",
                   "time": "2026-10-27T18:58:31.500+00:00", "id": "inv-42"}
    assert check({"type": "a", "source": "b", "time": "2026-10-27T18:58:31Z"})["time"] == "2026-10-27T18:58:31.000+00:00"


def test_a_structured_mode_cloudevent_is_accepted():
    out = check({"specversion": "1.0", "datacontenttype": "application/json", "type": "a.b", "source": "m", "data": 1})
    assert out == {"type": "a.b", "source": "m", "data": 1}


@pytest.mark.parametrize("obj,says", [
    ({"source": "m"}, "type is required"),
    ({"type": "a"}, "source is required"),
    ({"type": "", "source": "m"}, "non-empty"),
    ({"type": 3, "source": "m"}, "string"),
    ({"type": "has space", "source": "m"}, "letters"),
    ({"type": "a", "source": "a/b/c"}, "<machine>/<instance>"),
    ({"type": "a", "source": "/x"}, "<machine>"),
    ({"type": "a", "source": "m", "subject": "x\ny"}, "control"),
    ({"type": "a", "source": "m", "time": "yesterday"}, "RFC 3339"),
    ({"type": "a", "source": "m", "time": "2026-10-27T18:58:31"}, "timezone"),
    ({"type": "a", "source": "m", "id": "has space"}, "printable"),
    ({"type": "a", "source": "m", "ts": 1}, "unknown field ts"),
    ({"type": "a", "source": "m", "specversion": "0.3"}, "specversion"),
    ({"type": "a", "source": "m", "datacontenttype": "text/plain"}, "datacontenttype"),
    ({"type": "a" * 300, "source": "m"}, "at most 256"),
    ({"type": "a", "source": "m", "subject": "s" * 2000}, "at most 1024"),
])
def test_what_is_refused_says_why(obj, says):
    refused(obj, 400, says)


def test_orchestras_own_types_and_source_are_the_hosts_except_a_machines_announcement():
    refused({"type": "orchestra.host.started", "source": "m"}, 403, "Orchestra's own type")
    refused({"type": "orchestra.process.exited", "source": "m"}, 403)
    refused({"type": "x.y", "source": "orchestra-host"}, 403, "own source")
    refused({"type": "x.y", "source": "orchestra-host/2"}, 403)
    assert check({"type": "orchestra.machine.started", "source": "m/1", "data": {"mode": "continuous"}})["type"] == \
        "orchestra.machine.started"
    assert check({"type": "orchestra.machine.subscribed", "source": "m"})["source"] == "m"


def test_the_body_is_one_json_object_of_bounded_size():
    assert parse(b'{"type": "a"}') == {"type": "a"}
    for body, status in [(b"not json", 400), (b"[1, 2]", 400), (b"\xff", 400),
                         (json.dumps({"data": "x" * MAX_BODY}).encode(), 413)]:
        with pytest.raises(Invalid) as e:
            parse(body)
        assert e.value.status == status


def test_query_parameters():
    assert types_filter(None) is None and types_filter("") is None
    assert types_filter("a.b, c") == {"a.b", "c"}
    with pytest.raises(Invalid):
        types_filter("a b")
    assert number(None, "wait", 0.0, 0, 30) == 0.0
    assert number("2.5", "wait", 0.0, 0, 30) == 2.5
    for raw in ("31", "-1", "nan", "x"):
        with pytest.raises(Invalid):
            number(raw, "wait", 0.0, 0, 30)
    with pytest.raises(Invalid):
        number("1.5", "limit", 1, 1, 10, integer=True)


def test_listen_address():
    assert listen_address(None) == ("127.0.0.1", 0)
    assert listen_address("0.0.0.0:8075") == ("0.0.0.0", 8075)
    assert listen_address("[::1]:9000") == ("::1", 9000)
    assert listen_address("off") is None and listen_address(False) is None
    for bad in ("8075", "host:", "h:99999", 8075):
        with pytest.raises(ConfigError):
            listen_address(bad)
