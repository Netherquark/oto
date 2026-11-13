#!/usr/bin/env python3
"""``check_db.py`` -- inspect the registry DB for label contamination.

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.checks.db`.
Does NOT own: any check logic -- the contamination scan and its exit code live
in :mod:`oto.checks.db`.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.db import main

if __name__ == "__main__":
    sys.exit(main())
