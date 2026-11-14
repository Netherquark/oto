#!/usr/bin/env python3
"""Regression tests for the register-file side of the occupancy gate.

The per-thread and vectorisation rules: accumulators are ThreadTile0 *
ThreadTile1 * dtype_weight (capped by the 256-VGPR ISA limit), the vector
width is capped by dtype size and thread-tile shape, and VHI/load geometry is
validated against the same measured tables Tensile reported on gfx90c.
See ``tests/test_occupancy_model_lds.py`` for the LDS/workgroup rules, and
``tests/support_occupancy_gate.py`` for the shared ground truth.
"""
import unittest

from support_occupancy_gate import OBSERVED, cfg

from oto.device import loader as _loader
from oto.tensile.gates.loads import validate_tensile_loads
from oto.tensile.gates.occupancy import occupancy_feasible
from oto.tensile.gates.vgpr_model import (
    ACCVGPR_BUDGET,
    MAX_VGPR_PER_THREAD,
    MEASURED_VGPR,
    MEASURED_VGPR_BY_DTYPE,
    VGPR_PER_ELEMENT,
)


class TestVGPRWeights(unittest.TestCase):
    def test_complex_costs_double(self):
        assert VGPR_PER_ELEMENT["Z"] == 2 * VGPR_PER_ELEMENT["C"]
        assert VGPR_PER_ELEMENT["C"] == 2 * VGPR_PER_ELEMENT["D"]
        assert VGPR_PER_ELEMENT["D"] == 2 * VGPR_PER_ELEMENT["S"]
        assert VGPR_PER_ELEMENT["S"] == VGPR_PER_ELEMENT["H"]

    def test_isa_cap_is_256_per_thread(self):
        assert MAX_VGPR_PER_THREAD == 256
        assert _loader.current_profile().vgpr_per_cu == 65536
        assert _loader.current_profile().vgpr_per_cu // 2 == 32768


class TestMeasuredRule(unittest.TestCase):
    def test_accvgpr_is_threadtile_times_weight(self):
        for (t0, t1), total in OBSERVED.items():
            acc = t0 * t1 * VGPR_PER_ELEMENT["Z"]
            assert acc <= total, f"TT {t0}x{t1}: accumulators ({acc}) must fit inside the " f"observed total ({total})"

    def test_observed_totals_are_monotonic_in_threadtile(self):
        """More accumulators never means fewer VGPRs."""
        by_area = sorted(OBSERVED, key=lambda t: t[0] * t[1])
        totals = [OBSERVED[t] for t in by_area]
        assert totals == sorted(totals), by_area

    def test_gate_matches_every_observed_outcome(self):
        """The gate must agree with the hardware for all measured thread tiles."""
        for (t0, t1), total in OBSERVED.items():
            ok, why = occupancy_feasible(
                cfg("Z", "64x64x8", f"{t0}x{t1}")
            )
            legal_in_reality = total <= MAX_VGPR_PER_THREAD
            assert ok == legal_in_reality, f"TT {t0}x{t1} measured {total} VGPRs; gate said " f"{'legal' if ok else 'illegal'} ({why})"

    def test_measured_table_matches_observation(self):
        assert MEASURED_VGPR == OBSERVED

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
                assert gate_ok == legal, f"{ch} TT {t0}x{t1}: acc model {acc} vs budget " f"{ACCVGPR_BUDGET}, measured {total} VGPRs"

    def test_budget_sits_between_last_pass_and_first_fail(self):
        last_ok = max(t0 * t1 * VGPR_PER_ELEMENT["Z"]
                      for (t0, t1), v in OBSERVED.items() if v <= MAX_VGPR_PER_THREAD)
        first_bad = min(t0 * t1 * VGPR_PER_ELEMENT["Z"]
                        for (t0, t1), v in OBSERVED.items() if v > MAX_VGPR_PER_THREAD)
        assert last_ok == ACCVGPR_BUDGET
        assert first_bad > last_ok


