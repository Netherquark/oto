#!/usr/bin/env python3
"""``check_tensile_build.py`` -- prove every phase's config builds (CPU-only).

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the ``main()``
dispatch into :mod:`oto.checks.tensile_build`.
Does NOT own: any proof logic -- the Tensile kernel-writer subprocesses and the
validation table they produce live in :mod:`oto.checks.tensile_build`.
Public API: none beyond ``main`` re-exported for ``-m``/import parity.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.tensile_build import main

if __name__ == "__main__":
    sys.exit(main())
