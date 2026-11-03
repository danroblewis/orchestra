"""What the model calls a part named by its instrument's places, named once, here: every page
shows the title (the Dynamics, Machines and Instruments pages, and the diff between versions),
with its tags beside it.

A title says the place and the state only (the owner, 2026-11-02: "I don't know what 'deliveries'
means"); what narrows it is said as **tags**, a list of short strings beside the name, never in
it: each label of the series the place's value does not spell, as ``label=value``
(``workflow=delivery_sail``), then the noun its instrument's view declares, bare (``deliveries``).
The noun a series' own name ends in (``workflow_pile_items``: items) is its unit, said by neither.

An instrument that counts the things in each place says which label names the place (its
``count`` view's ``place``, ``collect.views``; ``sd.construction`` reads the same). When other
labels of the series spell that label's value, part by part, they are the place in words, in
the order they spell it: ``pile="write.held"`` with ``step="write"`` and ``place="held"`` is the
thing ``write`` and what is said of it there, ``held``. A stock is what is said of what sits
there, and where: "held at write". A value of one part (``step="review"``, spelled by another
label or by none) is the thing itself, a state, not a place: what sits there is "in" it ("in review", the owner, 2026-11-02: "it is in
the PR review state"), never "at review". The labels the value does not spell (``workflow``,
and whatever else narrows it: held or waiting, when a plugin says it so) are its scope, its tags:
two scopes that share a thing of one name read alike ("held at write") and are told apart by
them (``workflow=hotfix``); a move that does not carry a scope label (held or waiting) names
the thing all the same. The convention is the labels' own: no label's name is known here
(AGENTS.md rule 1). A series of the ``age`` view with the same labels is the age of what sits
there, in the stock's wording ("age at write (held)"; "age in review").

A move between two places (a ``moves`` view: its ``starts`` and ``stops`` labels hold the
places' values) is named by the things it leaves and enters, whether or not either is a stock:
"write → open_pr"; inside one thing, by what is said of it: "write: waiting → held"; a move to a
thing fewer moves from outside than the one it leaves is "(sent back)" ("ci → write (sent
back)"); a value in angle brackets is outside ("<start>": "outside → write"), any other value no
place spells is said in its words; the move's other labels are its tags; two moves that would
read alike with the same tags are said by their places' own parts ("ci (waiting) → write
(waiting)"). A state no series measures between such moves (a hidden passage, ``sd.passing``) is
named by the first and last things its items pass, in words ("between write and sail_check"; the
places it spans, in order, listed beside it: ``spans``), never by joining their states (the owner,
2026-11-01: "how are all of these considered one stock?"), or, when they enter and leave one
place, by what sits there ("waiting at sail"; "in sail" for a one-part place); by the one
thing, when its places are its states ("at write"); its tags are its places' scope and noun.
Label values keep their spelling (``sail_check``, never "sail check"); "-" and "_" are alike
inside a part (``code-review.waiting`` with ``step="code-review"``), and a place value with no
letters in it (``stage="3"``) spells no words, so the series keeps its own name.

**A series read from another system's store** (``orchestra.sources``: its provenance names its
``source``) has no count view, so it keeps its own name, said in words (``sourced``): the metric's
name without the source's prefix (``hackriff_prom:queue_depth``: ``queue_depth``), ``_`` and ``:``
as spaces, the unit dropped when it is a suffix the series' type says (a counter's ``_total``; a
level's ``_<unit>`` when its source says that unit, a named one, not a count), and the values of
the labels that differ among its sibling series (the series of the same name) as the said part,
each value once: "queue depth (hk-api)", "queue depth (writes, hk-store)". The source and the
labels that say which series it is are its tags, ``source=hackriff_prom`` first, then each label
as ``label=value``, a value two labels carry said once (by the label the source names its
machines by, when one of them is: its ``machine_label``). No label's name is known here (rule 1);
the source's own words never stand in its name ("hackriff prom:queue depth", bootstrap run 5)."""

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
    (what is said of it there: ``held``), the labels it does not spell (``scope``) and the noun its
    instrument's view declares of what it counts (``deliveries``; "" when none)."""

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
        """What is said of what sits there, and where: "held at write"; "in review" when nothing is
        said of it (the thing is the state)."""
        return " ".join([*self.said, "at", self.at]) if self.said else f"in {self.at}"

    @property
    def age(self) -> str:
        """The age of what sits there, in the stock's wording: "age at write (held)"; "age in review"."""
        return ("age at " if self.said else "age in ") + self.full

    @property
    def tags(self) -> list[str]:
        """What narrows it, said beside its name: its scope's labels (``workflow=hotfix``), then its noun."""
        return [f"{k}={v}" for k, v in self.scope.items()] + ([self.noun] if self.noun else [])


