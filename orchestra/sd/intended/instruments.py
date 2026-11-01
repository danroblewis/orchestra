"""The instruments an attachment may name, as the Instruments page names them (``web/instruments.py``):
a ``[[collect]]`` (a script), a ``[[scrape]]`` (a URL), a plugin's collector ``<plugin>.<name>``
(in the runtime record while a host runs) or a ``[[sources]]`` entry. Read from the configuration
(``project.config``), the runtime record and the sources' cached definitions; never by running or
querying an instrument.

``Instruments.check`` refuses an attachment to an instrument that does not exist, and, for a
source, an instance label that every definition the match selects sums away (its ``by``, or the
grouping of an aggregated view), with that reason (instruments-on-machines.md §2.2)."""

from __future__ import annotations

from .attach import parse
from .checks import IntentError


class Instruments:
    def __init__(self, project):
        self.project = project
        self._kinds: dict[str, str] | None = None
        self._specs = None

    def specs(self):
        if self._specs is None:
            from ...sources.spec import Specs, for_project
            try:
                self._specs = for_project(self.project)
            except Exception:  # noqa: BLE001 - a configuration that cannot be read names no source
                self._specs = Specs()
        return self._specs

    def kinds(self) -> dict[str, str]:
        """Every instrument's name and kind, as the Instruments page lists them
        (``collect.kinds.instrument_kinds``)."""
        if self._kinds is None:
            from ... import runtime
            from ...collect.kinds import instrument_kinds
            from ...collect.spec import from_toml

            try:
                record = runtime.read(self.project).get("instruments") or {}
            except Exception:  # noqa: BLE001 - no record: the configuration's entries stand
                record = {}
            found, _ = from_toml(getattr(self.project.config, "raw", None) or {})
            self._kinds = instrument_kinds(record, found, self.specs().sources)
        return self._kinds

    def source(self, name: str):
        return next((s for s in self.specs().sources if s.name == name), None)

    def definitions(self, name: str) -> list:
        """A source's definitions: the host's cached inference, or only the declared ones."""
        from ...sources.cache import cached
        from ...sources.infer import declared_definitions

        spec = self.source(name)
        if spec is None:
            return []
        declared = declared_definitions(spec, self.specs().declared)
        inf = cached(self.project.state_dir, name) if spec.infer else None
        seen = {d.id for d in declared}
        return declared + [d for d in (inf.kept if inf else []) if d.id not in seen]

    def check(self, att: dict) -> None:
        kinds = self.kinds()
        name = att.get("instrument")
        if name not in kinds:
            known = ", ".join(sorted(kinds)) or "none"
            raise IntentError(f"there is no instrument {name!r} (the Instruments page lists: {known})")
        label = att.get("instance_label")
        if kinds[name] != "source" or not label:
            return
        spec = self.source(name)
        prefix, _ = parse(att.get("match"))
        prefix = prefix.removeprefix(spec.series_prefix)
        defs = [d for d in self.definitions(name) if d.name.startswith(prefix)]
        dropping = [d for d in defs if drops(d, label, spec.aliases())]
        if defs and len(dropping) == len(defs):
            names = ", ".join(f"{d.name} (by {d.group_by or 'nothing'})" for d in dropping[:5])
            raise IntentError(f"instance label {label!r} is summed away by the source's definitions: {names}")


def drops(d, label: str, aliases: dict[str, str]) -> bool:
    """Whether a source definition's results lose ``label``: a ``select`` summed ``by`` labels or an
    aggregated view keeps only its grouping. A query as written is not judged."""
    aggregated = d.view == "increments" or bool(getattr(d, "agg", ""))
    return aggregated and aliases.get(label, label) not in d.group_by and label not in d.group_by
