"""Evergreen verification checks (verify_*.py) for the oto convergence pipeline.

Owns: the ``verify_*.py`` equivalence checks. Does NOT own the checks'
individual implementations (each ``verify_*.py`` owns its own) or the drift
manifest format (``oto/tools/verifiers/drift_manifest.json``).
Public API: none at import time; each check is its own CLI.
"""
