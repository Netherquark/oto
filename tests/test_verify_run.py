#!/usr/bin/env python3
"""Tests for verify_run.py -- the append-only / telemetry-usability checks.

No GPU: snapshots are taken against temp dirs and telemetry CSVs are written by
hand, exactly as test_thermal_gate.py does for the loaders.

What is pinned here is the behaviour the tool exists for: a run that appends
must read clean, and any shrink, in-place edit, removal or registry row loss
must read as a violation with a non-zero exit. A checker that cannot fail is
worse than no checker, so the failure paths get as much coverage as the happy one.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oto.tools.verify_run as vr

TELEMETRY_HEADER = ("timestamp,sclk_hz,mclk_hz,power_uw,temp_mc,gpu_busy_percent,"
                    "vram_used_bytes,vram_total_bytes,phase_id")


def snap(dirs=None, tables=None):
    return {"dirs": dirs or {}, "tables": tables or {}}


class TestDiffDetectsViolations(unittest.TestCase):
    def test_identical_snapshots_are_clean(self):
        s = snap({"run_a": [10, 100]}, {"runs": 1, "phases": 1, "records": 5})
        got = vr.diff_snapshots(s, s)
        assert got["ok"]
        assert got["violations"] == []

    def test_new_run_dir_and_more_rows_is_additive(self):
        before = snap({"run_a": [10, 100]}, {"runs": 1, "phases": 1, "records": 5})
        after = snap({"run_a": [10, 100], "run_b": [3, 30]},
                     {"runs": 2, "phases": 1, "records": 7})
        got = vr.diff_snapshots(before, after)
        assert got["ok"], got["violations"]
        assert got["added"] == ["run_b"]

    def test_shrinking_a_run_dir_is_a_violation(self):
        before = snap({"run_a": [10, 100]}, {"runs": 1, "phases": 1, "records": 5})
        after = snap({"run_a": [9, 90]}, {"runs": 1, "phases": 1, "records": 5})
        got = vr.diff_snapshots(before, after)
        assert not got["ok"]
        assert any("SHRANK" in v for v in got["violations"])

    def test_rewriting_in_place_is_a_violation_even_when_bigger(self):
        """Counts and bytes, not content hashes.

        A phase rerun that rewrites its CSVs in place usually leaves a similar
        size, and appending into an existing run dir is never legitimate either
        way -- so growth inside a run dir is reported, not waved through.
        """
        before = snap({"run_a": [10, 100]}, {"runs": 1, "phases": 1, "records": 5})
        after = snap({"run_a": [11, 111]}, {"runs": 1, "phases": 1, "records": 6})
        got = vr.diff_snapshots(before, after)
        assert not got["ok"]
        assert any("modified in place" in v for v in got["violations"])

    def test_removing_a_run_dir_is_a_violation(self):
        before = snap({"run_a": [10, 100], "run_b": [2, 20]},
                      {"runs": 2, "phases": 1, "records": 5})
        after = snap({"run_a": [10, 100]}, {"runs": 2, "phases": 1, "records": 5})
        got = vr.diff_snapshots(before, after)
        assert not got["ok"]
        assert got["removed"] == ["run_b"]

    def test_registry_rows_may_only_increase(self):
        before = snap({}, {"runs": 2, "phases": 3, "records": 10})
        after = snap({}, {"runs": 2, "phases": 3, "records": 9})
        got = vr.diff_snapshots(before, after)
        assert not got["ok"]
        assert any("records decreased" in v for v in got["violations"])

    def test_absent_table_is_not_treated_as_zero(self):
        """A missing table is unknown, not a count of 0.

        Reporting None as 0 would make every table look like it had lost all its
        rows the first time a snapshot is taken against a fresh DB.
        """
        before = snap({}, {"runs": 1, "phases": None, "records": None})
        after = snap({}, {"runs": 1, "phases": None, "records": None})
        got = vr.diff_snapshots(before, after)
        assert got["ok"], got["violations"]
        assert got["tables"]["phases"]["delta"] is None


class TestSnapshotShape(unittest.TestCase):
    def test_snapshot_of_temp_corpus_counts_dirs_and_rows(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "gfx90c_runs" / "run_x" / "phase_y").mkdir(parents=True)
            (base / "gfx90c_runs" / "run_x" / "phase_y" / "a.csv").write_text("1,2\n")
            (base / "gfx90c_results").mkdir()
            import sqlite3
            conn = sqlite3.connect(base / "gfx90c_results" / "registry.db")
            conn.execute("create table runs (run_id text)")
            conn.execute("insert into runs values ('run_x')")
            conn.commit()
            conn.close()

            got = vr.snapshot(base)
            assert got["dirs"] == {"run_x": [1, 4]}
            assert got["tables"]["runs"] == 1
            # Tables not created in this DB are None, not 0.
            assert got["tables"]["records"] is None

    def test_snapshot_of_empty_corpus_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            got = vr.snapshot(Path(d))
            assert got["dirs"] == {}
            assert got["tables"] == {}


class TestTelemetryFunnel(unittest.TestCase):
    def _run(self, rows, header=TELEMETRY_HEADER):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        logs = base / "gfx90c_runs" / "run_x" / "logs"
        logs.mkdir(parents=True)
        (logs / "telemetry.csv").write_text(
            "\n".join([header] + [",".join(str(c) for c in r) for r in rows]) + "\n")
        return base

    @staticmethod
    def _row(pid, hz, busy, temp_c=70):
        return [0, hz, 0, 20_000_000, int(temp_c * 1000), busy, 0, 0, pid]

    def test_missing_telemetry_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            got = vr.telemetry("run_nope", Path(d))
            assert not got["ok"]
            assert "error" in got

    def test_rows_without_phase_id_are_counted_separately(self):
        base = self._run([self._row("", 1_800_000_000, 5)] * 3)
        got = vr.telemetry("run_x", base)
        assert got["tagged_rows"] == 0
        assert got["untagged_rows"] == 3

    def test_legacy_schema_without_phase_id_is_flagged(self):
        base = self._run([self._row("p1", 1_800_000_000, 5)] * 4,
                         header="timestamp,sclk_hz,mclk_hz,power_uw,temp_mc,"
                                "gpu_busy_percent,vram_used_bytes,vram_total_bytes")
        got = vr.telemetry("run_x", base)
        assert not got["schema_ok"]
        assert not got["ok"]

    def test_low_busy_but_clocked_phase_is_not_reported_unmeasured(self):
        """The 2026-10-05 defect class: a filter must not hide data as silence.

        amdgpu reports 3-8% busy for small kernels, so this phase has zero
        samples above the busy threshold. It still has a real clock, and the
        funnel must say so rather than implying the run measured nothing.
        """
        base = self._run([self._row("p1", 1_787_000_000, 5)] * 6)
        got = vr.telemetry("run_x", base)
        e = got["phases"]["p1"]
        assert e["busy"] == 0, "precondition: nothing clears the busy gate"
        assert e["sclk"] == 6
        assert e["has_base"]
        assert got["unmeasured_phases"] == []

    def test_idle_floor_samples_are_reported_as_dropped(self):
        base = self._run([self._row("p1", 1_800_000_000, 80)] * 4
                         + [self._row("p1", 400_000_000, 2)] * 5)
        got = vr.telemetry("run_x", base)
        e = got["phases"]["p1"]
        assert e["sclk"] == 4, "the 400MHz idle floor must not be counted"
        assert e["hot"] == 0

    def test_hot_samples_are_reported_separately(self):
        base = self._run([self._row("p1", 1_800_000_000, 90, temp_c=70)] * 4
                         + [self._row("p1", 1_700_000_000, 90, temp_c=95)] * 3)
        got = vr.telemetry("run_x", base)
        e = got["phases"]["p1"]
        assert e["sclk"] == 7, "temp is a later gate, so sclk sees both"
        assert e["hot"] == 3
        assert e["clock"] == 4


class TestCliExitCodes(unittest.TestCase):
    """The exit code is the contract -- these run the tool as a subprocess."""

    def _cli(self, *args):
        return subprocess.run([sys.executable, "-m", "oto", "verify", "run", *args],
                              capture_output=True, text=True)

    def test_diff_exits_nonzero_on_violation(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.json", Path(d) / "b.json"
            a.write_text(json.dumps(snap({"run_a": [5, 50]},
                                         {"runs": 1, "phases": 1, "records": 2})))
            b.write_text(json.dumps(snap({"run_a": [4, 40]},
                                         {"runs": 1, "phases": 1, "records": 2})))
            res = self._cli("diff", str(a), str(b))
            assert res.returncode == 1, res.stdout + res.stderr
            assert "VIOLATIONS" in res.stdout

    def test_diff_exits_zero_when_additive(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.json", Path(d) / "b.json"
            a.write_text(json.dumps(snap({"run_a": [5, 50]},
                                         {"runs": 1, "phases": 1, "records": 2})))
            b.write_text(json.dumps(snap({"run_a": [5, 50], "run_b": [1, 10]},
                                         {"runs": 2, "phases": 1, "records": 3})))
            res = self._cli("diff", str(a), str(b))
            assert res.returncode == 0, res.stdout + res.stderr

    def test_snapshot_then_diff_on_this_corpus_is_clean(self):
        """Real repo, no writes: two snapshots must be identical.

        This is the tool's own smoke test, and it fails loudly if some other
        module has started writing into gfx90c_runs/ during a read-only command.
        """
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.json", Path(d) / "b.json"
            for out in (a, b):
                assert self._cli("--base-dir", str(ROOT), "snapshot", "--out", str(out)).returncode == 0
            res = self._cli("diff", str(a), str(b))
            assert res.returncode == 0, res.stdout + res.stderr


if __name__ == "__main__":
    unittest.main()
