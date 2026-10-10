"""The append-only ledger: registry, mutation, and the convergence loop.

Owns: durable state -- runs, records, phases, proposals, proposal observations
(registry.py), and the two halves of one state machine that consume it:
``mutator.Mutator`` (ledger-backed mutation + outcome write-back) and
``agent.ConvergenceAgent`` (harvest -> mutate -> converge).
Does NOT own: how a verdict is graded (oto.metrics), how a candidate is made
legal (oto.tensile), or how a phase is executed (oto.runners).
"""
