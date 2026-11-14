#!/usr/bin/env python3
"""Regression tests for the LDS/workgroup side of the occupancy gate.

The workgroup and LDS rules: 64K VGPR file holds dtype_weight * MT0 * MT1 *
LocalSplitU with room for operands; the LSU > 1 reduction buffer is LDS bytes
per bank; LDS reduction (LSU > 1) = LSU * MT0 * MT1 * numBytes() capped at the
65536-per-CU ceiling; real dtypes unaffected and unknown dtypes failing closed.
See ``tests/test_occupancy_model_vgpr.py`` for the per-thread rules, and
``tests/occupancy_gate_common.py`` for the shared synthetic config builder.
"""
import unittest

from occupancy_gate_common import cfg

from oto.tensile.gates.loads import validate_tensile_loads
from oto.tensile.gates.occupancy import (
    occupancy_feasible,
    occupancy_workgroups_per_cu,
)
from oto.tensile.gates.vgpr_model import (
    BYTES_PER_ELEMENT,
    LDS_BUDGET,
    VGPR_PER_ELEMENT,
)


class TestLdsGate(unittest.TestCase):
    """LDS is a second, independent limit -- on macro tile and depth, not
    thread tile. 128x32x16 complex needs 106496 B and Tensile rejects it with
    'Kernel Uses N > 65536 bytes of LDS', which no thread-tile fix can cure."""

    def test_depth_read_from_macro_tile_when_depth_u_absent(self):
        """Deck configs carry depth in MacroTile only; missing that read 16x small."""
        c = cfg("Z", "128x32x16", "2x8")
        c.pop("DepthU")
        assert not occupancy_feasible(c)[0]

    def test_depth_read_from_explicit_depth_u(self):
        assert not occupancy_feasible(cfg("Z", "128x32x16", "2x8", DepthU=16))[0]

    def test_128x32x16_rejected_however_thread_tile_is_chosen(self):
        for tt in ("2x2", "2x4", "4x2", "4x4", "2x8", "4x8", "8x4"):
            ok, _ = occupancy_feasible(cfg("Z", "128x32x16", tt))
            assert not ok, f"TT {tt} cannot rescue 128x32x16 (LDS bound)"

    def test_budget_sits_at_16384_bytes(self):
        """The budget does not move with the Z table: 16384, locked. For ZZ it
        binds at (MT0+MT1)*DepthU <= 1024 at Tensile's 16-byte element."""
        bpe = BYTES_PER_ELEMENT["Z"]
        assert LDS_BUDGET == 16384
        assert bpe == 16
        # Au niveau des tables: DD (8 B) tile at budget, and Z at DepthU 8:
        boundary8 = (64 + 64) * 8 * bpe   # Z at DepthU 8, exactly at budget
        beyond16 = (128 + 32) * 8 * bpe   # refused at DepthU 8 under the policy
        assert boundary8 == LDS_BUDGET
        assert beyond16 > LDS_BUDGET

    def test_measured_z_tiles_all_classified_correctly(self):
        """Post-2026-11-14 (Z == Tensile's 16 B, budget stays 16384): the
        policy refuses every ZZ tile with (MT0+MT1)*DepthU > 1024, including
        the tiles Tensile accepts. The curated deck obeys the refusal."""
        for mt, tt, legal in (
            ("32x32x8", "2x2", True), ("32x64x8", "2x4", True),
            ("64x32x8", "4x2", True), ("32x32x16", "2x2", True),
            ("32x32x16", "4x4", True), ("64x64x8", "4x2", True),
            ("64x64x8", "4x4", True), ("128x32x8", "2x8", False),
            ("32x128x8", "2x8", False), ("64x64x16", "2x2", False),
            ("64x64x16", "4x4", False), ("64x64x4", "4x4", True),
            ("128x32x16", "2x8", False),
        ):
            assert occupancy_feasible(cfg("Z", mt, tt))[0] == legal, f"{mt}/{tt}"

    def test_bytes_per_element_differs_from_vgpr_weight(self):
        """f64 is 8 bytes but only 2 VGPRs -- conflating them breaks the gate."""
        assert BYTES_PER_ELEMENT["D"] == 8
        assert VGPR_PER_ELEMENT["D"] == 2
        assert BYTES_PER_ELEMENT["H"] == 2


