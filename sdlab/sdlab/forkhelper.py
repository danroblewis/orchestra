"""A long-lived helper that runs machine programs by forking itself.

Starting a fresh Python for every firing costs about 20 ms, which is most of what a simple program
(take two socks, print one pair) costs. This helper starts once, imports the standard modules the
programs use, and for each request forks a copy of itself that runs the program as if it had been
started with ``python <path> <args>`` in the program's folder: same argv, stdin, stdout, stderr,
exit code. A fork costs a millisecond or two.

Protocol, one JSON object per line: request ``{"path", "argv", "stdin", "cwd", "timeout"}``,
response ``{"code", "stdout", "stderr"}`` or ``{"timeout": true, ...}``.
"""

from __future__ import annotations

# modules the programs commonly use, loaded once so each fork starts with them
import argparse  # noqa: F401
import heapq  # noqa: F401
import json
import math  # noqa: F401
import os
import random  # noqa: F401
import re  # noqa: F401
import selectors
import signal
import sys
import time
import traceback
import urllib.request  # noqa: F401


_compiled: dict[str, tuple[float, object]] = {}


def compiled(path: str):
    """A program's code, compiled once (again when the file changes) and run in every fork."""
    mtime = os.stat(path).st_mtime
    hit = _compiled.get(path)
    if not hit or hit[0] != mtime:
        with open(path, "rb") as f:
            hit = (mtime, compile(f.read(), path, "exec"))
        _compiled[path] = hit
    return hit[1]


def child(req: dict, fds: tuple[int, int, int], code_obj) -> None:
    code = 1
    try:
        os.chdir(req["cwd"])
        for fd, target in zip(fds, (0, 1, 2)):
            os.dup2(fd, target)
        sys.stdin = open(0, encoding="utf-8", closefd=False)
        sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
        sys.stderr = open(2, "w", encoding="utf-8", closefd=False)
        sys.argv = [req["path"], *req.get("argv", [])]
        sys.path.insert(0, os.path.dirname(req["path"]))
        code = 0
        try:
            if code_obj is None:
                code_obj = compiled(req["path"])              # raises: printed below, as python would
            exec(code_obj, {"__name__": "__main__", "__file__": req["path"], "__builtins__": __builtins__})
        except SystemExit as e:
            if e.code is None:
                code = 0
            elif isinstance(e.code, int):
                code = e.code
            else:
                print(e.code, file=sys.stderr)
                code = 1
        except BaseException:
            traceback.print_exc()
            code = 1
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(code)


def run(req: dict) -> dict:
    try:
        code_obj = compiled(req["path"])
    except (OSError, SyntaxError):
        code_obj = None                                      # the child reports it, as python would
    in_r, in_w = os.pipe()
    out_r, out_w = os.pipe()
    err_r, err_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        for fd in (in_w, out_r, err_r):
            os.close(fd)
        child(req, (in_r, out_w, err_w), code_obj)
    for fd in (in_r, out_w, err_w):
        os.close(fd)
    data = req.get("stdin", "").encode()
    out, err = bytearray(), bytearray()
    sel = selectors.DefaultSelector()
    if data:
        os.set_blocking(in_w, False)
        sel.register(in_w, selectors.EVENT_WRITE, "in")
    else:
        os.close(in_w)
    sel.register(out_r, selectors.EVENT_READ, out)
    sel.register(err_r, selectors.EVENT_READ, err)
    deadline = time.monotonic() + float(req.get("timeout") or 20)
    sent, timed_out = 0, False
    while len(sel.get_map()):
        left = deadline - time.monotonic()
        if left <= 0:
            timed_out = True
            break
        for key, _ in sel.select(timeout=left):
            if key.data == "in":
                try:
                    sent += os.write(in_w, data[sent:sent + 65536])
                except BrokenPipeError:
                    sent = len(data)
                if sent >= len(data):
                    sel.unregister(in_w)
                    os.close(in_w)
            else:
                chunk = os.read(key.fd, 65536)
                if chunk:
                    key.data.extend(chunk)
                else:
                    sel.unregister(key.fd)
                    os.close(key.fd)
    for key in list(sel.get_map().values()):
        sel.unregister(key.fd)
        os.close(key.fd)
    if timed_out:
        os.kill(pid, signal.SIGKILL)
    _, status = os.waitpid(pid, 0)
    res = {"code": os.waitstatus_to_exitcode(status), "stdout": out.decode(errors="replace"), "stderr": err.decode(errors="replace")}
    if timed_out:
        res["timeout"] = True
    return res


def main() -> None:
    channel_in, channel_out = sys.stdin.buffer, sys.stdout.buffer
    for line in channel_in:
        try:
            res = run(json.loads(line))
        except Exception as e:                               # report it; the caller falls back
            res = {"error": repr(e)}
        channel_out.write(json.dumps(res).encode() + b"\n")
        channel_out.flush()


if __name__ == "__main__":
    main()
