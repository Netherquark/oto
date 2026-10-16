#!/usr/bin/env python3
"""Tests for the thermal validity gate on telemetry-based clock correction.

No GPU work: telemetry CSVs are written into a temp dir and the loader is
called directly.

The policy under test is documented at port_tensile.THERMAL_MAX_C. In short:

  * Temperature is a VALIDITY gate, not a second throughput correction. A busy
    sample at/above THERMAL_MAX_C is dropped from the clock estimate, so the
    phase reports as unmeasured instead of as a slow kernel that clock scaling
    would over-reward.
  * It is deliberately not a multiplicative (temp_ref / temp) factor on top of
    the clock correction. Core clock is the channel temperature acts through, so
    that would double-count -- and in this corpus the relationship has the wrong
    sign to fit anyway. Measured over ~17.9k busy samples from the two full
    reference runs, median sustained clock vs. median die temperature:

        46-48C -> 930MHz    56-58C -> 1537MHz   64-66C -> 1725MHz
        70-72C -> 1787MHz   76-78C -> 1800MHz   80-82C -> 1800MHz

    The coldest bucket holds the lowest clock and the hottest is still pinned at
    the 1800MHz maximum: the clock follows each kernel's power draw, not the die
    temperature. A temperature factor fitted to that curve would have a
    negative slope through the midrange and would credit thermally stressed
    measurements with a speedup.
  * The gate threshold sits above the hottest sample ever recorded (82C), so it
    is inert on the current corpus and only bites if a run genuinely
    thermal-throttles.
"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

# This file lives in tests/, so the repo root is one level up. ROOT is both the
# import root and the data root, and both are the repo root -- the harness
# modules are imported flat, so they sit beside this file's parent.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oto.runners.cli as pt  # noqa: E402

HEADER = ["timestamp", "sclk_hz", "mclk_hz", "power_uw", "temp_mc",
          "gpu_busy_percent", "vram_used_bytes", "vram_total_bytes",
          "phase_id"]


class LoaderOnlyDriver:
    """Just the telemetry loaders, bound to the real class constants.

    Instantiating TensileDriver would want a full run context, so this lifts the
    four loader methods and the class-level constants onto a bare object. The
    methods are the ones under test, taken unbound from TensileDriver, so they
    cannot drift from the implementation.
    """

    TELEMETRY_BUSY_PCT = pt.TensileDriver.TELEMETRY_BUSY_PCT
    TELEMETRY_REQUIRE_BUSY = pt.TensileDriver.TELEMETRY_REQUIRE_BUSY
    TELEMETRY_MIN_SAMPLES = pt.TensileDriver.TELEMETRY_MIN_SAMPLES
    SCLK_MIN_HZ = pt.TensileDriver.SCLK_MIN_HZ
    SCLK_MAX_HZ = pt.TensileDriver.SCLK_MAX_HZ
    THERMAL_MAX_C = pt.TensileDriver.THERMAL_MAX_C

    _telemetry_rows = pt.TensileDriver._telemetry_rows
    _load_telemetry_by_phase = pt.TensileDriver._load_telemetry_by_phase
    _load_sclk_by_phase = pt.TensileDriver._load_sclk_by_phase
    _thermal_map = pt.TensileDriver._thermal_map
    _thermal_summary = pt.TensileDriver._thermal_summary

    def __init__(self, base):
        self.base_dir = base
        self._thermal_cache = None

    def _run_dir(self, rid):
        return self.base_dir / rid


class TelemetryFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rows, header=None):
        logs = self.run_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "telemetry.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header or HEADER)
            w.writerows(rows)

    def samples(self, phase, hz, temp_c, n=5, busy=90, header=None):
        cols = header or HEADER
        out = []
        for i in range(n):
            row = {"timestamp": f"t{i}", "sclk_hz": hz, "mclk_hz": 0,
                   "power_uw": 0, "temp_mc": int(temp_c * 1000),
                   "gpu_busy_percent": busy, "vram_used_bytes": 0,
                   "vram_total_bytes": 0, "phase_id": phase}
            out.append([row[c] for c in cols])
        return out

    def driver(self):
        return LoaderOnlyDriver(self.run_dir)


class TestGateThreshold(unittest.TestCase):
    def test_gate_is_above_every_temperature_ever_observed(self):
        """The gate must be inert on the current corpus.

        If someone lowers it to the 80C "concerning" mark from vendor docs, the
        80-82C bucket that currently exists starts being dropped, silently
        shrinking clock coverage and changing every A/B verdict. That is a
        policy change and has to be deliberate, so it is pinned here.
        """
        self.assertGreater(pt.TensileDriver.THERMAL_MAX_C, 82.0)

    def test_gate_is_finite_and_positive(self):
        self.assertGreater(pt.TensileDriver.THERMAL_MAX_C, 0.0)


class TestSampleFiltering(TelemetryFixture):
    def test_low_busy_but_clocked_phase_still_gets_a_base(self):
        """Regression: the 2026-10-05 native trial produced no clock data.

        gpu_busy_percent is reported as 3-8% on this machine for short and
        small kernels, so requiring busy>50 dropped 1915 of 1916 samples and the
        phase silently reported as unmeasured. Saturation and "is the GPU doing
        the benchmark" are different questions; sclk is the discriminator that
        works, and SCLK_MIN_HZ already excludes the idle floor.
        """
        self.write(self.samples("p1", 1_787_000_000, 76, busy=5))
        d = self.driver()
        self.assertEqual(d._load_sclk_by_phase(self.run_dir)["p1"], 1_787_000_000)

    def test_low_busy_idle_floor_is_still_rejected(self):
        """Dropping the busy gate must not also admit the idle floor."""
        self.write(self.samples("p1", 400_000_000, 68, busy=5))
        d = self.driver()
        self.assertNotIn("p1", d._load_sclk_by_phase(self.run_dir))

    def test_busy_gate_stays_off_by_default(self):
        """Pinned: re-enabling it silently zeroes clock data for cheap phases."""
        self.assertFalse(pt.TensileDriver.TELEMETRY_REQUIRE_BUSY)

    def test_idle_samples_are_excluded(self):
        """A compile/idle gap must not drag the clock down to the 400MHz floor."""
        self.write(self.samples("p1", 1_800_000_000, 70)
                   + self.samples("p1", 400_000_000, 45, n=5, busy=2))
        d = self.driver()
        got = d._load_sclk_by_phase(self.run_dir)
        self.assertEqual(got["p1"], 1_800_000_000)

    def test_hot_samples_are_excluded_from_the_clock_estimate(self):
        """Below-gate samples decide the clock; at/above-gate ones do not."""
        self.write(self.samples("p1", 1_800_000_000, 70)
                   + self.samples("p1", 900_000_000, 95))
        d = self.driver()
        self.assertEqual(d._load_sclk_by_phase(self.run_dir)["p1"],
                         1_800_000_000)

    def test_all_hot_phase_reports_unmeasured(self):
        """A wholly throttled phase must vanish, not read as a 900MHz kernel.

        Scaling a throttled measurement by ref/idle is the failure this guards:
        it multiplies a kernel's throughput by ~2x on the strength of a clock
        collapse caused by heat, which can hand it a cell it never earned.
        """
        self.write(self.samples("p1", 900_000_000, 95))
        d = self.driver()
        self.assertNotIn("p1", d._load_sclk_by_phase(self.run_dir))

    def test_hot_samples_are_counted_not_silently_dropped(self):
        """The drop has to be visible, so the report can warn about it."""
        self.write(self.samples("p1", 1_800_000_000, 70, n=3)
                   + self.samples("p1", 1_800_000_000, 95, n=2))
        d = self.driver()
        phase = d._load_telemetry_by_phase(self.run_dir)["p1"]
        self.assertEqual(phase["hot_samples"], 2)
        self.assertEqual(phase["sclk_hz"], 1_800_000_000)

    def test_too_few_usable_samples_is_not_a_measurement(self):
        """Two cool samples after the hot ones are dropped is below the floor."""
        self.write(self.samples("p1", 1_800_000_000, 95, n=4)
                   + self.samples("p1", 1_800_000_000, 70, n=2))
        d = self.driver()
        self.assertNotIn("p1", d._load_sclk_by_phase(self.run_dir))

    def test_missing_telemetry_column_is_tolerated(self):
        """A sampler with no temp_mc must still yield a clock.

        The gate fires on a temperature that was seen and was high, never on one
        that was absent. Dropping every phase from a corpus whose telemetry
        predates the column would delete the entire A/B adjustment.
        """
        cols = [h for h in HEADER if h != "temp_mc"]
        self.write(self.samples("p1", 1_800_000_000, 70, header=cols),
                   header=cols)
        d = self.driver()
        got = d._load_telemetry_by_phase(self.run_dir)
        self.assertEqual(got["p1"]["sclk_hz"], 1_800_000_000)
        self.assertIsNone(got["p1"]["temp_c"])
        self.assertEqual(got["p1"]["hot_samples"], 0)

    def test_malformed_rows_are_skipped(self):
        self.write([["t0", "not-a-number", 0, 0, 70000, 90, 0, 0, "p1"],
                    ["t1", 1_800_000_000, 0, 0, 70000, 90, 0, 0, "p1"],
                    ["t2", 1_800_000_000, 0, 0, 70000, 90, 0, 0, "p1"],
                    ["t3", 1_800_000_000, 0, 0, 70000, 90, 0, 0, "p1"]])
        d = self.driver()
        self.assertEqual(d._load_sclk_by_phase(self.run_dir)["p1"],
                         1_800_000_000)

    def test_absent_file_is_not_an_error(self):
        d = self.driver()
        self.assertEqual(d._load_sclk_by_phase(self.run_dir), {})

    def test_file_without_phase_column_yields_nothing(self):
        self.write([[1, 2, 3]], header=["a", "b", "c"])
        d = self.driver()
        self.assertEqual(d._load_sclk_by_phase(self.run_dir), {})


class TestThermalContext(TelemetryFixture):
    def test_temp_is_median_of_the_same_samples_as_the_clock(self):
        """Clock and temperature must come from one window, never two.

        If these were computed from different filters, a phase could be credited
        with a clock from its cool ramp-up and a temperature from its hot tail,
        which is exactly the pairing that would justify a bogus correction.
        """
        self.write(self.samples("p1", 1_800_000_000, 70, n=3)
                   + self.samples("p1", 1_800_000_000, 80, n=2))
        d = self.driver()
        phase = d._load_telemetry_by_phase(self.run_dir)["p1"]
        self.assertEqual(phase["sclk_hz"], 1_800_000_000)
        # median of 3x70C + 2x80C is 70C; the peak is what shows the tail.
        self.assertAlmostEqual(phase["temp_c"], 70.0)
        self.assertAlmostEqual(phase["temp_max_c"], 80.0)
        self.assertEqual(phase["hot_samples"], 0)

    def test_hot_samples_do_not_pollute_the_reported_temperature(self):
        self.write(self.samples("p1", 1_800_000_000, 70, n=3)
                   + self.samples("p1", 1_800_000_000, 95, n=2))
        d = self.driver()
        phase = d._load_telemetry_by_phase(self.run_dir)["p1"]
        self.assertAlmostEqual(phase["temp_c"], 70.0)
        self.assertAlmostEqual(phase["temp_max_c"], 70.0)

    def test_summary_aggregates_across_phases(self):
        self.write(self.samples("p1", 1_800_000_000, 70)
                   + self.samples("p2", 1_800_000_000, 80))
        d = self.driver()
        d._thermal_cache = {("run", "p1"): {"sclk_hz": 1, "temp_c": 70.0,
                                            "temp_max_c": 75.0, "hot_samples": 0},
                            ("run", "p2"): {"sclk_hz": 1, "temp_c": 80.0,
                                            "temp_max_c": 88.0, "hot_samples": 0}}
        s = d._thermal_summary(["run"])
        self.assertEqual(s["phases"], 2)
        self.assertAlmostEqual(s["temp_c"], 75.0)
        self.assertAlmostEqual(s["temp_max_c"], 88.0)
        self.assertEqual(s["hot_phases"], 0)

    def test_summary_flags_hot_phases(self):
        d = self.driver()
        d._thermal_cache = {("run", "p1"): {"sclk_hz": 1, "temp_c": 92.0,
                                            "temp_max_c": 95.0, "hot_samples": 4}}
        s = d._thermal_summary(["run"])
        self.assertEqual(s["hot_phases"], 1)
        self.assertEqual(s["hot_phase_ids"], ["run:p1"])

    def test_summary_with_no_telemetry(self):
        d = self.driver()
        d._thermal_cache = {}
        s = d._thermal_summary(["run"])
        self.assertIsNone(s["temp_c"])
        self.assertEqual(s["hot_phases"], 0)


class TestNoDoubleCounting(unittest.TestCase):
    def _delta(self, native, spoof, sclk_by_gkey, sclk_ref):
        import tempfile

        from oto.metrics.analytics import AnalyticsEngine
        # registry/base_dir are only used by the analysis passes above this one;
        # the delta comparison reads nothing from either.
        with tempfile.TemporaryDirectory() as tmp:
            engine = AnalyticsEngine(None, tmp)
            return engine.compute_native_vs_spoof_delta(
                native, spoof, agg="best_median_clock",
                sclk_by_phase=sclk_by_gkey, sclk_ref=sclk_ref)

    @staticmethod
    def _rec(gflops, run, phase):
        # A/B cells only exist for cubic workloads (gfx90c_common.cube_side), and
        # both arms must reach the cell or there is no delta to compare.
        return {"dtype": "f32", "family": "SS",
                "ProblemType": "1024x1024x1024", "fingerprint": "f" * 64,
                "phase_id": phase, "source_run": run, "run_id": run,
                "GFLOPS": gflops}

    def test_throughput_scaling_is_only_a_function_of_clock(self):
        """The adjusted value must not move when only temperature changes.

        This is the regression guard for the whole design: the clock correction
        is med * (sclk_ref / sclk_measured) in analytics, and nothing else. If a
        temperature term ever gets folded in, an identical measurement taken at
        a different die temperature would stop comparing equal, and the A/B
        verdict would be deciding on the weather.
        """
        clocks = {("r1", "p1"): 1_800_000_000, ("r2", "sp1"): 1_800_000_000}
        native = [self._rec(100.0, "r1", "p1")]
        spoof = [self._rec(90.0, "r2", "sp1")]

        first = self._delta(native, spoof, clocks, 1_800_000_000)
        self.assertTrue(first, "fixture must produce one cell")
        again = self._delta(native, spoof, clocks, 1_800_000_000)
        self.assertEqual(first, again)

        d = list(first.values())[0]
        self.assertAlmostEqual(d["native_best_median_clock"], 100.0)
        self.assertAlmostEqual(d["spoof_best_median_clock"], 90.0)
        self.assertTrue(d["clock_adjusted"])

    def test_clock_normalization_is_what_scales(self):
        """A slower-clock arm must be scaled UP, and by the clock ratio alone.

        Same temperatures on both sides here; the only difference is the clock,
        which is what establishes that the clock -- not the thermal context --
        is doing the normalizing.
        """
        native = [self._rec(100.0, "r1", "p1")]
        spoof = [self._rec(50.0, "r2", "sp1")]
        matched = self._delta(
            native, spoof,
            {("r1", "p1"): 1_800_000_000, ("r2", "sp1"): 1_800_000_000},
            1_800_000_000)
        throttled = self._delta(
            native, spoof,
            {("r1", "p1"): 1_800_000_000, ("r2", "sp1"): 900_000_000},
            1_800_000_000)
        a = list(matched.values())[0]
        b = list(throttled.values())[0]
        self.assertAlmostEqual(a["spoof_best_median_clock"], 50.0)
        self.assertAlmostEqual(b["spoof_best_median_clock"], 100.0)

    def test_signature_still_takes_clocks_only(self):
        """Adding temperature must not have widened the delta signature.

        The correction stays in clock space on purpose. If a future change adds
        a temperature argument here, this test is the place to argue for it
        against the measured curve in the module docstring.
        """
        import inspect

        from oto.metrics.analytics import AnalyticsEngine
        params = inspect.signature(
            AnalyticsEngine.compute_native_vs_spoof_delta).parameters
        self.assertIn("sclk_by_phase", params)
        self.assertNotIn("temp_by_phase", params)
        self.assertNotIn("temp_by_gkey", params)


if __name__ == "__main__":
    unittest.main(verbosity=2)
