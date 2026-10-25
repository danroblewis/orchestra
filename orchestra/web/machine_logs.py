"""A machine's log, as the machine announced it: read only when it lies within the project.

A machine says where its log is (``data.log`` in ``orchestra.machine.started``); anything that can
publish on the bus could name any file, so the web server reads one only when its real path (links
resolved) is a regular file under the project's repository or its state directory. Everything else
is refused, and nothing is ever written."""

from __future__ import annotations

from pathlib import Path


def readable(path: str | None, roots: list[Path]) -> tuple[Path | None, str | None]:
    """The file to read, or None and why not."""
    if not path:
        return None, "this machine has not said where its log is (data.log in orchestra.machine.started)"
    try:
        real = Path(path).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, f"{path} does not exist"
    if not real.is_file():
        return None, f"{path} is not a file"
    if not any(real.is_relative_to(r.resolve()) for r in roots):
        return None, f"{path} is outside the project, so it is not read"
    return real, None


def tail(path: Path, lines: int) -> list[str]:
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 240 * lines))
        return f.read().decode("utf-8", "replace").splitlines()[-lines:]
