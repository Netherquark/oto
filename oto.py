#!/usr/bin/env python3
"""oto — Tensile tuning for unsupported AMD GPUs.

Repo-root entry point. Run from the repository root:
    python3 oto.py doctor
    python3 oto.py status
    python3 oto.py tune --dry-run
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.cli.dispatch import main

if __name__ == "__main__":
    raise SystemExit(main())
