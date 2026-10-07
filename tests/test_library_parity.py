"""Coverage-parity rule: the produced TensileLibrary must map EXACTLY to the
shipped gfx900 library in (shape, dtype) cells (knowledge_base.md §6.1).

Two clauses:

* **No contraction** — every shipped cell needs >= 1 phase in the manifest.
* **No extension** — no phase may address a cell outside the shipped grid.

The committed deck + current overlays are pinned to the grid here, so any
future deck edit (D1-style additions, consolidation, candidate probes) that
breaks parity fails CI CPU-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from gfx90c_common import FAMILY_DTYPE_CHAR, FAMILY_SHAPES, cube_side  # noqa: E402
from library_parity import (  # noqa: E402
    phase_cells,
    phase_family,
    phases_cells,
    load_pipeline_phases,
    parity_report,
)

DECK = yaml.safe_load((REPO / "phases.yaml").read_text())
SEED_DOC = yaml.safe_load(
    (REPO / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml").read_text())
SEED = list(SEED_DOC["phases"].values()) if isinstance(
    SEED_DOC.get("phases"), dict) else SEED_DOC["phases"]

GRID_TOTAL = sum(len(v) for v in FAMILY_SHAPES.values())


def _phase(phase_id, family, shapes, config=None):
    return {
        "phase_id": phase_id,
        "config": config or {"FamilyLabel": family, "DataType": FAMILY_DTYPE_CHAR[family]},
        "shapes": shapes,
    }


class TestShippedGrid:
    def test_grid_size_is_38(self):
        assert GRID_TOTAL == 38

    def test_grid_uses_cube_shapes(self):
        from gfx90c_common import shipped_cell_set
        for family, shape in shipped_cell_set():
            assert cube_side(shape) is not None
            assert int(shape.split("x")[0]) in FAMILY_SHAPES[family]


class TestDeckParity:
    """The committed phases.yaml must map exactly to the shipped grid."""

    def test_deck_has_no_missing_cells(self):
        report = parity_report(DECK)
        assert report["parity_ok"]
        assert report["missing"] == []

    def test_deck_has_no_extra_cells(self):
        report = parity_report(DECK)
        assert report["extra"] == []

    def test_deck_covers_all_38(self):
        assert len(phases_cells(DECK)) == GRID_TOTAL

    def test_families_carry_correct_dtype_char(self):
        from gfx90c_common import shipped_cell_set
        grid = shipped_cell_set()
        for family, shape in phases_cells(DECK):
            assert (family, shape) in grid


class TestSeedOverlayParity:
    def test_seed_only_extends_within_grid(self):
        for family, shape in phases_cells(SEED):
            assert (family, shape) in {
                (f, s) for f, ss in FAMILY_SHAPES.items() for s in
                (f"{side}x{side}x{side}" for side in ss)}

    def test_seed_does_not_shrink_deck(self):
        assert phases_cells(DECK) == phases_cells(DECK) | phases_cells(SEED)


class TestPipelineManifestParity:
    def test_full_pipeline_manifest_holds_parity(self):
        manifest = load_pipeline_phases(str(REPO))
        report = parity_report(manifest)
        assert report["parity_ok"]
        assert report["deck_cells"] == GRID_TOTAL


class TestDivergenceDetection:
    def test_extra_cell_is_detected(self):
        bad = list(DECK) + [_phase("phase_ss_96_probe", "SS",
                                   ["96x96x96"], {"FamilyLabel": "SS", "DataType": "S"})]
        report = parity_report(bad)
        assert not report["parity_ok"]
        assert ("SS", "96x96x96") in report["extra"]

    def test_missing_cell_is_detected(self):
        # Remove every deck phase that addresses a chosen cell; that cell then
        # must be reported missing against the full shipped grid.
        killed = ("ZZ", "128x128x128")
        slim = [p for p in DECK if killed not in phase_cells(p)]
        report = parity_report(slim)
        assert not report["parity_ok"]
        assert killed in report["missing"]
        assert len(report["missing"]) >= 1

    def test_empty_manifest_is_total_contraction(self):
        report = parity_report([])
        assert not report["parity_ok"]
        assert len(report["missing"]) == GRID_TOTAL
        assert report["deck_cells"] == 0


class TestPhaseFamilyResolution:
    def test_config_familylabel_is_canonical(self):
        p = _phase("phase_auto_0_ss_256x256x256_42", "SS", ["256x256x256"],
                   {"FamilyLabel": "SS", "DataType": "S"})
        assert phase_family(p) == "SS"

    def test_hh_hpa_token_fallback(self):
        p = {"phase_id": "phase_hh_hpa_Ailk_Bljk_mt128x64x16",
             "shapes": ["512x512x512"]}
        assert phase_family(p) == "HH_HPA"

    def test_hs_hpa_token_fallback(self):
        p = {"phase_id": "phase_hs_hpa_spoof_baseline_vega10",
             "shapes": ["512x512x512"]}
        assert phase_family(p) == "HS_HPA"

    def test_probe_token_fallback(self):
        p = {"phase_id": "probe_N1_SS_64x64x8_8x8_vw4", "shapes": ["512x512x512"]}
        assert phase_family(p) == "SS"

    def test_non_cube_shapes_are_not_cells(self):
        p = _phase("phase_ss_gemv_probe", "SS", ["32x4096x1"])
        assert phase_cells(p) == set()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))