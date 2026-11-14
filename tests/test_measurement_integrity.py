#!/usr/bin/env python3
"""Tests for the measurement-integrity invariants.

Three seams that silently corrupted results before, and whose failure mode is
invisible in the output:

1. The classic-load gate's dtype table (``gates.loads.LOAD_DTYPE_INFO``) carried
   the ComplexFloat row for complex double (2 registers, 8 bytes), so its 16 B
   global-load cap admitted a ZZ VectorWidth 2 and Tensile rejected those configs
   at solution construction. It now reads ComplexDouble's 4/16 and every row is
   pinned to ``Tensile DataType.numBytes()``.
2. ``ab_audit.phase_family`` decides whether two measurements are comparable at
   all. It must read the *generator* (Tensile AutoTuner vs a deck sweep), not
   the raw phase-id prefix, or the live deck's ``phase_<cell>_*`` and the
   floor's ``phase_ss_*`` get misfiled as different generators.
3. Measurement data must never be overwritten in place: run directories,
   telemetry CSVs, per-phase results, and the locked floor.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import oto.metrics.ab_audit as ab_audit
import oto.tensile.candidate as candidate
import oto.tensile.gates.vgpr_model as vgpr_model
from oto.metrics.telemetry import HEADER, TelemetrySampler
from oto.tools.consolidate import _TENSILE_ROOT, dtype_bytes

if _TENSILE_ROOT and str(_TENSILE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TENSILE_ROOT))


class TestDtypeByteTable(unittest.TestCase):
    """scheduler's byte table must agree with Tensile.DataType."""

    #: Families whose loaded operands are a single dtype, so the char lookup is
    #: exact. HS/HS_HPA and HH_HPA are mixed-precision and are governed by
    #: their widest loaded operand, checked separately below.
    SINGLE_DTYPE = {"SS": "S", "DD": "D", "HH": "H", "CC": "C", "ZZ": "Z"}

    def test_single_dtype_families_match_tensile(self):
        for family, char in self.SINGLE_DTYPE.items():
            with self.subTest(family=family):
                assert dtype_bytes(char) is not None, f"Tensile has no dtype for char {char}"
                assert vgpr_model.FAMILY_BYTES_PER_ELEMENT[family] == dtype_bytes(char), f"{family}: scheduler table disagrees with Tensile numBytes()"

    def test_complex_double_is_16_bytes(self):
        """The exact defect: ZZ was 8, which let VectorWidth 2 through."""
        assert dtype_bytes("Z") == 16
        assert vgpr_model.FAMILY_BYTES_PER_ELEMENT["ZZ"] == 16

    def test_zz_vector_width_capped_at_one(self):
        for mt, tt in (("64x64x16", "4x4"), ("128x128x16", "8x8")):
            with self.subTest(macro=mt):
                assert candidate.cap_vector_width("ZZ", mt, tt) <= 1, "complex double must not admit VectorWidth 2"

    def test_load_gate_dtype_table_matches_tensile(self):
        """The classic-load gate carries its own dtype row, and it had drifted.

        ``Z`` held the ComplexFloat numbers (2 registers, 8 bytes) instead of
        ComplexDouble's (4, 16), so the gate's 16 B-cap read
        ``GLVW 2 * 8 = 16 <= 16`` while Tensile computed ``2 * 16 = 32`` and
        refused the solution -- the live
        ``phase_cand_zz_128_32x64x8_tt2x4_..._vw2`` phase. Pinning every row to
        Tensile's ``numBytes()`` is what keeps the two tables from splitting
        again. ``I8`` is skipped: Tensile spells int8 ``I8`` while
        ``dtype_bytes`` looks up the first character, which lands on int32.
        """
        from oto.tensile.gates.loads import LOAD_DTYPE_INFO
        for char in ("S", "D", "H", "B", "Z", "C"):
            with self.subTest(char=char):
                want = dtype_bytes(char)
                assert want is not None, f"Tensile has no dtype {char}"
                assert LOAD_DTYPE_INFO[char]["bytes"] == want, f"{char}: load gate says {LOAD_DTYPE_INFO[char]['bytes']} B, " f"Tensile numBytes() says {want}"
                assert int(LOAD_DTYPE_INFO[char]["reg"] * 4) == want, f"{char}: reg is not numBytes/4"

    def test_mixed_precision_families_governed_by_widest_operand(self):
        """HS/HS_HPA load a single alongside a half; HH_HPA loads half."""
        assert vgpr_model.FAMILY_BYTES_PER_ELEMENT["HS"] == dtype_bytes("S"), "HS is governed by its single operand"
        assert vgpr_model.FAMILY_BYTES_PER_ELEMENT["HS_HPA"] == dtype_bytes("S"), "HS_HPA is governed by its single operand"
        assert vgpr_model.FAMILY_BYTES_PER_ELEMENT["HH_HPA"] == dtype_bytes("H"), "HH_HPA is governed by its half operand"

    def test_all_runs_shares_the_same_table(self):
        """all_runs.py carried its own copy and drifted to the same wrong ZZ."""
        import oto.tools.run_census as all_runs
        assert all_runs.DTYPE_BYTES["Z"] == dtype_bytes("Z")
        for family, byte_width in vgpr_model.FAMILY_BYTES_PER_ELEMENT.items():
            with self.subTest(family=family):
                assert all_runs.DTYPE_BYTES[all_runs.FAMILY_CHAR[family]] == byte_width, f"{family} disagrees between all_runs and scheduler"


