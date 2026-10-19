"""python -m sdlab.ladder.real fetch [sources] | build [--check] [--only ids] | report [--strategies ...]"""

import sys

from . import build, report, sources


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "fetch":
        failed = 0
        for s in rest or list(sources.SOURCES):
            try:
                print(sources.fetch(s))
            except SystemExit as e:
                print(e, file=sys.stderr)
                failed += 1
            except Exception as e:                       # noqa: BLE001  (a network failure: say so, carry on)
                print(f"{s}: download failed: {type(e).__name__}: {e}", file=sys.stderr)
                failed += 1
        return 1 if failed else 0
    if cmd == "build":
        return build.main(rest)
    if cmd == "report":
        return report.main(rest)
    print(f"unknown command {cmd!r}\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
