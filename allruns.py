#!/usr/bin/env python3
"""``allruns.py`` -- best config per cell across ALL runs (claude.md §2.1).

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.tools.allruns`; the documented ``python3 allruns.py``
invocation.
Does NOT own: any logic -- the implementation, its owning modules and its
docstring-owned contract live in :mod:`oto.tools.allruns`.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.allruns import main

if __name__ == "__main__":
    sys.exit(main())