def merge_tags(*lists) -> list[str]:
    """Tags of several parts, each once, in the order first said."""
    return list(dict.fromkeys(t for ts in lists for t in ts or ()))


# the last word of a series' name that is a measure, not the noun of what it counts (``plural``)
MEASURES = {"seconds", "milliseconds", "bytes", "ratio", "total", "count", "current", "value", "size", "depth", "level"}


def plural(word: str) -> bool:
    """Whether a word of a series' name is the noun of things it counts (items, commits)."""
    return len(word) > 2 and word.endswith("s") and word not in MEASURES


def _outside(value: str) -> str:
    """A value no place spells, in words: one in angle brackets (``<start>``, ``<end>``) is outside
    the system, "outside", one word for one idea (R3, the information designer); any other, its words."""
    if re.fullmatch(r"<[^>]*>", value or ""):
        return "outside"
    return " ".join(w for w in re.split(r"[^\w-]+", value) if w) or value


NOT_SAID = WRITERS | {"simulated", "draft"}     # who wrote a series, never which one it is
OWN = "own"                                    # the own store's provenance source (orchestra.sources.own.OWN)


def remote(rec: dict) -> bool:
    """Whether a series' provenance says it was read from another system's store (a ``[[sources]]``
    entry), not the own store."""
    return rec.get("source") not in (None, "", OWN)


def _said_values(labels: dict, keys) -> list[str]:
    """The values of ``keys`` in ``labels``, by label, each once, and none whose words another
    value already says (a queue ``analytics.clicks`` says ``analytics``)."""
    vals = list(dict.fromkeys(v for k, v in sorted(labels.items()) if k in keys and re.sub(r"\W+", "", v)))
    words = [set(filter(None, re.split(r"\W+", v))) for v in vals]
    return [v for i, v in enumerate(vals) if not any(j != i and words[i] < words[j] for j in range(len(vals)))]


def sourced_words(name: str, rec: dict) -> str:
    """A source-fed series' metric name in words: without the source's prefix, ``_`` and ``:`` as
    spaces, the unit its type says dropped (a counter's ``_total``, a level's named unit)."""
    base = name.partition(":")[2] if ":" in name else name
    if rec.get("kind") in ("counter", "rate"):
        base = re.sub(r"_total$", "", base)
    elif (unit := str(rec.get("unit") or "")) and unit not in ("count", "items", "1") and base.endswith("_" + unit) and base != "_" + unit:
        base = base[: -len(unit) - 1]
    return " ".join(w for w in re.split(r"[_:]+", base) if w) or name


