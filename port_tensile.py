#!/usr/bin/env python3
"""``port_tensile.py`` -- the oto driver command line.

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.runners.cli`; keeps the documented
``python3 port_tensile.py --auto ...`` invocation (``command.txt`` and
``claude.md`` §2.1) working.
Does NOT own: any driver logic -- the stage dispatch and the auto-convergence
loop live in :mod:`oto.runners.cli` (and the runners mixins it routes to).
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.runners.cli import main

if __name__ == "__main__":
    sys.exit(main())