class TestVectorWidthCap(unittest.TestCase):
    """The native deck must contain a 16 B global-load config for every family.

    11 of the 16 large-cell losses had one cause: the family decks hardcoded a
    VectorWidth one step below the cap, so the winning config was never even
    generated. 11 cells could not be won by any number of iterations.
    """

    def setUp(self):
        from oto.tensile.candidate import CandidateGenerator
        g = CandidateGenerator.__new__(CandidateGenerator)
        self.decks = g._load_family_decks()

    def test_cap_vector_width_reproduces_the_floor_winners(self):
        from oto.tensile.candidate import cap_vector_width
        # The floor's winning widths, read off the completed reference chain.
        for fam, mt, tt, want in (
            ("SS", "128x128x16", "8x8", 4),
            ("HH", "128x128x16", "8x8", 8),
            ("DD", "64x64x8", "4x4", 2),
        ):
            assert cap_vector_width(fam, mt, tt) == want, fam

    def test_cap_vector_width_never_exceeds_the_hardware_cap(self):
        from oto.tensile.gates.loads import cap_vector_width
        for fam, bpe in _loader.current_profile().family_bytes_per_element.items():
            for _vw in (1, 2, 4, 8):
                v = cap_vector_width(fam, "128x128x16", "8x8")
                assert v * bpe <= _loader.current_profile().global_load_byte_cap, fam

    def test_cap_vector_width_respects_tile_divisibility(self):
        from oto.tensile.candidate import cap_vector_width
        # vw may not exceed the per-thread extent of a macro-tile dimension.
        assert cap_vector_width("SS", "32x32x16", "4x4") <= 8
        assert cap_vector_width("SS", "16x16x16", "8x8") <= 2

    def test_every_wide_family_deck_reaches_the_cap(self):
        for fam in ("SS", "DD", "HH"):
            bpe = _loader.current_profile().family_bytes_per_element[fam]
            best = 0
            for c in self.decks[fam]:
                vw = c.get("VectorWidth")
                if vw:
                    best = max(best, vw * bpe)
            assert best == 16, f"{fam} deck tops out at {best} B; the 16 B cap is unreachable " f"and this family cannot win a large cell"

    def test_added_candidates_pass_the_dual_resource_gate(self):
        from oto.tensile.gates.occupancy import occupancy_feasible
        checked = 0
        for fam, cfgs in self.decks.items():
            for c in cfgs:
                vw = c.get("VectorWidth")
                if not vw:
                    continue
                # DataType must be the real dtype char, not the family label: a
                # phase's DataType is what the gate weights, and the label is
                # only a fallback for label-only auto phases.
                config = {"DataType": _loader.current_profile().family_dtype_char[fam], "FamilyLabel": fam,
                          "NLCA": 1, "WorkGroupMapping": 4, "GlobalSplitU": 1,
                          "ContractionPattern": "Ailk_Bjlk", "VectorWidth": vw}
                config.update({k: v for k, v in c.items() if k != "NLCA"})
                ok, why = occupancy_feasible(config)
                assert ok, f"{fam} {c.get('MacroTile')} vw{vw}: {why}"
                checked += 1
        assert checked > 0

    def test_family_labels_resolve_to_a_dtype(self):
        """Every family in a deck must be modellable by the register-file gate.

        A family label with no mapping in _dtype_char makes occupancy fail
        closed, which drops the whole family from generation rather than
        reporting a bad config.
        """
        from oto.tensile.gates.occupancy import dtype_char
        from oto.tensile.gates.vgpr_model import VGPR_PER_ELEMENT
        for fam in self.decks:
            ch = dtype_char({"DataType": fam, "FamilyLabel": fam})
            assert ch in VGPR_PER_ELEMENT, f"{fam} resolves to dtype {ch!r}, absent from " f"VGPR_PER_ELEMENT; its candidates would all be dropped"

    def test_widened_variants_do_not_duplicate_an_existing_tile(self):
        for fam in ("SS", "DD", "HH"):
            seen = set()
            for c in self.decks[fam]:
                key = (c.get("MacroTile"), c.get("ThreadTile"), c.get("VectorWidth"))
                assert key not in seen, f"duplicate {fam} {key}"
                seen.add(key)
            widths = {c.get("VectorWidth") for c in self.decks[fam]}
            assert widths, fam


