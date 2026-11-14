#!/usr/bin/env python3
"""Live-panel and execution-timing regression tests for run_status.

The live TTY panel must never be able to kill the run it is watching, and the
acceptance report must carry the wall-clock time the run actually cost.
"""
import io
import json
import sys
import time
from pathlib import Path
from unittest import mock

from support_run_status import StatusFixture, _record

import oto.metrics.run_status as rs


class TestLiveStatus(StatusFixture):
    """The live TTY panel must never be able to kill the run it is watching."""

    def _panel(self, base=None, **kw):
        import io
        return rs.LiveStatus(base or self.base, interval=kw.pop("interval", 0.05),
                             stream=kw.pop("stream", None) or io.StringIO(), **kw)

    def _seed(self):
        self.add_run("gfx900_ref_r1", "completed", [
            _record("gfx900_ref_r1", self.phases[0], "completed", "success")],
            started="2026-09-25T10:00:00", completed="2026-09-25T12:00:00")

    class _Tty(io.StringIO):
        """A stream that claims to be a terminal, so the ANSI path is taken."""

        def isatty(self):
            return True

    def test_survives_a_missing_registry(self):
        """build_report raises SystemExit with no registry -- not an Exception.

        A first run starts in exactly that state. If _paint/refresh let it
        escape, the live status takes down the run it was meant to observe.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as empty:
            p = rs.LiveStatus(Path(empty), interval=0.05, stream=io.StringIO())
            p.start()
            p.refresh()          # must not raise
            time.sleep(0.15)
            p.stop()
        assert p.errors > 0, "missing registry was not counted"

    def test_start_and_stop_restore_stdout(self):
        self._seed()
        before = sys.stdout
        p = rs.LiveStatus(self.base, interval=0.05, stream=self._Tty())
        p.start()
        assert sys.stdout is not before, "panel did not wrap stdout"
        p.stop()
        assert sys.stdout is before, "stdout was not restored"

    def test_non_tty_emits_no_ansi_and_appends(self):
        """A piped log must stay readable: no escape codes, no repainting."""
        self._seed()
        buf = io.StringIO()
        p = rs.LiveStatus(self.base, interval=0.05, stream=buf)
        p.start()
        p.refresh()
        time.sleep(0.15)
        p.stop()
        out = buf.getvalue()
        assert "\x1b[" not in out, "ANSI escapes leaked into a non-TTY log"
        assert "elapsed" in out

    def test_panel_lines_are_erased_before_run_output(self):
        """A run's own prints must clear the panel, or the next repaint shreds them."""
        self._seed()
        buf = io.StringIO()
        p = rs.LiveStatus(self.base, interval=0.05, stream=buf)
        p._isatty = True
        p._painted = 5
        proxy = rs._PanelStdout(buf, p)
        proxy.write("Skipping phase phase_ss_x_1\n")
        out = buf.getvalue()
        # The erase must come first, so the panel is gone before the new line
        # is written and the next repaint cannot overwrite the line.
        assert out.startswith("\x1b[5A\x1b[J"), f"panel was not erased first: {out!r}"
        assert "Skipping phase phase_ss_x_1" in out
        assert p._painted == 0

    def test_errors_do_not_escape_a_refresh(self):
        self._seed()
        p = self._panel()
        with mock.patch.object(rs, "build_report", side_effect=SystemExit("no db")):
            p.refresh()          # must not raise
        assert p.errors == 1


class TestExecutionTiming(StatusFixture):
    """Execution time in the acceptance report."""

    def _driver(self):
        from oto.ledger.registry import SQLiteRegistry
        from oto.runners.stage_cli import TensileDriver
        d = TensileDriver.__new__(TensileDriver)
        d.base_dir = self.base
        d._last_run_status = "completed"
        d.registry = SQLiteRegistry(self.base)
        d._reference_floor_runs = lambda rid: ["gfx900_ref_floor_r1"]
        return d

    def test_run_timing_reports_wall_clock(self):
        self.add_run("gfx900_ref_floor_r1", "completed", [],
                     started="2026-09-25T10:00:00",
                     completed="2026-09-26T12:30:00")
        d = self._driver()
        t = d._compute_execution_timing("gfx900_ref_floor_r1")
        run = t["native_run"]
        self.assertAlmostEqual(run["elapsed_minutes"], 1590.0, places=1)
        assert run["elapsed_human"] == "1d 2h 30m"
        assert not run["in_flight"]

    def test_in_flight_run_reports_no_elapsed_yet(self):
        """A run still going has no execution time; saying so beats 0.0."""
        self.add_run("gfx900_ref_floor_r1", "interrupted", [],
                     started="2026-09-25T10:00:00", completed=None)
        d = self._driver()
        run = d._compute_execution_timing("gfx900_ref_floor_r1")["native_run"]
        assert run["elapsed_minutes"] is None
        assert run["elapsed_human"] == "unknown"
        assert run["in_flight"]

    def test_chain_and_native_are_reported_separately(self):
        """A resumed floor spans runs; one number would understate its cost."""
        self.add_run("gfx900_ref_floor_r1", "completed", [],
                     started="2026-09-25T10:00:00", completed="2026-09-25T12:00:00")
        d = self._driver()
        t = d._compute_execution_timing("gfx900_ref_floor_r1",
                                        {"SS": {"total_min": 5.0}})
        assert t["reference_chain"]["elapsed_minutes"] == 120.0
        assert t["phase_busy"]["minutes"] == 5.0
        assert "SS" in t["phase_busy"]["per_family_minutes"]

    def test_unknown_run_does_not_raise(self):
        d = self._driver()
        t = d._compute_execution_timing("no_such_run")
        assert t["native_run"]["elapsed_minutes"] is None
        assert t["native_run"]["elapsed_human"] == "unknown"

    def test_summary_includes_execution_time(self):
        from oto.metrics.acceptance_report import ABVerdict, AcceptanceReporter
        r = AcceptanceReporter(self.base)
        v = [ABVerdict(dtype="S", shape="1024x1024x1024", fp="f",
                       native_median=1.0, spoof_median=1.0, delta_pct=0.0,
                       tie=True, verdict="TIE", family="SS",
                       native_value=1.0, spoof_value=1.0, agg="winner")]
        timing = {"native_run": {"elapsed_human": "1d 2h 30m",
                                 "elapsed_minutes": 1590.0, "in_flight": False}}
        rep = r.generate_acceptance_report(
            run_id="r1", ab_verdicts=v, all_analytics=[], red_list=[],
            execution_timing=timing)
        assert "Execution time: 1d 2h 30m" in rep.summary
        assert rep.execution_timing == timing

    def test_timing_is_serialised_into_the_report_json(self):
        """family_timing used to be computed and then dropped on the floor."""
        from oto.metrics.acceptance_report import AcceptanceReporter
        r = AcceptanceReporter(self.base)
        timing = {"native_run": {"elapsed_human": "3h", "elapsed_minutes": 180.0,
                                 "in_flight": False}}
        ft = {"SS": {"cells": 3, "mean_sec": 10.0, "total_min": 0.5}}
        rep = r.generate_acceptance_report(
            run_id="r1", ab_verdicts=[], all_analytics=[], red_list=[],
            family_timing=ft, execution_timing=timing)
        out = self.base / "rep.json"
        r.write_report(rep, out)
        got = json.loads(out.read_text())
        assert got["execution_timing"] == timing
        assert got["family_timing"] == ft
