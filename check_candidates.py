#!/usr/bin/env python3
"""``check_candidates.py`` -- "is this deck Tensile-legal?" (claude.md §2.1).

Thin entrypoint: the implementation lives in :mod:`oto.checks.candidates`. Runs
the four CPU legality gates and exits 1 if any candidate is illegal.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.candidates import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
