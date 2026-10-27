"""How Orchestra proves who it is to a source: every credential from an environment variable or a
file outside the repository, read when a request is made (so a rotated token is picked up), and
never shown: pages, logs and errors say which kind, where it comes from and whether it is there.

```toml
auth = { bearer_env = "TOKEN" }                       # or bearer_file = "~/.config/x/token"
auth = { header = { name = "API-Token", value_env = "TOKEN" } }
auth = { header = { name = "X-Scope-OrgID", value = "tenant-1" } }   # a header that is no secret
auth = { basic = { user = "orchestra", password_env = "PASS" } }      # or password_file
auth = { client_cert = "~/certs/me.pem", client_key = "~/certs/me.key", ca_file = "~/certs/ca.pem" }
```

Kinds may be combined (a bearer token over mTLS). ``insecure = true`` on the source skips TLS
verification and is always shown as such. Command, OAuth2 and SigV4 are not built yet (the
proposal's slices 2 and 3) and are refused with that reason."""

from __future__ import annotations

import base64
import os
import re
import ssl
from dataclasses import dataclass, field
from pathlib import Path

from . import SourceError

SECRET_HEADER = re.compile(r"(?i)auth|token|key|secret|pass|cookie|session")
LATER = {"bearer_command": "slice 2", "oauth2": "slice 2", "sigv4": "slice 3"}
FIELDS = {"bearer_env", "bearer_file", "header", "basic", "client_cert", "client_key", "ca_file"}


@dataclass
class AuthSpec:
    bearer_env: str | None = None
    bearer_file: str | None = None
    headers: list[dict] = field(default_factory=list)      # {name, value_env | value_file | value}
    basic: dict | None = None                              # {user, password_env | password_file}
    client_cert: str | None = None
    client_key: str | None = None
    ca_file: str | None = None
    problems: list[str] = field(default_factory=list)      # what parsing refused

    @classmethod
    def parse(cls, d: dict) -> AuthSpec:
        a = cls()
        if not isinstance(d, dict):
            a.problems.append("auth must be a table, e.g. auth = { bearer_env = \"TOKEN\" }")
            return a
        for k in d:
            if k in LATER:
                a.problems.append(f"auth {k} is not built yet ({LATER[k]} of the sources proposal)")
            elif k not in FIELDS:
                a.problems.append(f"auth {k}: unknown; a literal secret in orchestra.toml is refused "
                                  "(use bearer_env or bearer_file)" if re.search("(?i)token|bearer|pass|secret|key", k)
                                  else f"auth {k}: unknown (known: {', '.join(sorted(FIELDS))})")
        a.bearer_env, a.bearer_file = d.get("bearer_env"), d.get("bearer_file")
        h = d.get("header") or []
        a.headers = [h] if isinstance(h, dict) else list(h)
        a.basic = d.get("basic")
        a.client_cert, a.client_key, a.ca_file = d.get("client_cert"), d.get("client_key"), d.get("ca_file")
        return a

    def kinds(self) -> list[str]:
        out = []
        if self.bearer_env or self.bearer_file:
            out.append("bearer")
        if self.headers:
            out.append("header")
        if self.basic:
            out.append("basic")
        if self.client_cert or self.client_key:
            out.append("mtls")
        return out or ["none"]


