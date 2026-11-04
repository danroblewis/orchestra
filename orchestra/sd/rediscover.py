"""Rediscover the model: discover it from the metrics store over a recent window, with the
configured strategy, cache the result for readers, and save it as a new version when its structure
changed.

One code path for every caller: the bootstrap host (every ``[discovery] every``), ``orchestra sd
discover``, and the Dynamics page's "rediscover" button, which may name another strategy or other
options for that one run. One discovery runs at a time per project, across processes (a lock file
in the state directory): the host skips a scheduled run while another holds it, the others wait.
An SD Lab strategy is given a deadline below ``[discovery] every``, so one run cannot outlast the
interval. The window's ends are on multiples of the step (``aligned``), so runs a few seconds
apart sample the same grid: on a grid shifted by a few seconds a state that lasts a moment is
seen in a different number of steps, and a borderline stock comes and goes between runs.

The series come through one catalogue (``orchestra.sources.catalogue``): the own store's as they
are, and each remote source's read for exactly this window and step. When a source is missing
(refused, unreachable, failing), the model is discovered from what arrived and cached for the
page with the reason, but never saved as a version: a version without a source would delete its
stocks and churn versions with every outage. A run long after the previous one (the machine
slept) reads the whole window again like any other and records the gap.

**Eras** (``sd.eras``, ``sd.prior``). The window never reaches back past the start of the current
era for what the era's change could have altered: after a machine changed the system, what came
before is not evidence for it. A change of the project's configuration (``config.changed``) alters
nothing another system's store measures, so a source's series keep their history through it: the
window reaches back to the last era begun otherwise, and the own store's series are read from the
current era's start (``cuts``; ``discovery["sources_kept"]``). Given the bus
(``events``: the host, ``orchestra sd discover``), the eras are brought up to date from it first
and each new one is announced (``orchestra.era.started``); otherwise (the web page's button) the
eras the host recorded are used. When the era is new since the last discovery, that discovery
(the previous era's last model) is saved as a version first, so the past era stays readable. What
was found in the era is then merged with its prior, the latest version of another era
(``sd.prior.merge``), compared with it (``sd.compare``: ``discovery["era_comparison"]``), and
saved as a version when its structure changed or it is the era's first.

**The sources' history** (``sources.held``). With the configured window (no window or step asked
for), a source's first read finds how far back it holds, up to its ``history`` (7 days), and the
window is the longer of ``[discovery] window`` and that, up to ``MAX_WINDOW`` but no longer than the
era that cuts the sources (``cuts``), in whole multiples of the window with the step scaled alike (``held_window``: the grid
keeps its number of steps); ``discovery["history"]`` says so. A source added with a week behind it
gives a model from its first discovery, not an hour later.

**A quiet window** (``sd.quiet``). A stock of the current version whose series was written to the
end of the window and moved fewer than five times in it (for a hidden stock, every counter of its
flows) is carried into the discovery from that version, with its flows, before the structures are
compared: a window with too little motion is no evidence
that a stock is gone, so it never saves a poorer version. When nothing else changed, no version
is saved and the record says the model of v<N> stands (``stands``; quiet since ``since``). An era younger than two
steps is not discovered: its model is its prior, carried whole. With no era (no change was ever
announced) nothing of this applies, and discovery is exactly as before.

**A window too quiet for any counter** (``widen``). When a discovery finds no stock because no
counter counted ``MIN_EVENTS`` in the window (the owner, 2026-11-02: "the sprint board itself is
low traffic"), the window is doubled, with its step (the grid keeps its number of steps), up to
``MAX_WINDOW`` (7 days), never past the era's start and no further than the oldest point read, and discovered again, before any "no
model" is said; the record says which windows were read (``discovery["widened"]``) and
``window_s`` is the one the model was fitted over.

**Sparse own data** (``sparse_window``). When every level discovery judged moved in fewer than
``MIN_STEPS`` of its live steps (``discovery["level_steps"]``: a board that moves one ticket every
four hours, beside agents' counters that count every minute, so no counter is short of events) but
the project's own series span longer than the window, the window is widened at once, in whole
multiples of the configured window with the step scaled alike (as for a source's history), to the
shortest that holds ``MIN_STEPS`` steps in which one of those levels moved, up to ``MAX_WINDOW``,
never past the era's start and no further than the own data reach; ``discovery["widened"]`` says
it was widened for sparse data (``sparse``)."""

