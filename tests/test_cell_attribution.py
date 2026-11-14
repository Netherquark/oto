#!/usr/bin/env python3
"""
test_cell_attribution.py — typecode-first cell attribution (anti-contamination).

Covers the §13.2 contamination taxonomy end-to-end:

  * the `phase_auto_*` family bug — 'auto' was a FAMILY_TO_DTYPE key, so
    extract_family_from_phase_id greedily matched the 4-char pool prefix and
    resolved EVERY auto-pool phase to family 'auto' -> dtype 'S', dumping
    HH/CC/DD kernels into the SS cells;
  * HHS/HSS (fp16-family) kernels must never count toward SS cells;
  * kernel typecode (SB/DB/HB/CB/ZB) overrides a contradicting phase-level
    family stamp;
  * HPA variant stamps survive typecode resolution;
  * kernel_db / aggregate paths share the same resolver (single source of
    truth in gfx90c_common).
"""
from __future__ import annotations

import pytest

from oto.device import loader as _loader
from oto.device.kernel_vocabulary import (
    dtype_from_kernel_name,
    family_from_kernel_name,
    kernel_typecode,
)
from oto.metrics.benchmark_analytics import (
    extract_family_from_phase_id,
    resolve_cell_family,
)

# ---------------------------------------------------------------------------
# phase_id family extraction: the 'auto' pool prefix must never be a family
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("phase_id", "expected"), [
    ("phase_auto_1_hh_1024x1024x1024_3", "hh"),
    ("phase_auto_0_cc_192x192x192_2", "cc"),
    ("phase_auto_0_dd_1365x1365x1365_7", "dd"),
    ("phase_auto_1_zz_128x128x128_0", "zz"),
    ("phase_auto_0_ss_1000x1000x1000_0", "ss"),
    # bare single-letter dtype token (legacy auto pool naming)
    ("phase_auto_0_S_256x256x256_42", "ss"),
    ("phase_auto_1_H_512x512x512_9", "hh"),
    # non-auto families unchanged
    ("phase_hh_hpa_Ailk_Bljk_512", "hh_hpa"),
    ("phase_hs_hpa_Ailk_Bjlk_1024", "hs_hpa"),
    ("phase_spoof_ss_256x256x256_1", "ss"),
])
def test_extract_family_auto_prefix(phase_id: str, expected: str) -> None:
    """`phase_auto_*` must resolve to its REAL family token, never 'auto'."""
    assert extract_family_from_phase_id(phase_id) == expected


# ---------------------------------------------------------------------------
# kernel typecode -> family (gfx90c_common, the single resolver)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("kernel", "fam", "code"), [
    ("Cijk_Ailk_Bjlk_SB_MT32x64x16_SN_K1", "SS", "SB"),
    ("Cijk_Ailk_Bjlk_DB_MT64x64x8_SN_K1", "DD", "DB"),
    ("Cijk_Ailk_Bjlk_HB_MT64x64x16_SN_K1", "HH", "HB"),
    ("Cijk_Ailk_Bjlk_CB_MT64x64x8_SN_K1", "CC", "CB"),
    ("Cijk_Ailk_Bjlk_ZB_MT64x64x16_SN_K1", "ZZ", "ZB"),
    # layout-suffixed typecodes: the marker must be skipped
    ("Cijk_Ailk_Bljk_HHS_BH_MT32x32x16_SN_K1", "HH", "HHS"),
    ("Cijk_Ailk_Bljk_ZB_GB_MT32x32x16_SN_K1", "ZZ", "ZB"),
    ("Cijk_Ailk_Bljk_HSS_BH_MT32x32x16_SN_K1", "HH", "HSS"),
    ("Cijk_Alik_Bljk_SB_MT64x64x16_SN_1LDSB0_APM1_ABV0", "SS", "SB"),
    # unparseable -> ''
    ("", "", ""),
    ("not-a-kernel", "", ""),
])
def test_kernel_typecode_family(kernel: str, fam: str, code: str) -> None:
    assert kernel_typecode(kernel) == code
    assert family_from_kernel_name(kernel) == fam
    assert dtype_from_kernel_name(kernel) == _loader.current_profile().family_dtype_char.get(fam, "")


