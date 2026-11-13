"""Entry point for ``python3 -m oto``."""

from __future__ import annotations

from oto.cli.dispatch import main

if __name__ == "__main__":
    raise SystemExit(main())
