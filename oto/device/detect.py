"""Device auto-detection: resolve the GPU codename from the system.

Owns: reading the codename from rocminfo (or a starter file). Falls back to
gfx90c when detection fails (with a warning).

Public API: detect_codename.
"""

from __future__ import annotations

import re
import shutil
import subprocess


def detect_codename() -> str:
    """Return the GPU codename (e.g. 'the device') from rocminfo, or 'the device' fallback."""
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