class TestPhaseFamily(unittest.TestCase):
    """The certainty tier is only as good as this mapping."""

    def test_autotuner_phases_are_auto(self):
        assert ab_audit.phase_family("phase_auto_0_S_1000x1000x1000_9") == "auto"

    def test_all_deck_namings_are_one_generator(self):
        for pid in ("phase_ss_Ailk_Bjlk_mt128x128x16_tt8x8_vw2_wgm4_alu",
                    "phase_hh_Ailk_Bjlk_mt128x128x16_tt8x8_vw4_wgm4_alu",
                    "phase_ss_gfx900_Ailk_Bjlk_mt128-tt8-vw2-du16-gsu1-88dde43f"):
            with self.subTest(phase=pid):
                assert ab_audit.phase_family(pid) == "deck", "deck sweeps must not be split by prefix"

    def test_missing_phase_id_is_unknown_not_deck(self):
        assert ab_audit.phase_family("") == "unknown"


class TestTelemetryIsAppendOnly(unittest.TestCase):
    def test_matching_schema_reuses_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "telemetry.csv"
            p.write_text(HEADER + "\n1,2,3,4,5,6,7,8,phase_x\n")
            s = TelemetrySampler(p)
            assert s._resolve_log_path() == p

    def test_legacy_schema_is_not_appended_to(self):
        """Appending 9-field rows to an 8-column file yields an unparseable CSV."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "telemetry.csv"
            legacy = "timestamp,sclk_hz,mclk_hz,power_uw,temp_mc," \
                     "gpu_busy_percent,vram_used_bytes,vram_total_bytes\n"
            p.write_text(legacy + "1,2,3,4,5,6,7,8\n")
            s = TelemetrySampler(p)
            chosen = s._resolve_log_path()
            assert chosen != p, "must step aside from a legacy file"
            assert chosen.suffix == ".csv"
            # The previous data is left exactly as it was.
            assert p.read_text() == legacy + "1,2,3,4,5,6,7,8\n"

    def test_missing_file_is_used_directly(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "telemetry.csv"
            assert TelemetrySampler(p)._resolve_log_path() == p


class TestRunDirIsNotSilentlyReused(unittest.TestCase):
    def _registry(self, root: Path):
        from oto.ledger.registry import SQLiteRegistry
        return SQLiteRegistry(root)

    def test_populated_run_dir_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            reg = self._registry(Path(d))
            run = reg.create_run_dir("run_fixed")
            # Stand in for a phase that has already written its results.
            (run / "phase_x").mkdir()
            with pytest.raises(FileExistsError):
                reg.create_run_dir("run_fixed")

    def test_explicit_reuse_is_allowed_and_keeps_data(self):
        with tempfile.TemporaryDirectory() as d:
            reg = self._registry(Path(d))
            reg.create_run_dir("run_fixed")
            (reg.runs_dir / "run_fixed" / "marker.txt").write_text("keep")
            reg.create_run_dir("run_fixed", allow_existing=True)
            assert (reg.runs_dir / "run_fixed" / "marker.txt").read_text() == "keep", "continuing a run must not clear what is already there"

    def test_fresh_run_dir_is_fine(self):
        with tempfile.TemporaryDirectory() as d:
            reg = self._registry(Path(d))
            reg.create_run_dir("run_a")
            reg.create_run_dir("run_b")


class TestPhaseResultsAreNotOverwritten(unittest.TestCase):
    def test_rerun_refuses_existing_benchmark_csvs(self):
        import oto.runners.benchmark as _bench

        with tempfile.TemporaryDirectory() as d:
            phase_out = Path(d) / "phase_test"
            (phase_out / "2_BenchmarkData").mkdir(parents=True)
            (phase_out / "2_BenchmarkData" / "Cijk_Ailk_Bjlk_SB_00.csv").write_text(
                "GFlops, SizeI\n1,2\n")

            class _Stub:
                tensile_root = Path(d)

            with pytest.raises(FileExistsError):
                _bench.BenchmarkMixin._run_tensile_benchmark(
                    _Stub(), Path(d) / "cfg.yaml", phase_out, 60)

    def test_empty_phase_dir_is_allowed(self):
        import oto.runners.benchmark as _bench

        with tempfile.TemporaryDirectory() as d:
            phase_out = Path(d) / "phase_fresh"

            class _Stub:
                tensile_root = Path(d) / "no-such-tensile"

                def __init__(self, root):
                    self.client_build_dir = root / "client_build"
                    self.client_build_dir.mkdir(parents=True, exist_ok=True)

                def _get_tensile_env(self):
                    return {}

            # No Tensile binary present, so it returns a failure result rather
            # than raising; the point is that the guard did not fire.
            result = _bench.BenchmarkMixin._run_tensile_benchmark(
                _Stub(Path(d)), Path(d) / "cfg.yaml", phase_out, 5)
            assert isinstance(result, dict)


class TestLockedFloorIsSwappedNotDeleted(unittest.TestCase):
    def test_install_does_not_delete_the_live_lock(self):
        """A rebuild must never rmtree the locked floor in place."""
        src = (Path(__file__).resolve().parent.parent
               / "oto" / "tools" / "consolidate_install.py").read_text()
        body = src.split("def install(", 1)[1]
        assert "rmtree(live_lock)" not in body, "install() must archive the old lock, not delete it"
        assert "superseded_locks" in body


if __name__ == "__main__":
    unittest.main()
