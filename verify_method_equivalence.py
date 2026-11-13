#!/usr/bin/env python3
"""``verify_method_equivalence.py`` -- Method equivalence verification.

Owns: the thin entrypoint -- the ``sys.path`` bootstrap and the subprocess
invocation of ``oto.tools.verifiers.verify_method_equivalence`` (the implementation is a
script: it runs its corpus at import time and calls ``sys.exit``; there is
no ``main`` to import).
Does NOT own: any verification logic -- the corpus, the REFACTOR_BASE pin
and the exit-code contract live in ``oto.tools.verifiers.verify_method_equivalence``.
Public API: none -- script entry; ``verify_all.py`` depends on the process
exit code (0 clean, 1 findings).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The implementation is a script, not a library: it runs its corpus at import
# time and calls sys.exit itself. So run it as one, rather than importing a
# `main` that does not exist. `verify_all.py` invokes the moved module directly
# and never came through here, which is why this stayed broken unnoticed.
if __name__ == "__main__":
    import runpy

    runpy.run_module("oto.tools.verifiers.verify_method_equivalence", run_name="__main__")
