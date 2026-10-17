"""Serve a generated dataset over the Prometheus HTTP API.

python -m sdlab.promlab.server --data DIR --port 9090 [--clock end|replay --replay-from DAYS --speed N]
"""

import argparse

import uvicorn

from .api import Clock, create_app
from .store import Dataset


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9090)
    ap.add_argument("--clock", choices=["end", "replay"], default="end")
    ap.add_argument("--replay-from", type=float, default=1.0, help="replay: start this many days before the end")
    ap.add_argument("--speed", type=float, default=1.0, help="replay: data seconds per wall-clock second")
    ap.add_argument("--no-loop", action="store_true", help="replay: stop at the end instead of starting over")
    a = ap.parse_args(argv)
    ds = Dataset(a.data)
    app = create_app(ds, Clock(ds, a.clock, a.replay_from, a.speed, loop=not a.no_loop))
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
