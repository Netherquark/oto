#!/usr/bin/env python3
"""``verify_all.py`` -- Refactor-1 equivalence verification suite.

Thin entrypoint: the implementation lives in ``oto.tools.verifiers.verify_all``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.verifiers.verify_all import main

if __name__ == "__main__":
    sys.exit(main())
