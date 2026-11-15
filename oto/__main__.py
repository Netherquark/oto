"""Entry point for ``python3 -m oto``.

Owns: exposing ``main`` as the process entry. Does NOT own argument parsing
(that is ```oto.cli.parser```/:mod:`oto.cli.dispatch`), the CLI surface (```oto.cli```),
or the run loop (:mod:`oto.runners`).
Public API: ``main``.
"""

from __future__ import annotations

from oto.cli.dispatch import main

if __name__ == "__main__":
    raise SystemExit(main())
