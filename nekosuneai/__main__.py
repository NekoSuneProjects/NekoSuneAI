"""Console entry point: ``python -m nekosuneai``."""

from __future__ import annotations

import sys

from .launcher import main


def run() -> int:
    main()
    return 0


if __name__ == "__main__":
    sys.exit(run())
