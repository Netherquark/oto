#!/usr/bin/env python3
"""The curated family tile decks: the starting candidates, and what kind each is.

Owns: ``FAMILY_DECKS`` -- one list per family label, every entry annotated with
what kind of candidate it is:

  MEASURED  the shipped-gfx900 floor's own winning solution at a named cell, read
            from that phase's resolved 2_BenchmarkData yaml. These convert known
            losses directly.
  QUANT     a tile chosen for 7-CU wave quantization. gfx90c has 7 CUs, so
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

from typing import Any, Dict, List

FAMILY_DECKS: Dict[str, List[Dict[str, Any]]] = {
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
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1, "VectorWidth": 4, "WorkGroupMapping": 4},
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
            # unpacks the 256 square on a 7-CU part.
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "NLCA": 1, "VectorWidth": 8, "WorkGroupMapping": 4},
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
            {"MacroTile": "32x32x16", "ThreadTile": "2x2", "VectorWidth": 2, "NLCA": 1},
            # MEASURED floor winner at ZZ:192 -- 32x32x8 on 4x4 threads, not
            # the 2x2 this deck had assumed. At complex double 4x4 is
            # TT0*TT1*8 = 128 accumulator VGPRs, exactly on the budget, so
            # it is legal but at the ceiling; this is the measured optimum
            # and was never generated natively.
            {"MacroTile": "32x32x8", "ThreadTile": "4x4", "NLCA": 1},
            # LADDER: exercise DepthU, which no ZZ entry has varied. Complex
            # double LDS is 8 B/elem, so DepthU 8 halves the 16 KB footprint.
            {"MacroTile": "64x64x4", "ThreadTile": "4x4", "NLCA": 1},
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "NLCA": 1},
            # MEASURED floor winner at ZZ:128 is 64x64x16/4x4/VW1, and
            # ZZ:512 is the same tile at DepthU 8 plus LdsPadB 1. Pad B is
            # the only ZZ knob with measured support; include it.
            {"MacroTile": "64x64x16", "ThreadTile": "4x4", "LdsPadB": 1, "NLCA": 1},
            {"MacroTile": "64x64x8", "ThreadTile": "4x4", "LdsPadB": 1, "NLCA": 1},
        ],
        # ---- CC: 2.5-19.7% of the FP32 roof on every cell, and the only
        # family where the floor's winning config was already run natively
        # and still lost. Complex single is 8 B/elem for A and B, so this
        # family is data-movement bound long before it is ALU bound: the
        # lever is tile size and LDS padding, not width (VW2 = 16 B is
        # already the cap).
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
