#!/usr/bin/env python3
"""``check_library_parity.py`` -- coverage-parity check vs shipped gfx900.

Thin entrypoint: the implementation lives in :mod:`oto.checks.library_parity`.
The rule it enforces is stated once in ``knowledge_base.md`` §6.1.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.library_parity import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
