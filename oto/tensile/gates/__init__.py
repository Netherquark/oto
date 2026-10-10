"""The three CPU-only legality gate families.

Each gate answers exactly one question about a Tensile config and returns
``(ok, reason)``; a reject reason is always human-readable and always cites the
Tensile source line it comes from, because a rejection the operator cannot
explain is rejected again next week.

Owns: ``assembly.py`` (is this GEMM class legal at all), ``occupancy.py``
(register-file + LDS budgets), ``loads.py`` (classic-path load divisibility),
``vgpr_model.py`` (the measured VGPR tables the occupancy gate cites).
Does NOT own: the candidate generator (oto.tensile.candidate), the launch-boundary
shared vocabulary between gates (see oto.tensile.candidate.validate_config, which
is the orchestrator), or any device constant (oto.device.peaks).
"""
