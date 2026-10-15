#!/usr/bin/env python3
"""``verify_ast_equivalence.py`` -- Symbol-level AST equivalence verification.

Thin entrypoint: the implementation lives in ``oto.tools.verifiers.verify_ast_equivalence``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from oto.tools.verifiers.verify_ast_equivalence import main

if __name__ == "__main__":
    sys.exit(main())
