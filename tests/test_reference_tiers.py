#!/usr/bin/env python3
"""Regression tests for the T2 held/release flag plumbing.

No GPU work: run_gfx900_reference is stubbed and only the call arguments and
the tier-selection order are asserted.

Covers the three call sites that must forward release_held:
  1. run_gfx900_reference (fresh / direct)  -- the tier split itself
  2. run_auto  -> existing reference (resume branch)
  3. run_auto  -> NO existing reference (fresh branch)  <- the bug this guards
"""
import hashlib
import json
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

# This file lives in tests/, so the repo root is one level up. ROOT is both the
# import root and the data root (the results dir), and both are the repo root --
# the harness modules are imported flat, so they sit beside this file's parent.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oto.runners.auto_prompt as ap
import oto.runners.driver as pt
import oto.tensile.shipped_manifest as tl
from oto.runners.paths import results_rel
from oto.tensile.shipped_library import _CANON

T1 = ["p_t1_a", "p_t1_b", "p_t1_c"]
T2 = ["p_t2_a", "p_t2_b"]
T3 = ["p_t3_a", "p_t3_b"]
ALL = T1 + T2 + T3


def tiered(mapping):
    """mapping: phase -> tier"""
    return [{"phase_id": p, "tier": mapping[p]} for p in ALL]


MAPPING = {}
MAPPING.update(dict.fromkeys(T1, tl.TIER_FIRST))
MAPPING.update(dict.fromkeys(T2, tl.TIER_HELD))
MAPPING.update(dict.fromkeys(T3, tl.TIER_DROP))

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
        assert [p["phase_id"] for p in out] == T1

    def test_release_puts_held_last(self):
        out = tl.apply_rerun_tiers(self.phases, MANIFEST, release_held=True)
        assert [p["phase_id"] for p in out] == T1 + T2

    def test_t3_dropped_unless_release_drop(self):
        """T3 is dropped by default, and is NOT bundled with releasing T2."""
        for rel in (False, True):
            out = tl.apply_rerun_tiers(_PHASES, MANIFEST, release_held=rel)
            assert "p_t3_a" not in [p["phase_id"] for p in out], "answering yes to T2 must not stage T3"

    def test_t3_staged_at_the_back_on_release_drop(self):
        out = [p["phase_id"] for p in
               tl.apply_rerun_tiers(_PHASES, MANIFEST, release_drop=True)]
        assert "p_t3_a" in out
        # T2 stays pinned -- releasing T3 is not a release of T2
        assert out == T1 + T3

    def test_t1_precedes_t3_on_release_drop(self):
        out = [p["phase_id"] for p in
               tl.apply_rerun_tiers(_PHASES, MANIFEST, release_drop=True)]
        assert out.index("p_t1_c") < out.index("p_t3_a")

    def test_both_releases_staged_independently(self):
        out = [p["phase_id"] for p in tl.apply_rerun_tiers(
            _PHASES, MANIFEST, release_held=True, release_drop=True)]
        assert out == T1 + T2 + T3

    def test_t1_precedes_t2_on_release(self):
        out = [p["phase_id"] for p in
               tl.apply_rerun_tiers(self.phases, MANIFEST, release_held=True)]
        assert out.index("p_t1_c") < out.index("p_t2_a")

    def test_lookup_is_by_phase_key_not_phase_id(self):
        """A rebuilt deck has different phase_ids; tiering must survive it."""
        rebuilt = [{"phase_id": f"rebuilt_{i}", "config": {"x": 1}}
                   for i in range(3)]
        man = {"tiers_by_key": {tl.phase_key(p): tl.TIER_FIRST
                                for p in _PHASES}}
        # every rebuilt phase is unrecognised -> TIER_KEEP, never a crash
        out = tl.apply_rerun_tiers(rebuilt, man)
        assert len(out) == 3

    def test_no_manifest_is_pass_through(self):
        out = tl.apply_rerun_tiers(self.phases, None)
        assert [p["phase_id"] for p in out] == ALL

    def test_default_signature_is_conservative(self):
        sig = __import__("inspect").signature(tl.apply_rerun_tiers)
        assert not sig.parameters["release_held"].default
        assert not sig.parameters["release_drop"].default


def _bare_driver():
    """Minimal driver instance: only the flags run_auto reads before it hands
    off to the reference runner.  No registry, no DB, no GPU."""
    d = pt.TensileDriver.__new__(pt.TensileDriver)
    d._stop_requested = False
    d._finish_after_iteration = False
    d.run_dir = Path("fake_run_does_not_exist_on_disk")
    return d


