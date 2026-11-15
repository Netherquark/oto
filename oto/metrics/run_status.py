#!/usr/bin/env python3
"""Run status: the report builder, the renderers and the live panel.

Owns: the façade every consumer imports — the re-exported ``build_report``
(the whole status dict for a run/plan/chain), the text renderings of it
(``render_compact``, ``render``, ``bar``), and ``LiveStatus`` with
``_PanelStdout`` — the background-threaded TTY repainter and the stdout
proxy that erases the panel before any other write. The implementation is
split across ``oto.metrics.status_helpers`` (helpers),
``oto.metrics.ledger_state`` (registry/corpus state) and
``oto.metrics.build_status`` (report assembly and ETAs); tests patch this
module's ``tlib`` and ``build_report``.
Does NOT own: the plan it prices (oto.metrics.run_plan), the thermal
envelope it cites (oto.metrics.thermal_telemetry), or the driver that starts it
(oto.runners.driver).
Public API: RunPlan / PhaseCost / Estimate (re-exported), build_report, bar,
render_compact, render, LiveStatus, _PanelStdout, fmt_duration, bucket,
_parse_ts, _jittery, read_thermals, main, tlib.
"""

from __future__ import annotations

import oto.tensile.shipped_floor_manifest as tlib
from oto.metrics.build_status import build_report

# Re-exported for the pre-split import surface; the implementations live in
# oto.metrics.thermal_telemetry / oto.metrics.run_plan.
from oto.metrics.ledger_state import (
    ACTIVE_STATES as ACTIVE_STATES,
)
from oto.metrics.ledger_state import (
    DB_REL as DB_REL,
)
from oto.metrics.render_status import (
    LiveStatus,
    _PanelStdout,
    bar,
    main,
    render,
    render_compact,
)
from oto.metrics.run_plan import (
    Estimate,
    PhaseCost,
    RunPlan,
)
from oto.metrics.status_helpers import (
    _jittery,
    _parse_ts,
    bucket,
    fmt_duration,
)
from oto.metrics.thermal_telemetry import read_thermals

__all__ = [
    "ACTIVE_STATES",
    "DB_REL",
    "Estimate",
    "LiveStatus",
    "PhaseCost",
    "RunPlan",
    "_PanelStdout",
    "_jittery",
    "_parse_ts",
    "bar",
    "bucket",
    "build_report",
    "fmt_duration",
    "main",
    "read_thermals",
    "render",
    "render_compact",
    "tlib",
]


if __name__ == "__main__":
    # Documented by oto/metrics/render_status.py as the standalone view;
    # it was deleted in a split and never restored. Route straight at the
    # live renderer, which owns the CLI.
    from oto.metrics.render_status import main as _main

    raise SystemExit(_main())