class TestMacroTileIsNotTheConstraint(unittest.TestCase):
    """The regression that motivated this rewrite."""

    def test_wide_macro_tile_with_small_thread_tile_is_legal(self):
        """64x64 with TT 8x4 needs 256 accVGPRs per thread; TT 2x8 on the same
        MacroTile is fine. At Tensile's 16 B, 128x32x8-class ZZ tiles are
        policy-refused on LDS before the thread tile gets a say."""
        assert not occupancy_feasible(cfg("Z", "64x64x8", "8x4"))[0]
        assert occupancy_feasible(cfg("Z", "64x64x8", "2x8"))[0]
        # the wide ZZ area ladder died with the 2026-11-14 decision
        assert not occupancy_feasible(cfg("Z", "128x32x8", "2x8"))[0]
        assert not occupancy_feasible(cfg("Z", "32x128x8", "2x8"))[0]

    def test_narrow_macro_tile_with_big_thread_tile_is_illegal(self):
        """The old area-based model could not express this at all."""
        assert not occupancy_feasible(cfg("Z", "32x32x8", "8x8"))[0]
        assert occupancy_feasible(cfg("Z", "32x32x8", "2x2"))[0]

    def test_old_dead_tiles_still_rejected(self):
        """The original error-4 tiles must not come back."""
        for mt, tt in (("128x64x8", "8x4"), ("64x128x8", "4x8")):
            assert not occupancy_feasible(cfg("Z", mt, tt))[0], f"{mt}/{tt} must stay rejected"


class TestWorkgroupRegisterFile(unittest.TestCase):
    """Tensile's second, independent register constraint (error 4).

    The per-thread rule above bounds ``TT0*TT1*weight``. The *workgroup* rule
    bounds every thread's accumulators together: ``weight*MT0*MT1*LocalSplitU``
    must stay strictly under the 64K file, because the kernel still needs
    operand and address VGPRs. ThreadTile cancels, so this fires on wide
    MacroTiles the per-thread rule accepts (C/Z 128x128x8 tt4x4: 64 accVGPR per
    thread passes the 128 budget, but 1024 threads * 64 = 65536 fills the file
    and Tensile raises "resulted in error 4").
    """

    def test_field_filling_tiles_are_refused(self):
        assert not occupancy_feasible(cfg("C", "128x128x8", "4x4"))[0]
        assert not occupancy_feasible(cfg("C", "128x128x8", "8x4"))[0]
        assert not occupancy_feasible(cfg("Z", "128x128x8", "2x2"))[0]
        assert not occupancy_feasible(cfg("Z", "128x64x8", "4x4"))[0]

    def test_one_step_down_the_area_ladder_is_legal(self):
        assert occupancy_feasible(cfg("C", "128x64x8", "8x4"))[0]
        assert occupancy_feasible(cfg("Z", "64x64x4", "4x4"))[0]
        # ZZ one area step below 128x64 died with the 2026-11-14 decision
        assert not occupancy_feasible(cfg("Z", "128x32x8", "4x4"))[0]
        assert not occupancy_feasible(cfg("Z", "32x128x8", "4x4"))[0]

    def test_threadtile_cancels_out_of_the_workgroup_rule(self):
        """Verdict follows MacroTile, not ThreadTile, once per-thread passes."""
        for tt in ("2x2", "4x4"):
            assert not occupancy_feasible(cfg("Z", "128x64x8", tt))[0], tt
        for tt in ("2x2", "4x4"):
            assert occupancy_feasible(cfg("Z", "64x64x8", tt))[0], tt

    def test_local_split_u_multiplies_the_workgroup_cost(self):
        """LSU is part of the workgroup cost, not just the load thread count.

        NumThreads = (MT0/TT0)*(MT1/TT1)*LSU, so the per-thread budget Tensile
        computes (65536 // NumThreads) halves when LSU doubles -- the reason the
        register reason is reported (the register rule is checked first).
        """
        ok, why = occupancy_feasible(
            cfg("D", "128x128x8", "8x8", LocalSplitU=2,
                WorkGroup=[16, 16, 2]))
        assert not ok
        assert "accumulator" in why
        # The same tile at LSU 1 is legal.
        assert occupancy_feasible(cfg("D", "128x128x8", "8x8"))[0]


