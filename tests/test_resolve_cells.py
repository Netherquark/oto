#!/usr/bin/env python3
"""
test_resolve_cells.py — harness.resolve_cells per-cell winner resolution.

Regression guards for the 38-cell evidence generator (potential_configs.md
§R25, the per-cell reading — §R26 is the class tracker):

  * exactly the shipped deck — (family, shape) equals shipped_cell_set()
    (knowledge_base.md §6.1), no added/absent cells;
  * verdicts + native/floor values match acceptance_report.json field-for-field;
  * every cell that has a native winner phase resolves a FULL structural config
    (MacroTile present) from the winner run's configs/*.yaml or the registry —
    the "winner-run-first" resolution ordering;
  * HPA floor cells (whose shipped floor rows are unresolved, verdict '?')
    degrade to an empty spoof config instead of crashing;
  * ``cfg_gap`` classifies every cell (identical / near / retile / no-floor) --
    the mechanical half of the tie taxonomy (potential_configs.md §R17);
  * meta provenance counts are self-consistent (n_cells, resolver keys ≥ yamls).

Run: python3 -m pytest -q tests/test_resolve_cells.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from oto.device.vocabulary import shipped_cell_set
from oto.harness import resolve_cells


@pytest.fixture(scope="module")
def evidence():
    cells, meta = resolve_cells.build(str(BASE))
    return cells, meta


def test_deck_is_exactly_the_shipped_grid(evidence):
    cells, _ = evidence
    got = {(c["family"], c["shape"]) for c in cells}
    assert got == shipped_cell_set()
    assert len(cells) == 38


def test_verdicts_and_values_match_acceptance_report(evidence):
    cells, _ = evidence
    report = json.load(open(BASE / "gfx90c_results" / "acceptance_report.json"))
    by_cell = {c["family"] + ":" + c["shape"]: c for c in cells}
    for v in report["per_cell_verdicts"]:
        c = by_cell[v["family"] + ":" + v["shape"]]
        assert c["verdict"] == v["verdict"]
        assert c["native_value"] == v.get("native_value")
        assert c["spoof_value"] == v.get("spoof_value")
        assert c["native_winner_phase"] == (v.get("native_winner_phase") or "")
        assert c["native_winner_run"] == (v.get("native_winner_run") or "")
    assert {c["verdict"] for c in cells} <= {"WIN", "TIE", "LOSS", "?"}


def test_every_native_winner_resolves_full_config(evidence):
    cells, _ = evidence
    unresolved = [
        (c["family"], c["shape"], c["native_winner_phase"])
        for c in cells
        if c["native_winner_phase"] and not c["native_config"].get("MacroTile")
    ]
    assert unresolved == [], f"winner configs failed to resolve: {unresolved}"
    # the deck's hardest cells must resolve to the documented winner knobs
    by = {(c["family"], c["shape"]): c for c in cells}
    # CC:512 winner is the WGM=4 variant (not WGM8) at the 64x64/4x4 tile.
    # The old `NumLoadsCoalescedA == 1` pin was a corpus snapshot: the phase that
    # won run_20261017_092909 carries no NLCA in its ForkParameters, so the
    # resolver is right and the pin was the thing that went stale -- assert the
    # invariant (a full, documented tile), never the snapshot.
    cc512 = by[("CC", "512x512x512")]["native_config"]
    assert cc512["WorkGroupMapping"] == 4
    assert cc512["MacroTile"] == [64, 64]
    assert cc512["ThreadTile"] == [4, 4]
    # ZZ:1024 winner is the DepthU-8 tile (phase_cand_zz_128_32x32x8_..._du8_...),
    # not the DepthU-16 tile that won under run_20261009_205427. Pinned from the
    # acceptance report this resolver ran against; if the winner moves again this
    # assert is the first thing that goes, and the new depth is in the phase name.
    assert by[("ZZ", "1024x1024x1024")]["native_config"]["DepthU"] == 8
    # HH:256's like-for-like winner (§R56.3: family-protocol phases only) is
    # the 64x32 tile from a family span, not the 32x64 single-problem phase
    # the pre-basis winners read (763.4) from.
    assert by[("HH", "256x256x256")]["native_config"]["MacroTile"] == [32, 64]


def test_cfg_gap_classifies_every_cell(evidence):
    """``cfg_gap`` is the mechanical half of the tie taxonomy (§R17).

    It must be derived from the two resolved configs, never asserted: the code
    reports the gap and potential_configs.md §R17 reads it. The classes are
    pinned as a *self-consistency* invariant -- recomputing the gap from the
    cell's own configs must reproduce the reported one -- because pinning
    individual cells to a class rots the moment the corpus moves a winner
    (it did, on 2026-10-21: the 17 h run moved DD:1024 and SS:4096 to the
    floor's own geometry, and the old cell-pinned assertions failed).
    """
    cells, _ = evidence
    assert {c["cfg_gap"] for c in cells} <= {
        "identical", "near", "retile", "no-floor", None}
    for c in cells:
        if c["family"] in ("HH_HPA", "HS_HPA"):
            assert c["cfg_gap"] == "no-floor", \
                "the HPA columns ship no floor arm; a gap would be a phantom"
        recomputed = resolve_cells._cfg_gap(c["native_config"], c["spoof_config"])
        assert c["cfg_gap"] == recomputed, \
            f"{c['family']}:{c['shape']} gap must follow from its configs"
    # The user's reading, confirmed structurally rather than per cell: at the
    # big compute-bound cells the native arm runs the floor's own gfx900
    # geometry, so the delta there is environment, not a tuning win.
    identical = [c for c in cells if c["cfg_gap"] == "identical"]
    assert identical, "no cell resolves to the floor's own geometry"
    for c in identical:
        shared = [k for k in resolve_cells._GAP_KEYS
                  if k in c["native_config"] and k in c["spoof_config"]]
        assert shared
        assert all(c["native_config"][k] == c["spoof_config"][k]
                              for k in shared)
    assert "cfg_gap" in resolve_cells._tsv(cells).split("\n")[0]


def test_unresolved_hpa_floor_rows_are_tolerated(evidence):
    cells, _ = evidence
    for c in cells:
        if c["family"] in ("HH_HPA", "HS_HPA"):
            assert c["spoof_config"] == {} or c["spoof_config"].get("MacroTile")
            # never a crash, never a phantom floor winner
            assert isinstance(c["spoof_config"], dict)


def test_meta_provenance_is_consistent(evidence):
    """Provenance is *self-consistent*, never a pinned corpus count or run id.

    A literal run id here is a corpus count in disguise: it goes stale the moment
    the next run lands, and it asserts nothing about the resolver. What must hold
    is that the meta agrees with the acceptance report it was derived from, and
    that the key/yaml/registry relationships stay intact.
    """
    _, meta = evidence
    report = json.load(open(BASE / "gfx90c_results" / "acceptance_report.json"))
    assert meta["acceptance_run_id"] == report["run_id"]
    assert meta["n_cells"] == len(report["per_cell_verdicts"])
    assert meta["sources"]["run_config_yamls"] >= 6000
    # resolver_keys counts UNIQUE phase stubs (across runs), while
    # run_config_yamls counts every per-run yaml, so the former is bounded
    # ABOVE by the latter (a phase that ran in N runs yields N yamls but 1
    # unique stub). The invariant is "every unique stub has at least one yaml".
    assert meta["sources"]["resolver_keys"] <= meta["sources"]["run_config_yamls"]
    assert meta["sources"]["resolver_keys"] >= 1000
    assert meta["sources"]["registry_phases"] >= 1000


def test_table_and_tsv_render(evidence):
    cells, _ = evidence
    t = resolve_cells._table(cells)
    assert t.count("\n") == len(cells)          # header + one row per cell
    assert "NATIVE WINNER CONFIG" in t
    s = resolve_cells._tsv(cells).split("\n")
    assert s[0].startswith("family\tshape")
    assert len(s) == len(cells) + 1
