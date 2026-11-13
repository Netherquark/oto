#!/usr/bin/env python3
"""``verify_all.py`` -- Refactor-1 equivalence verification suite.

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into ``oto.tools.verifiers.verify_all``.
Does NOT own: any verification logic -- the check list, the subprocess wiring
and the summary report live in ``oto.tools.verifiers.verify_all``.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.verifiers.verify_all import main

if __name__ == "__main__":
    sys.exit(main())