class Places:
    """The places an instrument's count views spell, from every series of the window (``items``:
    name, labels, key), whether or not it became a stock."""

    def __init__(self, items, provenance: dict):
        self.provenance = provenance or {}
        # a source-fed series' siblings (the series of its name): the labels whose values differ among them
        values: dict[str, dict[str, set]] = {}
        keys_of: dict[str, set[str]] = {}
        sourced = [(name, labels) for name, labels, key in items if remote(self.provenance.get(key) or {})]
        for name, labels in sourced:
            keys_of.setdefault(name, set()).update(k for k in labels if k not in NOT_SAID)
        for name, labels in sourced:
            for k in keys_of[name]:
                values.setdefault(name, {}).setdefault(k, set()).add(labels.get(k))
        self.varying = {name: {k for k, vs in by.items() if len(vs) > 1} for name, by in values.items()}
        self.by_value: dict[str, list[Place]] = {}
        self.by_labels: dict[tuple, Place] = {}
        self.keys: dict[str, list[tuple[Place, str]]] = {}     # place value -> (its place, the key of the count that spells it)
        spelled = []
        for name, labels, key in items:
            if got := self._spelled(name, labels, key):
                spelled.append((labels, got))
                self.by_value.setdefault(got[1], []).append(got[0])
                self.keys.setdefault(got[1], []).append((got[0], key))
        for labels, (pl, _) in spelled:
            self.by_labels[tuple(sorted(labels.items()))] = pl
        moves = [(labels, key, m) for _, labels, key in items if (m := self._move(labels, key))]
        self.depth = self._depths(moves)
        self.next: dict[str, set[str]] = {}            # place value -> the place values a move takes items to
        for labels, _, (into, out_of, _) in moves:
            a, b = labels.get(out_of), labels.get(into)
            if a and b and self._place(a, labels) and self._place(b, labels):
                self.next.setdefault(a, set()).add(b)
        # two moves that read alike with the same tags (two scopes' moves differ by their tags)
        short = [(t, tuple(self.move_tags(labels, key))) for labels, key, _ in moves if (t := self._move_title(labels, key, full=False))]
        self.clash = {t for t in short if short.count(t) > 1}

    def _spelled(self, name: str, labels: dict, key: str):
        rec = self.provenance.get(key) or {}
        place = rec.get("place") if rec.get("view") == "count" else None
        value = labels.get(place) if place else None
        if not value or not re.search(r"[^\W\d_]", value):
            return None                                  # a value that spells no words (stage="3"): named by its series
        own = {k: v for k, v in sorted(labels.items()) if k != place and k not in WRITERS}
        parts = _parts(value)
        spell: list[str] = []
        for part in parts:
            k = next((k for k, v in own.items() if _same(v, part) and k not in spell), None)
            if k is None:
                spell = []
                break
            spell.append(k)
        if spell:
            at, said = own[spell[0]], tuple(own[k] for k in spell[1:])
        elif len(parts) == 1:
            at, said = value, ()                         # one part no other label spells: the thing itself
        else:
            return None
        pl = Place(at, said, {k: v for k, v in own.items() if k not in spell}, rec.get("noun") or "")
        return pl, value

    def sourced(self, name: str, labels: dict, key: str) -> str | None:
        """A source-fed series' title (the module's docstring): its metric's words and the values of
        the labels that differ among its siblings; None for a series of the own store."""
        rec = self.provenance.get(key) or {}
        if not remote(rec):
            return None
        said = _said_values(labels, self.varying.get(name, set()))
        return sourced_words(name, rec) + (f" ({', '.join(said)})" if said else "")

    def sourced_tags(self, name: str, labels: dict, key: str) -> list[str]:
        """A source-fed series' tags: ``source=<name>``, then the labels that say which series it
        is, a value two labels carry once (by the source's machine label, when one is); []
        for a series of the own store."""
        rec = self.provenance.get(key) or {}
        if not remote(rec):
            return []
        own = {k: v for k, v in sorted(labels.items()) if k not in NOT_SAID and v}
        first = rec.get("machine_label")
        order = sorted(own, key=lambda k: (k != first, k))
        by_value: dict[str, str] = {}
        for k in order:
            by_value.setdefault(own[k], k)
        kept = set(by_value.values())
        return [f"source={rec['source']}"] + [f"{k}={own[k]}" for k in sorted(own) if k in kept]

    def _place(self, value: str, labels: dict) -> Place | None:
        """The place a value names among those whose scope the labels carry; else, among those
        whose scope agrees on the labels carried (a move that does not say what the count's
        other labels say: held or waiting), that place within the labels' own scope."""
        for pl in self.by_value.get(value, []):
            if all(labels.get(k) == v for k, v in pl.scope.items()):
                return pl
        for pl in self.by_value.get(value, []):
            if all(labels.get(k) == v for k, v in pl.scope.items() if k in labels):
                return Place(pl.at, pl.said, {k: v for k, v in pl.scope.items() if k in labels}, pl.noun)
        return None

    def place(self, value: str, labels: dict) -> str | None:
        """The place a move's label value names, in its own parts ("write (held)"), among places
        whose other labels the move carries (the same instrument's place)."""
        pl = self._place(value, labels)
        return pl.full if pl else None

    def _level_place(self, labels: dict, key: str, name: str) -> tuple[Place, bool] | None:
        if got := self._spelled(name, labels, key):
            return got[0], False
        age = (self.provenance.get(key) or {}).get("view") == "age"
        pl = self.by_labels.get(tuple(sorted(labels.items()))) if age else None
        return (pl, True) if pl else None

    def level(self, labels: dict, key: str, name: str = "") -> str | None:
        """A level's title: what is said of what sits in a place its count spells, and where ("held
        at write"; "in review" when nothing is said), or the age of it in the same wording ("age at
        write (held)"; "age in review"); None otherwise."""
        got = self._level_place(labels, key, name)
        if not got:
            return None
        pl, age = got
        return pl.age if age else pl.sits

    def level_tags(self, labels: dict, key: str, name: str = "") -> list[str]:
        """A level's tags: its place's scope and noun ([] when its places do not name it)."""
        got = self._level_place(labels, key, name)
        return got[0].tags if got else []

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
        into, out_of, _ = got
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
                full = (self._move_title(labels, key, full=False), tuple(self.move_tags(labels, key))) in self.clash
            title = f"{end(a, src)} → {end(b, dst)}"
            sc = tuple(sorted((b or a).scope.items()))
            if a and b and a.at != b.at and self.depth.get((sc, b.at), 0) < self.depth.get((sc, a.at), 0):
                title += " (sent back)"
        return title

    def move(self, labels: dict, key: str) -> str | None:
        """A move's title, by the things it leaves and enters ("write → open_pr", "ci → write (sent
        back)", "outside → write"; "write: waiting → held" inside one); its places' own parts
        when two moves with the same tags would read alike; None when neither end is a place."""
        return self._move_title(labels, key)

    def move_tags(self, labels: dict, key: str) -> list[str]:
        """A move's tags: its labels other than its places' (``workflow=hotfix``), then its places'
        noun; [] when neither end is a place."""
        got = self._move(labels, key)
        if not got:
            return []
        into, out_of, rest = got
        ends = [pl for v in (labels.get(out_of), labels.get(into)) if v and (pl := self._place(v, labels))]
        if not ends:
            return []
        return merge_tags([f"{k}={v}" for k, v in rest.items()], [pl.noun for pl in ends if pl.noun])

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

    def _ends(self, ins: list, outs: list):
        """The places a hidden state's ins enter and its outs leave, as (value, Place) lists; None
        unless every one of them names a place."""
        enter, leave = [], []
        for cs, end, into in ((ins, enter, True), (outs, leave, False)):
            for c in cs:
                got = self._move(c.labels, c.key)
                if not got:
                    return None
                v = c.labels.get(got[0] if into else got[1]) or ""
                pl = self._place(v, c.labels)
                if not pl:
                    return None
                end.append((v, pl))
        return (enter, leave) if enter and leave else None

    def spans(self, ins: list, outs: list) -> list[str]:
        """The places a hidden state spans, in the order items pass them ("write (held)", "open_pr
        (waiting)", …, "sail_check (waiting)"): those on a path of moves from a place its ins enter
        to one its outs leave; the places entered and left alone when no such path is measured."""
        got = self._ends(ins, outs)
        if not got:
            return []
        enter, leave = got
        starts, stops = [v for v, _ in enter], {v for v, _ in leave}
        dist: dict[str, int] = {}
        frontier, d = list(dict.fromkeys(starts)), 0
        while frontier:
            for v in frontier:
                dist.setdefault(v, d)
            d += 1
            frontier = [w for v in frontier for w in sorted(self.next.get(v, ())) if w not in dist]
        back: dict[str, set[str]] = {}
        for a, bs in self.next.items():
            for b in bs:
                back.setdefault(b, set()).add(a)
        reach, todo = set(stops), list(stops)
        while todo:
            for a in back.get(todo.pop(), ()):
                if a not in reach:
                    reach.add(a)
                    todo.append(a)
        on = [v for v in dist if v in reach] if stops & set(dist) else list(dict.fromkeys([*starts, *(v for v, _ in leave)]))
        on.sort(key=lambda v: (dist.get(v, d), v))
        pls = {v: pl for v, pl in enter + leave}
        out = []
        for v in on:
            pl = pls.get(v) or next(iter(self.by_value.get(v, [])), None)
            if pl is not None and pl.full not in out:
                out.append(pl.full)
        return out

    def between(self, ins: list, outs: list) -> str | None:
        """A hidden state between moves (``ins``, ``outs``: Series), by the first and last things
        its items pass ("between write and sail_check"), never by joining their states; what is
        said of what sits there when they enter and leave one place ("waiting at sail"); None
        unless every one of them names a place."""
        got = self._ends(ins, outs)
        if not got:
            return None
        enter, leave = got
        pls = [pl for _, pl in enter + leave]
        a, b = list(dict.fromkeys(pl.full for _, pl in enter)), list(dict.fromkeys(pl.full for _, pl in leave))
        if a == b and len(a) == 1:
            return pls[0].sits                           # one place, entered and left: what sits there
        first = list(dict.fromkeys(pl.at for _, pl in enter))
        last = list(dict.fromkeys(pl.at for _, pl in leave))
        if first == last:
            return f"at {' or '.join(first)}"
        return f"between {' or '.join(first)} and {' or '.join(last)}"

    def between_tags(self, ins: list, outs: list) -> list[str]:
        """A hidden state's tags: its places' scopes and nouns, each once ([] unless its places name it)."""
        got = self._ends(ins, outs)
        return merge_tags(*(pl.tags for _, pl in got[0] + got[1])) if got else []
