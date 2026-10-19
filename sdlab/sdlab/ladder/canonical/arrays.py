"""Subscripts (arrays) for the reader (read.py): every subscripted variable is flattened into one
variable per element, so a subscripted stock becomes one SD Lab stock per element.

    subs = Subscripts(section, root)
    subs.coords(element)          -> [("north",), ("south",)]: the element's instances, in order
    subs.instance(element, coord) -> (component, binding): the definition that covers it, and the
                                     range names bound to elements while its equation is read
    subs.resolve(name, binding)   -> the element a subscript in a reference means there

PySD's own SubscriptManager (pysd.builders.python.subscripts) reads the ranges: subranges, copies
(B <-> A), numeric ranges (a1-a10), ranges from files, and the range mappings (A: a1, a2 -> B). A
reference's subscripts are resolved by position against the variable it names, as PySD does: a range
bound in the current definition is its element, a range mapped to a bound one is the element at the
same position, a subrange is the bound element of its family, and a range ending in ! (SUM(x[A!])) is
bound by the aggregation that reads it. A whole range read where one element is meant is an array
operation the flattening cannot hold (blocked as arrays).
"""

from __future__ import annotations

from itertools import product

import numpy as np

F_ARRAYS = "arrays (subscripts)"


class Subscripts:
    def __init__(self, section, root):
        from pysd.builders.python.subscripts import SubscriptManager

        self.sm = SubscriptManager(list(section.subscripts), root)
        self.ranges: dict[str, list[str]] = {k: list(v) for k, v in self.sm.subscripts.items()}
        self.mapping: dict[str, list[str]] = {k: [m for m in (v or []) if isinstance(m, str)] for k, v in self.sm.mapping.items()}
        self._coords: dict[int, list] = {}
        self._cover: dict[int, dict] = {}

    # ---- an element's instances ----
    def expand(self, subs: list[str], exceptions: list | None = None) -> list[tuple]:
        """The coordinates a definition's subscripts cover (ranges expanded), minus its :EXCEPT: ones."""
        out = [tuple(c) for c in product(*[self.ranges[s] if s in self.ranges else [s] for s in subs])]
        for exc in exceptions or []:
            out = [c for c in out if not (len(exc) == len(c) and all(e == x or e in self.ranges.get(x, ()) for e, x in zip(c, exc)))]
        return out

    def coords(self, el) -> list[tuple]:
        """Every instance of an element, in the order of its definitions (() for a scalar)."""
        key = id(el)
        if key not in self._coords:
            seen, cover = {}, {}
            for comp in el.components:
                subs, exc = comp.subscripts
                for c in self.expand(list(subs), exc):
                    seen.setdefault(c, None)
                    cover.setdefault(c, comp)
            self._coords[key], self._cover[key] = list(seen), cover
        return self._coords[key]

    def dims(self, el) -> list[str]:
        """The element's dimensions (range names), as PySD merges its definitions."""
        lists = [list(c.subscripts[0]) for c in el.components]
        if not any(lists):
            return []
        try:
            return list(self.sm.make_merge_list(lists, el.name))
        except Exception:                                                       # noqa: BLE001
            return lists[0]

    def instance(self, el, coord: tuple):
        """(component, binding) for one instance; binding maps the definition's ranges (and the element's
        dimensions) to the instance's elements."""
        self.coords(el)
        comp = self._cover[id(el)].get(tuple(coord))
        if comp is None:
            return None, None
        subs = list(comp.subscripts[0])
        binding = {s: e for s, e in zip(subs, coord) if s in self.ranges}
        for d, e in zip(self.dims(el), coord):
            binding.setdefault(d, e)
        return comp, binding

    # ---- references ----
    def resolve(self, s: str, binding: dict) -> str | None:
        """The element subscript s means under binding (None: a whole range, not one element)."""
        if s in binding:
            return binding[s]
        if s not in self.ranges:
            return s                                                            # an element named directly
        for r, e in binding.items():                                            # a mapped range: same position
            if r in self.ranges and (s in self.mapping.get(r, []) or r in self.mapping.get(s, [])) \
                    and len(self.ranges[r]) == len(self.ranges[s]) and e in self.ranges[r]:
                return self.ranges[s][self.ranges[r].index(e)]
        found = {e for r, e in binding.items() if not r.endswith("!") and e in self.ranges[s]}
        if len(found) == 1:                                                     # a subrange or superrange of a bound one
            return found.pop()
        return None

    def main_position(self, e: str) -> int | None:
        """An element's position (1, 2, ...) in its main range, as Vensim reads a subscript as a number."""
        for name in self.sm.subranges:
            if e in self.ranges.get(name, ()):
                return self.ranges[name].index(e) + 1
        return None

    def number(self, ref: str, binding: dict, py) -> int | None:
        """A range or an element read as a value (x[A] = A): the bound element's position in its main
        range; None when ref names neither."""
        for name in self.ranges:
            if py(name) == ref:
                e = self.resolve(name, binding)
                return None if e is None else self.main_position(e)
        for elems in self.ranges.values():
            for e in elems:
                if py(e) == ref:
                    return self.main_position(e)
        return None

    def array_value(self, arr, comp, coord: tuple) -> float | None:
        """One element of a numeric array definition (x[A, B] = 1, 2; 3, 4)."""
        a = np.asarray(arr, dtype=float)
        subs = list(comp.subscripts[0])
        if a.ndim == 0 or a.size == 1:
            return float(a.reshape(-1)[0])
        at_ranges = [self.ranges[s].index(e) for s, e in zip(subs, coord) if s in self.ranges]
        shape = [len(self.ranges[s]) for s in subs if s in self.ranges]
        if a.ndim == 1 and len(shape) > 1 and a.size == int(np.prod(shape)):          # a tabbed array, read flat
            a = a.reshape(shape)
        if a.ndim == len(at_ranges):
            return float(a[tuple(at_ranges)])
        if a.ndim == len(subs):
            return float(a[tuple(self.ranges[s].index(e) if s in self.ranges else 0 for s, e in zip(subs, coord))])
        return None


def label(name: str, coord: tuple) -> str:
    """A flattened variable's name as PySD writes its output column: Stock A[Entry 1,Column 1]."""
    return f"{name}[{','.join(coord)}]" if coord else name
