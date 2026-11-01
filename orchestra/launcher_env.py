"""The environment of every command Orchestra runs (the launcher's processes, ``[[collect]]``
commands, a source's transform script): ``python`` and ``python3`` are the Python Orchestra runs
in, even inside ``sh -c``. ``child_env`` puts a directory whose ``python`` and ``python3`` are
``sys.executable`` first on the child's PATH (``python_dir``), and a first word ``python`` or
``python3`` is replaced by ``sys.executable`` outright (``own_python``). So a plugin's modules and
Orchestra's own are importable whatever is first on the PATH ``orchestra run`` was started with.
The project's own Python is ``uv run python`` (uv picks the project's environment, not the PATH's)
or ``.venv/bin/python``."""

from __future__ import annotations

import hashlib
import os
import shlex
import sys

from .config import home

PYTHONS = ("python", "python3")   # a command's first word that means the Python Orchestra runs in


def own_python(argv: list[str]) -> list[str]:
    """``argv`` with a first word of ``python`` or ``python3`` replaced by the Python Orchestra runs in,
    so the command imports what Orchestra can (its plugins, ``orchestra`` itself) rather than
    whatever Python is first on the PATH (often none, or another one)."""
    if argv and argv[0] in PYTHONS and sys.executable:
        return [sys.executable, *argv[1:]]
    return argv


def _is_python(path: str) -> bool:
    """Whether ``path`` runs the Python Orchestra runs in: the same file, reached from the same
    directory (a venv's ``bin/python`` and its base interpreter are one file but not one Python)."""
    try:
        return os.path.samefile(path, sys.executable) and os.path.dirname(path) == os.path.dirname(sys.executable)
    except OSError:
        return False


def python_dir() -> str | None:
    """A directory whose ``python`` and ``python3`` are the Python Orchestra runs in: the one
    ``sys.executable`` is in when both names there are it (a venv's or a uv tool's ``bin``), else a
    small one made under Orchestra's home (``~/.orchestrator/python/<id>``) holding two scripts
    that exec it. Scripts, not symlinks: a symlink to a venv's python, outside the venv, starts the
    base interpreter without the venv's packages. None when neither can be had; a directory whose
    ``python`` is another interpreter is never given."""
    exe = sys.executable
    if not exe or not os.path.isabs(exe):
        return None
    here = os.path.dirname(exe)
    if all(_is_python(os.path.join(here, n)) for n in PYTHONS):
        return here
    shim = home() / "python" / hashlib.sha256(exe.encode()).hexdigest()[:12]
    body = f"#!/bin/sh\nexec {shlex.quote(exe)} \"$@\"\n"
    try:
        shim.mkdir(parents=True, exist_ok=True)
        for n in PYTHONS:
            f = shim / n
            if not f.is_file() or f.read_text() != body:
                tmp = shim / f".{n}.{os.getpid()}"
                tmp.write_text(body)
                tmp.chmod(0o755)
                tmp.replace(f)
    except OSError:
        return None
    return str(shim)


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment of a process Orchestra starts: its own, with ``extra``, and ``python_dir``
    first on the PATH, so ``python`` there is Orchestra's Python even inside ``sh -c``.
    ``VIRTUAL_ENV`` is dropped when it names Orchestra's own environment, so a ``uv run`` in the
    child neither warns about it nor takes it for the project's."""
    env = {**os.environ, **(extra or {})}
    if (d := python_dir()) is not None:
        rest = [p for p in env.get("PATH", os.defpath).split(os.pathsep) if p and p != d]
        env["PATH"] = os.pathsep.join([d, *rest])
    venv = env.get("VIRTUAL_ENV")
    if venv and os.path.realpath(venv) == os.path.realpath(sys.prefix):
        del env["VIRTUAL_ENV"]
    return env