class TestGlobalLoadVectorWidthRule(unittest.TestCase):
    """An explicit GlobalLoadVectorWidth is not free.

    Tensile refuses ``GLVW != VectorWidth and != 1`` unless ``BufferLoad`` and
    ``GuaranteeNoPartialA`` hold (SolutionStructs.py:4584-4595) -- and for the
    assembly path this device takes, ``AssertFree0ElementMultiple`` defaults to 1
    while ``TLUA`` is true for ``Ailk_Bljk``, so ``GuaranteeNoPartialA`` is false
    and the restriction bites. The gate used to ignore an explicit ``GLVW``
    entirely (it derived ``max(VW, numElemPerReg)``), so ``GLVW=2`` passed on a
    ``VectorWidth=4`` tile and Tensile then dropped the phase at solution
    construction -- the reference-rerun hashes ``7f866dcf`` / ``a0edeb30``.
    """

    def test_explicit_glvw2_on_vw4_is_refused(self):
        ok, why = validate_tensile_loads(
            cfg("S", "128x128x8", "8x8", VectorWidth=4,
                GlobalLoadVectorWidthA=2, GlobalLoadVectorWidthB=2))
        assert not ok
        assert "must be == VectorWidth" in why

    def test_explicit_glvw_equal_to_vw_is_accepted(self):
        ok, why = validate_tensile_loads(
            cfg("S", "128x128x8", "8x8", VectorWidth=4,
                GlobalLoadVectorWidthA=4, GlobalLoadVectorWidthB=4))
        assert ok, why

    def test_glvw1_narrow_is_accepted_on_a_vw4_tile(self):
        """GLVW=1 is the only *non-default* legal value on a VW>1 tile."""
        ok, why = validate_tensile_loads(
            cfg("S", "128x128x8", "8x8", VectorWidth=4,
                GlobalLoadVectorWidthA=1, GlobalLoadVectorWidthB=1))
        assert ok, why

    def test_auto_glvw_is_unaffected(self):
        """-1 is the '= VectorWidth' default and must stay legal."""
        ok, why = validate_tensile_loads(
            cfg("S", "128x128x8", "8x8", VectorWidth=4,
                GlobalLoadVectorWidthA=-1, GlobalLoadVectorWidthB=-1))
        assert ok, why

    def test_pv_reduction_cancels_a_widening_into_a_noop(self):
        """D 32x32x8, VW=1: the pv reduction (SolutionStructs.py:2010) turns an
        explicit GLVW=2 back into 1, so it is legal but measures the base tile.

        Deliberately not ZZ: complex double is 16 B, so GLVW=2 trips the 16 B cap
        first (SolutionStructs:3459, which runs before
        ``setGlobalLoadVectorWidth``'s pv reduction), and the no-op this test is
        about never gets a chance to happen.
        """
        ok, why = validate_tensile_loads(
            cfg("D", "32x32x8", "2x2", VectorWidth=1,
                GlobalLoadVectorWidthA=2, GlobalLoadVectorWidthB=2))
        assert ok, why

    def test_zz_vector_width_2_is_refused_by_the_byte_cap(self):
        """complexDouble is 16 B, so VW 2 loads 32 B and Tensile refuses the
        solution. The gate read the ComplexFloat row (8 B) and let it through --
        which is how ``phase_cand_zz_128_32x64x8_tt2x4_..._vw2`` reached a live
        run and came back with 0 CSV."""
        ok, why = validate_tensile_loads(
            cfg("Z", "32x64x8", "2x4", VectorWidth=2))
        assert not ok
        assert "> 16" in why
        ok, why = validate_tensile_loads(
            cfg("Z", "32x64x8", "2x4", VectorWidth=1))
        assert ok, why

    def test_assert_free_element_multiple_lifts_the_restriction(self):
        """The guard is conditional: GuaranteeNoPartialA holds when
        AssertFree0ElementMultiple is a multiple of GLVW_A (SolutionStructs:4177),
        so GLVW=2 beside AF0EM=2 is legal on a VW4 tile.

        FORWARD_KNOB_DOMAINS explores exactly this pair
        (GlobalLoadVectorWidthA/B in {1,2,4} x AssertFree0ElementMultiple in
        {1,2}), so a gate that refused it unconditionally would delete a legal
        slice of the synthesis space.
        """
        ok, why = validate_tensile_loads(
            cfg("S", "128x128x8", "8x8", VectorWidth=4,
                GlobalLoadVectorWidthA=2, GlobalLoadVectorWidthB=2,
                AssertFree0ElementMultiple=2, AssertFree1ElementMultiple=2))
        assert ok, why

    def test_source_language_keeps_the_restriction(self):
        """``bufferLoad`` also requires KernelLanguage Assembly
        (SolutionStructs:3292); Source takes the unconditional branch."""
        ok, why = validate_tensile_loads(
            cfg("S", "128x128x8", "8x8", VectorWidth=4,
                GlobalLoadVectorWidthA=2, GlobalLoadVectorWidthB=2,
                AssertFree0ElementMultiple=2, AssertFree1ElementMultiple=2,
                KernelLanguage="Source"))
        assert not ok
        assert "must be == VectorWidth" in why


