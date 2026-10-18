"""python -m sdlab.ladder: the ladder's command line (sdlab/ladder/cli.py)."""

import sys

from .cli import main

if __name__ == "__main__":                       # worker processes import this module again
    sys.exit(main())
