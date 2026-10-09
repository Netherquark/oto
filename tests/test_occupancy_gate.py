#!/usr/bin/env python3
"""
test_occupancy_gate.py — regression tests for the register-file occupancy gate.

The gate exists because complex (Z) phases kept dying inside Tensile, twice for
two different reasons, and neither was caught before burning real GPU time:

  * 8 phases, run_20260920_235815 / run_20260926_201835: macro tiles 128x64 and
    64x128 failed with overflowedResources == 4 ("Occupancy limit").
  * 232 attempts, run_20260928_024945: thread tiles 8x4 and 8x8 failed with
    "Generating asm kernel error: total vgpr: 271 not in [0, 256]".

The gate now models the real constraint, measured with Tensile's own kernel
writer (see check_tensile_build.py, which is CPU-only):

    accVGPRs per thread = ThreadTile0 * ThreadTile1 * dtype_weight
    a thread is architecturally capped at 256 VGPRs

MacroTile does not appear in that expression -- it only changes how many threads
share the 64K register file. An earlier version of this gate modelled
R * MacroTile_area <= 32768 instead, which passed every failing case above.

Run: python3 test_occupancy_gate.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

# This file lives in tests/, so the repo root is one level up. BASE is both the
# import root and the data root (phases.yaml) and the cwd used to shell out to
# check_candidates.py, and all three are the repo root.
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
for _p in (os.environ.get("TENSILE_ROOT"), "/home/netherquark/Soham/Large_code/sources/GPU/Tensile"):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

from scheduler import (ACCVGPR_BUDGET, BYTES_PER_ELEMENT, LDS_BUDGET,  # noqa: E402
                       MAX_VGPR_PER_THREAD, MEASURED_VGPR,
                       MEASURED_VGPR_BY_DTYPE, VGPR_PER_ELEMENT,
                       VGPR_BUDGET, VGPR_PER_CU, occupancy_feasible,
                       occupancy_workgroups_per_cu)

# Ground truth: per-thread VGPR totals Tensile's kernel writer reported on
# gfx90c for complex (Z, weight 8) thread tiles.
OBSERVED = {
    (2, 2): 63,   # 32x32x8 and 32x32x16
    (4, 2): 95,   # 64x64x8
    (2, 4): 99,   # 32x64x8
    (4, 4): 154,  # 64x64x8
    (2, 8): 171,  # 32x128x8
    (8, 4): 271,  # 128x32x8  -- FAILED for real
    (8, 8): 519,  # 64x64x16  -- FAILED for real
}


def cfg(dtype, macro, thread, **kw):
    """Config helper. DepthU mirrors the MacroTile depth unless overridden, so
    a test cannot accidentally assert on a shallower tile than it names."""
    parts = str(macro).split("x")
    depth = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 8
    c = {"DataType": dtype, "FamilyLabel": dtype, "MacroTile": macro,
         "ThreadTile": thread, "VectorWidth": 1, "DepthU": depth,
         "WorkGroupMapping": 4, "GlobalSplitU": 1, "StaggerU": 32,
         "ContractionPattern": "Ailk_Bjlk", "LdsPadB": 0}
    c.update(kw)
    return c


class TestVGPRWeights(unittest.TestCase):
    def test_complex_costs_double(self):
        self.assertEqual(VGPR_PER_ELEMENT["Z"], 2 * VGPR_PER_ELEMENT["C"])
        self.assertEqual(VGPR_PER_ELEMENT["C"], 2 * VGPR_PER_ELEMENT["D"])
        self.assertEqual(VGPR_PER_ELEMENT["D"], 2 * VGPR_PER_ELEMENT["S"])
        self.assertEqual(VGPR_PER_ELEMENT["S"], VGPR_PER_ELEMENT["H"])

    def test_isa_cap_is_256_per_thread(self):
        self.assertEqual(MAX_VGPR_PER_THREAD, 256)
        self.assertEqual(VGPR_PER_CU, 65536)
        self.assertEqual(VGPR_BUDGET, 32768)


class TestMeasuredRule(unittest.TestCase):
    def test_accvgpr_is_threadtile_times_weight(self):
        for (t0, t1), total in OBSERVED.items():
            acc = t0 * t1 * VGPR_PER_ELEMENT["Z"]
            self.assertLessEqual(
                acc, total,
                f"TT {t0}x{t1}: accumulators ({acc}) must fit inside the "
                f"observed total ({total})",
            )

    def test_observed_totals_are_monotonic_in_threadtile(self):
        """More accumulators never means fewer VGPRs."""
        by_area = sorted(OBSERVED, key=lambda t: t[0] * t[1])
        totals = [OBSERVED[t] for t in by_area]
        self.assertEqual(totals, sorted(totals), by_area)

    def test_gate_matches_every_observed_outcome(self):
        """The gate must agree with the hardware for all measured thread tiles."""
        for (t0, t1), total in OBSERVED.items():
            ok, why = occupancy_feasible(
                cfg("Z", "64x64x8", f"{t0}x{t1}")
            )
            legal_in_reality = total <= MAX_VGPR_PER_THREAD
            self.assertEqual(
                ok, legal_in_reality,
                f"TT {t0}x{t1} measured {total} VGPRs; gate said "
                f"{'legal' if ok else 'illegal'} ({why})",
            )

    def test_measured_table_matches_observation(self):
        self.assertEqual(MEASURED_VGPR, OBSERVED)

    def test_corpus_measured_totals_agree_with_gate(self):
        """Corpus code-object measurements (harness/measure_vgprs.py) must
        agree with the gate for every dtype: totals of gate-passing configs are
        < 256 VGPRs, totals of gate-failing ones are >= 256. This is the
        empirical link between the accVGPR model and emitted reality."""
        for ch, table in MEASURED_VGPR_BY_DTYPE.items():
            weight = VGPR_PER_ELEMENT[ch]
            for (t0, t1), total in table.items():
                acc = t0 * t1 * weight
                gate_ok = acc <= ACCVGPR_BUDGET
                legal = total <= MAX_VGPR_PER_THREAD
                self.assertEqual(
                    gate_ok, legal,
                    f"{ch} TT {t0}x{t1}: acc model {acc} vs budget "
                    f"{ACCVGPR_BUDGET}, measured {total} VGPRs",
                )

    def test_budget_sits_between_last_pass_and_first_fail(self):
        last_ok = max(t0 * t1 * VGPR_PER_ELEMENT["Z"]
                      for (t0, t1), v in OBSERVED.items() if v <= MAX_VGPR_PER_THREAD)
        first_bad = min(t0 * t1 * VGPR_PER_ELEMENT["Z"]
                        for (t0, t1), v in OBSERVED.items() if v > MAX_VGPR_PER_THREAD)
        self.assertEqual(ACCVGPR_BUDGET, last_ok)
        self.assertGreater(first_bad, last_ok)


class TestVectorWidthCap(unittest.TestCase):
    """The native deck must contain a 16 B global-load config for every family.

    11 of the 16 large-cell losses had one cause: the family decks hardcoded a
    VectorWidth one step below the cap, so the winning config was never even
    generated. 11 cells could not be won by any number of iterations.
    """

    def setUp(self):
        from scheduler import CandidateGenerator
        g = CandidateGenerator.__new__(CandidateGenerator)
        self.decks = g._load_family_decks()

    def test_cap_vector_width_reproduces_the_floor_winners(self):
        from scheduler import cap_vector_width
        # The floor's winning widths, read off the completed reference chain.
        for fam, mt, tt, want in (
            ("SS", "128x128x16", "8x8", 4),
            ("HH", "128x128x16", "8x8", 8),
            ("DD", "64x64x8", "4x4", 2),
        ):
            self.assertEqual(cap_vector_width(fam, mt, tt), want, fam)

    def test_cap_vector_width_never_exceeds_the_hardware_cap(self):
        from scheduler import (cap_vector_width, FAMILY_BYTES_PER_ELEMENT,
                               GLOBAL_LOAD_BYTE_CAP)
        for fam, bpe in FAMILY_BYTES_PER_ELEMENT.items():
            for vw in (1, 2, 4, 8):
                v = cap_vector_width(fam, "128x128x16", "8x8")
                self.assertLessEqual(v * bpe, GLOBAL_LOAD_BYTE_CAP, fam)

    def test_cap_vector_width_respects_tile_divisibility(self):
        from scheduler import cap_vector_width
        # vw may not exceed the per-thread extent of a macro-tile dimension.
        self.assertLessEqual(cap_vector_width("SS", "32x32x16", "4x4"), 8)
        self.assertLessEqual(cap_vector_width("SS", "16x16x16", "8x8"), 2)

    def test_every_wide_family_deck_reaches_the_cap(self):
        from scheduler import FAMILY_BYTES_PER_ELEMENT
        for fam in ("SS", "DD", "HH"):
            bpe = FAMILY_BYTES_PER_ELEMENT[fam]
            best = 0
            for c in self.decks[fam]:
                vw = c.get("VectorWidth")
                if vw:
                    best = max(best, vw * bpe)
            self.assertEqual(
                best, 16,
                f"{fam} deck tops out at {best} B; the 16 B cap is unreachable "
                f"and this family cannot win a large cell")

    def test_added_candidates_pass_the_dual_resource_gate(self):
        from scheduler import occupancy_feasible, FAMILY_DTYPE_CHAR
        checked = 0
        for fam, cfgs in self.decks.items():
            for c in cfgs:
                vw = c.get("VectorWidth")
                if not vw:
                    continue
                # DataType must be the real dtype char, not the family label: a
                # phase's DataType is what the gate weights, and the label is
                # only a fallback for label-only auto phases.
                config = {"DataType": FAMILY_DTYPE_CHAR[fam], "FamilyLabel": fam,
                          "NLCA": 1, "WorkGroupMapping": 4, "GlobalSplitU": 1,
                          "ContractionPattern": "Ailk_Bjlk", "VectorWidth": vw}
                config.update({k: v for k, v in c.items() if k != "NLCA"})
                ok, why = occupancy_feasible(config)
                self.assertTrue(ok, f"{fam} {c.get('MacroTile')} vw{vw}: {why}")
                checked += 1
        self.assertGreater(checked, 0)

    def test_family_labels_resolve_to_a_dtype(self):
        """Every family in a deck must be modellable by the register-file gate.

        A family label with no mapping in _dtype_char makes occupancy fail
        closed, which drops the whole family from generation rather than
        reporting a bad config.
        """
        from scheduler import _dtype_char, VGPR_PER_ELEMENT
        for fam in self.decks:
            ch = _dtype_char({"DataType": fam, "FamilyLabel": fam})
            self.assertIn(ch, VGPR_PER_ELEMENT,
                          f"{fam} resolves to dtype {ch!r}, absent from "
                          f"VGPR_PER_ELEMENT; its candidates would all be dropped")

    def test_widened_variants_do_not_duplicate_an_existing_tile(self):
        from scheduler import cap_vector_width
        for fam in ("SS", "DD", "HH"):
            seen = set()
            for c in self.decks[fam]:
                key = (c.get("MacroTile"), c.get("ThreadTile"), c.get("VectorWidth"))
                self.assertNotIn(key, seen, f"duplicate {fam} {key}")
                seen.add(key)
            widths = {c.get("VectorWidth") for c in self.decks[fam]}
            self.assertTrue(widths, fam)


class TestLdsGate(unittest.TestCase):
    """LDS is a second, independent limit -- on macro tile and depth, not
    thread tile. 128x32x16 complex needs 106496 B and Tensile rejects it with
    'Kernel Uses N > 65536 bytes of LDS', which no thread-tile fix can cure."""

    def test_depth_read_from_macro_tile_when_depth_u_absent(self):
        """Deck configs carry depth in MacroTile only; missing that read 16x small."""
        c = cfg("Z", "128x32x16", "2x8")
        c.pop("DepthU")
        self.assertFalse(occupancy_feasible(c)[0])

    def test_depth_read_from_explicit_depth_u(self):
        self.assertFalse(occupancy_feasible(cfg("Z", "128x32x16", "2x8", DepthU=16))[0])

    def test_128x32x16_rejected_however_thread_tile_is_chosen(self):
        for tt in ("2x2", "2x4", "4x2", "4x4", "2x8", "4x8", "8x4"):
            ok, _ = occupancy_feasible(cfg("Z", "128x32x16", tt))
            self.assertFalse(ok, f"TT {tt} cannot rescue 128x32x16 (LDS bound)")

    def test_budget_sits_at_measured_boundary(self):
        bpe = BYTES_PER_ELEMENT["Z"]
        self.assertEqual(LDS_BUDGET, 16384)
        legal = (64 + 64) * 16 * bpe
        dead = (128 + 32) * 16 * bpe
        self.assertEqual(legal, LDS_BUDGET)
        self.assertGreater(dead, LDS_BUDGET)

    def test_measured_z_tiles_all_classified_correctly(self):
        for mt, tt, legal in (
            ("32x32x8", "2x2", True), ("32x64x8", "2x4", True),
            ("64x32x8", "4x2", True), ("32x32x16", "2x2", True),
            ("32x32x16", "4x4", True), ("64x64x8", "4x2", True),
            ("64x64x8", "4x4", True), ("128x32x8", "2x8", True),
            ("32x128x8", "2x8", True), ("64x64x16", "2x2", True),
            ("64x64x16", "4x4", True), ("128x32x16", "2x8", False),
        ):
            self.assertEqual(occupancy_feasible(cfg("Z", mt, tt))[0], legal,
                             f"{mt}/{tt}")

    def test_bytes_per_element_differs_from_vgpr_weight(self):
        """f64 is 8 bytes but only 2 VGPRs -- conflating them breaks the gate."""
        self.assertEqual(BYTES_PER_ELEMENT["D"], 8)
        self.assertEqual(VGPR_PER_ELEMENT["D"], 2)
        self.assertEqual(BYTES_PER_ELEMENT["H"], 2)


class TestMacroTileIsNotTheConstraint(unittest.TestCase):
    """The regression that motivated this rewrite."""

    def test_wide_macro_tile_with_small_thread_tile_is_legal(self):
        """128x32 with TT 8x4 died 116 times; TT 2x8 on the same MT is fine."""
        self.assertFalse(occupancy_feasible(cfg("Z", "128x32x8", "8x4"))[0])
        self.assertTrue(occupancy_feasible(cfg("Z", "128x32x8", "2x8"))[0])

    def test_narrow_macro_tile_with_big_thread_tile_is_illegal(self):
        """The old area-based model could not express this at all."""
        self.assertFalse(occupancy_feasible(cfg("Z", "32x32x8", "8x8"))[0])
        self.assertTrue(occupancy_feasible(cfg("Z", "32x32x8", "2x2"))[0])

    def test_old_dead_tiles_still_rejected(self):
        """The original error-4 tiles must not come back."""
        for mt, tt in (("128x64x8", "8x4"), ("64x128x8", "4x8")):
            self.assertFalse(
                occupancy_feasible(cfg("Z", mt, tt))[0],
                f"{mt}/{tt} must stay rejected",
            )


class TestRealDtypesUnaffected(unittest.TestCase):
    def test_shipped_native_winners_still_legal(self):
        """Every tile that actually won a cell must survive the new gate."""
        winners = [
            ("S", "128x128x16", "8x8"),   # SS:2048 etc
            ("S", "128x128x8", "8x8"),
            ("S", "64x64x8", "4x4"),
            ("S", "256x128x8", "16x8"),
            ("S", "128x256x8", "8x16"),
            ("H", "128x128x16", "8x8"),   # HH:2048
            ("H", "128x256x8", "8x16"),
            ("D", "64x64x16", "4x4"),     # DD
            ("C", "64x64x8", "4x4"),      # CC
            ("Z", "64x32x8", "4x2"),      # ZZ:1024 winner
            ("Z", "32x32x8", "2x2"),      # ZZ:128/192/512 winner
            ("Z", "32x32x16", "2x2"),
            ("Z", "64x64x8", "4x4"),
            ("Z", "32x128x8", "2x8"),
        ]
        for dtype, mt, tt in winners:
            ok, why = occupancy_feasible(cfg(dtype, mt, tt))
            self.assertTrue(ok, f"{dtype} {mt}/{tt} regressed: {why}")

    def test_single_precision_allows_wide_thread_tiles(self):
        self.assertTrue(occupancy_feasible(cfg("S", "128x128x16", "8x8"))[0])
        self.assertTrue(occupancy_feasible(cfg("H", "128x128x16", "8x8"))[0])


class TestWorkgroupsPerCU(unittest.TestCase):
    def test_zero_when_rejected(self):
        self.assertEqual(occupancy_workgroups_per_cu(cfg("Z", "64x64x8", "8x8")), 0)
        self.assertEqual(occupancy_workgroups_per_cu(cfg("Z", "64x64x8", "8x4")), 0)

    def test_positive_for_legal(self):
        self.assertGreaterEqual(occupancy_workgroups_per_cu(cfg("Z", "64x64x8", "4x4")), 1)
        self.assertGreaterEqual(occupancy_workgroups_per_cu(cfg("S", "128x128x16", "8x8")), 1)

    def test_threadtile_cancels_in_workgroup_count(self):
        """A 4x2 tile on 64x64 and a 4x2 on 32x32 cost the same per thread."""
        a = occupancy_workgroups_per_cu(cfg("Z", "64x64x8", "4x2"))
        b = occupancy_workgroups_per_cu(cfg("Z", "32x32x8", "4x2"))
        self.assertEqual(a, b)


class TestUnknownDTypeFailsClosed(unittest.TestCase):
    def test_missing_dtype_rejected(self):
        c = cfg("Z", "64x64x8", "4x4")
        del c["DataType"]
        del c["FamilyLabel"]
        ok, why = occupancy_feasible(c)
        self.assertFalse(ok)
        self.assertIn("no VGPR weight", why)

    def test_family_label_alias_still_resolves(self):
        for alias in ("S", "SS", "H", "HH", "D", "DD", "C", "CC", "Z", "ZZ"):
            c = cfg("Z", "64x64x8", "4x4", FamilyLabel=alias)
            del c["DataType"]
            ok, _ = occupancy_feasible(c)
            self.assertTrue(ok, f"FamilyLabel {alias} must map to a real weight")


class TestThreadTileCancellation(unittest.TestCase):
    def test_unchanged_config_is_still_legal(self):
        self.assertTrue(occupancy_feasible(cfg("S", "64x64x8", "4x4"))[0])

    def test_widening_thread_tile_can_turn_legal_illegal(self):
        self.assertTrue(occupancy_feasible(cfg("Z", "64x64x8", "4x4"))[0])
        self.assertFalse(occupancy_feasible(cfg("Z", "64x64x8", "8x8"))[0])


class TestLiveDeck(unittest.TestCase):
    """The whole deck must satisfy every gate, not just hand-picked cases."""

    def setUp(self):
        self.deck = yaml.safe_load((BASE / "phases.yaml").read_text()) or []

    def test_deck_is_fully_legal(self):
        bad = []
        for p in self.deck:
            ok, why = occupancy_feasible(p["config"])
            if not ok:
                bad.append(f"{p['phase_id']}: {why}")
        self.assertEqual(bad, [], f"{len(bad)} live phases rejected:\n" + "\n".join(bad[:10]))

    def test_deck_has_no_dead_tiles(self):
        """The thread tiles that died on real hardware must be absent."""
        dead = {("128x32x8", "8x4"), ("128x32x16", "8x4"),
                ("64x64x16", "8x8"), ("128x64x8", "8x4"), ("64x128x8", "4x8")}
        zpresent = {
            (str(p["config"].get("MacroTile")), str(p["config"].get("ThreadTile")))
            for p in self.deck
            if str(p["config"].get("DataType", "")).upper() == "Z"
        }
        still = dead & zpresent
        self.assertEqual(still, set(), f"dead complex tiles still in deck: {still}")


class TestTensileBuildProof(unittest.TestCase):
    """If a build-proof report is present, the gate must agree with Tensile."""

    @staticmethod
    def _report():
        env = os.environ.get("OCCUPANCY_PROOF")
        if env:
            return Path(env)
        d = Path("/tmp/opencode")
        found = sorted(d.glob("zz*.json"), key=lambda q: q.stat().st_mtime)
        return found[-1] if found else d / "zz_build.json"

    def test_agrees_with_tensile_when_report_available(self):
        rep = self._report()
        if not rep.exists():
            self.skipTest(f"no build proof at {rep}")
        rows = json.loads(rep.read_text())
        deck = {p["phase_id"]: p for p in yaml.safe_load((BASE / "phases.yaml").read_text())}
        checked = mismatch = 0
        for row in rows:
            phase = deck.get(row["phase_id"])
            if not phase:
                continue
            ok, _ = occupancy_feasible(phase["config"])
            checked += 1
            if ok != row["ok"]:
                mismatch += 1
                self.fail(f"{row['phase_id']}: model "
                          f"{'legal' if ok else 'illegal'} but Tensile "
                          f"{'legal' if row['ok'] else 'illegal'}")
        self.assertGreater(checked, 0)
        self.assertEqual(mismatch, 0)


class TestDeckLinter(unittest.TestCase):
    def test_check_candidates_reports_clean(self):
        tool = BASE / "check_candidates.py"
        if not tool.exists():
            self.skipTest("check_candidates.py not present")
        proc = subprocess.run(
            [sys.executable, str(tool), "--quiet"],
            capture_output=True, text=True, cwd=str(BASE), timeout=1800,
        )
        self.assertIn(proc.returncode, (0, 1), proc.stdout + proc.stderr)
        self.assertNotIn("FAIL", proc.stdout)


class TestGeneratedPhaseCellIdentity(unittest.TestCase):
    """A generated phase must carry the family that defines its workload cell.

    cell_key() is built from config["FamilyLabel"], and the driver drops the
    cell_key stamp entirely when that is missing (cell_key("", side) is None),
    leaving analytics to recover the family from the phase_id text instead.
    That fallback happens to work today, so a missing FamilyLabel is silent:
    the run completes, the cells still fill in, and nothing looks wrong. It is
    still a real defect -- the documented identity path is the config, and the
    H/HH_HPA split (both DataType 'H') is exactly what the phase_id heuristic
    has to get right on its own. So assert the config carries it, not that the
    fallback happens to cope.
    """

    def _generated(self, family, pattern="Ailk_Bjlk", shape="256x256x256"):
        import tempfile
        from pathlib import Path
        from scheduler import CandidateGenerator
        with tempfile.TemporaryDirectory() as tmp:
            gen = CandidateGenerator(Path(tmp))
            cands = gen.generate_family_phases(family, [pattern], [shape])
            self.assertTrue(cands, f"no candidates generated for {family}")
            return cands

    def test_every_family_emits_a_resolvable_cell_key(self):
        from gfx90c_common import FAMILY_SHAPES, cell_key
        for family, sides in FAMILY_SHAPES.items():
            with self.subTest(family=family):
                shape = f"{sides[0]}x{sides[0]}x{sides[0]}"
                for cand in self._generated(family, shape=shape):
                    cfg = {**cand.template, **cand.knobs}
                    self.assertEqual(
                        cfg.get("FamilyLabel"), family,
                        f"{cand.phase_id} has no FamilyLabel; its records would "
                        f"be stamped with no cell_key")
                    self.assertIsNotNone(
                        cell_key(cfg.get("FamilyLabel"), shape),
                        f"{cand.phase_id} does not resolve to a cell key")

    def test_family_label_is_not_derivable_from_dtype(self):
        """'H' covers three families, so DataType cannot stand in for it."""
        from gfx90c_common import FAMILY_DTYPE_CHAR
        by_dtype = {}
        for fam, dt in FAMILY_DTYPE_CHAR.items():
            by_dtype.setdefault(dt, set()).add(fam)
        ambiguous = {dt: f for dt, f in by_dtype.items() if len(f) > 1}
        self.assertIn("H", ambiguous,
                      "expected the H dtype to be family-ambiguous")
        # DTYPE_TO_FAMILY resolves 'H' to HH alone, so anything relying on the
        # dtype fallback would fold HH_HPA and HS_HPA into HH.
        self.assertEqual(ambiguous["H"], {"HH", "HH_HPA", "HS_HPA"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