def test_hhs_never_counts_toward_ss() -> None:
    """The §13.2 rule: HHS/HSS kernels are fp16-family and land in HH, never SS."""
    assert family_from_kernel_name("Cijk_Ailk_Bljk_HHS_BH_MT32x32x16_SN_K1") == "HH"
    assert family_from_kernel_name("Cijk_Ailk_Bljk_HSS_BH_MT32x32x16_SN_K1") == "HH"


# ---------------------------------------------------------------------------
# resolve_cell_family: precedence + conflict handling
# ---------------------------------------------------------------------------

def test_resolve_contaminated_auto_rec_hh() -> None:
    """The exact §13.2 shape: hh auto phase, no family stamp, DataType 'S'.

    Pre-fix this recorded family 'auto' -> dtype 'S' and won the SS:1024 cell
    at 2142.55. Post-fix the kernel typecode (HHS -> HH) decides the cell.
    """
    rec = {
        "phase_id": "phase_auto_1_hh_1024x1024x1024_3",
        "fingerprint": "Cijk_Ailk_Bljk_HHS_BH_MT32x32x16_SN_K1",
        "DataType": "S",
        "family": "",
    }
    assert resolve_cell_family(rec) == "HH"


def test_typecode_wins_over_conflicting_stamp() -> None:
    """A phase stamped CC whose kernel is SB must attribute to SS (typecode wins)."""
    rec = {
        "phase_id": "phase_spoof_cc_256x256x256_1",
        "fingerprint": "Cijk_Ailk_Bjlk_SB_MT32x64x16_SN_K1",
        "DataType": "C",
        "family": "CC",
    }
    assert resolve_cell_family(rec) == "SS"


def test_hpa_stamp_preserved() -> None:
    """HPA variant cells are distinguished by their explicit stamp only."""
    rec = {
        "phase_id": "phase_cand_hh_hpa_512_32x32x16_tt2x2_Ailk_Bljk_vw2_du16_g1_w4",
        "fingerprint": "Cijk_Ailk_Bljk_HHS_BH_MT32x32x16_SN_K1",
        "family": "HH_HPA",
    }
    assert resolve_cell_family(rec) == "HH_HPA"
    rec2 = dict(rec, family="HS_HPA")
    assert resolve_cell_family(rec2) == "HS_HPA"


def test_family_stamp_kept_when_no_typecode() -> None:
    rec = {"phase_id": "phase_x_ss_256x256x256_0", "fingerprint": "nokernel",
           "DataType": "S", "family": "SS"}
    assert resolve_cell_family(rec) == "SS"


def test_unattributable_returns_empty() -> None:
    rec = {"phase_id": "phase_unknown_thing", "fingerprint": "x", "DataType": "Q"}
    assert resolve_cell_family(rec) == ""


# ---------------------------------------------------------------------------
# aggregate_by_cell_typecode keeps the resolved family on the cell
# ---------------------------------------------------------------------------

def test_aggregate_by_cell_typecode_partitions_by_kernel() -> None:
    from pathlib import Path

    from oto.metrics.benchmark_analytics import AnalyticsEngine

    engine = AnalyticsEngine(registry=None, base_dir=Path("."))
    records = [
        {"ProblemType": "1024x1024x1024", "fingerprint": "Cijk_Ailk_Bljk_HHS_BH_MT32x32x16_SN_K1",
         "GFLOPS": 100.0, "DataType": "S"},
        {"ProblemType": "1024x1024x1024", "fingerprint": "Cijk_Ailk_Bjlk_SB_MT32x64x16_SN_K1",
         "GFLOPS": 200.0, "DataType": "S"},
    ]
    cell_map = engine.aggregate_by_cell_typecode(records, phase_family="hh")
    keys = set(cell_map)
    # HHS kernel -> HH family, SB kernel -> SS family; both stay at shape 1024
    assert ("H", "1024x1024x1024", "Cijk_Ailk_Bljk_HHS_BH_MT32x32x16_SN_K1", "HH") in keys
    assert ("S", "1024x1024x1024", "Cijk_Ailk_Bjlk_SB_MT32x64x16_SN_K1", "SS") in keys
    assert len(keys) == 2

