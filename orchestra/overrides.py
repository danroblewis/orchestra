"""A project's overrides: a fix to an installed package, kept in the project until the package's own
release has it (docs/proposals/agent-first-machines.md §10.1). Orchestra's environments are not
editable installs, so a bug in an installed plugin is patched here, by file, and reported upstream.

An override is ``.orchestra/overrides/<name>.py``, loaded by file location as
``orchestra_local.overrides.<name>`` (AGENTS.md rule 10: never by adding to ``sys.path``)::

    TARGET = "tasking.gate:run_specs"       # module:attribute, the name it replaces
    PACKAGE = "orchestra-tasking==0.9.2"    # applied only while exactly this version is installed
    KIND = "wrap"                           # wrap | replace
    ISSUE = "danroblewis/orchestra-tasking#41"   # where the fix is asked for upstream (optional)

    def override(original):                 # KIND = "wrap": called once with the original,
        def run_specs(*a, **kw):            # returns what takes its place
            ...
        return run_specs

With ``KIND = "replace"``, ``override`` itself takes the attribute's place (it has the target's
signature) and the original is not passed.

**Applied** wherever plugin code runs: each time ``plugins.load`` runs (the host, the web server,
a configuration check) and before a plugin command (``commands.run``), which is how the launcher
starts plugin processes. Idempotent: an override already in place is not applied again; one whose
file changed is applied again from the original kept the first time; one removed, or gone stale,
is taken out and the original put back.

**Stale**: the installed version of ``PACKAGE`` is not the pinned one (or the package is not
installed). It is not applied, so it never outlives the fix it waits for, nor touches code it was
not written against. A broken override (it does not import, a header is missing, the target is not
there, two overrides of one target) is reported and skipped, never fatal.

**The limit**: the attribute is replaced on its module. Code that copied it before (``from x import
y`` run before the override was applied) keeps the original; an override is applied before
plugins are made and before a plugin command runs, which covers the plugins' own entry points, not
a module some other import already took a copy from."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
import threading
import types
from pathlib import Path

DIR = Path(".orchestra") / "overrides"
PREFIX = "orchestra_local.overrides"
KINDS = ("wrap", "replace")
_lock = threading.Lock()
_applied: dict[str, dict] = {}       # target -> {"original", "now", "file", "stamp"}


def _stamp(path: Path) -> tuple:
    st = path.stat()
    return (st.st_mtime_ns, st.st_size)


def _parent(name: str) -> None:
    """``orchestra_local`` and its sub-packages as empty namespaces, so a module loaded by file
    has a parent in ``sys.modules`` (nothing is put on ``sys.path``)."""
    parts = name.split(".")
    for i in range(1, len(parts)):
        mod = ".".join(parts[:i])
        if mod not in sys.modules:
            m = types.ModuleType(mod)
            m.__path__ = []
            sys.modules[mod] = m


def load_file(name: str, path: Path, package_dir: Path | None = None) -> types.ModuleType:
    """A module (or, with ``package_dir``, a package) executed from its file, registered as ``name``."""
    _parent(name)
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(package_dir)] if package_dir else None)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


def _put_back(target: str) -> None:
    rec = _applied.pop(target, None)
    if rec is None:
        return
    mod_name, _, attr = target.partition(":")
    mod = sys.modules.get(mod_name)
    if mod is not None and getattr(mod, attr, None) is rec["now"]:
        setattr(mod, attr, rec["original"])


def _one(path: Path, report: dict, claimed: dict[str, str]) -> None:
    mod = load_file(f"{PREFIX}.{path.stem}", path)
    target, package = getattr(mod, "TARGET", None), getattr(mod, "PACKAGE", None)
    kind, issue = getattr(mod, "KIND", "wrap"), getattr(mod, "ISSUE", None)
    report.update(target=target, package=package, kind=kind, issue=issue)
    if not (isinstance(target, str) and ":" in target):
        raise ValueError('TARGET must be "module:attribute"')
    if not (isinstance(package, str) and "==" in package):
        raise ValueError('PACKAGE must pin the version it was written against: "dist-name==1.2.3"')
    if kind not in KINDS:
        raise ValueError(f"KIND must be one of {', '.join(KINDS)}")
    if not callable(getattr(mod, "override", None)):
        raise TypeError("it defines no override function")
    if target in claimed:
        raise ValueError(f"{target} is already overridden by {claimed[target]}")
    claimed[target] = path.name
    dist, _, pinned = package.partition("==")
    try:
        installed = importlib.metadata.version(dist.strip())
    except importlib.metadata.PackageNotFoundError:
        installed = None
    report["installed"] = installed
    if installed != pinned.strip():
        _put_back(target)
        report["status"] = "stale"
        report["error"] = (f"{dist.strip()} {installed} is installed, not {pinned.strip()}: not applied"
                           if installed else f"{dist.strip()} is not installed: not applied")
        return
    mod_name, _, attr = target.partition(":")
    module = importlib.import_module(mod_name)
    stamp, rec = _stamp(path), _applied.get(target)
    if rec and rec["file"] == str(path) and rec["stamp"] == stamp and getattr(module, attr, None) is rec["now"]:
        report["status"] = "applied"
        return
    original = rec["original"] if rec else getattr(module, attr)    # raises when the target is not there
    new = mod.override(original) if kind == "wrap" else mod.override
    setattr(module, attr, new)
    _applied[target] = {"original": original, "now": new, "file": str(path), "stamp": stamp}
    report["status"] = "applied"


def apply(repo_root: Path | None) -> list[dict]:
    """Apply the project's overrides as they are now; each one's report (``name``, ``file``,
    ``target``, ``package``, ``installed``, ``kind``, ``issue``, ``status``: applied | stale |
    failed, ``error``)."""
    if repo_root is None:
        return []
    d = Path(repo_root).resolve() / DIR
    files = sorted(d.glob("*.py")) if d.is_dir() else []
    out, claimed = [], {}
    with _lock:
        for path in files:
            if path.name.startswith("_"):
                continue
            report = {"kind_of": "override", "name": path.stem, "file": str(DIR / path.name), "status": "failed", "error": None}
            try:
                _one(path, report, claimed)
            except Exception as e:  # noqa: BLE001 - one broken override is reported, never fatal
                report["status"], report["error"] = "failed", f"{type(e).__name__}: {e}"
            out.append(report)
        live = {(str(d / f"{r['name']}.py"), r["target"]) for r in out if r["status"] == "applied"}
        for target, rec in list(_applied.items()):
            if rec["file"].startswith(str(d)) and (rec["file"], target) not in live:
                _put_back(target)
    return out
