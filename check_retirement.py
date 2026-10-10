#!/usr/bin/env python3
"""``check_retirement.py`` -- inspect retirement records and per-cell samples.

Thin entrypoint: the implementation lives in :mod:`oto.checks.retirement`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.retirement import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