class TestCallSitePlumbing(unittest.TestCase):
    """The three call sites must forward the flag (regression for the
    run_auto fresh-branch bug where release_held was dropped)."""

    def test_run_gfx900_reference_default_is_false(self):
        sig = __import__("inspect").signature(
            pt.TensileDriver.run_gfx900_reference)
        assert not sig.parameters["release_held"].default

    def test_run_auto_default_is_false(self):
        sig = __import__("inspect").signature(pt.TensileDriver.run_auto)
        assert not sig.parameters["release_held"].default

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
        assert mref.call_args.kwargs.get("release_held"), "run_auto dropped release_held on the fresh-reference " "branch"

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
            pt.TensileDriver.run_auto(drv, budget=0, release_held=True,
                                      plan=ap.AutoPlan(rerun_illegal=True))
        assert mref.call_args.kwargs.get("release_held")

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
            pt.TensileDriver.run_auto(drv, budget=0,
                                      plan=ap.AutoPlan(rerun_illegal=True))
        assert not mref.call_args.kwargs.get("release_held")


class TestManifestIsPinned(unittest.TestCase):
    """Structural guarantees on the audited manifest.

    Asserts the *shape* of the triage, never the corpus size. Pinning literal
    totals here just moves the staleness: the next re-triaged cell fails this
    test without anything actually being wrong. What must hold forever is that
    every shipped cell carries exactly one known tier, that T2 stays pinned, and
    that the prompt's numbers agree with the manifest (which is what the user is
    actually shown).
    """

    def setUp(self):
        p = ROOT / results_rel("reference_rerun_manifest.json")
        sm = ROOT / results_rel("gfx900_shipped_manifest.json")
        if not p.exists() or not sm.exists():
            self.skipTest("manifest not present")
        self.m = json.load(open(p))
        self.shipped = json.load(open(sm))
        self.by = self.m.get("tiers_by_key") or {}

    def _tier_counts(self):
        c = Counter(v for v in self.by.values())
        return (c.get(tl.TIER_HELD, 0), c.get(tl.TIER_FIRST, 0),
                c.get(tl.TIER_DROP, 0))

    def test_t2_stays_pinned(self):
        held, _, _ = self._tier_counts()
        assert held > 0, "T2 must remain held by default"

    def test_every_shipped_cell_has_exactly_one_known_tier(self):
        known = {tl.TIER_KEEP, tl.TIER_FIRST, tl.TIER_HELD,
                 tl.TIER_LAST, tl.TIER_DROP}
        seen = 0
        for pats in self.shipped["families"].values():
            for dt in pats.values():
                for name in dt["kernels"]:
                    seen += 1
                    k = tl.phase_key(
                        {"kernel": _CANON.sub("Cijk", name)})
                    assert k in self.by, f"{k} is missing from the audited manifest"
                    assert self.by[k] in known, f"{k} has an unknown tier {self.by[k]!r}"
        assert len(self.by) == seen, "manifest must not tier anything outside the corpus"

    def test_recorded_counts_match_the_keys(self):
        held, first, drop = self._tier_counts()
        counts = self.m.get("counts") or {}
        assert counts.get(tl.TIER_HELD, 0) == held
        assert counts.get(tl.TIER_FIRST, 0) == first
        assert counts.get(tl.TIER_DROP, 0) == drop

    def test_prompt_numbers_agree_with_the_manifest(self):
        """The banner the user reads is built from the same tiers."""
        import oto.runners.auto_prompt as auto_prompt
        counts = auto_prompt._read_counts(ROOT)
        held, first, drop = self._tier_counts()
        assert counts["illegal"] == first
        assert counts["underspecified"] == held
        assert counts["unreproducible"] == drop