# ---------------------------------------------------------------------------
# Group C: ldspad_feasible legality gate (scheduler)
# ---------------------------------------------------------------------------

def test_ldspad_feasible_passes_without_pads():
    from oto.tensile.candidate import ldspad_feasible
    ok, reason = ldspad_feasible({"MacroTile": "64x64x8", "ThreadTile": "4x4",
                                  "DataType": "Z", "DepthU": 8})
    assert ok, reason


def test_ldspad_feasible_padded_ok_and_rejects_blowout():
    from oto.tensile.candidate import ldspad_feasible
    # 64x64x8 Z at DepthU 4: padded footprint (64+2+64+2)*4*16 = 8448 <= 16384
    # -> ok (DU8 at Tensile's 16 B Z is at/over the budget; the padded
    # at-budget rung is DU4 now).
    ok, reason = ldspad_feasible({"MacroTile": "64x64x8", "ThreadTile": "4x4",
                                  "DataType": "Z", "DepthU": 4,
                                  "LdsPadA": 2, "LdsPadB": 2})
    assert ok, reason
    # Same tile with absurd pads blows the 16384 budget:
    # (64+128+64+128)*4*16 = 24576 > 16384
    ok, reason = ldspad_feasible({"MacroTile": "64x64x8", "ThreadTile": "4x4",
                                  "DataType": "Z", "DepthU": 4,
                                  "LdsPadA": 128, "LdsPadB": 128})
    assert not ok
    assert "footprint" in reason


def test_ldspad_feasible_stagger_and_af0em_rejects():
    from oto.tensile.candidate import ldspad_feasible
    base = {"MacroTile": "64x64x8", "ThreadTile": "4x4",
            "DataType": "C", "DepthU": 32}
    # C (8 B) * DepthU 32 = 256; SUS=256 > 0.5*256 -> legal swizzle.
    ok, reason = ldspad_feasible({**base, "StaggerUStride": 256})
    assert ok, reason
    # SUS=0 with default StaggerU=32 -> coupling reject (SUS=0 only valid if SU=0).
    ok, reason = ldspad_feasible({**base, "StaggerUStride": 0})
    assert not ok
    assert "StaggerU" in reason
    # SUS>0 but below the 0.5*DepthU*bpe floor -> reject.
    ok, reason = ldspad_feasible({**base, "StaggerUStride": 16})
    assert not ok
    assert "StaggerUStride" in reason
    # SU=0 does NOT reject the stride or the mapping: Tensile FORCES both to 0
    # (SolutionStructs:3334-3336) and overwrites whatever the config carried.
    # The gate used to read that force as a reject and killed the whole
    # "no-swizzle" arm (14 deck rows, never measured).
    ok, reason = ldspad_feasible({**base, "StaggerU": 0, "StaggerUStride": 256})
    assert ok, reason
    ok, reason = ldspad_feasible({**base, "StaggerU": 0, "StaggerUMapping": 1})
    assert ok, reason
    ok, reason = ldspad_feasible({**base, "StaggerU": 0})
    assert ok, reason
    # Out-of-domain values -> reject.
    ok, reason = ldspad_feasible({**base, "StaggerU": 3})
    assert not ok
    assert "StaggerU" in reason
    ok, reason = ldspad_feasible({**base, "StaggerUStride": 100})
    assert not ok
    assert "StaggerUStride" in reason
    ok, reason = ldspad_feasible({**base, "AssertFree0ElementMultiple": 0})
    assert not ok
    assert "AssertFree0ElementMultiple" in reason
