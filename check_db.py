#!/usr/bin/env python3
"""``check_db.py`` -- inspect the registry DB for label contamination.

Thin entrypoint: the implementation lives in :mod:`oto.checks.db`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.db import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
