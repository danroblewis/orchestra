"""What the model calls a part named by its instrument's places, named once, here: every page
shows the title (the Dynamics, Machines and Instruments pages, and the diff between versions).

An instrument that counts the things in each place says which label names the place (its
``count`` view's ``place``, ``collect.views``; ``sd.construction`` reads the same). When other
labels of the series spell that label's value, part by part, they are the place in words, in
the order they spell it: ``pile="write.held"`` with ``step="write"`` and ``place="held"`` is
"write (held)"; the series' other values follow ("write (held) · delivery_sail"). The convention
is the labels' own: no label's name is known here (AGENTS.md rule 1). A series of the ``age``
view with the same labels is "age of" that place.

A move between two places (a ``moves`` view: its ``starts`` and ``stops`` labels hold the
places' values) is named by the places, whether or not either is a stock: "write (held) →
open_pr (waiting) · delivery_sail"; a value no place spells is said as it is ("<start>"). A state
no series measures between such moves (a hidden passage, ``sd.passing``) is named by the places
its moves name: the places its ins enter and its outs leave ("open_pr (waiting) … ci (waiting)",
one place said once). Label values keep their spelling (``sail_check``, never "sail check"); "-" and
"_" are alike inside a part (``code-review.waiting`` with ``step="code-review"``), and a place
value with no letters in it (``pile="3"``) spells no words, so the series keeps its own name."""

from __future__ import annotations

import re

from .construction import WRITERS


def _parts(value: str) -> list[str]:
    """A place value's parts: split where it is not a word, "-" and "_" kept inside a part
    (``code-review.waiting``: code-review, waiting)."""
    return [p for p in re.split(r"[^\w-]+", value) if p]


def _same(a: str, b: str) -> bool:
    return a.replace("-", "_") == b.replace("-", "_")


class Places:
    """The places an instrument's count views spell, from every series of the window (``items``:
    name, labels, key), whether or not it became a stock."""

    def __init__(self, items, provenance: dict):
        self.provenance = provenance or {}
        self.by_value: dict[str, list[tuple[str, dict]]] = {}
        self.by_labels: dict[tuple, str] = {}
        for name, labels, key in items:
            if got := self._spelled(labels, key):
                short, value, scope = got
                self.by_value.setdefault(value, []).append((short, scope))
                self.by_labels[tuple(sorted(labels.items()))] = _with(short, scope)

    def _spelled(self, labels: dict, key: str):
        rec = self.provenance.get(key) or {}
        place = rec.get("place") if rec.get("view") == "count" else None
        value = labels.get(place) if place else None
        if not value or not re.search(r"[^\W\d_]", value):
            return None                                  # a value that spells no words (pile="3"): named by its series
        own = {k: v for k, v in sorted(labels.items()) if k != place and k not in WRITERS}
        spell: list[str] = []
        for part in _parts(value):
            k = next((k for k, v in own.items() if _same(v, part) and k not in spell), None)
            if k is None:
                return None
            spell.append(k)
        if not spell:
            return None
        short = own[spell[0]] + (f" ({', '.join(own[k] for k in spell[1:])})" if len(spell) > 1 else "")
        return short, value, {k: v for k, v in own.items() if k not in spell}

    def place(self, value: str, labels: dict) -> str | None:
        """The place a move's label value names, in words, among places whose other labels the
        move carries (the same workflow's pile)."""
        for short, scope in self.by_value.get(value, []):
            if all(labels.get(k) == v for k, v in scope.items()):
                return short
        return None

    def level(self, labels: dict, key: str) -> str | None:
        """A level's title: a place its count spells, or the age of one; None otherwise."""
        if got := self._spelled(labels, key):
            return _with(got[0], got[2])
        age = (self.provenance.get(key) or {}).get("view") == "age"
        t = self.by_labels.get(tuple(sorted(labels.items()))) if age else None
        return "age of " + t if t else None

    def _move(self, labels: dict, key: str):
        rec = self.provenance.get(key) or {}
        if rec.get("view") != "moves":
            return None
        into, out_of = rec.get("starts"), rec.get("stops")
        rest = {k: v for k, v in sorted(labels.items()) if k not in WRITERS and k not in (into, out_of)}
        return into, out_of, rest

    def move(self, labels: dict, key: str) -> str | None:
        """A move's title, by the places it leaves and enters; None when neither is a place."""
        got = self._move(labels, key)
        if not got:
            return None
        into, out_of, rest = got
        src, dst = labels.get(out_of), labels.get(into)
        a = self.place(src, labels) if src else None
        b = self.place(dst, labels) if dst else None
        if not a and not b:
            return None
        return _with(f"{a or src or 'outside'} → {b or dst or 'outside'}", rest)

    def between(self, ins: list, outs: list) -> str | None:
        """A hidden state between moves (``ins``, ``outs``: Series), by the places its ins enter and
        its outs leave; None unless every one of them names a place."""
        enter, leave, scopes = [], [], []
        for cs, end, into in ((ins, enter, True), (outs, leave, False)):
            for c in cs:
                got = self._move(c.labels, c.key)
                if not got:
                    return None
                label = got[0] if into else got[1]
                p = self.place(c.labels.get(label) or "", c.labels)
                if not p:
                    return None
                end.append(p)
                scopes.append(got[2])
        if not enter or not leave:
            return None
        a, b = list(dict.fromkeys(enter)), list(dict.fromkeys(leave))
        name = " or ".join(a) if a == b else f"{' or '.join(a)} … {' or '.join(b)}"
        return _with(name, scopes[0] if all(s == scopes[0] for s in scopes) else {})


def _with(short: str, scope: dict) -> str:
    return short + (f" · {', '.join(scope.values())}" if scope else "")
