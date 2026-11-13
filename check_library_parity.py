#!/usr/bin/env python3
"""``check_library_parity.py`` -- coverage-parity check vs shipped gfx900.

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.checks.library_parity`.
Does NOT own: any parity logic -- the rule it enforces (``knowledge_base.md``
§6.1) and its checker live in :mod:`oto.checks.library_parity`.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.library_parity import main

if __name__ == "__main__":
    sys.exit(main())
