#!/usr/bin/env python3
"""``check_tensile_build.py`` -- prove every phase's config builds (CPU-only).

Thin entrypoint: the implementation lives in :mod:`oto.checks.tensile_build`.
Runs Tensile's own kernel writer in a subprocess per phase, no GPU.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.checks.tensile_build import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
