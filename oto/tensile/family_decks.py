#!/usr/bin/env python3
"""The curated family tile decks: the starting candidates, and what kind each is.

Owns: ``FAMILY_DECKS`` -- one list per family label, every entry annotated with
what kind of candidate it is:

  MEASURED  the shipped-gfx900 floor's own winning solution at a named cell, read
            from that phase's resolved 2_BenchmarkData yaml. These convert known
            losses directly.
  QUANT     a tile chosen for 7-CU wave quantization. this part has 7 CUs, so
            ceil(N/MT)^2 tiles spread badly whenever the count is a small power
            of two: at N=256 a 128x128 tile yields 4 tiles on 7 CUs and leaves
            3 idle (57% of the machine), while 32x32 yields 64 tiles at 91%.
            This is the "narrower" direction.
  LADDER    a width step either side of an existing deck entry, so the overnight
            run brackets each tile rather than guessing one width.

Widths are requested, not assumed: the candidate generator clamps any width the
gate rejects down to the widest it accepts, so an entry is never silently
dropped.
Does NOT own: the generator that consumes it (oto.tensile.candidate) or the
gates that judge the entries (oto.tensile.gates).
Public API: FAMILY_DECKS.
"""

from __future__ import annotations

from typing import Any

FAMILY_DECKS: dict[str, list[dict[str, Any]]] = {
            "SS": [
            # MEASURED floor winner, all 7 large cells: 128x128x8/8x8/VW4.
            {"MacroTile": "128x128x8", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
            # MEASURED floor winner at SS:256 -- 32x64x8/4x8/VW4, an
            # anisotropic tile. SS:256 is 25.5% of the 1613 GFLOPS roof, the
            # widest relative gap in the corpus, and the winning tile is
            # neither square nor in the quantisation ladder. It was never
            # generated, so native could not have matched it.
            {"MacroTile": "32x64x8", "ThreadTile": "4x8", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
            # LADDER 64x64x16/4x4/VW4: the 16 B square tile at the smallest
            # square that still has 16 tiles at N=256 (76%).
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
            # QUANT 32x32 at N=256 is 64 tiles / 7 CUs = 91% machine use,
            # the best packing of any tile in the ladder. Also 2x2 threads,
            # which halves VGPR pressure and doubles occupancy headroom.
            # VW2, not VW4: a 2-wide ThreadTile cannot be a multiple of a
            # 4-wide load (`TT0=2 not multiple of VW=4`); the narrow probe is
            # the point, so the load width follows the thread tile.
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            # QUANT 96x96 is non-power-of-two on purpose: ceil(2048/96)=22,
            # 22^2=484 tiles over 7 CUs quantizes far finer than 128x128's
            # 16^2=256, and at N=1365 it is the only tile in the ladder that
            # does not overshoot.
            {"MacroTile": "96x96x16", "ThreadTile": "6x6", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            # LADDER bracket the incumbent 128x128 VW2 downward, and the
            # incumbent 64x64 VW2 upward, so both are bracketed by data.
            {"MacroTile": "128x128x16", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            {"MacroTile": "128x128x8", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            # PrefetchGlobalRead stays off at 128x128: it doubles the LDS
            # footprint to 16 KB and the tile is already at the LDS budget.
        ],
        # ---- DD: FP64 is 85-96% of its 101 GFLOPS roof on every cell except
        # DD:192, which is at 20.5% and loses 12.7%. DD is 100% VW1 across
        # all 44 measured phases, so the whole width axis is unexplored.
        "DD": [
            # MEASURED floor winner on DD:192 -- 32x32x8/4x4/VW2, never run
            # natively. DD's deck has 32x32 but at 2x2 threads and VW1.
            {"MacroTile": "32x32x8", "ThreadTile": "4x4", "VectorWidth": 2},
            # MEASURED floor winner on DD:768 (a tie) and the 64x64 VW2 the
            # deck has never produced.
            {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
            # MEASURED floor winner on DD:1024 sits at DepthU 4, not 8 -- a
            # shallow-K variant no deck entry has expressed.
            {"MacroTile": "64x64x4", "ThreadTile": "4x4", "VectorWidth": 2},
            # QUANT DD:192 at 32x32 is 36 tiles / 7 = 86% machine use; 64x64
            # gives only 9 tiles and 64%. Keep both orientations.
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "VectorWidth": 2},
            # LADDER: DD is at 95% of roof on the big cells, so the only
            # open width is narrower, for the small ones.
            {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 1},
            {"MacroTile": "32x32x8", "ThreadTile": "2x2", "VectorWidth": 1},
        ],
        # ---- HH: loses 10.9-14.6% at 1024/2048/4096 while already at
        # 71-75% of the 3226 GFLOPS packed-FP16 roof -- the widest gap
        # between utilisation and verdict. Floor winner is 128x128x16 VW8.
        "HH": [
            # MEASURED floor winner on 1024/2048/4096. Native has never run
            # VW8 on any HH tile.
            {"MacroTile": "128x128x16", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 8, "WorkGroupMapping": 4, "PrefetchGlobalRead": False},
            # MEASURED floor winner at HH:256 -- 64x32x16, not 64x64. HH:256
            # is the one HH cell below 50% of roof (23.7%), and 64x32/4x4
            # gives 128 threads against 64x64's 64, which is the axis the
            # quantisation argument below cannot see. An earlier revision of
            # this deck asserted 64x64x16/4x4/VW4 was the measured winner;
            # it was not, and the tile that actually won was never generated.
            {"MacroTile": "64x32x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
            # QUANT HH:256 at 64x64 is 16 tiles / 7 = 76%; at 32x32 it is
            # 64 tiles and 91%, which is the only tile that meaningfully
            # unpacks the 256 square on a 7-CU part. VW2, not VW8: a 2-wide
            # ThreadTile cannot be a multiple of an 8-wide load, and half
            # requires VW >= 2, so 2 is the only legal width for this probe.
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            # QUANT 96x96/6x6: 484 tiles at N=2048, and ceil(4096/96)=43 so
            # 43^2 tiles at the top cell -- the finest quantization in the
            # ladder. 6x6 threads cap this family at VW2, which the
            # generator enforces.
            {"MacroTile": "96x96x16", "ThreadTile": "6x6", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
            # LADDER keep the incumbent 128x128 VW4 and the 64x64 VW2 so the
            # 8->4->2 descent is measured rather than assumed monotone.
            {"MacroTile": "128x128x16", "ThreadTile": "8x8", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4, "PrefetchGlobalRead": False},
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2, "WorkGroupMapping": 4},
        ],
        # ---- ZZ: wins all four large cells but at 16.7-23.7% of the 101
        # GFLOPS FP64 roof -- the worst absolute utilization in the corpus.
        # Every ZZ winner is VW1 across 40 measured configs, and 128x64x8 and
        # 64x128x8 are documented as dead (accumulator VGPR overflow).
        "ZZ": [
            # MEASURED-style probe: the floor never wins ZZ above VW1, so VW2
            # is a reach test, not a conversion. 4x4 threads at complex
            # double is TT0*TT1*8 VGPRs -- over the 128 accumulator budget,
            # so the generator's occupancy gate is expected to refuse it.
            {"MacroTile": "64x64x8", "ThreadTile": "4x4", "NLCA": 1},
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1},
            # QUANT: ZZ is quantized hardest of all -- 128x128 gives 4 tiles
            # at N=256 and 16 at N=512. 32x32 is the only tile that fills 7
            # CUs. This is the single highest-leverage ZZ change.
            {"MacroTile": "32x32x8", "ThreadTile": "2x2", "NLCA": 1},
            # (Removed 2026-10-18: a `32x32x16/2x2/VectorWidth=2` row sat here.
            # Complex double is 16 B/element, so the 16 B global-load cap admits
            # VW1 only: the row was a duplicate of the bare 32x32x16 above *and*
            # unbuildable (`GLVWA 2 * bpe 16 > 16`). VectorWidth is not a ZZ
            # axis -- the deck must not pretend otherwise.)
            # MEASURED floor winner at ZZ:192 -- 32x32x8 on 4x4 threads, not
            # the 2x2 this deck had assumed. At complex double 4x4 is
            # TT0*TT1*8 = 128 accumulator VGPRs, exactly on the budget, so
            # it is legal but at the ceiling; this is the measured optimum
            # and was never generated natively.
            {"MacroTile": "32x32x8", "ThreadTile": "4x4", "NLCA": 1},
            # LADDER: exercise DepthU, which no ZZ entry has varied. Complex
            # double is 16 B/elem (Tensile DataType reg=4) since the 2026-11-14
            # DECIDED §6 call: BYTES_PER_ELEMENT["Z"] is 16 B, LDS_BUDGET stays
            # 16384. Consequence: bare 64x64x16 (fp 32768 B) is refused by policy,
            # so the DepthU ladder here carries only the at-budget rungs
            # (64x64x4, 32x32x16) plus the measured winner 64x64x8/LdsPadB=1 at
            # exactly 16384. The 64x64x16 floor winner and its LdsPadB sibling are
            # TENSILE-LEGAL but policy-refused; they are not decked since 2026-11-14.
            {"MacroTile": "64x64x4", "ThreadTile": "4x4", "NLCA": 1},
            {"MacroTile": "64x64x8", "ThreadTile": "4x4", "LdsPadB": 1, "NLCA": 1},
            # ---- 2026-11-14 (owner decision, §6): the widest policy-admitted ZZ.
            # The 2026-10-14 rows (128x128x8/tt4x4 and 128x64x8/tt4x4) were wrong
            # on the workgroup register-file rule (error 4). The 2026-10-18 answer
            # (128x32x8/32x128x8 at DepthU 8) passed the gate only under the old
            # 8 B LDS reading; at Tensile's 16 B element it is 20480 B, so it was
            # retired with the 2026-11-14 decision. Asymmetric aspects that
            # remain at the budget: 64x64x8/LdsPadB=1 (16384 B) and 32x32x16.
        ],
        # ---- CC: 2.5-19.7% of the FP32 roof on every cell, and the only
        # family where the floor's winning config was already run natively
        # and still lost. Complex single is 8 B/elem for A and B, so this
        # family is data-movement bound long before it is ALU bound: the
        # lever is tile size and LDS padding, not width (VW2 = 16 B is
        # already the cap).
        # ---- 2026-10-14 additions (docs/gfx90c_tuning_guide.md §13 §8.2): the two
        # legal-and-never-generated corners. The accumulator cap
        # (ACCVGPR_BUDGET = 128) forbids TT6x6 and TT8x8, so the only way to
        # raise CC's arithmetic intensity is a BIGGER MacroTile at the same
        # ThreadTile -- the opposite direction to a ThreadTile ladder.
        # 128x128x8/8x4 gives AI 64 F/B = 167% of the 38.4 F/B ridge, and it
        # is legal: validated through validate_config.
        "CC": [
            # MEASURED floor winner on CC:192 -- 32x32x8/4x4/VW2, never run.
            {"MacroTile": "32x32x8", "ThreadTile": "4x4", "VectorWidth": 2},
            # MEASURED floor winner on CC:256/1024/512 (64x64x8/4x4/VW2).
            {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
            # MEASURED floor winner on CC:2048 is the same tile with
            # LdsPadA 2, LdsPadB 0 -- asymmetric, and the only CC row in the
            # whole census with a non-zero pad. GFX9 LDS bank =
            # (byte_addr/4) mod 32, so a 128 B-aligned B row collides.
            {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 2, "LdsPadA": 2, "LdsPadB": 0},
            # QUANT: CC is the most quantized family because a 128x128
            # complex tile is 128 KB of A and B. 32x32 is the only tile that
            # gets past 4 tiles at N=256.
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2},
            {"MacroTile": "16x16x16", "ThreadTile": "2x2", "VectorWidth": 2},
            # LADDER keep the incumbent VW1 tiles: at 8 B CC may genuinely
            # prefer the narrower load, and the overnight run should be able
            # to prove that rather than assume it.
            {"MacroTile": "32x32x16", "ThreadTile": "2x2"},
            {"MacroTile": "64x64x8", "ThreadTile": "4x4"},
            # ---- 2026-10-18 (docs/gfx90c_tuning_guide.md §13 §R24): the widest LEGAL CC
            # MacroTile. The 2026-10-14 rows here were wrong. 128x128x8 at
            # 8x4 *and* 4x8 makes R*MTarea = 4*16384 = 65536 accumulator VGPRs
            # across the workgroup, so the accumulators alone fill the 64K file
            # and Tensile raises error 4 before a kernel exists; 128x96x8/8x4
            # fails classic-load divisibility (totalElements 1024 %
            # (NumThreads*glvw) 768 != 0). Brute force over every CC tile with
            # area > 8192 found NONE legal, so 128x64/64x128 at DepthU 8 is the
            # widest legal CC tile -- and it was never emitted (the corpus max
            # is the same 128x64 at VW1, never at VW2/8x4).
            {"MacroTile": "128x64x8", "ThreadTile": "8x4", "VectorWidth": 2},
            {"MacroTile": "128x64x8", "ThreadTile": "4x4", "VectorWidth": 2},
            {"MacroTile": "64x128x8", "ThreadTile": "4x8", "VectorWidth": 2},
        ],
        # ---- HH_HPA: loses 7.7-9.8% at 2048/4096. The floor wins 4096 at
        # 128x64x8 with **8x4** threads and 2048 at the transposed
        # 64x128x8/4x8, both at VW2. The deck has 128x64x16 and 64x128x16 at
        # 4x8 threads and no VW, so it expresses neither floor winner.
        "HH_HPA": [
            # MEASURED floor winner HH_HPA:4096. TT is 8x4, not the deck's
            # 4x8 -- 128/8 x 64/4 = 16x16 threads either way, but the
            # per-thread extents differ, so these are different kernels.
            {"MacroTile": "128x64x8", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 2},
            # MEASURED floor winner HH_HPA:2048, the transposed tile.
            {"MacroTile": "64x128x8", "ThreadTile": "4x8", "NLCA": 1, "VectorWidth": 2},
            # MEASURED floor winner HH_HPA:1024 (a tie): 128x64x16/8x4/VW4.
            {"MacroTile": "128x64x16", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 4},
            # QUANT 96x96 and 32x32 to unpack the 512/1024 squares.
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2},
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1, "VectorWidth": 2},
            # LADDER keep the incumbent, and add the asymmetric pad the CC
            # census shows is sometimes decisive.
            {"MacroTile": "64x128x16", "ThreadTile": "4x8", "NLCA": 1},
            {"MacroTile": "128x64x16", "ThreadTile": "4x8", "NLCA": 1, "LdsPadA": 2, "LdsPadB": 0},
        ],
        # ---- HS_HPA: three ties at 83-89% of roof, one win at 512. No
        # losses, so the goal here is depth: the floor's winners are the
        # 128x64x16/8x4/VW4 tile, with LdsPad 4/4 on 2048 specifically.
        "HS_HPA": [
            # MEASURED floor winner on 1024/4096 (ties).
            {"MacroTile": "128x64x16", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 4},
            # MEASURED floor winner on 2048 (tie) is the same tile with
            # LdsPadA 4, LdsPadB 4.
            {"MacroTile": "128x64x16", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 4, "LdsPadA": 4, "LdsPadB": 4},
            # MEASURED floor winner on HS_HPA:512 is 64x64x8/4x4/VW4.
            {"MacroTile": "64x64x8", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 4},
            # QUANT: mirror the HH_HPA additions so the two HPA families are
            # compared on identical tiles rather than different ones.
            {"MacroTile": "128x64x8", "ThreadTile": "8x4", "NLCA": 1, "VectorWidth": 2},
            {"MacroTile": "64x128x8", "ThreadTile": "4x8", "NLCA": 1, "VectorWidth": 2},
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1, "VectorWidth": 2},
            # LADDER keep the incumbent tiles.
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1},
            {"MacroTile": "128x64x16", "ThreadTile": "4x8", "NLCA": 1},
            {"MacroTile": "64x128x16", "ThreadTile": "4x8", "NLCA": 1},
        ],
}

# ---------------------------------------------------------------------------
# The knob sweep deck (added 2026-10-14).
#
# `FAMILY_DECKS` is a tile deck. This is a different kind of candidate: one
# family's *current winner tile*, crossed with a single change to a knob the
# corpus never explicitly set. It exists because `oto.tools.run_census` reports
# `GlobalSplitU = ['1']` and `StaggerU = ['32']` as the only values ever seen
# across both arms, and because no winning config in `cells_resolved.json`
# sets PrefetchGlobalRead, AggressivePerfMode, MaxOccupancy, LocalSplitU,
# BufferLoad, InnerUnroll, FractionalLoad, UseSgprForGRO, LocalRead2A/B,
# GlobalRead2A/B, StorePriorityOpt or GlobalLoadVectorWidthA/B. "Never set" is
# not "never varied" -- see TENSILE_KNOB_DEFAULTS below for what the base
# already carries. Every tuning conclusion to date is therefore a conclusion
# about MacroTile x ThreadTile x DepthU x VectorWidth x WorkGroupMapping only
# -- and those axes are mined out.
#
# Why it is a separate table and not more rows in FAMILY_DECKS: a sweep entry
# is meaningless without the base tile it perturbs, so it needs (family -> base
# tile) to be a first-class part of the data, and the *same* sweep list is
# shared by every family. Cross-joining two independent tables is a job for the
# generator (`generate_knob_sweep_phases`), not for a duplicated block per
# family.
#
# Legality: `docs/gfx90c_tuning_guide.md` §13 §8.1 records which of these survive
# `validate_config` per family (111 of 133). The generator relies on the append
# boundary to refuse the rest, so an illegal row costs a rejection and not a
# crashed run -- but the table below is already pruned to the rows that pass on
# at least one family, so a reader is not shown candidates that cannot run.
#: Tensile's defaults for the knobs this sweep perturbs, read from
#: ``Tensile/Common.py:defaultBenchmarkCommonParameters`` (lines 1507-1670) at the
#: pinned commit ``e8a8999e``. Every absent knob takes its default, so "no winner
#: sets X" means "X was never *changed*", not "X was never varied": a sweep value
#: equal to the default re-measures the baseline and is not an experiment.
#: ``tests/test_knob_sweep.py`` asserts every ``KNOB_SWEEPS`` row offers at least
#: one non-default value. ``LocalSplitU`` is absent from that Tensile block; its
#: effective default is 1. Kept here (not in a gate) because it is the table the
#: sweep below is written against, and the sweep is this module's data.
TENSILE_KNOB_DEFAULTS: dict[str, Any] = {
    "BufferLoad": True,
    "BufferStore": True,
    "StaggerU": 32,
    "StaggerUStride": 256,
    "StaggerUMapping": 0,
    "MaxOccupancy": 40,
    "AggressivePerfMode": 1,
    "PrefetchGlobalRead": 1,
    "PrefetchLocalRead": 1,
    "UseSgprForGRO": -1,
    "GlobalLoadVectorWidthA": -1,
    "GlobalLoadVectorWidthB": -1,
    "AssertFree0ElementMultiple": 1,
    "AssertFree1ElementMultiple": 1,
    "NumLoadsCoalescedA": 1,
    "NumLoadsCoalescedB": 1,
    "InnerUnroll": 1,
    "GlobalSplitU": 1,
    "LocalSplitU": 1,
    "FractionalLoad": 0,
    "NonTemporalA": 0,
    "NonTemporalB": 0,
    "LocalRead2A": True,
    "LocalRead2B": True,
    "GlobalRead2A": True,
    "GlobalRead2B": True,
}

KNOB_SWEEP_BASES: dict[str, list[dict[str, Any]]] = {
    # The family's best measured winner tile, from
    # `python3 -m oto.harness.asm_occupancy`. These are the tiles the corpus
    # already validated and measured; sweeping knobs on top of them isolates
    # the knob's effect instead of moving the tile at the same time.
    "CC": [
        {"MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 1},
    ],
    "ZZ": [
        {"MacroTile": "32x32x8", "ThreadTile": "2x2", "VectorWidth": 1},
    ],
    "SS": [
        {"MacroTile": "128x128x8", "ThreadTile": "8x8", "VectorWidth": 4},
    ],
    "HH": [
        {"MacroTile": "128x128x16", "ThreadTile": "8x8", "VectorWidth": 4},
    ],
    "DD": [
        {"MacroTile": "32x32x8", "ThreadTile": "2x2", "VectorWidth": 2},
    ],
    "HH_HPA": [
        {"MacroTile": "128x128x8", "ThreadTile": "8x8", "VectorWidth": 4},
    ],
    "HS_HPA": [
        {"MacroTile": "128x128x8", "ThreadTile": "8x8", "VectorWidth": 4},
    ],
}

# ---------------------------------------------------------------------------
# Decision trials (2026-10-14, the D1/D2/D3 answer to "add candidates as
# trials").
#
# KNOB_SWEEPS can only express "one knob change on a fixed base tile". Three
# of the open decisions are not knob changes, so they need tiles of their own:
#
#   * D1 (CC:256's LOSS is a floor-arm measurement artifact) needs the CC tile
#     re-measured at the *shallow cells* it owns -- a shape question, not a
#     knob. The trial names its shapes explicitly so it does not depend on the
#     sweep's default shapes.
#   * D2 (`BYTES_PER_ELEMENT["Z"]` 8 vs 16) is RETIRED, 2026-11-14 (owner
#     decision, §6): the Tensile-verbatim 16 B table plus the unchanged
#     16384 B budget retired the boundary tile by policy; the ZZ VW2
#     differentiator was already settled against Tensile (``numBytes() * 2 > 16``).
#   * D3 is RETIRED, 2026-11-14 (owner decision, §6): the boundary/headroom
#     tiles are refused by the gate by design, so they are not decked.
#   * D5 (CC:256's 4-assert tensile SGEMM recipe) is ADOPTED, 2026-11-14
#     (owner decision, Option B: vendor-recipe adoption). The rows now ship
#     as first-class deck rows; only D1 remains a trial.
#
# Each entry is emitted unchanged (no knob delta), once per (pattern, shape),
# tagged `_trialD<n>` by the generator. Seen by
# `test_every_decision_trial_is_gate_legal` and
# `test_decision_trials_cover_d1`.
#: Decision-labelled trial tiles. `shapes`, when present, overrides the sweep's
#: shape list; otherwise the generator's shapes apply.
#:
#: D1 is the only open decision. D2/D3 are RETIRED, 2026-11-14 (owner decision,
#: <codename>_theoretical_limits.md §6): BYTES_PER_ELEMENT["Z"] is Tensile's 16 B
#: and LDS_BUDGET stays 16384, so the D2 boundary tile (64x64x16, gate footprint
#: 32768) and the D3 pair (128x32x8 / 32x128x8; 20480) are refused by design.
#: D5 (CC:256 the 4-assert Tensile SGEMM recipe) is ADOPTED, 2026-11-14 (owner
#: decision, Option B: vendor-recipe adoption): the 4-assert rows for CC:256 and
#: CC:512 ship as first-class deck rows
#: (`phase_cc_Ailk_Bljk_256x256x256_mt64x64x8_tt4x4_af4em4` / `_512x512x512_...`),
#: gate-legal and GPU-validated on the reference device at both shapes with NumElementsToValidate=128
#: in the client config. It is no longer a trial; DECISION_TRIAL_TILES keeps D1.
DECISION_TRIAL_TILES: list[dict[str, Any]] = [
    {
        "decision": "D1",
        "family": "CC",
        "knobs": {"MacroTile": "64x64x8", "ThreadTile": "4x4",
                  "VectorWidth": 2},
        "shapes": ["192x192x192", "256x256x256"],
        "why": "CC's only LOSS is the :256 small cell, judged against a floor "
               "arm with no telemetry (`spoof_clock_coverage = 0.0`). The trial "
               "re-measures the CC winner geometry (the steal tile, VW2) at "
               "the shallow cells, so a same-run floor re-arm can close D1. "
               "Measurement fix, not a kernel deficit.",
    },
]

#: One knob change applied on top of a KNOB_SWEEP_BASES tile. `families` lists
#: the families this row is legal for; the generator skips it elsewhere rather
#: than emitting a candidate that the append boundary will refuse. Measured
#: legality per family is in docs/gfx90c_tuning_guide.md §13 §8.1.
KNOB_SWEEPS: list[dict[str, Any]] = [
    # ---- Addressing / issue slots: the knobs that spend non-FMA issue slots.
    # Complex is issue-bound, not bandwidth-bound (§5 of the deck), so this
    # group is the highest-yield one.
    {
        "knob": "UseSgprForGRO",
        "families": ["CC", "ZZ", "SS", "HH", "DD", "HH_HPA", "HS_HPA"],
        "values": [{"UseSgprForGRO": True}],
        "why": "Moves global-read offsets out of VGPR into SGPR. ZZ is "
               "VGPR-bound at 63 VGPR on its winner tile, so this buys "
               "registers rather than instructions.",
    },
    # Paired GLVW widen -- the only realizable form (D4, added 2026-10-14).
    # An *unpaired* `GLVW=2` is either refused or a no-op on every base here:
    #   * Tensile refuses GLVW != VectorWidth and != 1 unless bufferLoad and
    #     GuaranteeNoPartialA (SolutionStructs.py:4584-4595), and with the default
    #     AssertFree0ElementMultiple=1 GuaranteeNoPartialA is false -- so the legal
    #     unpaired values are 1 or == VectorWidth. That refused CC/SS/HH/HPA.
    #   * where it is not refused, `setGlobalLoadVectorWidth`'s pv reduction
    #     (SolutionStructs.py:2010) cancels the 2 back to 1 (ZZ), or the explicit
    #     value already equals the derived default (DD) -- a no-op.
    # The widen is realizable only as a PAIR -- AssertFree0ElementMultiple=2 lifts
    # GuaranteeNoPartialA -- and only where pv does not cancel it: CC (VW1, pv=1,
    # 8 B -> 16 B). ZZ's winner tile pv-cancels it; for SS/HH/HPA the pair is a
    # *narrow*, not a widen. So the row is CC-only, swept as a trial (D4): the
    # run decides whether the wider global load pays. See §8.1 and §9 D4.
    {
        "knob": "GlobalLoadVectorWidth",
        "families": ["CC"],
        "values": [{"GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2,
                    "AssertFree0ElementMultiple": 2,
                    "AssertFree1ElementMultiple": 2}],
        "why": "The paired widen: GLVW=2 is refused alone (GuaranteeNoPartialA "
               "false at the default AssertFree0ElementMultiple=1); pairing it "
               "with AssertFree0/1ElementMultiple=2 lifts the guard, and only CC "
               "has pv=1 at VW1 so the width is not cancelled. A real 8 B -> 16 B "
               "global load. CC is issue-bound, so a wider load is a trial, not "
               "a known win -- the run decides (D4).",
    },
    {
        "knob": "InnerUnroll",
        "families": ["CC", "ZZ", "SS", "HH", "DD", "HH_HPA", "HS_HPA"],
        "values": [{"InnerUnroll": 2}],
        "why": "Default 1. Longer unroll cuts loop-control issues as a fraction "
               "of the inner loop. Only DepthU brackets have ever been tried for "
               "CC/ZZ.",
    },
    {
        "knob": "PrefetchGlobalRead",
        "families": ["CC", "ZZ", "SS", "HH", "DD", "HH_HPA", "HS_HPA"],
        "values": [{"PrefetchGlobalRead": 1}, {"PrefetchGlobalRead": 2}],
        "why": "Default 1, so the value-1 phase is the implicit CONTROL and 2 is "
               "the treatment (deeper pipeline). Two of the five complex winners "
               "set it to False, so 0 is a real alternative the corpus has seen "
               "but this row does not sweep.",
    },
    # ---- Load coalescing. NLCA is gated by VectorWidth through NumLoads, so
    # each row carries the width it was validated at; docs/potential_configs.md
    # §8.1 found NLCA=2 legal at CC vw1, SS vw1/vw2, HH vw2, and nowhere else.
    {
        "knob": "NumLoadsCoalescedA",
        "families": ["CC", "SS", "HH"],
        "width_override": {"CC": 1, "SS": 1, "HH": 2},
        "values": [{"NumLoadsCoalescedA": 2}, {"NumLoadsCoalescedB": 2}],
        "why": "One phase in the entire corpus sets NLCA. Legal only where "
               "VectorWidth gives NumLoads >= 2, which is why it carries its "
               "own width.",
    },
    # ---- Occupancy as an explicit lever. Default 40 (uncapped); these are all
    # non-default, so every value is a real treatment.
    {
        "knob": "MaxOccupancy",
        "families": ["CC", "ZZ", "SS", "HH", "DD", "HH_HPA", "HS_HPA"],
        "values": [{"MaxOccupancy": 8}, {"MaxOccupancy": 12},
                   {"MaxOccupancy": 20}],
        "why": "Default 40 (uncapped), so all three values are treatments. Pads "
               "per-workgroup LDS to DeviceLDS // N (floor), a pure occupancy "
               "clamp with no other effect. 100% of shipped gfx900/gfx906 "
               "solutions set 40. 7 CUs makes wave count scarcer than on the "
               "60-CU parts AMD tuned for.",
    },
    # `AggressivePerfMode` is deliberately NOT a row, and this one is measured
    # rather than suspected: the mode-2 sweep ran on 2026-10-15/17 and produced
    # **zero** `.hsaco` objects for every family and every tile (24 phases, 0
    # CSV), while its mode-1 control in the same run built 20 (one per target
    # arch). Tensile writes the source and then fails to compile it, so the
    # phase costs a full subprocess and returns nothing -- no tile property
    # predicts it, which is why it is a deck decision and not a gate. The
    # "2 waves/SIMD LDS cap" the old row proposed to probe stays unconfirmed
    # (`docs/knowledge_base.md` §Q-E ii); it is not a reason to ship dead phases.
    # ---- K splitting. Legal only for SS and DD on this gate:
    # `Assembly class: GlobalSplitU=2 on complex C: illegal`, and the same for
    # every half family. Route C in docs/potential_configs.md therefore applies to
    # SS and DD only.
    {
        "knob": "GlobalSplitU",
        "families": ["SS", "DD"],
        "values": [{"GlobalSplitU": 2}, {"GlobalSplitU": 4}],
        "why": "Pinned at 1 across every run in the corpus. The only lever that "
               "fixes 7-CU wave quantization for small shapes: G = ceil(M/MT) x "
               "ceil(N/NT) and GSU multiplies G.",
    },
    # ---- M splitting: wave-fill without a reduction kernel, so it is not
    # blocked by the GlobalSplitU restriction.
    {
        "knob": "LocalSplitU",
        "families": ["CC", "HH"],
        "values": [{"LocalSplitU": 2}],
        "why": "Splits the MacroTile M extent across waves inside one "
               "workgroup. Wave-fill without a second kernel, which is the "
               "shape of fix the small-shape rows need. Families narrowed from "
               "all seven by measurement (2026-10-15/17): LSU>1 multiplies "
               "NumThreads, so it only survives where the load wave still "
               "divides -- CC 64x64x8/4x4 and HH 128x128x16/8x8 built and ran, "
               "while SS/HH_HPA 128x128x8/8x8 hit `Kernel Uses 131072 > 65536 "
               "bytes of LDS` and ZZ/DD 32x32x8/2x2 hit `GlobalLoadVectorWidth "
               "2 % pv 4 != 0`. The gate now models that thread count.",
    },
    # ---- Raster / swizzle. StaggerU is legal at every value with and without
    # BufferLoad (validated), so this is free to sweep -- and it is currently
    # pinned at 32 corpus-wide.
    {
        "knob": "StaggerU",
        "families": ["CC", "ZZ", "SS", "HH", "DD", "HH_HPA", "HS_HPA"],
        "values": [{"StaggerU": 0}, {"StaggerU": 8}, {"StaggerU": 16}],
        "why": "Only ever 32. gfx900's dGPU tuning assumed 56-CU raster order; "
               "7 CUs wants a different swizzle.",
    },
    # `BufferLoad` is deliberately NOT a row. Its Tensile default is already
    # `True` (TENSILE_KNOB_DEFAULTS), so `BufferLoad: True` re-measures the base
    # tile; the only real change, `False`, also disables the StaggerU path and so
    # confounds itself against the StaggerU row below. Recorded, not swept.
    {
        "knob": "FractionalLoad",
        "families": ["CC", "ZZ", "SS", "HH", "DD", "HH_HPA", "HS_HPA"],
        "values": [{"FractionalLoad": 1}],
        "why": "The only knob that changes the load shape for non-divisible "
               "tails, which is what every odd cell size is (256, 192, 1365).",
    },
    # ---- Store side. NonTemporalA/B bypass L2; this part has 1 MB of L2 and the
    # winners sit at 16-25 KB of LDS, so L2 residency is worth an experiment
    # rather than an assumption.
    {
        "knob": "NonTemporal",
        "families": ["CC", "ZZ", "SS", "HH", "DD", "HH_HPA", "HS_HPA"],
        "values": [{"NonTemporalA": True}, {"NonTemporalB": True}],
        "why": "L2 is 1 MB shared with the CPU. Every winner keeps its tile "
               "resident, so the large-shape rows are the ones that could gain "
               "from streaming instead.",
    },
]
