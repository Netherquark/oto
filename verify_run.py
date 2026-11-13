#!/usr/bin/env python3
"""``verify_run.py`` -- corpus snapshot / diff / telemetry verification.

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.tools.verify_run`; the documented
``python3 verify_run.py {snapshot,diff,telemetry,cheapest} ...`` invocation.
Does NOT own: any verification logic -- the subcommands and their exit codes
live in :mod:`oto.tools.verify_run`.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.verify_run import main

if __name__ == "__main__":
    sys.exit(main())
