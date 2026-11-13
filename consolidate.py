#!/usr/bin/env python3
"""``consolidate.py`` -- deck consolidation (mine / all subcommands).

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.tools.consolidate`.
Does NOT own: any consolidation logic -- the mine/all subcommands live in
:mod:`oto.tools.consolidate`.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.consolidate import main

if __name__ == "__main__":
    sys.exit(main())
