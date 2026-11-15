"""The reachable MacroTile frontier is two tile shapes, and an assertion opens it.

The report's 18 tied cells all sit at a 128x128 (SS/HH) or 64x64 (CC/DD) tile,
and the corpus's only larger tiles carry ThreadTile 16x8 -- 128 accumulators a
thread against the winner's 64 -- so "bigger tiles are worse" was never measured
with the register pressure held fixed. That experiment cannot be run by editing
a tile in a config, because Tensile's classic load structure
(`oto.tensile.gates.loads`, a port of SolutionStructs'
`setGlobalLoadTileDimClassic`) only emits an operand load when the per-k-slice
element count and `NumThreads * GlobalLoadVectorWidth` are commensurate. With
LocalSplitU 1 that pins the tile to `MT1 * GLVW == ThreadTile0 * ThreadTile1 *
DepthU`, and then `NumThreads * GLVW == MT0 * DepthU` exactly, so operand A
balances for any MT0 and operand B balances iff MT0/MT1 is an integer. The only
escape from that is `AssertFree0/1ElementMultiple`, which certifies the free
dimension is a multiple of the wide load and lifts the
`GLVW_eff != VectorWidth` refusal.

What this pins:

* an exhaustive sweep of the tile space (MT 64..512 step 8, ten thread tiles,
  every legal vector width, DepthU 8/16/32, with and without the assertion)
  finds exactly four legal tiles above 16384 elements: 128x256 and 256x128 for
  SS, and those plus the 4:1 pair 64x512/512x64 for HH and HH-HPA. A gate
  change that admits more must update `candidate_rows._FRONTIER`, and one that
  admits fewer must be caught here rather than 78 seconds into a benchmark;
* the named near misses (192x192, 192x128, 160x256, ...) stay refused, so the
  "just try a bigger tile" idea cannot silently reappear as a wasted draw;
* CC, DD and ZZ have *no* legal tile above 16384 at all, which is the structural
  half of why their realistic ceilings are unreachable (docs/gfx90c/potential_configs.md
  §R40);
* the three retired illegal tiles that produced the 7 failed phases of
  run_20261018_004835 stay refused by the accumulator budget;
* the assertion really is what opens the full-width frontier: VW4 at 256x128 is
  refused for SS without it and legal with it.

CPU only. No GPU, no Tensile run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from oto.harness.candidate_pool import _base_config, _strip_not_forwarded
from oto.harness.candidate_rows import _FRONTIER
from oto.tensile.candidate import CandidateGenerator

#: Every thread tile the deck, the ladder and the generator emit, plus their
#: transposes. A thread tile outside this set is not a candidate the harness can
#: express, so the sweep does not need to model it.
THREAD_TILES = ("16x8", "8x16", "16x4", "4x16", "8x8", "8x4", "4x8",
                "4x4", "2x4", "4x2")
#: Vector widths per element size, capped by the 16 B global-load rule.
VECTOR_WIDTHS = {"SS": (4, 2), "HH": (8, 4, 2), "CC": (2, 1), "DD": (2, 1),
                 "ZZ": (1,), "HH_HPA": (8, 4, 2), "HS_HPA": (4, 2)}
#: Assertion values swept on both free dimensions (0 = absent).
ASSERTIONS = (0, 2, 4)


def _generator() -> CandidateGenerator:
    return CandidateGenerator(REPO)


def _legal(fam: str, tile: str, tt: str, vw: int, du: int,
           extra: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Validate one config through the real generator gate."""
    config = {**_base_config(fam), "MacroTile": tile, "ThreadTile": tt,
              "VectorWidth": vw, "DepthU": du,
              "ContractionPattern": "Ailk_Bjlk", **(extra or {})}
    config, _ = _strip_not_forwarded(config)
    ok, why = _generator().validate_config(config)
    return ok, why


