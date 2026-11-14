"""Device auto-detection: resolve the GPU codename from the system.

Owns: reading the codename from ``rocminfo`` and falling back to the
committed default (``gfx90c``) when that fails. Used by the loader's profile
resolution (``OTO_PROFILE`` override > detection > committed default).
Does NOT own: profile loading (``oto.device.loader``) or the codename table
(``oto.device.tensile_isa``).
Public API: detect_codename.
"""

from __future__ import annotations

import re
import shutil
import subprocess


def detect_codename() -> str:
    """Return the GPU codename from rocminfo, or the default codename when detection fails."""
    rocminfo = shutil.which("rocminfo")
    if rocminfo:
        try:
            out = subprocess.run([rocminfo], capture_output=True, text=True, timeout=30).stdout or ""
            m = re.search(r"Name:\s*(gfx\w+)", out)
            if m:
                return m.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "gfx90c"
