"""Measurement: everything that turns benchmark rows into a verdict or a report.

Owns: analytics (CSV loading, per-cell aggregation, LCB), the A/B audit and
acceptance band, the report formats, run status / cost model, the coverage
state machine, cell policy, and telemetry parsing.
Does NOT own: the runs that produced the data (oto.runners), the ledger that
stores it (oto.ledger), or the device facts that bound it (oto.device.loader).
Public API: none at import time; this package re-exports nothing, so importing
it has no side effects. The public names of each module are in their own
docstrings (AnalyticsEngine, AcceptanceReporter, LiveStatus, ...).
"""