def _sweep(fam: str) -> set[tuple[int, int]]:
    """Every tile above 16384 elements the gate admits, at the swept grid."""
    found: set[tuple[int, int]] = set()
    for mt0 in range(64, 513, 8):
        for mt1 in range(64, 513, 8):
            if mt0 * mt1 <= 16384:
                continue
            for tt in THREAD_TILES:
                t0, t1 = (int(x) for x in tt.split("x"))
                if mt0 % t0 or mt1 % t1:
                    continue
                threads = (mt0 // t0) * (mt1 // t1)
                if threads > 1024 or threads % 64:
                    continue
                for vw in VECTOR_WIDTHS[fam]:
                    for du in (8, 16, 32):
                        for level in ASSERTIONS:
                            extra = {} if not level else {
                                "AssertFree0ElementMultiple": level,
                                "AssertFree1ElementMultiple": level}
                            if _legal(fam, f"{mt0}x{mt1}x{du}", tt, vw,
                                      du, extra)[0]:
                                found.add((mt0, mt1))
    return found


def test_no_tile_above_16384_is_legal_except_the_frontier():
    """SS keeps the 2:1 tile; HH and HH-HPA also reach a 4:1 tile at DepthU 8."""
    expected = {
        "SS": {(128, 256), (256, 128)},
        "HH": {(128, 256), (256, 128), (64, 512), (512, 64)},
        "HH_HPA": {(128, 256), (256, 128), (64, 512), (512, 64)},
        "HS_HPA": {(128, 256), (256, 128), (64, 512), (512, 64)},
    }
    for fam, want in expected.items():
        assert _sweep(fam) == want, f"{fam} frontier drifted"


def test_the_capped_families_have_no_large_tile_at_all():
    """CC, DD and ZZ are accumulator-bound below 16384, which §R40 needs true."""
    for fam in ("CC", "DD", "ZZ"):
        assert _sweep(fam) == set(), f"{fam} unexpectedly admits a large tile"


def test_near_miss_tiles_are_refused_by_load_divisibility():
    """The tiles a reader would reach for first are illegal, not merely slow."""
    for fam in ("SS", "HH"):
        for tile in ("192x192x8", "192x128x8", "128x192x8", "256x192x8",
                     "160x256x8", "224x256x8"):
            ok, why = _legal(fam, tile, "8x8", 4 if fam == "SS" else 8, 8)
            assert not ok, f"{fam} {tile} must stay refused"
            assert "load divisibility" in why, (fam, tile, why)


def test_retired_illegal_tiles_stay_refused_by_the_accumulator_budget():
    """The three stale rows behind the 7 failed phases of the 10-18 run."""
    for fam, tile, tt in (("ZZ", "128x128x8", "4x4"),
                          ("ZZ", "128x64x8", "4x4"),
                          ("CC", "128x128x8", "4x4")):
        ok, why = _legal(fam, tile, tt, 1 if fam == "ZZ" else 2, 8)
        assert not ok, f"{fam} {tile} must stay refused"
        assert "accumulator VGPRs" in why, (fam, tile, why)


def test_the_full_width_frontier_needs_the_free_dimension_assertion():
    """The assertion is the mechanism, not a detail: pin both sides of it."""
    cases = (
        ("SS", "256x128x8", "8x8", 4, 8, "AssertFree1ElementMultiple", 2),
        ("HH", "256x128x16", "8x8", 8, 16, "AssertFree1ElementMultiple", 4),
    )
    for fam, tile, tt, vw, du, knob, level in cases:
        refused, why = _legal(fam, tile, tt, vw, du)
        assert not refused and "GLVW" in why, (fam, tile, why)
        ok, why = _legal(fam, tile, tt, vw, du, {knob: level})
        assert ok, (fam, tile, why)


def test_frontier_table_only_holds_tiles_above_the_old_ceiling():
    """A frontier row at or below 16384 would be a re-measurement, not a test."""
    for fam, (_why, tiles) in _FRONTIER.items():
        for tile, tt, _vw, _du, _extra in tiles:
            mt0, mt1 = (int(x) for x in tile.split("x")[:2])
            t0, t1 = (int(x) for x in tt.split("x"))
            threads = (mt0 // t0) * (mt1 // t1)
            assert mt0 * mt1 > 16384, (fam, tile)
            assert threads % 64 == 0 and threads <= 1024, (fam, tile, threads)
