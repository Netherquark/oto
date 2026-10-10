#!/usr/bin/env python3
"""``port_tensile.py`` -- the oto driver command line.

Thin entrypoint: the implementation lives in :mod:`oto.runners.cli`. This file
exists so the documented invocation ``python3 port_tensile.py --auto ...`` (see
``command.txt`` and ``claude.md`` §2.1) keeps working; it owns no logic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.runners.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
