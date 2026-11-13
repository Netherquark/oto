#!/usr/bin/env python3
"""``check_candidates.py`` -- "is this deck Tensile-legal?" (claude.md §2.1).

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.checks.candidates`.
Does NOT own: any gate logic -- the four CPU legality gates (and the exit code
they set) live in :mod:`oto.checks.candidates`.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.candidates import main

if __name__ == "__main__":
    sys.exit(main())
