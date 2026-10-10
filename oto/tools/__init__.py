"""Offline analysis tools: corpus consolidation, cross-run reporting, verification.

These are the heavy read-only operators that walk every run directory and the
whole registry. They are intentionally separate from ``oto.checks`` because they
mutate nothing but write reports, and from ``oto.runners`` because they never
launch Tensile.
"""