from __future__ import annotations

import fcntl
import itertools
import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..metrics import MetricsStore
from ..sources.catalogue import Catalogue
from ..sources.own import OWN
from ..sources.spec import for_project
from . import eras as era_record
from . import persistence, quiet, simulated
from . import snapshot as snap
from .balance import MIN_EVENTS
from .compare import compare
from .discover import MIN_STEPS, structure
from .model import Model
from .prior import merge
from .provenance import annotate
from .series import series_key
from .store import ModelStore
from .strategies import CONSERVATION, DEFAULT, sd_installed

_lock = threading.Lock()       # one rediscovery at a time per process
DEADLINE_SHARE = 0.8           # of [discovery] every: what an SD Lab strategy may take


class Busy(Exception):
    """Another process is discovering this project's model."""


@dataclass
class Result:
    model: Model
    at: float
    version: int | None        # the new version, when the structure changed
    strategy: str


def configured_strategy(project) -> str:
    s = project.config.discovery_strategy or (DEFAULT if sd_installed() else CONSERVATION)
    return s if s == CONSERVATION or sd_installed() else CONSERVATION


@contextmanager
def discovery_lock(state_dir: Path, *, wait: bool):
    """The project's cross-process discovery lock, held while discovering; ``Busy`` when another
    process holds it and this caller would rather not wait."""
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(state_dir) / "discovery.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise Busy("another discovery is running for this project") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def aligned(start: float, end: float, step: float) -> tuple[float, float]:
    """The window ``[start, end]`` moved back to end on the last multiple of ``step`` at or
    before ``end``, as long as it was (to the nearest step)."""
    last = math.floor(end / step) * step
    return last - round((end - start) / step) * step, last


MAX_WINDOW = 7 * 86400.0      # the furthest back a widened window reaches
HELD_SLACK = 0.1              # of the window: history this little longer than it does not lengthen it


def window_words(s: float) -> str:
    """A window's length in words: "1 h", "2 d"."""
    return f"{s / 86400:g} d" if s >= 86400 else f"{s / 3600:g} h" if s >= 3600 else f"{s / 60:g} min"


def widen(m: Model, window_s: float, step_s: float, now: float, era_start: float | None,
          first: float | None = None) -> tuple[float, float] | None:
    """The next window to read (doubled, with its step, so the grid keeps its number of steps),
    when the discovery ``m`` found no stock because no counter it read counted ``MIN_EVENTS`` in its
    window (a low-traffic system: a sprint board moves a few tickets an hour, and on one that moves
    once in two hours half the hours hold no move at all); None when it found one, when it read no
    counter, when one had the events, when the window is already ``MAX_WINDOW``, when the era began
    inside it, or when it already reaches back to ``first``, the oldest point read (a wider window
    reads nothing more)."""
    d = m.discovery or {}
    ce = d.get("counter_events") or {}
    read = d.get("counters_read", ce.get("counters"))
    if m.stocks or not read or ce.get("most", 0) >= MIN_EVENTS or window_s >= MAX_WINDOW:
        return None
    if era_start is not None and era_start > now - window_s:
        return None
    if first is not None and first >= now - window_s:
        return None
    wider = min(MAX_WINDOW, 2 * window_s)
    return wider, step_s * wider / window_s


