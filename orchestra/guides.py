"""Guides: what an AI operator (the Supervisor) reads to configure Orchestra and its plugins.

Orchestra's own guide (``guide.md`` beside this module) comes first, then each loaded plugin's
(``Plugin.guide``), in the order the plugins loaded. A guide is decision knowledge, not a
procedure: what each setting is for, when to choose each value, the pitfalls, how to check a
setting took, and which choices belong to the human. Orchestra serves the text and reads nothing
in it. A plugin whose guide cannot be read is listed with the reason and no text, never fatal."""

from __future__ import annotations

from pathlib import Path

CORE = Path(__file__).parent / "guide.md"


def collect(project, loaded=None) -> list[dict]:
    """``[{"name", "text"}]``: Orchestra's guide (``"orchestra"``), then each plugin's that has one,
    named for the plugin. ``loaded`` is ``plugins.load(project)`` when the caller has it already. A
    guide that cannot be read has ``text`` empty and ``error`` saying why."""
    if loaded is None:
        from .plugins import load
        loaded = load(project)
    out = [_read("orchestra", CORE)]
    for p in loaded.plugins:
        if p.guide is not None:
            out.append(_read(p.name, Path(p.guide)))
    return out


def _read(name: str, path: Path) -> dict:
    try:
        return {"name": name, "text": path.read_text(encoding="utf-8")}
    except (OSError, UnicodeDecodeError) as e:
        return {"name": name, "text": "", "error": f"its guide {path} cannot be read: {type(e).__name__}: {e}"}
