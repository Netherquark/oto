#!/usr/bin/env python3
"""``verify_gate_differential.py`` -- Gate differential verification.

Thin entrypoint: the implementation lives in ``oto.tools.verifiers.verify_gate_differential``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.verifiers.verify_gate_differential import main

if __name__ == "__main__":
    sys.exit(main())
