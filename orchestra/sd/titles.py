"""What the model calls a part named by its instrument's places, named once, here: every page
shows the title (the Dynamics, Machines and Instruments pages, and the diff between versions).

An instrument that counts the things in each place says which label names the place (its
``count`` view's ``place``, ``collect.views``; ``sd.construction`` reads the same). When other
labels of the series spell that label's value, part by part, they are the place in words, in
the order they spell it: ``pile="write.held"`` with ``step="write"`` and ``place="held"`` is the
thing ``write`` and what is said of it there, ``held``. A stock is what sits there: the noun its
series counts (the last word of its name when that is a plural noun: ``workflow_pile_items``,
items), what is said of it, and where: "items held at write". The labels the value does not
spell (``workflow``) are its scope, said only when two scopes share a thing of one name ("items
held at write (hotfix)"). The convention is the labels' own: no label's name is known here
(AGENTS.md rule 1). A series of the ``age`` view with the same labels is "age of" that place.

A move between two places (a ``moves`` view: its ``starts`` and ``stops`` labels hold the
places' values) is named by the things it leaves and enters, whether or not either is a stock:
"write → open_pr"; inside one thing, by what is said of it: "write: waiting → held"; a move to a
thing fewer moves from outside than the one it leaves is "(sent back)" ("ci → write (sent
back)"); a value no place spells is said in its words ("<start>": "start → write"); two moves
that would read alike are said by their places' own parts ("ci (waiting) → write (waiting)"). A
state no series measures between such moves (a hidden passage, ``sd.passing``) is named by the
places its moves name, in words ("items passing open_pr and ci"), or, when they
enter and leave one place, by what sits there ("items waiting at sail"). Label values keep their spelling (``sail_check``, never "sail check"); "-" and "_" are
alike inside a part (``code-review.waiting`` with ``step="code-review"``), and a place value with
no letters in it (``stage="3"``) spells no words, so the series keeps its own name."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .construction import WRITERS


def _parts(value: str) -> list[str]:
    """A place value's parts: split where it is not a word, "-" and "_" kept inside a part
    (``code-review.waiting``: code-review, waiting)."""
    return [p for p in re.split(r"[^\w-]+", value) if p]


def _same(a: str, b: str) -> bool:
    return a.replace("-", "_") == b.replace("-", "_")


@dataclass(frozen=True)
class Place:
    """A place a count spells: its first part (the thing it is at: ``write``), the parts after it
    (what is said of it there: ``held``), the labels it does not spell (``scope``) and the noun of
    what its series counts (``items``)."""

    at: str
    said: tuple[str, ...]
    scope: dict
    noun: str

    @property
    def full(self) -> str:
        """The place in its own parts: "write (held)"."""
        return self.at + (f" ({', '.join(self.said)})" if self.said else "")

    @property
    def sits(self) -> str:
        """What sits there: "items held at write"."""
        return " ".join([self.noun, *self.said, "at", self.at])


# the last word of a series' name that is a measure, not the noun of what it counts
MEASURES = {"seconds", "milliseconds", "bytes", "ratio", "total", "count", "current", "value", "size", "depth", "level"}


def plural(word: str) -> bool:
    """Whether a word of a series' name is the noun of things it counts (items, commits)."""
    return len(word) > 2 and word.endswith("s") and word not in MEASURES


def noun_of(name: str) -> str:
    """What a count of things in places counts, from its series' name: its last word when that
    is a plural noun (``workflow_pile_items``: items), else the name in words."""
    words = [w for w in re.split(r"[\W_]+", name) if w]
    last = words[-1] if words else ""
    return last if plural(last) else " ".join(words)


def _outside(value: str) -> str:
    """A value no place spells, in words: "<start>" is "start"."""
    return " ".join(w for w in re.split(r"[^\w-]+", value) if w) or value


