#!/usr/bin/env python3
"""``verify_ast_equivalence.py`` -- Symbol-level AST equivalence verification.

Thin entrypoint: the implementation lives in ``oto.tools.verifiers.verify_ast_equivalence``.
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

    runpy.run_module("oto.tools.verifiers.verify_ast_equivalence", run_name="__main__")
