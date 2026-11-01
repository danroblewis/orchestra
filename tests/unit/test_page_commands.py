"""Every command a page tells the user to run (``<code>orchestra …</code>`` in the static pages and
scripts) exists in the CLI, with that action."""

import argparse
import re
from pathlib import Path

from orchestra.cli import build_parser

STATIC = Path(__file__).resolve().parents[2] / "orchestra" / "web" / "static"
CODE = re.compile(r"<code>orchestra ([^<]*)</code>")


def _commands() -> dict[str, set[str] | None]:
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    out = {}
    for name, p in sub.choices.items():
        action = next((a for a in p._actions if a.dest == "action" and a.choices), None)
        out[name] = set(action.choices) if action else None
    return out


def test_every_command_a_page_names_exists():
    cmds, seen = _commands(), []
    for f in sorted([*STATIC.glob("*.html"), *STATIC.glob("*.js")]):
        for words in (m.group(1).split() for m in CODE.finditer(f.read_text())):
            seen.append((f.name, words))
            assert words[0] in cmds, f"{f.name}: orchestra {' '.join(words)}: no command {words[0]}"
            actions = cmds[words[0]]
            if len(words) > 1 and not words[1].startswith("-"):
                assert actions is not None and words[1] in actions, f"{f.name}: orchestra {' '.join(words)}: no action {words[1]}"
    assert any(w[:2] == ["sd", "discover"] for _, w in seen)
