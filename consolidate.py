#!/usr/bin/env python3
"""``consolidate.py`` -- deck consolidation (mine / all subcommands).

Thin entrypoint: the implementation lives in :mod:`oto.tools.consolidate`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.consolidate import main

if __name__ == "__main__":
    sys.exit(main())
