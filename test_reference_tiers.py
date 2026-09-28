#!/usr/bin/env python3
"""Regression tests for the T2 held/release flag plumbing.

No GPU work: run_gfx900_reference is stubbed and only the call arguments and
the tier-selection order are asserted.

Covers the three call sites that must forward release_held:
  1. run_gfx900_reference (fresh / direct)  -- the tier split itself
  2. run_auto  -> existing reference (resume branch)
  3. run_auto  -> NO existing reference (fresh branch)  <- the bug this guards
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import port_tensile as pt  # noqa: E402
import tensile_library as tl  # noqa: E402

T1 = ["p_t1_a", "p_t1_b", "p_t1_c"]
T2 = ["p_t2_a", "p_t2_b"]
T3 = ["p_t3_a", "p_t3_b"]
ALL = T1 + T2 + T3


def tiered(mapping):
    """mapping: phase -> tier"""
    return [{"phase_id": p, "tier": mapping[p]} for p in ALL]


MAPPING = {}
MAPPING.update({p: tl.TIER_FIRST for p in T1})
MAPPING.update({p: tl.TIER_HELD for p in T2})
MAPPING.update({p: tl.TIER_DROP for p in T3})

# apply_rerun_tiers looks tiers up by phase_key, so build the fixture manifest
# the same way the real one is built.
_PHASES = tiered(MAPPING)
MANIFEST = {"tiers_by_key": {tl.phase_key(p): p["tier"] for p in _PHASES},
            "tiers": {p["phase_id"]: p["tier"] for p in _PHASES}}


class TestTierSelection(unittest.TestCase):
    """apply_rerun_tiers is the single place ordering is decided."""

    def setUp(self):
        self.phases = _PHASES

    def test_default_drops_held_and_keeps_t1(self):
        out = tl.apply_rerun_tiers(self.phases, MANIFEST)
        self.assertEqual([p["phase_id"] for p in out], T1)

    def test_release_puts_held_last(self):
        out = tl.apply_rerun_tiers(self.phases, MANIFEST, release_held=True)
        self.assertEqual([p["phase_id"] for p in out], T1 + T2)

    def test_t3_never_staged_even_on_release(self):
        for rel in (False, True):
            out = tl.apply_rerun_tiers(_PHASES, MANIFEST, release_held=rel)
            self.assertNotIn("p_t3_a", [p["phase_id"] for p in out])

    def test_t1_precedes_t2_on_release(self):
        out = [p["phase_id"] for p in
               tl.apply_rerun_tiers(self.phases, MANIFEST, release_held=True)]
        self.assertLess(out.index("p_t1_c"), out.index("p_t2_a"))

    def test_lookup_is_by_phase_key_not_phase_id(self):
        """A rebuilt deck has different phase_ids; tiering must survive it."""
        rebuilt = [{"phase_id": f"rebuilt_{i}", "config": {"x": 1}}
                   for i in range(3)]
        man = {"tiers_by_key": {tl.phase_key(p): tl.TIER_FIRST
                                for p in _PHASES}}
        # every rebuilt phase is unrecognised -> TIER_KEEP, never a crash
        out = tl.apply_rerun_tiers(rebuilt, man)
        self.assertEqual(len(out), 3)

    def test_no_manifest_is_pass_through(self):
        out = tl.apply_rerun_tiers(self.phases, None)
        self.assertEqual([p["phase_id"] for p in out], ALL)

    def test_default_signature_is_conservative(self):
        sig = __import__("inspect").signature(tl.apply_rerun_tiers)
        self.assertFalse(sig.parameters["release_held"].default)


def _bare_driver():
    """Minimal driver instance: only the flags run_auto reads before it hands
    off to the reference runner.  No registry, no DB, no GPU."""
    d = pt.TensileDriver.__new__(pt.TensileDriver)
    d._stop_requested = False
    d._finish_after_iteration = False
    d.run_dir = Path("/tmp/opencode/_fake_run")
    return d


class TestCallSitePlumbing(unittest.TestCase):
    """The three call sites must forward the flag (regression for the
    run_auto fresh-branch bug where release_held was dropped)."""

    def test_run_gfx900_reference_default_is_false(self):
        sig = __import__("inspect").signature(
            pt.TensileDriver.run_gfx900_reference)
        self.assertFalse(sig.parameters["release_held"].default)

    def test_run_auto_default_is_false(self):
        sig = __import__("inspect").signature(pt.TensileDriver.run_auto)
        self.assertFalse(sig.parameters["release_held"].default)

    def test_run_auto_forwards_release_on_fresh_branch(self):
        """No existing reference -> run_gfx900_reference(release_held=...)"""
        drv = _bare_driver()
        with mock.patch.object(pt.TensileDriver, "run_preflight",
                               return_value=True), \
             mock.patch.object(pt.TensileDriver, "_latest_reference_run",
                               return_value=None), \
             mock.patch.object(pt.TensileDriver, "run_gfx900_reference",
                               return_value={"status": "completed",
                                             "run_id": "r"}) as mref, \
             mock.patch.object(pt.TensileDriver, "generate_acceptance_report",
                               return_value=None):
            pt.TensileDriver.run_auto(drv, budget=0, release_held=True)
        mref.assert_called_once()
        self.assertTrue(mref.call_args.kwargs.get("release_held"),
                        "run_auto dropped release_held on the fresh-reference "
                        "branch")

    def test_run_auto_forwards_release_on_resume_branch(self):
        drv = _bare_driver()
        with mock.patch.object(pt.TensileDriver, "run_preflight",
                               return_value=True), \
             mock.patch.object(pt.TensileDriver, "_latest_reference_run",
                               return_value="existing"), \
             mock.patch.object(pt.TensileDriver, "_reference_remaining",
                               side_effect=[5, 0]), \
             mock.patch.object(pt.TensileDriver, "run_gfx900_reference",
                               return_value={"status": "completed"}) as mref, \
             mock.patch.object(pt.TensileDriver, "generate_acceptance_report",
                               return_value=None):
            pt.TensileDriver.run_auto(drv, budget=0, release_held=True)
        self.assertTrue(mref.call_args.kwargs.get("release_held"))

    def test_run_auto_default_does_not_release(self):
        drv = _bare_driver()
        with mock.patch.object(pt.TensileDriver, "run_preflight",
                               return_value=True), \
             mock.patch.object(pt.TensileDriver, "_latest_reference_run",
                               return_value=None), \
             mock.patch.object(pt.TensileDriver, "run_gfx900_reference",
                               return_value={"status": "completed",
                                             "run_id": "r"}) as mref, \
             mock.patch.object(pt.TensileDriver, "generate_acceptance_report",
                               return_value=None):
            pt.TensileDriver.run_auto(drv, budget=0)
        self.assertFalse(mref.call_args.kwargs.get("release_held"))


class TestManifestIsPinned(unittest.TestCase):
    """The shipped manifest must stay in the conservative state."""

    def test_manifest_pins_t2(self):
        p = ROOT / "gfx90c_results" / "reference_rerun_manifest.json"
        if not p.exists():
            self.skipTest("manifest not present")
        import json
        m = json.load(open(p))
        by = m.get("tiers_by_key") or {}
        held = [k for k, v in by.items() if v == tl.TIER_HELD]
        self.assertEqual(len(held), 1881, "T2 hold count drifted")
        self.assertEqual(len([k for k, v in by.items()
                              if v == tl.TIER_FIRST]), 127)
        self.assertEqual(len([k for k, v in by.items()
                              if v == tl.TIER_DROP]), 277)


if __name__ == "__main__":
    unittest.main(verbosity=2)