def _path(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def _inside(p: str, root: Path) -> bool:
    try:
        _path(p).relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def auth_problems(a: AuthSpec, repo_root: Path) -> list[str]:
    """Why this auth cannot be used: refusals from parsing, literal secrets, secret files inside
    the repository, and incomplete kinds."""
    out = list(a.problems)
    if a.bearer_env and a.bearer_file:
        out.append("auth: give bearer_env or bearer_file, not both")
    for h in a.headers:
        if not isinstance(h, dict) or not h.get("name"):
            out.append("auth header: give { name = ..., value_env = ... }")
            continue
        if "value" in h and SECRET_HEADER.search(str(h["name"])):
            out.append(f"auth header {h['name']}: a literal secret in orchestra.toml is refused; use value_env or value_file")
        if not any(k in h for k in ("value", "value_env", "value_file")):
            out.append(f"auth header {h['name']}: give value_env, value_file, or value (for a header that is no secret)")
    if a.basic is not None:
        if not isinstance(a.basic, dict) or not a.basic.get("user"):
            out.append("auth basic: give { user = ..., password_env = ... }")
        elif "password" in a.basic:
            out.append("auth basic password: a literal secret in orchestra.toml is refused; use password_env or password_file")
        elif not (a.basic.get("password_env") or a.basic.get("password_file")):
            out.append("auth basic: give password_env or password_file")
    if bool(a.client_cert) != bool(a.client_key):
        out.append("auth mTLS: give both client_cert and client_key")
    secret_files = [("bearer_file", a.bearer_file), ("client_key", a.client_key)]
    secret_files += [(f"header {h.get('name')} value_file", h.get("value_file")) for h in a.headers if isinstance(h, dict)]
    if isinstance(a.basic, dict):
        secret_files.append(("basic password_file", a.basic.get("password_file")))
    for what, p in secret_files:
        if p and _inside(p, repo_root):
            out.append(f"auth {what} is inside the repository, where it would be committed; keep it outside")
    return out


def _secret(env: str | None, file: str | None, what: str) -> str:
    if env:
        v = os.environ.get(env)
        if not v:
            raise SourceError(f"{what}: environment variable {env} is not set")
        return v.strip()
    try:
        return _path(file).read_text().strip()
    except OSError as e:
        raise SourceError(f"{what}: cannot read {file}: {e.strerror}") from None


class Auth:
    def __init__(self, spec: AuthSpec, insecure: bool = False):
        self.spec, self.insecure = spec, insecure
        self._ctx: ssl.SSLContext | None = None

    def headers(self) -> dict[str, str]:
        """The request headers, read now from their variables and files."""
        a, out = self.spec, {}
        if a.bearer_env or a.bearer_file:
            out["Authorization"] = "Bearer " + _secret(a.bearer_env, a.bearer_file, "bearer token")
        if a.basic:
            pw = _secret(a.basic.get("password_env"), a.basic.get("password_file"), "basic password")
            out["Authorization"] = "Basic " + base64.b64encode(f"{a.basic['user']}:{pw}".encode()).decode()
        for h in a.headers:
            out[h["name"]] = str(h["value"]) if "value" in h else _secret(h.get("value_env"), h.get("value_file"), f"header {h['name']}")
        return out

    def ssl_context(self) -> ssl.SSLContext | None:
        """The TLS context for https: the CA file and client certificate when given, no
        verification when ``insecure``; None for the system's defaults."""
        a = self.spec
        if not (a.ca_file or a.client_cert or self.insecure):
            return None
        if self._ctx is None:
            ctx = ssl.create_default_context(cafile=str(_path(a.ca_file)) if a.ca_file else None)
            if a.client_cert:
                try:
                    ctx.load_cert_chain(str(_path(a.client_cert)), str(_path(a.client_key)))
                except (OSError, ssl.SSLError) as e:
                    raise SourceError(f"mTLS: cannot load the client certificate or key: {e}") from None
            if self.insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self._ctx = ctx
        return self._ctx

    def describe(self) -> dict:
        """What may be shown: the kinds, where each credential comes from, and whether it is
        there now. Never a value."""
        a = self.spec
        where: list[dict] = []
        if a.bearer_env or a.bearer_file:
            where.append(_where("bearer", a.bearer_env, a.bearer_file))
        if a.basic:
            where.append({**_where("basic password", a.basic.get("password_env"), a.basic.get("password_file")), "user": a.basic.get("user")})
        for h in a.headers:
            where.append({"what": f"header {h['name']}", "from": "inline (no secret)", "present": True} if "value" in h
                         else _where(f"header {h['name']}", h.get("value_env"), h.get("value_file")))
        if a.client_cert:
            where.append({"what": "client certificate", "from": f"files {a.client_cert}, {a.client_key}",
                          "present": _path(a.client_cert).is_file() and _path(a.client_key).is_file()})
        if a.ca_file:
            where.append({"what": "CA", "from": f"file {a.ca_file}", "present": _path(a.ca_file).is_file()})
        return {"kinds": a.kinds(), "credentials": where, "insecure": self.insecure}


def _where(what: str, env: str | None, file: str | None) -> dict:
    if env:
        return {"what": what, "from": f"environment variable {env}", "present": bool(os.environ.get(env))}
    return {"what": what, "from": f"file {file}", "present": bool(file) and _path(file).is_file()}
