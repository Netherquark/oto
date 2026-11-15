"""CLI scaffold: output, errors, flags, dispatch.

Owns: the ``oto <cmd>`` command tree's packaging (parser, dispatch, errors,
output policy). Does NOT own the subcommands themselves (``oto.cli.*`` modules)
or the backends they call.
Public API: none at import time; this package carries no import-time work.
"""
