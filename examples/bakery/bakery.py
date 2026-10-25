"""A toy system of machines, to see Orchestra find its dynamics on its own.

Three machines, each its own process, outside Orchestra. They use Orchestra only as a library:
the event bus (CloudEvents, ``orchestra.events``) and the metrics store (``orchestra.metrics``).
Nothing in Orchestra knows what bread is.

- **oven** bakes loaves at a base rate that changes with its shift (day and night, ten minutes
  each), plus faster while it has orders to fill. It listens for
  ``bread.ordered``, publishes ``bread.baked``, and writes
  ``bakery_loaves_baked_total``, ``bakery_orders_filled_total`` and the gauge
  ``bakery_oven_orders_pending``.
- **shop** puts baked loaves on its shelf. Customers buy in proportion to what is on the shelf;
  loaves go stale in proportion too; when the shelf runs low it orders more. It listens for
  ``bread.baked``, publishes ``bread.sold``, ``bread.discarded`` and ``bread.ordered``, and
  writes the gauge ``bakery_shelf_loaves`` and the counters ``bakery_loaves_sold_total``,
  ``bakery_loaves_discarded_total`` and ``bakery_loaves_ordered_total``.
- **weather** reports a temperature that drifts. It is unrelated to the bakery on purpose: the
  model generator should leave it out.

The loop: a low shelf → orders → the oven bakes faster → a fuller shelf (balancing).

Time runs in minutes and the machines tick every second, so rates are per minute and a few
minutes of running give plenty of data.

    ORCHESTRA_REPO=~/orchestra-sd uv run --project ~/orchestra_2 python examples/bakery/bakery.py oven
"""

from __future__ import annotations

import math
import random
import sys
import time

from orchestra.config import load_project
from orchestra.events import Events
from orchestra.metrics import Point
from orchestra.metrics import for_project as metrics_for

TICK_S = 1.0                    # seconds between ticks (a tick takes a little longer: rates use the real time)

# the rates, per minute: what the model should find
DAY, NIGHT = 6.0, 1.5           # loaves/min the oven bakes on its own, by shift
SHIFT_MIN = 10                  # the shifts alternate every this many minutes
ORDER_BAKE = 0.5                # extra loaves/min per pending ordered loaf
SELL = 0.20                     # share of the shelf bought per minute
STALE = 0.05                    # share of the shelf thrown out per minute
LOW_SHELF = 10                  # the shop orders when the shelf is below this
ORDER_SIZE = 20


def poisson(mean: float) -> int:
    """A Poisson draw (Knuth; means here are small)."""
    if mean <= 0:
        return 0
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= random.random()
        if p <= limit:
            return k
        k += 1


class Machine:
    """What a machine needs from Orchestra: publish, listen, and write its metrics. ``tick``
    returns the minutes since the last tick, so rates hold however long a tick takes."""

    def __init__(self, name: str, listens_for: list[str]):
        self.name = name
        self.project = load_project()
        self.events = Events.for_project(self.project, source=name)
        self.metrics = metrics_for(self.project)
        self.listens_for = listens_for
        self.offset = self.events.end()          # new events only, from now
        self.counters: dict[str, float] = {}
        self._last = time.time()
        if listens_for:
            self.events.publish("orchestra.machine.subscribed", {"types": listens_for})

    def tick(self) -> float:
        time.sleep(TICK_S)
        now = time.time()
        dt, self._last = (now - self._last) / 60, now
        return dt

    def inbox(self) -> list[dict]:
        evs, self.offset = self.events.read(self.offset, limit=10_000)
        return [e for e in evs if e.get("type") in self.listens_for]

    def count(self, series: str, n: float) -> None:
        self.counters[series] = self.counters.get(series, 0.0) + n

    def write(self, gauges: dict[str, float]) -> None:
        lab = {"project": self.project.key, "machine": self.name}
        now = time.time()
        self.metrics.write([Point(s, v, now, lab) for s, v in {**self.counters, **gauges}.items()])

    def resume_counters(self, *series: str) -> None:
        """Counters continue from what the store already holds, so a restart doesn't reset them."""
        lab = {"project": self.project.key, "machine": self.name}
        for s in series:
            last = self.metrics.latest(s, lab)
            self.counters[s] = last[1] if last else 0.0


def oven() -> None:
    m = Machine("oven", ["bread.ordered"])
    m.resume_counters("bakery_loaves_baked_total", "bakery_orders_filled_total")
    pending = 0
    while True:
        dt = m.tick()
        for ev in m.inbox():
            pending += int((ev.get("data") or {}).get("loaves", 0))
        base = DAY if int(time.time() // (SHIFT_MIN * 60)) % 2 == 0 else NIGHT
        baked = poisson((base + ORDER_BAKE * pending) * dt)
        filled = min(pending, baked)
        pending -= filled
        if baked:
            m.events.publish("bread.baked", {"loaves": baked})
            m.count("bakery_loaves_baked_total", baked)
            m.count("bakery_orders_filled_total", filled)
        m.write({"bakery_oven_orders_pending": pending})


def shop() -> None:
    m = Machine("shop", ["bread.baked"])
    m.resume_counters("bakery_loaves_sold_total", "bakery_loaves_discarded_total", "bakery_loaves_ordered_total")
    last = m.metrics.latest("bakery_shelf_loaves", {"project": m.project.key, "machine": "shop"})
    shelf = int(last[1]) if last else 0
    ordered_at = 0.0
    while True:
        dt = m.tick()
        for ev in m.inbox():
            shelf += int((ev.get("data") or {}).get("loaves", 0))
        sold = min(shelf, poisson(SELL * shelf * dt))
        shelf -= sold
        stale = min(shelf, poisson(STALE * shelf * dt))
        shelf -= stale
        if sold:
            m.events.publish("bread.sold", {"loaves": sold})
            m.count("bakery_loaves_sold_total", sold)
        if stale:
            m.events.publish("bread.discarded", {"loaves": stale})
            m.count("bakery_loaves_discarded_total", stale)
        if shelf < LOW_SHELF and time.time() - ordered_at > 60:     # at most one order a minute
            m.events.publish("bread.ordered", {"loaves": ORDER_SIZE})
            m.count("bakery_loaves_ordered_total", ORDER_SIZE)
            ordered_at = time.time()
        m.write({"bakery_shelf_loaves": shelf})


def weather() -> None:
    m = Machine("weather", [])
    temp, n = 15.0, 0
    while True:
        m.tick()
        temp += random.gauss(0, 0.15) + (15.0 - temp) * 0.01
        n += 1
        if n % 10 == 0:
            m.events.publish("weather.reported", {"celsius": round(temp, 2)})
        m.write({"weather_temperature_celsius": round(temp, 2)})


if __name__ == "__main__":
    {"oven": oven, "shop": shop, "weather": weather}[sys.argv[1]]()
