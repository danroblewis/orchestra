"""Changing a project's configuration: the one way anything (a plugin's tool, the Supervisor)
changes a setting, in the repository's ``orchestra.toml`` or in the private overlay
(``orchestra/overlay.py``), so that no plugin opens or edits either file itself.

``project.config_edit`` (a ``ConfigEdit``) has ``set``, ``unset``, ``add_entry`` and
``remove_entry``, each with ``target="repo"`` (the shared ``orchestra.toml``) or ``"overlay"``
(the owner's private file, created on its first change). Each one:

- edits the target file's text through ``tomlkit``, so its comments and layout are kept and only
  what changed differs (``toml_text``);
- validates the merged result, the repository's file with the overlay over it, as Orchestra reads
  it (its settings, ``[[machines]]``, ``[[collect]]`` and ``[[scrape]]``) and as the caller's
  ``check`` does (a plugin passes its own reader): a change that makes any of them say something
  new against the configuration is refused with what they said;
- writes the file whole (a reader never sees half of it), reloads ``project.config`` and returns a
  ``Change``: the file, its text before and after, one line saying what changed, and the keys of
  the merged configuration whose value changed (none when the overlay's value still wins).

``dry_run=True`` returns the ``Change`` without writing it, for a caller with checks of its own
(the Supervisor refuses what looks like a secret); ``apply`` then writes it, unless the file
changed in between. ``restore`` puts a change's file back as it was, when it still holds what the
change wrote. Committing is the caller's choice: Orchestra never commits, and the overlay lives
outside the repository, so it is never committed.

In the overlay an entry is replaced whole by name when merged, so ``add_entry`` there starts from
the repository's entry of that name, and ``remove_entry`` there writes ``{ name, enabled = false }``
when the repository has the entry (which takes it out of the merged configuration) and drops the
overlay's own entry otherwise."""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit

from . import toml_text as tt
from .collect import spec as collect_spec
from .config import Config, ConfigError
from .launcher import check as check_process
from .launcher import from_toml as processes_from_toml
from .overlay import OVERLAY, REPO, OverlayError, describe, merge

if TYPE_CHECKING:
    from .config import Project

TARGETS = (REPO, OVERLAY)
Check = Callable[[dict], list[str]]      # the merged configuration -> what a reader says against it

OVERLAY_HEADER = ("# The private overlay: merged over the repository's orchestra.toml, never committed\n"
                  "# (Orchestra's USING_ORCHESTRA.md §2).\n")


@dataclass
class Change:
    target: str                     # repo | overlay
    file: str                       # the file changed
    what: str                       # one line: what changed (an overlay's values are not repeated)
    before: str | None              # the file's text before; None: there was no file
    after: str                      # its text after
    keys: list[str] = field(default_factory=list)   # keys of the merged configuration whose value changed
    note: str = ""                  # e.g. the overlay's value still wins over a change to the repository

    @property
    def changed(self) -> bool:
        return self.after != (self.before or "")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Change:
        return cls(**{k: d[k] for k in ("target", "file", "what", "before", "after") if k in d},
                   keys=list(d.get("keys") or []), note=d.get("note") or "")


def problems(raw: dict, check: Check | None = None) -> list[str]:
    """What Orchestra's readers, and ``check``, say against a merged configuration."""
    out: list[str] = []
    try:
        Config.from_raw(raw)
    except (ConfigError, ValueError, TypeError) as e:
        out.append(f"Orchestra's settings: {e}")
    try:
        out += [f"[[machines]]: {why}" for p in processes_from_toml(raw) if (why := check_process(p))]
    except TypeError as e:
        out.append(f"[[machines]]: {e}")
    out += collect_spec.from_toml(raw)[1]
    if check is not None:
        try:
            out += list(check(raw))
        except (ConfigError, ValueError, TypeError) as e:
            out.append(str(e))
    return out


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _write(path: Path, text: str, private: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else (0o600 if private else 0o644))
    except OSError:
        pass
    os.replace(tmp, path)


def _shown(value: Any) -> str:
    try:
        return json.dumps(value)
    except TypeError:
        return repr(value)