class Places:
    """The places an instrument's count views spell, from every series of the window (``items``:
    name, labels, key), whether or not it became a stock."""

    def __init__(self, items, provenance: dict):
        self.provenance = provenance or {}
        self.by_value: dict[str, list[Place]] = {}
        self.by_labels: dict[tuple, str] = {}
        self.keys: dict[str, list[tuple[Place, str]]] = {}     # place value -> (its place, the key of the count that spells it)
        spelled = []
        for name, labels, key in items:
            if got := self._spelled(name, labels, key):
                spelled.append((labels, got))
                self.by_value.setdefault(got[1], []).append(got[0])
                self.keys.setdefault(got[1], []).append((got[0], key))
        # a thing two scopes share (two workflows with a step of one name): said with its scope
        scopes: dict[str, set] = {}
        for _, (pl, _) in spelled:
            scopes.setdefault(pl.at, set()).add(tuple(sorted(pl.scope.items())))
        self.shared = {at for at, ss in scopes.items() if len(ss) > 1}
        for labels, (pl, _) in spelled:
            self.by_labels[tuple(sorted(labels.items()))] = self._sits(pl)
        moves = [(labels, key, m) for _, labels, key in items if (m := self._move(labels, key))]
        self.depth = self._depths(moves)
        short = [self._move_title(labels, key, full=False) for labels, key, _ in moves]
        self.clash = {t for t in short if t and short.count(t) > 1}

    def _spelled(self, name: str, labels: dict, key: str):
        rec = self.provenance.get(key) or {}
        place = rec.get("place") if rec.get("view") == "count" else None
        value = labels.get(place) if place else None
        if not value or not re.search(r"[^\W\d_]", value):
            return None                                  # a value that spells no words (stage="3"): named by its series
        own = {k: v for k, v in sorted(labels.items()) if k != place and k not in WRITERS}
        spell: list[str] = []
        for part in _parts(value):
            k = next((k for k, v in own.items() if _same(v, part) and k not in spell), None)
            if k is None:
                return None
            spell.append(k)
        if not spell:
            return None
        pl = Place(own[spell[0]], tuple(own[k] for k in spell[1:]), {k: v for k, v in own.items() if k not in spell},
                   rec.get("noun") or noun_of(name))
        return pl, value

    def _sits(self, pl: Place) -> str:
        return pl.sits + self._scoped(pl)

    def _scoped(self, pl: Place) -> str:
        return f" ({', '.join(pl.scope.values())})" if pl.scope and pl.at in self.shared else ""

    def _place(self, value: str, labels: dict) -> Place | None:
        for pl in self.by_value.get(value, []):
            if all(labels.get(k) == v for k, v in pl.scope.items()):
                return pl
        return None

    def place(self, value: str, labels: dict) -> str | None:
        """The place a move's label value names, in its own parts ("write (held)"), among places
        whose other labels the move carries (the same instrument's place)."""
        pl = self._place(value, labels)
        return pl.full if pl else None

    def level(self, labels: dict, key: str, name: str = "") -> str | None:
        """A level's title: what sits in a place its count spells ("items held at write"), or the
        age of them; None otherwise."""
        if got := self._spelled(name, labels, key):
            t = self.by_labels.get(tuple(sorted(labels.items())))
            return t or self._sits(got[0])
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

    def _depths(self, moves: list) -> dict:
        """How many moves from outside each thing is, by scope ((scope, thing) -> n): a move to a
        thing nearer the start than the one it leaves sends the item back."""
        edges: dict[tuple, set] = {}
        for labels, _, (into, out_of, _) in moves:
            a, b = self._place(labels.get(out_of) or "", labels), self._place(labels.get(into) or "", labels)
            if b is not None:
                scope = tuple(sorted(b.scope.items()))
                edges.setdefault((scope, a.at if a else None), set()).add(b.at)
        depth: dict[tuple, int] = {}
        for scope in {sc for sc, src in edges if src is None}:
            frontier, d = [None], 0
            while frontier:
                d += 1
                frontier = [y for x in frontier for y in sorted(edges.get((scope, x), ())) if (scope, y) not in depth]
                for y in frontier:
                    depth.setdefault((scope, y), d)
        return depth

    def _move_title(self, labels: dict, key: str, full: bool | None = None) -> str | None:
        got = self._move(labels, key)
        if not got:
            return None
        into, out_of, rest = got
        src, dst = labels.get(out_of), labels.get(into)
        a = self._place(src, labels) if src else None
        b = self._place(dst, labels) if dst else None
        if not a and not b:
            return None
        end = lambda pl, v: pl.full if pl and full else pl.at if pl else _outside(v) if v else "outside"
        if a and b and a.at == b.at and a.said and b.said:
            title = f"{a.at}: {', '.join(a.said)} → {', '.join(b.said)}"
        else:
            if full is None:
                full = self._move_title(labels, key, full=False) in self.clash
            title = f"{end(a, src)} → {end(b, dst)}"
            sc = tuple(sorted((b or a).scope.items()))
            if a and b and a.at != b.at and self.depth.get((sc, b.at), 0) < self.depth.get((sc, a.at), 0):
                title += " (sent back)"
        known = {**(a.scope if a else {}), **(b.scope if b else {})}
        shared = any(pl and pl.at in self.shared for pl in (a, b))
        kept = {k: v for k, v in rest.items() if shared or known.get(k) != v}
        return title + (f" ({', '.join(kept.values())})" if kept else "")

    def move(self, labels: dict, key: str) -> str | None:
        """A move's title, by the things it leaves and enters ("write → open_pr", "ci → write (sent
        back)", "start → write"; "write: waiting → held" inside one); its places' own parts
        when two moves would read alike; None when neither end is a place."""
        return self._move_title(labels, key)

    def level_series(self, ins: list, outs: list) -> str | None:
        """The key of the count written for the one place a hidden state's moves all enter (``ins``)
        and leave (``outs``), when they name one and its instrument counts it; None otherwise."""
        values = set()
        for cs, into in ((ins, True), (outs, False)):
            for c in cs:
                got = self._move(c.labels, c.key)
                if not got or not (v := c.labels.get(got[0] if into else got[1])):
                    return None
                values.add((v, tuple(sorted((self._place(v, c.labels) or Place("", (), {}, "")).scope.items()))))
        if len(values) != 1:
            return None
        value, scope = next(iter(values))
        return next((k for pl, k in self.keys.get(value, []) if tuple(sorted(pl.scope.items())) == scope), None)

    def between(self, ins: list, outs: list) -> str | None:
        """A hidden state between moves (``ins``, ``outs``: Series), by the places its ins enter and
        its outs leave; None unless every one of them names a place."""
        enter, leave, pls = [], [], []
        for cs, end, into in ((ins, enter, True), (outs, leave, False)):
            for c in cs:
                got = self._move(c.labels, c.key)
                if not got:
                    return None
                label = got[0] if into else got[1]
                pl = self._place(c.labels.get(label) or "", c.labels)
                if not pl:
                    return None
                end.append(pl.full)
                pls.append(pl)
        if not enter or not leave:
            return None
        a, b = list(dict.fromkeys(enter)), list(dict.fromkeys(leave))
        if a == b and len(a) == 1:
            return self._sits(pls[0])                    # one place, entered and left: what sits there
        if a == b:
            name = " or ".join(a)
        else:
            # in words: the things passed, with what is said of them only where the places differ in it
            same = all(p.said == pls[0].said for p in pls)
            word = lambda pl: pl.at if same else f"{pl.at} {' '.join(pl.said)}".strip()
            ins_ = list(dict.fromkeys(word(p) for p in pls[:len(enter)]))
            outs_ = list(dict.fromkeys(word(p) for p in pls[len(enter):]))
            name = f"{pls[0].noun} passing {' or '.join(ins_)} and {' or '.join(outs_)}"
        return name + (self._scoped(pls[0]) if all(p.scope == pls[0].scope for p in pls) else "")