class TestSSUnbuildableTriaged(unittest.TestCase):
    """The 16 SS cells Tensile 4.44 cannot build must stay T3 with a reason.

    They were ILLEGAL because our own config emitter was wrong. The emitter is
    fixed now, and the remaining 16 rejects are not ours to fix: Tensile refuses
    the *shipped* kernel regardless of which knobs are pinned. The only variant
    that compiled (23e1d06b, probed 2026-09-28) needed FractionalLoad=1, which is
    a different kernel -- it would have made the floor describe something other
    than the reference. So they move to T3 with the reject text recorded.

    If a future Tensile can build them, this test is what will notice.
    """

    #: phase_id suffix -> the reject Tensile actually printed in the run log.
    REJECTED = {
        # classic global-load divisibility -> "No valid DepthU found"
        "0880ea65": "No valid DepthU",
        "23e1d06b": "No valid DepthU",
        "261e9d1a": "No valid DepthU",
        "4aef4399": "No valid DepthU",
        "558db072": "No valid DepthU",
        "6769a5e5": "No valid DepthU",
        "737cd099": "No valid DepthU",
        "748f0da1": "No valid DepthU",
        "97ff23ce": "No valid DepthU",
        "e0c50513": "No valid DepthU",
        "e7f706ca": "No valid DepthU",
        "eb9521a6": "No valid DepthU",
        # ThreadTile not a multiple of VectorWidth
        "82478872": "not a multiple of VectorWidth",
        "ebaaa20e": "not a multiple of VectorWidth",
        # GlobalLoadVectorWidthA must be == VectorWidth or == 1
        "7f866dcf": "must be == VectorWidth",
        "a0edeb30": "must be == VectorWidth",
    }
    #: killed mid-run, so it is not a Tensile reject and stays T1
    INTERRUPTED = "184f2441"

    def setUp(self):
        import json
        p = ROOT / results_rel("reference_rerun_manifest.json")
        sm = ROOT / results_rel("gfx900_shipped_manifest.json")
        if not p.exists() or not sm.exists():
            self.skipTest("manifest not present")
        self.m = json.load(open(p))
        self.by = self.m.get("tiers_by_key") or {}
        self.reasons = self.m.get("tier_reasons") or {}
        # phase_id suffix -> canonical kernel name, i.e. what phase_key hashes
        self.name_of = {}
        for pats in json.load(open(sm))["families"].values():
            for dt in pats.values():
                for n in dt["kernels"]:
                    self.name_of[hashlib.sha1(n.encode()).hexdigest()[:8]] = \
                        _CANON.sub("Cijk", n)

    def _key(self, tag):
        return tl.phase_key({"kernel": self.name_of[tag]})

    def test_every_rejected_cell_is_t3(self):
        assert len(self.REJECTED) == 16
        for tag in self.REJECTED:
            k = self._key(tag)
            assert self.by.get(k) == tl.TIER_DROP, f"{tag} must be T3_UNREPRODUCIBLE, got {self.by.get(k)!r}"

    def test_reject_reason_is_recorded_per_cell(self):
        # tier_reasons is keyed by phase_id. phase_ids are re-derived from the
        # shipped knobs and have changed between runs, so resolve the current one
        # from the deck rather than trusting a tag-shaped substring.
        sm = ROOT / results_rel("gfx900_shipped_manifest.json")
        pid_of = {tl.phase_key(p): p["phase_id"]
                  for p in tl.emit_spoof_phases(json.load(open(sm)))}
        for tag, frag in self.REJECTED.items():
            key = self._key(tag)
            pid = pid_of.get(key)
            assert pid is not None, f"{tag} is not in the emitted deck"
            assert pid in self.reasons, f"{tag} has no recorded reason for its current phase_id"
            assert frag in self.reasons[pid], f"{tag} is missing reject text {frag!r}"

    def test_interrupted_cell_is_not_reclassified(self):
        """184f2441 was killed mid-run. That is not a Tensile reject.

        It must keep its T1 verdict so the resume re-measures it.
        """
        assert self.by.get(self._key(self.INTERRUPTED)) == tl.TIER_FIRST

    def test_reclassification_did_not_empty_any_cell(self):
        """The floor is best-per-cell, so losing non-winners must not matter.

        Guards the actual risk of moving 16 cells to T3: a cell left with no
        reference kernel at all would have no floor to compare against.
        """
        sm = ROOT / results_rel("gfx900_shipped_manifest.json")
        cells = {}
        for fam, pats in json.load(open(sm))["families"].items():
            for pat, dt in pats.items():
                cells.setdefault((fam, pat), set())
                for n in dt["kernels"]:
                    cells[(fam, pat)].add(
                        tl.phase_key({"kernel": _CANON.sub("Cijk", n)}))
        empty = []
        for cell, keys in cells.items():
            usable = [k for k in keys if self.by.get(k) != tl.TIER_DROP]
            if not usable:
                empty.append(cell)
        assert empty == [], f"cells left with no floor-usable reference: {empty}"


def _name_for(_tag):
    raise NotImplementedError


if __name__ == "__main__":
    unittest.main(verbosity=2)
