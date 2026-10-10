"""Tests for the tunnel-health decision logic.

These verify the key requirement: only restart the cloudflared tunnel when the
web app is healthy but the public tunnel URL is down -- never restart the tunnel
for a problem that is really the web app itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

import web.server as server  # noqa: E402


@pytest.fixture
def fake_probe(monkeypatch):
    """Replace server._probe with a configurable stub.

    ``responses`` maps a URL -> status code (or None for unreachable).
    """

    def _install(responses: dict):
        def _probe(url: str):
            return responses.get(url)

        monkeypatch.setattr(server, "_probe", _probe)

    return _install


def test_both_up_reuses_tunnel(fake_probe):
    # Real cloudflared URLs are bare domains (no trailing slash).
    fake_probe(
        {
            "http://127.0.0.1:8000/": 200,
            "https://good.trycloudflare.com": 200,
        }
    )
    assert server._tunnel_healthy(8000, "https://good.trycloudflare.com") is True


def test_webapp_down_but_tunnel_up_does_not_restart(fake_probe):
    """The startup race: the app isn't serving yet, but the tunnel is fine.

    We must NOT restart the tunnel just because localhost is down at startup --
    that would spin up a needless new tunnel.
    """
    fake_probe(
        {
            "http://127.0.0.1:8000/": None,  # app not serving yet
            "https://good.trycloudflare.com": 200,
        }
    )
    assert server._tunnel_healthy(8000, "https://good.trycloudflare.com") is True


def test_webapp_down_and_tunnel_down_never_reuses(fake_probe):
    """Both down -> not healthy, so a fresh attempt is warranted."""
    fake_probe(
        {
            "http://127.0.0.1:8000/": None,
            "https://dead.trycloudflare.com": 502,
        }
    )
    assert server._tunnel_healthy(8000, "https://dead.trycloudflare.com") is False


def test_tunnel_down_but_webapp_up_triggers_restart(fake_probe):
    """The important case: app healthy, tunnel dead -> restart the tunnel."""
    fake_probe(
        {
            "http://127.0.0.1:8000/": 200,
            "https://dead.trycloudflare.com": 502,
        }
    )
    assert server._tunnel_healthy(8000, "https://dead.trycloudflare.com") is False


def test_unreachable_tunnel_is_unhealthy(fake_probe):
    fake_probe(
        {
            "http://127.0.0.1:8000/": 200,
            "https://unreachable.trycloudflare.com": None,
        }
    )
    assert server._tunnel_healthy(8000, "https://unreachable.trycloudflare.com") is False


def test_probe_tunnel_falls_back_to_cloudflared_alive(fake_probe, monkeypatch):
    """When the public URL can't be probed but cloudflared is running our
    named tunnel, the tunnel is considered reusable."""
    fake_probe(
        {
            "http://127.0.0.1:8000/": 200,
            "https://orchestra.dansproject.space": None,  # DNS not propagated
        }
    )
    monkeypatch.setattr(server, "_cloudflared_tunnel_alive", lambda name: True)
    assert server._probe_tunnel("https://orchestra.dansproject.space", 8000) is True


def test_probe_tunnel_no_reuse_when_cloudflared_down(fake_probe, monkeypatch):
    """Public URL down AND no cloudflared process -> not reusable (restart)."""
    fake_probe(
        {
            "http://127.0.0.1:8000/": 200,
            "https://orchestra.dansproject.space": None,
        }
    )
    monkeypatch.setattr(server, "_cloudflared_tunnel_alive", lambda name: False)
    assert server._probe_tunnel("https://orchestra.dansproject.space", 8000) is False


def test_5xx_from_tunnel_marks_unhealthy(fake_probe):
    fake_probe(
        {
            "http://127.0.0.1:8000/": 200,
            "https://5xx.trycloudflare.com": 503,
        }
    )
    assert server._tunnel_healthy(8000, "https://5xx.trycloudflare.com") is False
