#!/usr/bin/env python3
"""``check_retirement.py`` -- inspect retirement records and per-cell samples.

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.checks.retirement`.
Does NOT own: any retirement logic -- the record inspection and its exit code
live in :mod:`oto.checks.retirement`.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.retirement import main

if __name__ == "__main__":
    sys.exit(main())
