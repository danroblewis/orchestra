"""The web UI's authentication (orchestra/web/auth.py): every route behind the project's token, a
session cookie for browsers, a bearer token for programs, CSRF and guessing refused."""

import os
import re
import stat
import subprocess

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from orchestra import plugins
from orchestra.config import ConfigError, init_project
from orchestra.web import auth
from orchestra.web.app import create_app

ORIGIN = "http://testserver"


class EntryPoint:
    def __init__(self, name, fn):
        self.name, self.fn = name, fn

    def load(self):
        return self.fn


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_HOME", str(tmp_path / "home"))
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    p = init_project(r)

    def outbox(project):                              # a plugin with a page, static files and a JSON write
        (tmp_path / "s").mkdir(exist_ok=True)
        (tmp_path / "s" / "outbox.js").write_text("// outbox")
        page = tmp_path / "outbox.html"
        page.write_text("<nav id='nav'></nav>the outbox")
        router = APIRouter()

        @router.get("/state")
        def state() -> dict:
            return {"ok": True}

        @router.post("/send")
        async def send(request: Request) -> dict:
            return {"ok": True, "sent": (await request.json())["id"]}
        return plugins.Plugin("outbox", [plugins.Page("/outbox", "Outbox", page)], tmp_path / "s", router)
    monkeypatch.setattr(plugins, "entry_points", lambda group: [EntryPoint("outbox", outbox)])
    return p


def set_auth(project, value: str) -> None:
    text = re.sub(r'^(# )?auth = "[^"]*"', f'auth = "{value}"', project.config_file.read_text(), count=1, flags=re.MULTILINE)
    project.config_file.write_text(text)
    project.reload_config()