class TestLdsReductionBuffer(unittest.TestCase):
    """LocalSplitU > 1 adds an LDS reduction buffer (SolutionStructs:4108).

    Tensile sizes it at ``LSU*MT0*MT1*ComputeDataType.numBytes()`` elements and
    rejects the kernel at :4334 when the byte total passes 65536 -- the
    "Kernel Uses 131072 > 65536 bytes of LDS" class (13 phases on the corpus).
    """

    def test_oversized_reduction_is_refused(self):
        # TT 8x8 so the *reduction* rule is the binding one: at 1024 threads
        # (TT 4x4) the per-thread occupancy limit fires first and says so.
        ok, why = occupancy_feasible(
            cfg("S", "128x128x8", "8x8", LocalSplitU=2, WorkGroup=[16, 16, 2]))
        assert not ok
        assert "reduction" in why

    def test_moderate_reduction_is_allowed(self):
        ok, why = occupancy_feasible(
            cfg("S", "64x64x8", "4x4", LocalSplitU=2, WorkGroup=[16, 16, 2]))
        assert ok, why

    def test_the_two_spellings_of_local_split_u_must_agree(self):
        """Tensile reads LSU from WorkGroup[2]; the key beside it is a no-op.

        The writer folds the key into element [2] so the knob is honoured, and
        the gate refuses a row whose two spellings disagree -- a config that
        means two different things must not be benchmarked by accident.
        """
        from oto.tensile.config_writer import _fork_thread_macro_workgroup
        folded = _fork_thread_macro_workgroup(
            {"WorkGroup": [16, 16, 1], "LocalSplitU": 2}, 4, 4, 64, 64)
        assert folded["WorkGroup"] == [[16, 16, 2]]
        ok, why = occupancy_feasible(
            cfg("C", "64x64x8", "4x4", WorkGroup=[16, 16, 1], LocalSplitU=2))
        assert not ok
        assert "LocalSplitU" in why
        ok, why = occupancy_feasible(
            cfg("C", "64x64x8", "4x4", WorkGroup=[16, 16, 2], LocalSplitU=2))
        assert ok, why

    def test_rule_only_applies_when_local_split_u_is_raised(self):
        """LSU 1 has no reduction buffer, however wide the MacroTile."""
        ok, why = occupancy_feasible(cfg("S", "128x128x8", "4x4"))
        assert ok, why


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
            ("Z", "64x64x4", "4x4"),   # ZZ: at-budget rung (64x64x16 family ladder retired)
        ]
        for dtype, mt, tt in winners:
            ok, why = occupancy_feasible(cfg(dtype, mt, tt))
            assert ok, f"{dtype} {mt}/{tt} regressed: {why}"

    def test_single_precision_allows_wide_thread_tiles(self):
        assert occupancy_feasible(cfg("S", "128x128x16", "8x8"))[0]
        assert occupancy_feasible(cfg("H", "128x128x16", "8x8"))[0]


class TestWorkgroupsPerCU(unittest.TestCase):
    def test_zero_when_rejected(self):
        assert occupancy_workgroups_per_cu(cfg("Z", "64x64x8", "8x8")) == 0
        assert occupancy_workgroups_per_cu(cfg("Z", "64x64x8", "8x4")) == 0

    def test_positive_for_legal(self):
        assert occupancy_workgroups_per_cu(cfg("Z", "64x64x8", "4x4")) >= 1
        assert occupancy_workgroups_per_cu(cfg("S", "128x128x16", "8x8")) >= 1

    def test_threadtile_cancels_in_workgroup_count(self):
        """A 4x2 tile on 64x64 and a 4x2 on 32x32 cost the same per thread."""
        a = occupancy_workgroups_per_cu(cfg("Z", "64x64x8", "4x2"))
        b = occupancy_workgroups_per_cu(cfg("Z", "32x32x8", "4x2"))
        assert a == b


class TestUnknownDTypeFailsClosed(unittest.TestCase):
    def test_missing_dtype_rejected(self):
        c = cfg("Z", "64x64x8", "4x4")
        del c["DataType"]
        del c["FamilyLabel"]
        ok, why = occupancy_feasible(c)
        assert not ok
        assert "no VGPR weight" in why

    def test_family_label_alias_still_resolves(self):
        for alias in ("S", "SS", "H", "HH", "D", "DD", "C", "CC", "Z", "ZZ"):
            c = cfg("Z", "64x64x8", "4x4", FamilyLabel=alias)
            del c["DataType"]
            ok, _ = occupancy_feasible(c)
            assert ok, f"FamilyLabel {alias} must map to a real weight"


class TestUnparseableTileFailsClosed(unittest.TestCase):
    """A placeholder tile ("NONE") must not crash a gate; it fails closed.

    The gates cannot model a non-numeric MacroTile, so each reports "nothing to
    check" rather than raising -- the contract ``tile_dims``/``_load_geometry``
    document, and the case that used to crash ``gate_calibration`` on a phase
    config whose fork carried a placeholder.
    """

    def test_load_gate_does_not_raise_on_a_placeholder_tile(self):
        for macro in ("NONE", ["NONE"], "MT_NONE", None):
            with self.subTest(macro=macro):
                ok, why = validate_tensile_loads(
                    cfg("S", "64x64x8", "4x4", MacroTile=macro))
                assert ok, why

    def test_occupancy_gate_does_not_raise_on_a_placeholder_tile(self):
        for macro in ("NONE", ["NONE"], None):
            with self.subTest(macro=macro):
                ok, why = occupancy_feasible(
                    cfg("S", "64x64x8", "4x4", MacroTile=macro))
                assert (ok, why) == (True, "")


class TestThreadTileCancellation(unittest.TestCase):
    def test_unchanged_config_is_still_legal(self):
        assert occupancy_feasible(cfg("S", "64x64x8", "4x4"))[0]

    def test_widening_thread_tile_can_turn_legal_illegal(self):
        assert occupancy_feasible(cfg("Z", "64x64x8", "4x4"))[0]
        assert not occupancy_feasible(cfg("Z", "64x64x8", "8x8"))[0]