class TestLocalSplitUThreadCount(unittest.TestCase):
    """LocalSplitU multiplies NumThreads (SolutionStructs:1964).

    Tensile reads it from ``WorkGroup[2]`` -- the workgroup still covers
    MT0 x MT1, it just gains LSU extra wavefronts -- so every pv and load-wave
    reading downstream sees the larger count. The gate read the tile alone, and
    the whole LSU=2 sweep therefore looked legal: 20 of 24 phases died
    (``GLVW 2 % pv 4 != 0`` on 32x32x8/2x2; ``Kernel Uses 131072 > 65536 bytes
    of LDS`` on 128x128x8/8x8) while the four that built -- CC 64x64x8/4x4 and
    HH 128x128x16/8x8, two shapes each -- are the control this fix must keep.
    """

    def test_lsu2_survives_where_the_load_wave_still_divides(self):
        for dtype, mt, tt, vw in (("C", "64x64x8", "4x4", 1),
                                  ("H", "128x128x16", "8x8", 4)):
            with self.subTest(dtype=dtype):
                ok, why = validate_tensile_loads(
                    cfg(dtype, mt, tt, VectorWidth=vw, LocalSplitU=2))
                assert ok, why

    def test_lsu2_dies_where_it_does_not(self):
        for dtype, mt, tt, vw, want in (
                ("Z", "32x32x8", "2x2", 1, "% pv"),
                ("D", "32x32x8", "2x2", 2, "% pv"),
                ("S", "128x128x8", "8x8", 4, "must be == VectorWidth"),
                ("H", "128x128x8", "8x8", 4, "must be == VectorWidth")):
            with self.subTest(dtype=dtype):
                ok, why = validate_tensile_loads(
                    cfg(dtype, mt, tt, VectorWidth=vw, LocalSplitU=2))
                assert not ok
                assert want in why

    def test_workgroup_spelling_reads_the_same(self):
        """An emitted phase carries only ``WorkGroup`` ("16x16x2"); a deck row
        carries ``LocalSplitU``. Both must produce the same thread count."""
        for kw in ({"LocalSplitU": 2}, {"WorkGroup": "16x16x2"}):
            with self.subTest(**kw):
                ok, why = validate_tensile_loads(
                    cfg("D", "32x32x8", "2x2", VectorWidth=2, **kw))
                assert not ok
                assert "% pv" in why

    def test_an_explicit_workgroup_shadows_the_knob(self):
        """``config_writer._fork_tile`` emits an explicit ``WorkGroup`` verbatim
        and only folds ``LocalSplitU`` in when WorkGroup is absent, so the two
        keys together are a silent no-op: the deck's own steal rows carried
        ``WorkGroup: [16,16,1]`` beside ``LocalSplitU: 2`` and benchmarked at
        LSU 1 (potential_configs.md §R23). The gate reads the emitted value."""
        ok, why = validate_tensile_loads(
            cfg("S", "128x128x8", "8x8", VectorWidth=4,
                WorkGroup=[16, 16, 1], LocalSplitU=2))
        assert ok, why            # emitted LSU is 1, so the tile lives
        ok, why = validate_tensile_loads(
            cfg("S", "128x128x8", "8x8", VectorWidth=4, LocalSplitU=2))
        assert not ok                # no WorkGroup: the LSU really lands
        assert "must be == VectorWidth" in why

    def test_lsu1_is_the_default_and_unchanged(self):
        ok, why = validate_tensile_loads(cfg("D", "32x32x8", "2x2", VectorWidth=2))
        assert ok, why
