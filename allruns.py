#!/usr/bin/env python3
"""``allruns.py`` -- best config per cell across ALL runs (claude.md §2.1).

Thin entrypoint: the implementation lives in :mod:`oto.tools.allruns`. Drives
oto's own loaders, so it cannot drift from the pipeline that produced the ledger.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.allruns import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