def logged_in(project) -> TestClient:
    c = TestClient(create_app(project))
    r = c.post("/login", data={"token": auth.token(project), "next": "/core"}, headers={"Origin": ORIGIN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/core"
    return c


def test_the_token_is_the_projects_kept_owner_only(project):
    t = auth.token(project)
    assert len(t) >= 40 and auth.token(project) == t
    assert stat.S_IMODE(os.stat(auth.token_file(project)).st_mode) == 0o600
    assert t not in project.config_file.read_text()


@pytest.mark.parametrize("path", ["/api/core", "/api/machines", "/api/plugins/outbox/state", "/plugins/outbox/static/outbox.js",
                                  "/static/app.js", "/api/session", "/docs", "/openapi.json"])
def test_without_a_login_every_route_is_refused(project, path):
    r = TestClient(create_app(project)).get(path)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("path", ["/", "/core", "/outbox", "/machines?x=1"])
def test_a_page_without_a_login_goes_to_the_login_page_and_back(project, path):
    c = TestClient(create_app(project))
    r = c.get(path, headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    page = c.get(r.headers["location"])
    assert page.status_code == 200 and 'name="token"' in page.text
    assert f'value="{path}"' in page.text.replace("&amp;", "&")


def test_health_stays_open(project):
    assert TestClient(create_app(project)).get("/health").json() == {"ok": True}


def test_a_post_without_a_login_is_refused_and_does_nothing(project):
    r = TestClient(create_app(project)).post("/api/plugins/outbox/send", json={"id": 1}, headers={"Origin": ORIGIN})
    assert r.status_code == 401


def test_the_websocket_is_refused_without_a_login(project):
    c = TestClient(create_app(project))
    with pytest.raises(WebSocketDisconnect) as e, c.websocket_connect("/api/events"):
        pass
    assert e.value.code == 1008


def test_after_logging_in_pages_apis_plugins_and_the_websocket_pass(project):
    c = logged_in(project)
    cookie = c.cookies.get(f"orchestra_{project.key}")
    assert cookie and cookie.startswith("v1.")
    assert c.get("/core", headers={"Accept": "text/html"}).status_code == 200
    assert c.get("/api/plugins/outbox/state").json() == {"ok": True}
    assert c.get("/outbox").text.endswith("the outbox")
    assert c.get("/api/session").json() == {"ok": True, "auth": True, "via": "cookie"}
    with c.websocket_connect("/api/events", headers={"Origin": ORIGIN}):
        pass
    r = c.post("/api/plugins/outbox/send", json={"id": 7}, headers={"Origin": ORIGIN})
    assert r.json() == {"ok": True, "sent": 7}


def test_the_session_cookie_is_httponly_and_samesite_strict(project):
    r = TestClient(create_app(project)).post("/login", data={"token": auth.token(project)}, headers={"Origin": ORIGIN},
                                             follow_redirects=False)
    set_cookie = r.headers["set-cookie"]
    assert "HttpOnly" in set_cookie and "SameSite=Strict" in set_cookie and "Path=/" in set_cookie
    assert "Secure" not in set_cookie                    # plain http to this server
    through_tunnel = TestClient(create_app(project)).post("/login", data={"token": auth.token(project)},
                                                          headers={"Origin": ORIGIN, "X-Forwarded-Proto": "https"}, follow_redirects=False)
    assert "Secure" in through_tunnel.headers["set-cookie"]


def test_a_bearer_token_passes_without_a_cookie_or_an_origin(project):
    c = TestClient(create_app(project), headers=auth.bearer(project))
    assert c.get("/api/core").status_code == 200
    assert c.post("/api/plugins/outbox/send", json={"id": 3}).json()["sent"] == 3
    with c.websocket_connect("/api/events"):
        pass


def test_a_forged_or_expired_cookie_is_no_session(project):
    c = TestClient(create_app(project))
    secret = auth.Secret(project)
    name = f"orchestra_{project.key}"
    c.cookies.set(name, "v1.99999999999.0000")
    assert c.get("/api/core").status_code == 401
    c.cookies.set(name, secret.session(now=1000.0))     # signed, but long expired
    assert c.get("/api/core").status_code == 401


def test_a_wrong_token_is_refused_and_guessing_is_limited(project):
    c = TestClient(create_app(project))
    for _ in range(auth.FAIL_MAX):
        r = c.post("/login", data={"token": "guess"}, headers={"Origin": ORIGIN})
        assert r.status_code == 401 and "not this project" in r.text
    assert c.post("/login", data={"token": "guess"}, headers={"Origin": ORIGIN}).status_code == 429
    r = c.post("/login", data={"token": auth.token(project)}, headers={"Origin": ORIGIN}, follow_redirects=False)
    assert r.status_code == 429                         # even the right one, until the window passes
    assert c.get("/api/core", headers={"Authorization": f"Bearer {auth.token(project)}"}).status_code == 429


def test_a_wrong_bearer_token_counts_as_a_guess(project):
    c = TestClient(create_app(project))
    for _ in range(auth.FAIL_MAX):
        assert c.get("/api/core", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = c.get("/api/core", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_a_session_keeps_working_while_its_peer_is_limited(project):
    app = create_app(project)
    c = TestClient(app)
    c.post("/login", data={"token": auth.token(project)}, headers={"Origin": ORIGIN})
    for _ in range(auth.FAIL_MAX + 1):
        TestClient(app).get("/api/core", headers={"Authorization": "Bearer nope"})
    assert c.get("/api/core").status_code == 200


def test_failures_age_out():
    f = auth.Failures(most=2, window_s=10)
    f.fail("p", now=0)
    f.fail("p", now=1)
    assert f.wait("p", now=2) == pytest.approx(8) and f.wait("q", now=2) == 0
    assert f.wait("p", now=10.5) == 0


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"},
                                     {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
                                     {"Origin": ORIGIN, "Sec-Fetch-Site": "same-site"},
                                     {"Referer": "https://evil.example/page"}, {}])
def test_a_cross_site_post_with_the_cookie_is_refused(project, headers):
    c = logged_in(project)
    r = c.post("/api/plugins/outbox/send", json={"id": 1}, headers=headers)
    assert r.status_code == 403
    assert c.post("/api/dynamics/rediscover", headers=headers).status_code == 403


def test_a_same_origin_post_by_referer_passes(project):
    c = logged_in(project)
    assert c.post("/api/plugins/outbox/send", json={"id": 2}, headers={"Referer": ORIGIN + "/outbox"}).status_code == 200


def test_a_cross_site_websocket_with_the_cookie_is_refused(project):
    c = logged_in(project)
    with pytest.raises(WebSocketDisconnect), c.websocket_connect("/api/events", headers={"Origin": "https://evil.example"}):
        pass


def test_login_from_another_site_is_refused(project):
    r = TestClient(create_app(project)).post("/login", data={"token": auth.token(project)},
                                             headers={"Origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403 and "set-cookie" not in r.headers


@pytest.mark.parametrize("nxt", ["https://evil.example", "//evil.example/x", "/\\evil.example", "/login"])
def test_login_goes_only_to_a_path_here(project, nxt):
    r = TestClient(create_app(project)).post("/login", data={"token": auth.token(project), "next": nxt},
                                             headers={"Origin": ORIGIN}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_logout_ends_the_session(project):
    c = logged_in(project)
    r = c.post("/logout", headers={"Origin": ORIGIN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login" and "Max-Age=0" in r.headers["set-cookie"]
    assert c.get("/api/core").status_code == 401


def test_rotating_the_token_ends_every_session(project):
    c = logged_in(project)
    old = auth.token(project)
    assert c.get("/api/core").status_code == 200
    new = auth.rotate_token(project)
    assert new != old and stat.S_IMODE(os.stat(auth.token_file(project)).st_mode) == 0o600
    assert c.get("/api/core").status_code == 401
    assert c.get("/api/core", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    assert c.get("/api/core", headers={"Authorization": f"Bearer {new}"}).status_code == 200


# ---- the default on loopback, and auth = "off"

def test_auth_is_on_by_default_on_loopback_too(project):
    assert auth.enabled(project, "127.0.0.1") and auth.enabled(project, "0.0.0.0")
    assert TestClient(create_app(project, "127.0.0.1"), base_url="http://127.0.0.1:8000").get("/api/core").status_code == 401


def test_off_is_refused_on_anything_but_loopback(project):
    set_auth(project, "off")
    assert auth.enabled(project, "127.0.0.1") is False and auth.enabled(project, "::1") is False
    assert auth.enabled(project, "localhost") is False
    for host in ("0.0.0.0", "::", "192.168.1.5"):
        with pytest.raises(ConfigError, match="loopback"):
            auth.enabled(project, host)
    set_auth(project, "maybe")
    with pytest.raises(ConfigError, match='"on" or "off"'):
        auth.enabled(project, "127.0.0.1")


def test_off_on_loopback_serves_this_computer_only(project):
    set_auth(project, "off")
    c = TestClient(create_app(project, "127.0.0.1"), base_url="http://127.0.0.1:8000")
    assert c.get("/api/core").status_code == 200
    assert c.get("/api/session").json() == {"ok": True, "auth": False}
    assert c.post("/api/plugins/outbox/send", json={"id": 4}).json()["sent"] == 4
    with c.websocket_connect("/api/events", headers={"Host": "127.0.0.1:8000"}):
        pass
    # a tunnel or proxy in front of it, or a name that resolves here (DNS rebinding): refused
    assert c.get("/api/core", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 403
    assert c.get("/api/core", headers={"Cf-Connecting-Ip": "1.2.3.4"}).status_code == 403
    assert c.get("/api/core", headers={"Host": "demo.trycloudflare.com"}).status_code == 403
    assert c.post("/api/plugins/outbox/send", json={"id": 1}, headers={"Origin": "https://evil.example"}).status_code == 403
    with pytest.raises(WebSocketDisconnect), c.websocket_connect("/api/events", headers={"Host": "127.0.0.1:8000",
                                                                                  "Origin": "https://evil.example"}):
        pass
    assert c.get("/login", follow_redirects=False).headers["location"] == "/"


def test_the_core_page_and_login_work_when_plugins_are_broken(project, monkeypatch):
    def broken(project):
        raise RuntimeError("no database")
    monkeypatch.setattr(plugins, "entry_points", lambda group: [EntryPoint("bad", broken)])
    c = logged_in(project)
    assert c.get("/core").status_code == 200 and c.get("/api/core").json()["bus"]["ok"]


def test_the_cli_prints_and_rotates_the_token(project, capsys, monkeypatch):
    from orchestra.cli import main
    monkeypatch.chdir(project.repo_root)
    assert main(["web", "token"]) == 0
    first = capsys.readouterr().out.strip()
    assert first == auth.token(project)
    assert main(["web", "token", "--rotate"]) == 0
    assert capsys.readouterr().out.strip() == auth.token(project) != first