class ConfigEdit:
    """The configuration of ``project`` as it is changed (see the module's docstring)."""

    def __init__(self, project: Project):
        self.project = project

    def file(self, target: str) -> Path:
        if target not in TARGETS:
            raise ConfigError(f"target is {' or '.join(TARGETS)}, not {target!r}")
        return self.project.config_file if target == REPO else self.project.overlay_file

    def text(self, target: str) -> str | None:
        """The target file's text now (None: there is no overlay)."""
        return _read(self.file(target))

    # what each change does to the document

    def set(self, key, value: Any, *, target: str = REPO, check: Check | None = None, dry_run: bool = False) -> Change:
        """Set ``key`` (``"tasks.workers"``, or a list of parts) to ``value``."""
        parts = tt.split(key)

        def edit(doc, merged):
            tt.set_key(tt.table(doc, parts[:-1], create=True), parts[-1], value)
            return f"{'.'.join(parts)} = {_shown(value)}"
        return self._change(target, edit, check, dry_run)

    def unset(self, key, *, target: str = REPO, check: Check | None = None, dry_run: bool = False) -> Change:
        """Remove ``key``: in the overlay, the repository's value applies again."""
        parts = tt.split(key)

        def edit(doc, merged):
            tt.unset(doc, parts)
            return f"removed {'.'.join(parts)}"
        return self._change(target, edit, check, dry_run)

    def add_entry(self, array, entry: dict[str, Any], *, target: str = REPO, check: Check | None = None,
                  dry_run: bool = False) -> Change:
        """Add the entry ``entry["name"]`` to the array of tables ``array`` (``"machines"``,
        ``"gate.unit"``), or set ``entry``'s fields on it when there is one; fields not given stay."""
        parts = tt.split(array)
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"]:
            raise ConfigError("an entry is a table with a name")
        name = entry["name"]

        def edit(doc, merged):
            where = f"[[{'.'.join(parts)}]] {name}"
            if target == OVERLAY:
                items = tt.entries(doc, parts) or []
                i = tt.find(items, name)
                if i is None or items[i].get("enabled") is False:        # none of its own, or one that removes it
                    base = self._repo_entry(parts, name)
                    tt.replace_entry(doc, parts, {**(base or {}), **entry})
                    return f"{'changed' if base else 'added'} {where}"
            return f"{'added' if tt.upsert(doc, parts, entry) is None else 'changed'} {where}"
        return self._change(target, edit, check, dry_run)

    def remove_entry(self, array, name: str, *, target: str = REPO, check: Check | None = None,
                     dry_run: bool = False) -> Change:
        """Take the entry ``name`` out of ``array``. In the overlay, an entry the repository has is
        taken out of the merged configuration (``enabled = false``)."""
        parts = tt.split(array)
        where = f"[[{'.'.join(parts)}]] {name}"
        if target == REPO:
            return self._change(target, lambda text: (f"removed {where}", tt.remove(text, parts, name)), check, dry_run,
                                on_text=True)

        def edit(doc, merged):
            if self._repo_entry(parts, name) is not None:
                tt.replace_entry(doc, parts, {"name": name, "enabled": False})
                return f"removed {where}"
            items = tt.entries(doc, parts)
            i = tt.find(items, name)
            if i is None:
                raise ConfigError(f"there is no {where} in either file")
            del items[i]
            return f"removed {where}"
        return self._change(target, edit, check, dry_run)

    # writing

    def apply(self, change: Change) -> Change:
        """Write a change made with ``dry_run``; refused when its file changed since."""
        path = Path(change.file)
        if _read(path) != change.before:
            raise ConfigError(f"{path} changed after the change was worked out; work it out again")
        if change.changed:
            _write(path, change.after, private=change.target == OVERLAY)
            self.project.reload_config()
        return change

    def restore(self, change: Change) -> bool:
        """Put the change's file back as it was before it, when the file still holds what the
        change wrote (an overlay the change created is removed). False when it does not."""
        path = Path(change.file)
        if _read(path) != change.after:
            return False
        if change.before is None:
            path.unlink(missing_ok=True)
        else:
            _write(path, change.before, private=change.target == OVERLAY)
        self.project.reload_config()
        return True

    # the work

    def _repo_entry(self, parts: list[str], name: str) -> dict | None:
        items = tt.get(tomllib.loads(self.text(REPO) or ""), parts)
        i = tt.find(items if isinstance(items, list) else [], name)
        return None if i is None else items[i]

    def _merged(self, repo: str, overlay: str | None):
        raw = tomllib.loads(repo)
        if overlay is None:
            return raw, None
        return merge(raw, tomllib.loads(overlay), str(self.file(OVERLAY)))

    def _change(self, target: str, edit, check: Check | None, dry_run: bool, on_text: bool = False) -> Change:
        path = self.file(target)
        texts = {REPO: self.text(REPO), OVERLAY: self.text(OVERLAY)}
        if texts[REPO] is None:
            raise ConfigError(f"there is no {path}")
        before = texts[target]
        try:
            merged, layers = self._merged(texts[REPO], texts[OVERLAY])
        except (tomllib.TOMLDecodeError, OverlayError) as e:
            raise ConfigError(f"the configuration does not read now, so it cannot be changed: {e}") from e
        if on_text:
            what, after = edit(before or "")
        else:
            doc = tomlkit.parse(before if before is not None else OVERLAY_HEADER)
            what = edit(doc, merged)
            after = tomlkit.dumps(doc)
        if target == OVERLAY:
            what = what.split(" = ")[0] + " in the private overlay"     # the overlay's values are not repeated
        change = Change(target, str(path), what, before, after)
        if not change.changed:
            return change
        try:
            new, new_layers = self._merged(*(after if t == target else texts[t] for t in TARGETS))
        except (tomllib.TOMLDecodeError, OverlayError) as e:
            raise ConfigError(f"the change was not made: the result would not read ({e})") from e
        old = set(problems(merged, check))
        said = [p for p in problems(new, check) if p not in old]
        if said:
            raise ConfigError("the change was not made, because " + "; ".join(said))
        was = {r["key"]: r for r in describe(merged, layers)}
        now = {r["key"]: r for r in describe(new, new_layers)}
        change.keys = sorted(k for k in was.keys() | now.keys() if was.get(k) != now.get(k))
        if not change.keys and target == REPO and texts[OVERLAY] is not None:
            change.note = f"the private overlay ({self.file(OVERLAY)}) sets this, and its value still wins"
        return change if dry_run else self.apply(change)