def sparse_window(m: Model, reading, window_s: float, step_s: float, now: float, era_start: float | None,
                  ) -> tuple[float, float] | None:
    """The window and step to read when every level the discovery ``m`` judged moved in fewer than
    ``MIN_STEPS`` live steps (``discovery["level_steps"]``) and the project's own series span longer
    than ``window_s``: the shortest whole multiple of the window (the step scaled alike, so the grid
    keeps its number of steps) in which one of those levels, from its own points, moved in
    ``MIN_STEPS`` steps, up to ``MAX_WINDOW``, the era's start and the oldest own point. None when a
    level had the steps, none was judged, the own data reach no further, or no wider window holds them."""
    ls = (m.discovery or {}).get("level_steps") or {}
    sparse = ls.get("sparse") or {}
    if not ls.get("levels") or len(sparse) < ls["levels"] or window_s >= MAX_WINDOW:
        return None
    own = [(series_key(n, lab), pts) for n, lab, pts in reading.dump
           if pts and (reading.provenance.get(series_key(n, lab)) or {}).get("source") in (None, OWN)]
    first = min((pts[0][0] for _, pts in own), default=None)
    if first is None or now - first <= (1 + HELD_SLACK) * window_s:
        return None
    reach = min(now - first, MAX_WINDOW, now - era_start if era_start is not None else MAX_WINDOW)
    top = max(1, min(math.ceil(reach / window_s - HELD_SLACK), math.floor(MAX_WINDOW / window_s)))
    moves = [[b[0] for a, b in itertools.pairwise(pts) if b[1] != a[1]] for key, pts in own if key in sparse]
    for k in range(2, top + 1):
        w, st = window_s * k, step_s * k
        start, _ = aligned(now - w, now, st)
        if any(len({int((t - start) // st) for t in ts if t > start}) >= MIN_STEPS for ts in moves):
            return w, st
    return None


def oldest(reading) -> float | None:
    """The oldest point a reading holds (the own store's series hold all their history)."""
    return min((pts[0][0] for _, _, pts in reading.dump if pts), default=None)


def held_window(window_s: float, step_s: float, held_s: float, era_start: float | None, now: float) -> tuple[float, float]:
    """Discovery's window and step when the sources hold ``held_s`` of history (``sources.held``):
    the longer of the configured window and that, up to ``MAX_WINDOW``, but no longer than the
    current era (and never shorter than the configured window), in whole multiples of the window
    with the step scaled alike, so the grid keeps its number of steps."""
    span = min(held_s, MAX_WINDOW)
    if era_start is not None:
        span = min(span, now - era_start)
    if span <= (1 + HELD_SLACK) * window_s:      # a store holding about the window (its first point a step before it): the window
        return window_s, step_s
    k = min(math.ceil(span / window_s - HELD_SLACK), max(1, math.floor(MAX_WINDOW / window_s)))
    return window_s * k, step_s * k


def era_window(start: float, end: float, step: float, era_start: float | None) -> float:
    """The window's start, moved forward to the era's start (on the grid) when the era is younger."""
    if era_start is None or era_start <= start:
        return start
    return min(end, math.ceil(era_start / step) * step)


def cuts(project, eras: list, now: float) -> tuple[float | None, float | None]:
    """Where the current era cuts what discovery reads: (the own store's series from, the window
    from). The era cuts the window only for the series its change could have altered: a source's
    series (another system's store, read in place) only from the last era that could change what
    that system measures (``eras.sources_era``: not a ``config.changed``), so a change of the
    project's own configuration never throws a source's history away (bootstrap run 5: a week read,
    then the fit cut to 58 minutes by an era its setup began)."""
    era = era_record.current(eras, now)
    own = era.start if era else None
    if not for_project(project).sources:
        return own, own
    src = era_record.sources_era(eras, now)
    return own, src.start if src else None


def rediscover(project, metrics: MetricsStore, *, strategy: str | None = None, options: dict | None = None,
               window_s: float | None = None, step_s: float | None = None,
               note: str = "discovered: the structure changed", skip_if_busy: bool = False,
               events=None, now: float | None = None, collectors: list | None = None,
               snapshot: Path | str | None = None) -> Result:
    """``collectors``: the plugins' collectors the caller runs or has loaded, which say which
    instruments are simulated (``sd.simulated``); None loads the plugins when needed (the CLI).
    ``snapshot``: a directory to write what this discovery read to (``sd.snapshot``), so it can be
    replayed; nothing is written when the era is too young to read."""
    cfg = project.config
    strategy = strategy or configured_strategy(project)
    options = cfg.discovery_options if options is None else options
    asked = window_s is not None or step_s is not None
    window_s = window_s or cfg.discovery_window
    step_s = step_s or cfg.discovery_step
    with _lock, discovery_lock(project.state_dir, wait=not skip_if_busy):
        store = ModelStore.for_state(project.state_dir)
        if events is not None:
            eras, _ = era_record.follow(store, events, project, events.publish)
        else:
            eras = era_record.recorded(store)
        now = time.time() if now is None else now
        era = era_record.current(eras, now)
        own_from, cut = cuts(project, eras, now)
        held: dict[str, float] = {}
        if not asked:                         # the configured window: as long as the sources hold, within the era
            catalogue = Catalogue(project, metrics)
            a0, e0 = aligned(now - window_s, now, step_s)    # inferred over the window discovery would read without it
            held = catalogue.held(now, era_window(a0, e0, step_s, cut), e0) if catalogue.specs.sources else {}
            window_s, step_s = held_window(window_s, step_s, max(held.values(), default=0.0), cut, now)
        lengthened = window_s > cfg.discovery_window and bool(held)    # inferred over the configured window still
        start, end = aligned(now - window_s, now, step_s)
        start = era_window(start, end, step_s, cut)
        own_from = own_from if own_from is not None and own_from > start else None    # the own series are cut further than the window
        if era is None or end - start >= 2 * step_s:
            base_s, tried, sparse_at = window_s, [], None
            while True:
                reading = Catalogue(project, metrics).read(start, end, step_s, infer_s=cfg.discovery_window if lengthened and not tried else None,
                                                           own_from=own_from)
                allowed = None
                if snapshot is not None:
                    sim = snap.simulated_allowed(project, reading, collectors)
                    snap.write(snapshot, reading, start=start, end=end, step=step_s, strategy=strategy, options=options,
                               deadline=DEADLINE_SHARE * cfg.discovery_every, window_s=window_s, project=project, simulated=sim)
                    allowed = lambda sim=sim: set(sim or [])  # the same set the snapshot records
                m = simulated.discovered(project, reading, collectors=collectors, start=start, end=end, step=step_s, strategy=strategy,
                                         options=options, deadline=DEADLINE_SHARE * cfg.discovery_every, provenance=reading.provenance,
                                         allowed=allowed)
                annotate(m, reading.provenance)
                wider = widen(m, window_s, step_s, now, cut, oldest(reading))
                if wider is None and (wider := sparse_window(m, reading, window_s, step_s, now, cut)) is not None:
                    sparse_at = sparse_at or window_s
                if wider is None:
                    break
                tried.append(window_s)
                window_s, step_s = wider
                start, end = aligned(now - window_s, now, step_s)
                start = era_window(start, end, step_s, cut)
                own_from = own_from if own_from is not None and own_from > start else None
            if tried:
                why = (f"the {window_words(sparse_at)} window held fewer than {MIN_STEPS} steps in which any level moved, "
                       f"over longer own data: widened for sparse data to {window_words(window_s)}" if sparse_at == base_s else
                       f"the {window_words(base_s)} window held too few events for any counter (a balance needs {MIN_EVENTS}): "
                       f"widened to {window_words(window_s)}" + (f", then for sparse data (the {window_words(sparse_at)} window held "
                                                               f"fewer than {MIN_STEPS} steps in which any level moved)" if sparse_at else ""))
                m.discovery["widened"] = {"from_s": base_s, "tried_s": tried, "window_s": window_s, "step_s": step_s, "why": why,
                                          **({"sparse": {"from_s": sparse_at, "needed": MIN_STEPS}} if sparse_at else {})}
        else:                                   # the era is too young to read: its prior, carried whole
            reading = None
            m = Model("system", "The system", "The era is too young to discover: its prior, carried.")
            m.discovery = {"start": start, "end": end, "step": step_s, "left_out": {}, "too_young": True}
        m.discovery.update(window_s=window_s, step_s=step_s)
        if held and window_s > cfg.discovery_window:
            m.discovery["history"] = {"sources_s": {k: round(v) for k, v in held.items()}, "from_s": cfg.discovery_window,
                                   "why": f"the sources hold {window_words(max(held.values()))} of history: the window is "
                                          f"{window_words(window_s)}, not {window_words(cfg.discovery_window)}"}
        m.eras, m.era = eras, era.id if era else None
        for f in m.flows:
            for e in f.equations:
                e.era = m.era
        prev = store.latest_discovery()
        if era is not None:
            if prev and prev[1].era != m.era and prev[1].stocks and not prev[1].discovery.get("not_saved"):
                store.save(prev[1], note=f"the last model of {'era ' + prev[1].era if prev[1].era else 'the time before any era'}")
            prior = store.prior_for(m.era)
            if prior is not None:
                m = merge(m, prior, age_s=now - era.start, keep_s=cfg.prior_for or window_s)
                m.discovery["era_comparison"] = compare(prior, m)
            m.discovery["era_start"] = era.start
            if own_from is not None:
                m.discovery["sources_kept"] = {"from": start, "own_from": own_from,
                                               "why": f"era {era.id} began with a change of the project's configuration "
                                                      f"({era.subject or era.type}), which changes nothing another system's store "
                                                      "measures: the sources' series keep their history, the own store's are read "
                                                      "from the era's start"}
        if reading is None:
            store.write_discovery(m, at=now)
            cur = store.load()
            version = store.save(m, note=f"era {m.era} began: its prior") if m.stocks and (cur is None or cur.era != m.era) else None
            return Result(m, now, version, strategy)
        persistence.apply(store, m, now)          # each stock's share of recent discoveries that found it the same way
        if len(reading.status) > 1 or reading.missing:
            m.discovery["sources"] = reading.status
        if reading.missing:
            m.discovery["not_saved"] = "missing " + "; ".join(f"{k}: {v}" for k, v in reading.missing.items())
        prev = store.latest_discovery()
        if prev and now - prev[0] > 2 * cfg.discovery_every:
            m.discovery["since_last_s"] = round(now - prev[0])      # the machine slept, or nothing ran: this window was read whole, as always
        cur = store.load()
        vs = store.versions()
        m = quiet.hold(m, cur, vs[-1]["version"] if vs else None, reading.dump)
        changed = m.stocks and (cur is None or structure(cur) != structure(m) or cur.era != m.era)
        if m.discovery.get("quiet") and not changed:
            m.discovery["quiet"].update(stands=True, note=quiet.stands(m))      # nothing but quiet: the current version stands
        store.write_discovery(m, at=now)
        # nothing is saved from a reading with a source missing, or with simulated series whose
        # instruments are unknown because the plugins failed to load: the structure is not known
        version = (store.save(m, note=f"{note} ({strategy})")
                   if changed and not reading.missing and not m.discovery.get("plugins_error") else None)
        return Result(m, now, version, strategy)


def snapshot(project, metrics: MetricsStore, directory: Path | str, *, strategy: str | None = None,
             window_s: float | None = None, step_s: float | None = None, now: float | None = None,
             collectors: list | None = None) -> Path:
    """Write what a discovery now would read (the window ``rediscover`` would take, within the era
    the host recorded) to ``directory`` (``sd.snapshot``), without discovering or saving anything
    to the model store; the reads are not kept for the next discovery."""
    cfg = project.config
    window_s = window_s or cfg.discovery_window
    step_s = step_s or cfg.discovery_step
    now = time.time() if now is None else now
    own_from, cut = cuts(project, era_record.recorded(ModelStore.for_state(project.state_dir)), now)
    start, end = aligned(now - window_s, now, step_s)
    start = era_window(start, end, step_s, cut)
    reading = Catalogue(project, metrics).read(start, end, step_s, keep=False,
                                               own_from=own_from if own_from is not None and own_from > start else None)
    return snap.write(directory, reading, start=start, end=end, step=step_s, strategy=strategy or configured_strategy(project),
                      options=cfg.discovery_options, deadline=DEADLINE_SHARE * cfg.discovery_every, window_s=window_s,
                      project=project, simulated=snap.simulated_allowed(project, reading, collectors))
